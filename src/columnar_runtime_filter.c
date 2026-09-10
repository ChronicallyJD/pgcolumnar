/*-------------------------------------------------------------------------
 *
 * columnar_runtime_filter.c
 *    Serial hash-join runtime-filter coordinator.
 *
 * The coordinator owns execution order while PostgreSQL core retains exact
 * Hash Join semantics.  Its child HashPath is private: a HashPath already in
 * joinrel->pathlist can be freed by add_path(), so retaining or copying that
 * same-rel path is unsafe.
 *
 *-------------------------------------------------------------------------
 */
#include "postgres.h"

#include "columnar.h"
#include "columnar_customscan.h"

#include "access/table.h"
#include "commands/explain.h"
#if PG_VERSION_NUM >= 180000
#include "commands/explain_format.h"
#endif
#include "executor/executor.h"
#include "miscadmin.h"
#include "nodes/extensible.h"
#include "nodes/makefuncs.h"
#include "nodes/nodeFuncs.h"
#include "optimizer/cost.h"
#include "optimizer/pathnode.h"
#include "optimizer/paths.h"
#include "optimizer/restrictinfo.h"
#include "parser/parsetree.h"
#include "utils/lsyscache.h"
#include "utils/datum.h"
#include "utils/memutils.h"
#include "utils/typcache.h"
#include "utils/tuplestore.h"

bool pgcolumnar_enable_join_runtime_filter = true;

typedef struct PgColumnarRuntimeFilterState
{
    CustomScanState customScanState;
    PlanState *joinState;
    CustomScanState *tapState;
    AttrNumber factAttno;
    bool rangeAttached;
    bool prepared;
} PgColumnarRuntimeFilterState;

typedef struct PgColumnarRuntimeTapState
{
    CustomScanState customScanState;
    PlanState *sourceState;
    Tuplestorestate *store;
    TupleTableSlot *replaySlot;
    AttrNumber keyResno;
    Oid keyType;
    Oid keyCollation;
    FmgrInfo compareFn;
    MemoryContext valueContext;
    Datum minimum;
    Datum maximum;
    int16 typeLength;
    bool typeByValue;
    bool intervalAvailable;
    bool hasValues;
    uint64 buildRows;
    bool replay;
} PgColumnarRuntimeTapState;

static set_join_pathlist_hook_type previous_set_join_pathlist_hook = NULL;

static Plan *PgColumnarPlanRuntimeFilterPath(PlannerInfo *root,
                                             RelOptInfo *rel,
                                             CustomPath *bestPath,
                                             List *tlist,
                                             List *clauses,
                                             List *customPlans);
static Node *PgColumnarCreateRuntimeFilterState(CustomScan *customScan);
static Node *PgColumnarCreateRuntimeTapState(CustomScan *customScan);
static void PgColumnarBeginRuntimeTap(CustomScanState *node,
                                      EState *estate,
                                      int eflags);
static TupleTableSlot *PgColumnarExecRuntimeTap(CustomScanState *node);
static void PgColumnarEndRuntimeTap(CustomScanState *node);
static void PgColumnarReScanRuntimeTap(CustomScanState *node);
static void PgColumnarExplainRuntimeTap(CustomScanState *node,
                                        List *ancestors,
                                        ExplainState *es);
static void PgColumnarBeginRuntimeFilter(CustomScanState *node,
                                         EState *estate,
                                         int eflags);
static TupleTableSlot *PgColumnarExecRuntimeFilter(CustomScanState *node);
static void PgColumnarEndRuntimeFilter(CustomScanState *node);
static void PgColumnarReScanRuntimeFilter(CustomScanState *node);
static void PgColumnarShutdownRuntimeFilter(CustomScanState *node);
static void PgColumnarExplainRuntimeFilter(CustomScanState *node,
                                           List *ancestors,
                                           ExplainState *es);

