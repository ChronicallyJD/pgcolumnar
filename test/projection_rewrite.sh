#!/usr/bin/env bash
#
# pgColumnar: a declared projection must survive a rewrite (#876, #887).
#
# #876 reports the symptom: pgcolumnar.read_projection raises 42704 after a
# rewrite, for a projection that is still declared over an intact base table.
# Three properties must hold after ANY rewrite, and before this suite nothing in
# the tree asserted the first of them:
#
#   P1  read_projection answers, and holds exactly the rows the base table holds.
#   P2  no pgcolumnar.projection row names a storage id the table no longer has.
#   P3  the declaration survives, so a rebuild is always possible.
#
# Two traps this suite is built around.
#
# An arm that asserts only "read_projection did not raise" passes on a tree where
# the projection was re-recorded EMPTY, so every arm compares pgc_set_hash
# against the base table rather than counting rows or checking for an error.
#
# And an operation that FAILED or that no-opped leaves the storage id unchanged
# and read_projection answering -- indistinguishable from an operation that
# handled projections correctly. Three rows of #887's table were vacuous that
# way. So every arm asserts what the operation DID (REWROTE / NOOP / FAILED)
# before its outcome is allowed to mean anything.
#
# Usage:  test/projection_rewrite.sh [PG_CONFIG]
#
# Written fresh for pgColumnar; it does not reuse any upstream test file.

set -uo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

pgc_setup "${1:-/usr/local/pg17/bin/pg_config}"

N=5000

# ---------------------------------------------------------------------------
# Premises. Every verdict below is vacuous if the fixture is not what it says,
# so these run first and are checks in their own right.
# ---------------------------------------------------------------------------
psql_run "CREATE TABLE prem (id int, a int, b text) USING pgcolumnar;"
psql_run "INSERT INTO prem SELECT g, g%50, 'b'||g FROM generate_series(1,$N) g;"
psql_run "SELECT pgcolumnar.add_projection('prem','pp',ARRAY['a','b'],ARRAY['a']);"
check "PREMISE base holds its rows" "$(q 'SELECT count(*) FROM prem;')" "$N"
check "PREMISE projection answers before any rewrite" \
	"$(q "SELECT count(*) FROM pgcolumnar.read_projection('prem','pp');")" "$N"
check "PREMISE projection agrees with base before any rewrite" \
	"$(pgc_set_hash "SELECT pgcolumnar.read_projection('prem','pp')")" \
	"$(pgc_set_hash "SELECT a::text||'|'||b FROM prem")"
check "PREMISE two catalog rows under the current storage" \
	"$(q "SELECT count(*) FROM pgcolumnar.projection WHERE storage_id = pgcolumnar.get_storage_id('prem');")" "2"

# P2's oracle: a projection row whose storage id is not the CURRENT storage id of
# any live columnar relation. It must read 0 at every point in this suite.
#
# NOT "has no pgcolumnar.storage row", which is what this asserted first and is
# wrong in a way that made it pass for the wrong reason. A storage row is written
# on the first WRITE, not when the storage is created, so straight after a
# TRUNCATE the table's own current storage has no row -- and a correctly
# re-recorded projection under it read as retired. The version below asks the
# question the property is about, and it is deliberately GLOBAL: a row orphaned
# under any table is a leak, whichever arm caused it.
#
# This arm is a guard, not the detector for #876. It reads 0 on unmodified main
# too, because pgcolumnar_delete_storage_tree deletes the rows rather than
# stranding them (#867). It is here to redden if a fix strands them instead --
# which re-recording in the wrong place does.
retired_rows() {
	q "SELECT count(*) FROM pgcolumnar.projection p
	    WHERE NOT EXISTS (
	        SELECT 1 FROM pg_class c JOIN pg_am am ON am.oid = c.relam
	         WHERE am.amname = 'pgcolumnar' AND c.relkind = 'r'
	           AND pgcolumnar.get_storage_id(c.oid) = p.storage_id);"
}
check "PREMISE no retired projection rows to begin with" "$(retired_rows)" "0"

