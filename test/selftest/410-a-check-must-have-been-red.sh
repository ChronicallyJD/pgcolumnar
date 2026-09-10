# ---- a check must have been seen red, or be counted as debt -----------------
#
# Nothing records whether a check has ever been red. That is the gap that let 39
# checks across 35 suites ship unable to fail, three of them inside this very
# suite. The gate answers "did anything print FAIL" and has never answered "could
# anything print FAIL".
#
# An audit fixes today; only a ledger keeps it fixed. And a ledger somebody
# maintains is a hand-maintained count, which this repository has spent a day
# proving the cost of: nine collisions on one written number, both sides wrong
# every time. So the ledger is DERIVED FROM RUNS. The only hand-written numbers
# are the two budgets, and they may only go down.
#
# WHAT THIS LEDGER CLAIMS, AND WHAT IT DOES NOT. It records that a named check
# WAS OBSERVED RED in a recorded run. It does NOT claim the check is proven able
# to fail: that is a stronger statement, it needs a named mutation applied
# deliberately, and conflating the two would put a claim in the ledger that
# nothing measured. v1 fills the observed column honestly and leaves the rest as
# debt, counted.
# ---------------------------------------------------------------------------

_led="$PGC_TESTDIR/pgc_ledger.py"
_ledger="$PGC_TESTDIR/check_ledger.tsv"
_budget="$PGC_TESTDIR/check_ledger_budget.txt"

check "premise: the ledger tool exists" "$([ -f "$_led" ] && echo yes || echo no)" "yes"
check "premise: the ledger itself is a tracked file, not a variable" \
	"$([ -f "$_ledger" ] && echo yes || echo no)" "yes"
check "premise: the budget is a tracked file too" \
	"$([ -f "$_budget" ] && echo yes || echo no)" "yes"

_lw="$PGC_WORKDIR/ledger"; mkdir -p "$_lw"
_led_run() { python3 "$_led" "$@" 2>&1; }

# ---- the census comes out of a run, not out of a list -----------------------

cat > "$_lw/green.log" <<'LOG'
RESULT	demo	part1	first check	PASS	
RESULT	demo	part1	second check	PASS	
checks run: 2
LOG

check "the census reads a run's records" \
	"$(_led_run census "$_lw/green.log" | wc -l)" "2"
check "and names the suite and the check, not just a count" \
	"$(_led_run census "$_lw/green.log" | head -1)" "demo	part1	first check	PASS"

# ---- merging a green run adds the checks as DEBT, not as proven -------------
#
# The arm that matters. A green run has seen nothing go red, so merging one must
# never record a red observation. Anything else would let an ordinary CI run
# retire the debt it exists to count.

: > "$_lw/ledger.tsv"
_led_run merge --ledger "$_lw/ledger.tsv" "$_lw/green.log" >/dev/null
check "merging a green run records both checks" \
	"$(grep -c . "$_lw/ledger.tsv")" "2"
check "and records neither as ever having been red" \
	"$(cut -f4 "$_lw/ledger.tsv" | sort -u | tr '\n' ' ')" "never "

# ---- merging a run that DID go red records the observation ------------------

cat > "$_lw/red.log" <<'LOG'
RESULT	demo	part1	first check	FAIL	
RESULT	demo	part1	second check	PASS	
checks run: 2
LOG

_led_run merge --ledger "$_lw/ledger.tsv" --date 2026-09-10 "$_lw/red.log" >/dev/null
check "a check observed red gains the date it was seen" \
	"$(awk -F'\t' '$3=="first check"{print $4}' "$_lw/ledger.tsv")" "2026-09-10"
check "and a check that stayed green keeps its debt" \
	"$(awk -F'\t' '$3=="second check"{print $4}' "$_lw/ledger.tsv")" "never"

# An observation is not undone by a later green run. The ledger records that the
# check WAS seen red, which stays true.
_led_run merge --ledger "$_lw/ledger.tsv" --date 2026-09-11 "$_lw/green.log" >/dev/null
check "a later green run does not erase an observation" \
	"$(awk -F'\t' '$3=="first check"{print $4}' "$_lw/ledger.tsv")" "2026-09-10"

# ---- the gate: new checks must not be added to the debt silently ------------
#
# A gate that fails on 3,762 unledgered checks is a gate somebody disables under
# deadline, and then we are back at PGC_SKIP_TIMING with extra steps. So the
# budget grandfathers what exists and refuses to grow.