static const CustomPathMethods PgColumnarRuntimeFilterPathMethods = {
    .CustomName = "Columnar Runtime Filter Coordinator",
    .PlanCustomPath = PgColumnarPlanRuntimeFilterPath,
    .ReparameterizeCustomPathByChild = NULL,
};

static const CustomScanMethods PgColumnarRuntimeFilterScanMethods = {
    .CustomName = "Columnar Runtime Filter Coordinator",
    .CreateCustomScanState = PgColumnarCreateRuntimeFilterState,
};

static const CustomExecMethods PgColumnarRuntimeFilterExecMethods = {
    .CustomName = "Columnar Runtime Filter Coordinator",
    .BeginCustomScan = PgColumnarBeginRuntimeFilter,
    .ExecCustomScan = PgColumnarExecRuntimeFilter,
    .EndCustomScan = PgColumnarEndRuntimeFilter,
    .ReScanCustomScan = PgColumnarReScanRuntimeFilter,
    .ShutdownCustomScan = PgColumnarShutdownRuntimeFilter,
    .ExplainCustomScan = PgColumnarExplainRuntimeFilter,
};

static const CustomScanMethods PgColumnarRuntimeTapScanMethods = {
    .CustomName = "Columnar Runtime Filter Build Tap",
    .CreateCustomScanState = PgColumnarCreateRuntimeTapState,
};

static const CustomExecMethods PgColumnarRuntimeTapExecMethods = {
    .CustomName = "Columnar Runtime Filter Build Tap",
    .BeginCustomScan = PgColumnarBeginRuntimeTap,
    .ExecCustomScan = PgColumnarExecRuntimeTap,
    .EndCustomScan = PgColumnarEndRuntimeTap,
    .ReScanCustomScan = PgColumnarReScanRuntimeTap,
    .ExplainCustomScan = PgColumnarExplainRuntimeTap,
};

static Node *
PgColumnarStripRelabel(Node *node)
{
    while (node != NULL && IsA(node, RelabelType))
        node = (Node *) ((RelabelType *) node)->arg;

    return node;
}

static bool
PgColumnarRuntimeBaseScanPath(Path *path)
{
    CustomPath *customPath;

    if (path == NULL || !IsA(path, CustomPath))
        return false;

    customPath = (CustomPath *) path;
    return customPath->methods != NULL &&
           strcmp(customPath->methods->CustomName, "PgColumnarScan") == 0 &&
           customPath->custom_private == NIL &&
           path->param_info == NULL &&
           !path->parallel_aware &&
           path->parallel_workers == 0;
}

static bool
PgColumnarRuntimeFilterVars(PlannerInfo *root,
                            HashPath *hashPath,
                            Var **factVarOut,
                            Var **buildVarOut)
{
    RestrictInfo *restrictInfo;
    OpExpr *operatorExpr;
    Node *left;
    Node *right;
    Var *factVar;
    Var *buildVar;
    Relids factRelids;
    Relids buildRelids;
    RangeTblEntry *rte;

    if (list_length(hashPath->path_hashclauses) != 1)
        return false;

    restrictInfo = linitial_node(RestrictInfo, hashPath->path_hashclauses);
    if (!IsA(restrictInfo->clause, OpExpr))
        return false;

    operatorExpr = (OpExpr *) restrictInfo->clause;
    if (list_length(operatorExpr->args) != 2)
        return false;

    left = PgColumnarStripRelabel(linitial(operatorExpr->args));
    right = PgColumnarStripRelabel(lsecond(operatorExpr->args));
    if (!IsA(left, Var) || !IsA(right, Var))
        return false;

    factRelids = hashPath->jpath.outerjoinpath->parent->relids;
    buildRelids = hashPath->jpath.innerjoinpath->parent->relids;
    if (bms_is_member(((Var *) left)->varno, factRelids) &&
        bms_is_member(((Var *) right)->varno, buildRelids))
    {
        factVar = (Var *) left;
        buildVar = (Var *) right;
    }
    else if (bms_is_member(((Var *) right)->varno, factRelids) &&
             bms_is_member(((Var *) left)->varno, buildRelids))
    {
        factVar = (Var *) right;
        buildVar = (Var *) left;
    }
    else
        return false;

    if (factVar->varlevelsup != 0 || buildVar->varlevelsup != 0 ||
        factVar->varattno <= 0 || buildVar->varattno <= 0)
        return false;

    rte = planner_rt_fetch(factVar->varno, root);
    if (rte->rtekind != RTE_RELATION ||
        !PgColumnarIsColumnarRelation(rte->relid))
        return false;

    *factVarOut = factVar;
    *buildVarOut = buildVar;
    return true;
}