# ---------------------------------------------------------------------------
# One arm: build a fixture, run one operation, assert all three properties.
#
#   $1 table    $2 operation SQL    $3 what the operation must DO
#   $4 the base-table projection of the covered columns, AFTER the operation
# ---------------------------------------------------------------------------
arm() {
	local tag="$1" op="$2" wantdid="$3" oracle="$4"
	local sid0 did err

	psql_run "CREATE TABLE $tag (id int, a int, b text) USING pgcolumnar;" >/dev/null
	psql_run "INSERT INTO $tag SELECT g, g%50, 'b'||g FROM generate_series(1,$N) g;" >/dev/null
	psql_run "SELECT pgcolumnar.add_projection('$tag','pp',ARRAY['a','b'],ARRAY['a']);" >/dev/null
	sid0="$(q "SELECT pgcolumnar.get_storage_id('$tag');")"

	if err="$(psql_run "$op" 2>&1)"; then
		[ "$sid0" = "$(q "SELECT pgcolumnar.get_storage_id('$tag');")" ] && did=NOOP || did=REWROTE
	else
		did="FAILED"
	fi

	# The gate. An operation that did not do what the arm is about proves
	# nothing either way, so the properties are not reported for it.
	if [ "$did" != "$wantdid" ]; then
		pgc_fail "$tag: operation must $wantdid" \
			"got $did${err:+ — $(sed -nE 's/.*(ERROR:.*)$/\1/p' <<<"$err" | head -1)}"
		check_unrunnable "$tag P1 projection agrees with base" \
			UNMET_PRECONDITION "operation did not $wantdid"
		check_unrunnable "$tag P2 no retired projection rows" \
			UNMET_PRECONDITION "operation did not $wantdid"
		check_unrunnable "$tag P3 declaration survives" \
			UNMET_PRECONDITION "operation did not $wantdid"
		return
	fi
	pgc_pass "$tag: operation $wantdid"

	# P1 -- the projection holds exactly what the base holds. Compared as a set
	# hash, so a projection re-recorded EMPTY fails here rather than passing on
	# "read_projection did not raise". read_projection raising is also a failure:
	# pgc_set_hash of a failed query returns empty, which cannot equal the
	# oracle unless the base is empty too -- and where the base IS empty the
	# oracle is the EMPTY sentinel, which a raised error still does not produce.
	check "$tag P1 projection agrees with base" \
		"$(pgc_set_hash "SELECT pgcolumnar.read_projection('$tag','pp')")" \
		"$(pgc_set_hash "$oracle")"
	check "$tag P2 no retired projection rows" "$(retired_rows)" "0"
	check "$tag P3 declaration survives" \
		"$(q "SELECT count(*) FROM pgcolumnar.projection_declaration
		       WHERE rel = '$tag'::regclass AND name = 'pp';")" "1"
}

echo "-- the rewrites that lose the projection today (#876)"

# TRUNCATE then re-INSERT: the projection must answer with the NEW rows.
arm t_trunc_reinsert \
	"TRUNCATE t_trunc_reinsert;
	 INSERT INTO t_trunc_reinsert SELECT g, g%7, 'z'||g FROM generate_series(1,100) g;" \
	REWROTE \
	"SELECT a::text||'|'||b FROM t_trunc_reinsert"

# TRUNCATE alone. The correct end state is a projection that answers and is
# EMPTY, which is why the oracle is the base table rather than a row count: an
# arm demanding rows would be wrong here and right for every other arm.
arm t_trunc_empty "TRUNCATE t_trunc_empty;" REWROTE \
	"SELECT a::text||'|'||b FROM t_trunc_empty"

# A type change on a COVERED column. The stored value must come back under the
# new type, so the oracle is read after the ALTER, not before.
arm t_altertype "ALTER TABLE t_altertype ALTER COLUMN a TYPE bigint;" REWROTE \
	"SELECT a::text||'|'||b FROM t_altertype"

# A type change on a column the projection does NOT cover still rewrites the
# whole table, so it loses the projection just the same.
arm t_altertype_unc "ALTER TABLE t_altertype_unc ALTER COLUMN id TYPE bigint;" REWROTE \
	"SELECT a::text||'|'||b FROM t_altertype_unc"