printf 'suites_not_covered 0\nchecks_never_observed_red 1\n' > "$_lw/budget.txt"
check "a run whose debt is within budget passes the gate" \
	"$(_led_run gate --ledger "$_lw/ledger.tsv" --budget "$_lw/budget.txt" "$_lw/green.log" >/dev/null 2>&1 \
		&& echo ok || echo over)" "ok"

printf 'suites_not_covered 0\nchecks_never_observed_red 0\n' > "$_lw/budget.txt"
check "and one over budget does not" \
	"$(_led_run gate --ledger "$_lw/ledger.tsv" --budget "$_lw/budget.txt" "$_lw/green.log" >/dev/null 2>&1 \
		&& echo ok || echo over)" "over"
check "and the gate says which number was exceeded, by how much" \
	"$(_led_run gate --ledger "$_lw/ledger.tsv" --budget "$_lw/budget.txt" "$_lw/green.log" 2>&1 \
		| grep -c 'checks_never_observed_red: 1 exceeds the budget of 0')" "1"

# A check the run produced that the ledger has never heard of is the case the
# allowlist exists for: it is NEW, and it must not enter as silent debt.
printf 'suites_not_covered 0\nchecks_never_observed_red 1\n' > "$_lw/budget.txt"
cat > "$_lw/newcheck.log" <<'LOG'
RESULT	demo	part1	first check	PASS	
RESULT	demo	part1	second check	PASS	
RESULT	demo	part1	a brand new check	PASS	
checks run: 3
LOG
check "a check the ledger has never seen is refused, not absorbed" \
	"$(_led_run gate --ledger "$_lw/ledger.tsv" --budget "$_lw/budget.txt" "$_lw/newcheck.log" >/dev/null 2>&1 \
		&& echo ok || echo refused)" "refused"
check "and it is named, so the author knows which one" \
	"$(_led_run gate --ledger "$_lw/ledger.tsv" --budget "$_lw/budget.txt" "$_lw/newcheck.log" 2>&1 \
		| grep -c 'not in the ledger: demo	part1	a brand new check')" "1"

# ---- the budget may only go DOWN --------------------------------------------
#
# Both numbers are debt. A change that raises either is a change that adds debt,
# and it must be visible in a diff as exactly that rather than as a passing gate.

check "the committed budget names both debts" \
	"$(grep -cE '^(suites_not_covered|checks_never_observed_red) [0-9]+$' "$_budget")" "2"

# ---- inputs == sum(buckets), over the real ledger ---------------------------

_l_total="$(grep -c . "$_ledger" || true)"
_l_red="$(awk -F'\t' '$4!="never"' "$_ledger" | grep -c . || true)"
_l_never="$(awk -F'\t' '$4=="never"' "$_ledger" | grep -c . || true)"
echo "  ledger: inputs=$_l_total | observed red=$_l_red, never=$_l_never | sum=$((_l_red + _l_never))"
check "the ledger partitions into observed and never" \
	"$((_l_red + _l_never))" "$_l_total"
check "premise: the ledger is not empty, so the partition means something" \
	"$([ "$_l_total" -gt 0 ] && echo yes || echo no)" "yes"

# The committed budget must match the committed ledger. If it does not, one of
# the two was edited by hand -- which is the failure this whole design refuses.
check "the committed budget matches the committed ledger's debt" \
	"$(sed -n 's/^checks_never_observed_red //p' "$_budget")" "$_l_never"

# ---- a rename is not a new check, and must not look like one ----------------
#
# The ledger is keyed by check NAME, and check names in this harness are prose --
# they are renamed freely, which is most of why #917 exists. So a rename loses
# the check's history and reads exactly like a brand-new check that has never
# been red, which is the ONE state the ledger exists to distinguish.
#
# Raised by OffgridwithJD, who also named the detector: a name appearing with no
# history in the same run another disappears is a rename, and the ledger should
# SAY so rather than quietly resetting a count to `never`. It is the same
# both-directions set comparison as the suite reconciliation, over check names.
#
# The alternative -- a synthetic stable id -- would have to be maintained, and
# this repository removed a hand-maintained list today for that exact reason.

: > "$_lw/ren.tsv"
cat > "$_lw/before.log" <<'LOG'
RESULT	demo	part1	the old name	FAIL	
RESULT	demo	part1	a stable check	PASS	
checks run: 2
LOG
_led_run merge --ledger "$_lw/ren.tsv" --date 2026-09-01 "$_lw/before.log" >/dev/null
check "premise: the check has history before the rename" \
	"$(awk -F'\t' '$3=="the old name"{print $4}' "$_lw/ren.tsv")" "2026-09-01"