static HashPath *
PgColumnarPrivateHashPath(PlannerInfo *root,
                          RelOptInfo *joinrel,
                          HashPath *candidate,
                          JoinPathExtraData *extra)
{
    JoinCostWorkspace workspace;
    Path *outerPath = candidate->jpath.outerjoinpath;
    Path *innerPath = candidate->jpath.innerjoinpath;
    Relids requiredOuter;

    requiredOuter = calc_non_nestloop_required_outer(outerPath, innerPath);
    if (requiredOuter != NULL)
    {
        bms_free(requiredOuter);
        return NULL;
    }

    initial_cost_hashjoin(root,
                          &workspace,
                          candidate->jpath.jointype,
                          candidate->path_hashclauses,
                          outerPath,
                          innerPath,
                          extra,
                          false);

    return create_hashjoin_path(root,
                                joinrel,
                                candidate->jpath.jointype,
                                &workspace,
                                extra,
                                outerPath,
                                innerPath,
                                false,
                                extra->restrictlist,
                                NULL,
                                candidate->path_hashclauses);
}

static void
PgColumnarSetJoinPathlist(PlannerInfo *root,
                          RelOptInfo *joinrel,
                          RelOptInfo *outerrel,
                          RelOptInfo *innerrel,
                          JoinType jointype,
                          JoinPathExtraData *extra)
{
    HashPath *candidate = NULL;
    HashPath *privateHashPath;
    CustomPath *customPath;
    Var *factVar = NULL;
    Var *buildVar = NULL;
    ListCell *cell;
    Cost availableOuterWork;
    Cost cappedSaving;

    if (previous_set_join_pathlist_hook != NULL)
        previous_set_join_pathlist_hook(root,
                                        joinrel,
                                        outerrel,
                                        innerrel,
                                        jointype,
                                        extra);

    if (!pgcolumnar_enable_join_runtime_filter || jointype != JOIN_INNER)
        return;

    foreach(cell, joinrel->pathlist)
    {
        Path *path = lfirst(cell);
        HashPath *hashPath;

        if (!IsA(path, HashPath))
            continue;

        hashPath = (HashPath *) path;
        if (path->param_info != NULL ||
            path->parallel_aware ||
            path->parallel_workers != 0 ||
            hashPath->jpath.innerjoinpath->param_info != NULL ||
            !PgColumnarRuntimeBaseScanPath(hashPath->jpath.outerjoinpath) ||
            !PgColumnarRuntimeFilterVars(root,
                                         hashPath,
                                         &factVar,
                                         &buildVar))
            continue;

        candidate = hashPath;
        break;
    }

    if (candidate == NULL)
        return;

    privateHashPath = PgColumnarPrivateHashPath(root,
                                                joinrel,
                                                candidate,
                                                extra);
    if (privateHashPath == NULL)
        return;

    customPath = makeNode(CustomPath);
    customPath->path.pathtype = T_CustomScan;
    customPath->path.parent = joinrel;
    customPath->path.pathtarget = joinrel->reltarget;
    customPath->path.param_info = NULL;
    customPath->path.parallel_aware = false;
    customPath->path.parallel_safe = false;
    customPath->path.parallel_workers = 0;
    customPath->path.rows = privateHashPath->jpath.path.rows;
    customPath->path.disabled_nodes =
        privateHashPath->jpath.path.disabled_nodes;
    customPath->path.startup_cost =
        privateHashPath->jpath.path.startup_cost;

    /*
     * The eventual coordinator pays a spool cost and saves only fact-side work.
     * Until those measured costs are installed, cap the competing-path credit at
     * five percent of the core join and never below startup cost.  This makes the
     * choice deterministic without changing join order or inventing unbounded
     * savings.
     */
    availableOuterWork =
        Max(0.0,
            candidate->jpath.outerjoinpath->total_cost -
                candidate->jpath.outerjoinpath->startup_cost);
    cappedSaving = Min(availableOuterWork,
                       privateHashPath->jpath.path.total_cost * 0.05);
    customPath->path.total_cost =
        Max(customPath->path.startup_cost,
            privateHashPath->jpath.path.total_cost - cappedSaving);
    customPath->path.pathkeys = NIL;
    customPath->flags = 0;
    customPath->custom_paths = list_make1(privateHashPath);
    customPath->custom_private =
        list_make4(makeInteger(factVar->varattno),
                   makeInteger(buildVar->varno),
                   makeInteger(buildVar->varattno),
                   makeInteger(((OpExpr *) linitial_node(RestrictInfo,
                       candidate->path_hashclauses)->clause)->opno));
#if PG_VERSION_NUM >= 170000
    customPath->custom_restrictinfo = extra->restrictlist;
#endif
    customPath->methods = &PgColumnarRuntimeFilterPathMethods;

    /* add_path() may free candidate.  Nothing below this line reads it. */
    add_path(joinrel, &customPath->path);
}