# ADD COLUMN with a volatile default rewrites AND changes the live column set.
# The base projection (projection_id 0) records all live columns, so a fix that
# copies the old row verbatim leaves it naming a stale column set -- which no
# arm above would catch, because pp does not cover the new column.
arm t_addcol_vol \
	"ALTER TABLE t_addcol_vol ADD COLUMN zz double precision DEFAULT random();" \
	REWROTE "SELECT a::text||'|'||b FROM t_addcol_vol"

# TRUNCATE naming SEVERAL tables rewrites every one of them, so a fix that
# repairs only the first relation in the statement passes every arm above.
psql_run "CREATE TABLE t_trunc_two (id int, a int, b text) USING pgcolumnar;" >/dev/null
psql_run "INSERT INTO t_trunc_two SELECT g, g%50, 'b'||g FROM generate_series(1,$N) g;" >/dev/null
psql_run "SELECT pgcolumnar.add_projection('t_trunc_two','pp',ARRAY['a','b'],ARRAY['a']);" >/dev/null
arm t_trunc_multi "TRUNCATE t_trunc_multi, t_trunc_two;" REWROTE \
	"SELECT a::text||'|'||b FROM t_trunc_multi"
check "t_trunc_multi: the SECOND table in the statement also survives" \
	"$(pgc_set_hash "SELECT pgcolumnar.read_projection('t_trunc_two','pp')")" \
	"$(pgc_set_hash "SELECT a::text||'|'||b FROM t_trunc_two")"

# TRUNCATE ... CASCADE reaches a table through a FOREIGN KEY. That table is not
# named in the statement and is not an inheritance descendant of anything named, so
# a repair that walks the statement's relation list plus find_all_inheritors never
# visits it (@linuxhikerpm, #892 review). The repair therefore records what the
# table-AM callback actually rewrote instead of re-deriving the statement's reach.
#
# The parent here is a HEAP table with no projections of its own, so the only thing
# that can make this arm pass is the child being repaired.
echo "-- a columnar table truncated through a foreign-key CASCADE"
psql_run "CREATE TABLE cas_parent (id int PRIMARY KEY);"
psql_run "CREATE TABLE cas_child (id int REFERENCES cas_parent(id), v int) USING pgcolumnar;"
psql_run "SELECT pgcolumnar.add_projection('cas_child','pv',ARRAY['id','v'],ARRAY['v']);"
psql_run "INSERT INTO cas_parent SELECT g FROM generate_series(1,$N) g;"
psql_run "INSERT INTO cas_child SELECT g, g%7 FROM generate_series(1,$N) g;"
check "PREMISE the cascade fixture reads before the truncate" \
	"$(q "SELECT count(*) FROM pgcolumnar.read_projection('cas_child','pv');")" "$N"
CAS_SID0="$(q "SELECT pgcolumnar.get_storage_id('cas_child');")"
psql_run "TRUNCATE cas_parent CASCADE;"
if [ "$CAS_SID0" = "$(q "SELECT pgcolumnar.get_storage_id('cas_child');")" ]; then
	# If the cascade did not rewrite the child there is nothing to repair, and the
	# arm below would pass for the wrong reason.
	check_unrunnable "cas_child P1 the cascaded child keeps its projection" \
		UNMET_PRECONDITION "the CASCADE did not rewrite the child"
else
	pgc_pass "cas_child: the CASCADE rewrote the child"
	check "cas_child P1 the cascaded child keeps its projection" \
		"$(pgc_set_hash "SELECT pgcolumnar.read_projection('cas_child','pv')")" \
		"$(pgc_set_hash "SELECT id::text||'|'||v::text FROM cas_child")"
	check "cas_child P2 no retired projection rows" "$(retired_rows)" "0"
	check "cas_child P3 declaration survives" \
		"$(q "SELECT count(*) FROM pgcolumnar.projection_declaration
		       WHERE rel = 'cas_child'::regclass AND name = 'pv';")" "1"
fi