cat > "$_lw/after.log" <<'LOG'
RESULT	demo	part1	the new name	PASS	
RESULT	demo	part1	a stable check	PASS	
checks run: 2
LOG
check "a name that appeared while another disappeared is reported as a rename" \
	"$(_led_run rename-scan --ledger "$_lw/ren.tsv" "$_lw/after.log" 2>&1 \
		| grep -c 'possible rename: the old name -> the new name')" "1"
check "and the stable check is not reported" \
	"$(_led_run rename-scan --ledger "$_lw/ren.tsv" "$_lw/after.log" 2>&1 \
		| grep -c 'a stable check')" "0"

# The detector must not fire when a check is simply ADDED. Without this it names
# a rename on every new check, which is noise that gets it ignored.
cat > "$_lw/added.log" <<'LOG'
RESULT	demo	part1	the old name	PASS	
RESULT	demo	part1	a stable check	PASS	
RESULT	demo	part1	a genuinely new check	PASS	
checks run: 3
LOG
check "a check merely added is not reported as a rename" \
	"$(_led_run rename-scan --ledger "$_lw/ren.tsv" "$_lw/added.log" 2>&1 \
		| grep -c 'possible rename')" "0"

# Nor when one is simply REMOVED.
cat > "$_lw/removed.log" <<'LOG'
RESULT	demo	part1	a stable check	PASS	
checks run: 1
LOG
check "a check merely removed is not reported as a rename either" \
	"$(_led_run rename-scan --ledger "$_lw/ren.tsv" "$_lw/removed.log" 2>&1 \
		| grep -c 'possible rename')" "0"

# ---- the mutation field, present from v1 even though nothing fills it -------
#
# If an entry can record WHICH mutation reddened a check, the mutation catalogue
# builds itself out of work people already do by hand -- the vacuity branches are
# writing nine to eleven per change tonight, each chosen to revert one property.
# OffgridwithJD's point, and the reason the column exists now: adding it later
# means rewriting every entry.
#
# NOTHING FILLS IT AUTOMATICALLY YET, and the arms say so rather than implying a
# capability that does not exist.

: > "$_lw/mut.tsv"
_led_run merge --ledger "$_lw/mut.tsv" --date 2026-09-10 "$_lw/red.log" >/dev/null
check "every ledger row carries four fields, the fourth being the mutation" \
	"$(awk -F'\t' 'NF!=5' "$_lw/mut.tsv" | grep -c . || true)" "0"
check "and it is empty when nothing named a mutation" \
	"$(awk -F'\t' '$3=="first check"{print "[" $5 "]"}' "$_lw/mut.tsv")" "[]"

_led_run merge --ledger "$_lw/mut.tsv" --date 2026-09-10 \
	--mutation 'PGCOLUMNAR_SAOP_ELEMENT_LIMIT 128 -> 0' "$_lw/red.log" >/dev/null
check "a merge that names its mutation records it against the check that reddened" \
	"$(awk -F'\t' '$3=="first check"{print $5}' "$_lw/mut.tsv")" "PGCOLUMNAR_SAOP_ELEMENT_LIMIT 128 -> 0"
check "and not against one that stayed green" \
	"$(awk -F'\t' '$3=="second check"{print "[" $5 "]"}' "$_lw/mut.tsv")" "[]"

# ---- a duplicated check name shares one ledger row --------------------------
#
# The ledger is keyed by (suite, name). Two checks with the same name in one
# suite therefore share a row, so ONE of them going red marks BOTH as observed
# red -- a claim about a check nothing attacked, which is exactly what this
# ledger must not make.
#
# It cannot be fixed by keying harder without a synthetic id someone would have
# to maintain. So it is REPORTED, and the number is printed rather than assumed:
# the selftest corpus carries some today, which is how this was noticed at all --
# 609 records reduced to 605 rows.

cat > "$_lw/dupe.log" <<'LOG'
RESULT	demo	part1	the same name	PASS	
RESULT	demo	part1	the same name	FAIL	
RESULT	demo	part1	a unique name	PASS	
checks run: 3
LOG
: > "$_lw/dupe.tsv"
check "a duplicated check name is reported by name" \
	"$(_led_run merge --ledger "$_lw/dupe.tsv" --date 2026-09-10 "$_lw/dupe.log" \
		| grep -c 'duplicate check name, so one ledger row covers 2: demo	part1	the same name')" "1"
check "and a unique one is not" \
	"$(_led_run merge --ledger "$_lw/dupe.tsv" --date 2026-09-10 "$_lw/dupe.log" \
		| grep -c 'a unique name')" "0"
check "the two collapse to one row, which is the loss being reported" \
	"$(grep -c . "$_lw/dupe.tsv")" "2"