static AttrNumber
PgColumnarFindKeyResno(Plan *plan, Index varno, AttrNumber attno)
{
    ListCell *cell;

    foreach(cell, plan->targetlist)
    {
        TargetEntry *entry = lfirst_node(TargetEntry, cell);
        Node *expr = PgColumnarStripRelabel((Node *) entry->expr);

        if (IsA(expr, Var) &&
            ((Var *) expr)->varno == varno &&
            ((Var *) expr)->varattno == attno)
            return entry->resno;
    }

    return InvalidAttrNumber;
}

static Plan *
PgColumnarPlanRuntimeFilterPath(PlannerInfo *root,
                                RelOptInfo *rel,
                                CustomPath *bestPath,
                                List *tlist,
                                List *clauses,
                                List *customPlans)
{
    CustomScan *customScan;
    CustomScan *tapScan;
    HashJoin *joinPlan;
    Hash *hashPlan;
    Plan *sourcePlan;
    Index buildVarno;
    AttrNumber buildAttno;
    AttrNumber keyResno;

    if (list_length(customPlans) != 1)
        elog(ERROR, "pgcolumnar runtime filter expected one core join plan");

    joinPlan = linitial_node(HashJoin, customPlans);
    if (!IsA(joinPlan, HashJoin) || !IsA(innerPlan(joinPlan), Hash))
        elog(ERROR, "pgcolumnar runtime filter expected a core Hash Join");

    hashPlan = (Hash *) innerPlan(joinPlan);
    sourcePlan = outerPlan(hashPlan);
    buildVarno = intVal(list_nth(bestPath->custom_private, 1));
    buildAttno = intVal(list_nth(bestPath->custom_private, 2));
    keyResno = PgColumnarFindKeyResno(sourcePlan, buildVarno, buildAttno);
    if (!AttributeNumberIsValid(keyResno))
        elog(ERROR, "pgcolumnar runtime filter could not locate the build key");

    tapScan = makeNode(CustomScan);
    tapScan->scan.plan.targetlist = copyObject(sourcePlan->targetlist);
    tapScan->scan.plan.qual = NIL;
    tapScan->scan.scanrelid = 0;
    tapScan->flags = 0;
    tapScan->custom_plans = list_make1(sourcePlan);
    tapScan->custom_private = list_make1(makeInteger(keyResno));
    tapScan->custom_scan_tlist = copyObject(sourcePlan->targetlist);
    tapScan->methods = &PgColumnarRuntimeTapScanMethods;
    outerPlan(hashPlan) = &tapScan->scan.plan;

    customScan = makeNode(CustomScan);
    customScan->scan.plan.targetlist = tlist;
    customScan->scan.plan.qual = NIL;
    customScan->scan.scanrelid = 0;
    customScan->flags = 0;
    customScan->custom_plans = list_make1(joinPlan);
    customScan->custom_private = copyObject(bestPath->custom_private);
    customScan->custom_scan_tlist = copyObject(joinPlan->join.plan.targetlist);
    customScan->methods = &PgColumnarRuntimeFilterScanMethods;

    return &customScan->scan.plan;
}