# A partitioned CHILD, rewritten by a type change on the PARENT. The statement
# names pt, the rewrite lands on pt1, and pt is not itself a columnar relation --
# so a fix that looks only at the relation named in the statement never fires
# here. This is the same reason the #778 rename block walks find_all_inheritors.
echo "-- a partitioned child rewritten through its parent"
psql_run "CREATE TABLE ptr (id int, a int, b text) PARTITION BY RANGE (id);"
psql_run "CREATE TABLE ptr1 PARTITION OF ptr FOR VALUES FROM (1) TO (100000) USING pgcolumnar;"
psql_run "INSERT INTO ptr SELECT g, g%50, 'b'||g FROM generate_series(1,$N) g;"
psql_run "SELECT pgcolumnar.add_projection('ptr1','pp',ARRAY['a','b'],ARRAY['a']);"
PTR_SID0="$(q "SELECT pgcolumnar.get_storage_id('ptr1');")"
psql_run "ALTER TABLE ptr ALTER COLUMN a TYPE bigint;"
if [ "$PTR_SID0" = "$(q "SELECT pgcolumnar.get_storage_id('ptr1');")" ]; then
	check_unrunnable "ptr1 P1 child projection agrees with base" \
		UNMET_PRECONDITION "the parent-level ALTER did not rewrite the child"
else
	pgc_pass "ptr1: parent-level ALTER rewrote the child"
	check "ptr1 P1 child projection agrees with base" \
		"$(pgc_set_hash "SELECT pgcolumnar.read_projection('ptr1','pp')")" \
		"$(pgc_set_hash "SELECT a::text||'|'||b FROM ptr1")"
fi

echo "-- and the base projection must still name every live column"
check "t_addcol_vol base projection covers the added column" \
	"$(q "SELECT columns FROM pgcolumnar.projection
	       WHERE storage_id = pgcolumnar.get_storage_id('t_addcol_vol')
	         AND projection_id = 0;")" \
	"{1,2,3,4}"

echo "-- the rewrites that already handle projections: regression arms"
# These are GREEN on main. pgcolumnar_compact_relation and its siblings re-record
# after RelationSetNewRelfilenumber, which dispatches through the same table-AM
# callback the arms above go through. So a fix placed IN that callback double-
# records for these three and violates projection_pkey (storage_id,
# projection_id). They are here to redden if that happens.
arm r_vacuum      "SELECT pgcolumnar.vacuum('r_vacuum');"                 REWROTE \
	"SELECT a::text||'|'||b FROM r_vacuum"
arm r_vacsorted   "SELECT pgcolumnar.vacuum_sorted('r_vacsorted','a');"   REWROTE \
	"SELECT a::text||'|'||b FROM r_vacsorted"
arm r_cluster     "SELECT pgcolumnar.cluster('r_cluster','a');"           REWROTE \
	"SELECT a::text||'|'||b FROM r_cluster"

# ---------------------------------------------------------------------------
# The re-record must never abort the statement that triggered it.
#
# A declaration can name a column the relation no longer has: ALTER TABLE ...
# RENAME COLUMN does not carry the rename through projection_declaration's
# columns/sort_key arrays (#888). The re-record resolves those NAMES against the
# relation as it is now, so on such a table it cannot materialise the projection.
#
# What it must not do is take the user's statement down with it. Measured before
# this arm existed: the re-record raised `column "a" does not exist` inside an
# unrelated ALTER TABLE ... ALTER COLUMN id TYPE bigint, exit 1, and the type
# change was rolled back -- turning a silently lost projection into a blocked
# schema change. A repair that cannot run must degrade to a WARNING and leave
# the projection for rebuild_projections, which is the documented recovery.
#
# This arm is independent of whether #888 lands: a declaration can also go stale
# through a path nobody has closed yet, and the statement must survive either way.
echo "-- a stale declaration must not abort the statement (#888 interaction)"
psql_run "CREATE TABLE stale (id int, a int, b text) USING pgcolumnar;"
psql_run "INSERT INTO stale SELECT g, g%50, 'b'||g FROM generate_series(1,$N) g;"
psql_run "SELECT pgcolumnar.add_projection('stale','pp',ARRAY['a','b'],ARRAY['a']);"
psql_run "ALTER TABLE stale RENAME COLUMN a TO a2;"
STALE_DECL="$(q "SELECT columns::text FROM pgcolumnar.projection_declaration WHERE rel='stale'::regclass;")"
if [ "$STALE_DECL" = "{a,b}" ]; then
	pgc_pass "PREMISE the rename left the declaration naming a dead column"
else
	# #888 landing makes this premise false, and then the arm below is vacuous
	# rather than passing: it can only test a statement that must survive a
	# stale declaration if the declaration is actually stale.
	check_unrunnable "stale: the statement survives a stale declaration" \
		UNMET_PRECONDITION "declaration is $STALE_DECL, not stale; #888 may have landed"
	check_unrunnable "stale: the base table keeps its rows" \
		UNMET_PRECONDITION "declaration is $STALE_DECL, not stale; #888 may have landed"
	check_unrunnable "stale: the unrelated type change took effect" \
		UNMET_PRECONDITION "declaration is $STALE_DECL, not stale; #888 may have landed"
fi
if [ "$STALE_DECL" = "{a,b}" ]; then
	if psql_run "ALTER TABLE stale ALTER COLUMN id TYPE bigint;" >/dev/null 2>&1; then
		pgc_pass "stale: the statement survives a stale declaration"
	else
		pgc_fail "stale: the statement survives a stale declaration" \
			"the re-record aborted an unrelated ALTER TABLE"
	fi
	check "stale: the base table keeps its rows" "$(q 'SELECT count(*) FROM stale;')" "$N"
	check "stale: the unrelated type change took effect" \
		"$(q "SELECT format_type(atttypid,atttypmod) FROM pg_attribute
		       WHERE attrelid='stale'::regclass AND attname='id';")" "bigint"

	# A skip the user is never told about is a silent projection loss, which is
	# the whole complaint in #876. Assert the WARNING from its own output, and
	# assert the negative control in the same breath: a table whose declaration
	# is intact must not produce one, or the arm passes on a warning that fires
	# unconditionally.
	psql_run "CREATE TABLE stale2 (id int, a int, b text) USING pgcolumnar;" >/dev/null
	psql_run "INSERT INTO stale2 SELECT g, g%50, 'b'||g FROM generate_series(1,$N) g;" >/dev/null
	psql_run "SELECT pgcolumnar.add_projection('stale2','pp',ARRAY['a','b'],ARRAY['a']);" >/dev/null
	psql_run "ALTER TABLE stale2 RENAME COLUMN a TO a2;" >/dev/null
	check "stale: the skip warns, naming the projection and the recovery" \
		"$(psql_run "ALTER TABLE stale2 ALTER COLUMN id TYPE bigint;" 2>&1 |
		    grep -cE 'WARNING:.*could not restore projection "pp"|rebuild_projections')" "2"
	psql_run "CREATE TABLE fresh2 (id int, a int, b text) USING pgcolumnar;" >/dev/null
	psql_run "INSERT INTO fresh2 SELECT g, g%50, 'b'||g FROM generate_series(1,$N) g;" >/dev/null
	psql_run "SELECT pgcolumnar.add_projection('fresh2','pp',ARRAY['a','b'],ARRAY['a']);" >/dev/null
	check "stale: an intact declaration produces NO warning" \
		"$(psql_run "ALTER TABLE fresh2 ALTER COLUMN id TYPE bigint;" 2>&1 |
		    grep -ci warning)" "0"
fi

echo "-- rebuild_projections stays the documented manual recovery (#876)"
psql_run "CREATE TABLE rec (id int, a int, b text) USING pgcolumnar;"
psql_run "INSERT INTO rec SELECT g, g%50, 'b'||g FROM generate_series(1,$N) g;"
psql_run "SELECT pgcolumnar.add_projection('rec','pp',ARRAY['a','b'],ARRAY['a']);"
psql_run "TRUNCATE rec; INSERT INTO rec SELECT g, g%9, 'y'||g FROM generate_series(1,200) g;"
psql_run "SELECT pgcolumnar.rebuild_projections('rec');" >/dev/null 2>&1
check "rebuild_projections still repairs a lost projection" \
	"$(pgc_set_hash "SELECT pgcolumnar.read_projection('rec','pp')")" \
	"$(pgc_set_hash "SELECT a::text||'|'||b FROM rec")"
check "and leaves no retired projection rows" "$(retired_rows)" "0"

pgc_summary