static Node *
PgColumnarCreateRuntimeFilterState(CustomScan *customScan)
{
    PgColumnarRuntimeFilterState *state = palloc0(sizeof(*state));

    state->customScanState.ss.ps.type = T_CustomScanState;
    state->customScanState.methods = &PgColumnarRuntimeFilterExecMethods;
    return (Node *) state;
}

static Node *
PgColumnarCreateRuntimeTapState(CustomScan *customScan)
{
    PgColumnarRuntimeTapState *state = palloc0(sizeof(*state));

    state->customScanState.ss.ps.type = T_CustomScanState;
    state->customScanState.methods = &PgColumnarRuntimeTapExecMethods;
    return (Node *) state;
}

static void
PgColumnarBeginRuntimeTap(CustomScanState *node,
                          EState *estate,
                          int eflags)
{
    PgColumnarRuntimeTapState *state = (PgColumnarRuntimeTapState *) node;
    CustomScan *customScan = (CustomScan *) node->ss.ps.plan;
    Plan *sourcePlan;

    if (list_length(customScan->custom_plans) != 1)
        elog(ERROR, "pgcolumnar runtime filter tap expected one source plan");

    sourcePlan = linitial_node(Plan, customScan->custom_plans);
    state->sourceState = ExecInitNode(sourcePlan, estate, eflags);
    node->custom_ps = list_make1(state->sourceState);
    state->keyResno = intVal(linitial(customScan->custom_private));
    state->keyType = TupleDescAttr(ExecGetResultType(state->sourceState),
                                   state->keyResno - 1)->atttypid;
    state->keyCollation = TupleDescAttr(ExecGetResultType(state->sourceState),
                                        state->keyResno - 1)->attcollation;
    get_typlenbyval(state->keyType,
                    &state->typeLength,
                    &state->typeByValue);
    {
        TypeCacheEntry *typeCache =
            lookup_type_cache(state->keyType, TYPECACHE_CMP_PROC_FINFO);

        if (OidIsValid(typeCache->cmp_proc_finfo.fn_oid))
        {
            fmgr_info_copy(&state->compareFn,
                           &typeCache->cmp_proc_finfo,
                           estate->es_query_cxt);
            state->intervalAvailable = true;
        }
    }
    state->valueContext =
        AllocSetContextCreate(estate->es_query_cxt,
                              "pgcolumnar runtime filter values",
                              ALLOCSET_SMALL_SIZES);
    state->store = tuplestore_begin_heap(true, false, work_mem);
    state->replaySlot = ExecInitExtraTupleSlot(estate,
                                               ExecGetResultType(state->sourceState),
                                               &TTSOpsMinimalTuple);
}

static void
PgColumnarRuntimeTapAddValue(PgColumnarRuntimeTapState *state, Datum value)
{
    MemoryContext oldContext;
    int32 comparison;

    if (!state->intervalAvailable)
        return;

    if (!state->hasValues)
    {
        oldContext = MemoryContextSwitchTo(state->valueContext);
        state->minimum = datumCopy(value,
                                   state->typeByValue,
                                   state->typeLength);
        state->maximum = datumCopy(value,
                                   state->typeByValue,
                                   state->typeLength);
        MemoryContextSwitchTo(oldContext);
        state->hasValues = true;
        return;
    }

    comparison = DatumGetInt32(FunctionCall2Coll(&state->compareFn,
                                                  state->keyCollation,
                                                  value,
                                                  state->minimum));
    if (comparison < 0)
    {
        if (!state->typeByValue)
            pfree(DatumGetPointer(state->minimum));
        oldContext = MemoryContextSwitchTo(state->valueContext);
        state->minimum = datumCopy(value,
                                   state->typeByValue,
                                   state->typeLength);
        MemoryContextSwitchTo(oldContext);
    }

    comparison = DatumGetInt32(FunctionCall2Coll(&state->compareFn,
                                                  state->keyCollation,
                                                  value,
                                                  state->maximum));
    if (comparison > 0)
    {
        if (!state->typeByValue)
            pfree(DatumGetPointer(state->maximum));
        oldContext = MemoryContextSwitchTo(state->valueContext);
        state->maximum = datumCopy(value,
                                   state->typeByValue,
                                   state->typeLength);
        MemoryContextSwitchTo(oldContext);
    }
}

static TupleTableSlot *
PgColumnarRuntimeTapOutput(CustomScanState *node, TupleTableSlot *sourceSlot)
{
    ExecCopySlot(node->ss.ss_ScanTupleSlot, sourceSlot);
    if (node->ss.ps.ps_ProjInfo != NULL)
        return ExecProject(node->ss.ps.ps_ProjInfo);
    return node->ss.ss_ScanTupleSlot;
}

static TupleTableSlot *
PgColumnarExecRuntimeTap(CustomScanState *node)
{
    PgColumnarRuntimeTapState *state = (PgColumnarRuntimeTapState *) node;
    TupleTableSlot *slot;

    if (state->replay)
    {
        ExecClearTuple(state->replaySlot);
        if (!tuplestore_gettupleslot(state->store,
                                     true,
                                     false,
                                     state->replaySlot))
            return NULL;
        return PgColumnarRuntimeTapOutput(node, state->replaySlot);
    }

    slot = ExecProcNode(state->sourceState);
    if (TupIsNull(slot))
        return NULL;

    tuplestore_puttupleslot(state->store, slot);
    {
        bool isNull;
        Datum value = slot_getattr(slot, state->keyResno, &isNull);

        if (!isNull)
        {
            state->buildRows++;
            PgColumnarRuntimeTapAddValue(state, value);
        }
    }
    return PgColumnarRuntimeTapOutput(node, slot);
}

static void
PgColumnarResetRuntimeTap(PgColumnarRuntimeTapState *state)
{
    tuplestore_clear(state->store);
    MemoryContextReset(state->valueContext);
    state->hasValues = false;
    state->buildRows = 0;
    state->replay = false;
    ExecReScan(state->sourceState);
}

static void
PgColumnarEndRuntimeTap(CustomScanState *node)
{
    PgColumnarRuntimeTapState *state = (PgColumnarRuntimeTapState *) node;

    if (state->store != NULL)
        tuplestore_end(state->store);
    if (state->valueContext != NULL)
        MemoryContextDelete(state->valueContext);
    ExecEndNode(state->sourceState);
}

static void
PgColumnarReScanRuntimeTap(CustomScanState *node)
{
    PgColumnarResetRuntimeTap((PgColumnarRuntimeTapState *) node);
}

static void
PgColumnarExplainRuntimeTap(CustomScanState *node,
                            List *ancestors,
                            ExplainState *es)
{
    PgColumnarRuntimeTapState *state = (PgColumnarRuntimeTapState *) node;

    ExplainPropertyInteger("Runtime Filter Build Rows",
                           NULL,
                           (int64) state->buildRows,
                           es);
}

static void
PgColumnarBeginRuntimeFilter(CustomScanState *node,
                             EState *estate,
                             int eflags)
{
    PgColumnarRuntimeFilterState *state =
        (PgColumnarRuntimeFilterState *) node;
    CustomScan *customScan = (CustomScan *) node->ss.ps.plan;
    Plan *childPlan;
    HashJoinState *joinState;
    HashState *hashState;

    if (list_length(customScan->custom_plans) != 1)
        elog(ERROR,
             "pgcolumnar runtime filter expected one core Hash Join plan");

    childPlan = linitial_node(Plan, customScan->custom_plans);
    state->joinState = ExecInitNode(childPlan, estate, eflags);
    if (!IsA(state->joinState, HashJoinState))
        elog(ERROR,
             "pgcolumnar runtime filter expected one core Hash Join state");

    joinState = (HashJoinState *) state->joinState;
    hashState = (HashState *) innerPlanState(joinState);
    if (!IsA(hashState, HashState) ||
        !IsA(outerPlanState(hashState), CustomScanState))
        elog(ERROR, "pgcolumnar runtime filter expected a build tap");

    state->tapState = (CustomScanState *) outerPlanState(hashState);
    state->factAttno = intVal(linitial(customScan->custom_private));
    node->custom_ps = list_make1(state->joinState);
}

static void
PgColumnarPrepareRuntimeFilter(PgColumnarRuntimeFilterState *state)
{
    PgColumnarRuntimeTapState *tapState =
        (PgColumnarRuntimeTapState *) state->tapState;

    while (!TupIsNull(ExecProcNode((PlanState *) state->tapState)))
        CHECK_FOR_INTERRUPTS();

    if (tapState->hasValues && tapState->intervalAvailable)
        state->rangeAttached =
            PgColumnarAttachRuntimeRange(outerPlanState(state->joinState),
                                         state->factAttno,
                                         tapState->keyType,
                                         tapState->minimum,
                                         tapState->maximum);

    tapState->replay = true;
    tuplestore_rescan(tapState->store);
    state->prepared = true;
}

static TupleTableSlot *
PgColumnarExecRuntimeFilter(CustomScanState *node)
{
    PgColumnarRuntimeFilterState *state =
        (PgColumnarRuntimeFilterState *) node;

    if (!state->prepared)
        PgColumnarPrepareRuntimeFilter(state);

    return ExecProcNode(state->joinState);
}

static void
PgColumnarEndRuntimeFilter(CustomScanState *node)
{
    PgColumnarRuntimeFilterState *state =
        (PgColumnarRuntimeFilterState *) node;

    ExecEndNode(state->joinState);
}

static void
PgColumnarReScanRuntimeFilter(CustomScanState *node)
{
    PgColumnarRuntimeFilterState *state =
        (PgColumnarRuntimeFilterState *) node;

    ExecReScan(state->joinState);
    PgColumnarResetRuntimeTap((PgColumnarRuntimeTapState *) state->tapState);
    state->rangeAttached = false;
    state->prepared = false;
}

static void
PgColumnarShutdownRuntimeFilter(CustomScanState *node)
{
    /*
     * ExecShutdownNode already walks custom_ps before invoking this callback.
     * Explicitly shutting down the child here would do so twice.
     */
}

static void
PgColumnarExplainRuntimeFilter(CustomScanState *node,
                               List *ancestors,
                               ExplainState *es)
{
    PgColumnarRuntimeFilterState *state =
        (PgColumnarRuntimeFilterState *) node;

    ExplainPropertyBool("Runtime Filter Ready", state->prepared, es);
}

void
PgColumnarRuntimeFilterInit(void)
{
    RegisterCustomScanMethods(&PgColumnarRuntimeFilterScanMethods);
    RegisterCustomScanMethods(&PgColumnarRuntimeTapScanMethods);
    previous_set_join_pathlist_hook = set_join_pathlist_hook;
    set_join_pathlist_hook = PgColumnarSetJoinPathlist;
}
