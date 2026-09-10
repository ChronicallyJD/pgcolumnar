# ---- a check result must be machine-readable, from ONE counter --------------
#
# Check results are prose. `check`, `check_num` and `check_text` print PASS or
# FAIL and nothing else, so proving that a mutation reddened one NAMED check
# means grepping text. Every mutation proof in this repository is currently a
# person reading `FAIL  <name>` out of a log and retyping it into a comment.
#
# That is how a reverted guard once reported plain green while the check count
# fell from 190 to 186: the suite passed, and the only evidence anything had
# changed was a number nobody was comparing.
#
# The fix is NOT a second emitter beside the counters. A second source of truth
# for how many checks ran is the defect this issue family exists to close, and
# lib.sh had ELEVEN places that bumped PGC_CHECKS -- eleven chances to add the
# twelfth and forget the line beside it.
#
# So counting a check and recording it are ONE operation, pgc_record, and every
# helper routes through it. The arms below hold that shape rather than the
# behaviour of any one helper, because the shape is what stops the next
# expect_fail from being written.
# ---------------------------------------------------------------------------

_libsh="$PGC_TESTDIR/lib.sh"

check "premise: lib.sh is where the check helpers live" \
	"$(grep -c '^check() {' "$_libsh")" "1"

# THE STRUCTURAL ARM. One counter site, not eleven.
check "lib.sh bumps PGC_CHECKS in exactly one place" \
	"$(grep -c 'PGC_CHECKS=\$((PGC_CHECKS' "$_libsh")" "1"
check "and that place is pgc_record" \
	"$(sed -n '/^pgc_record()/,/^}/p' "$_libsh" | grep -c 'PGC_CHECKS=\$((PGC_CHECKS')" "1"

# ---- the record line itself -------------------------------------------------
#
# Tab separated, so a name containing spaces survives. Fields: suite, name,
# verdict, reason. The reason carries phase 1's REASON_CODE, which is what makes
# this more than a reformat: an unrunnable check is distinguishable from a
# passing one without parsing prose.

_rec() {	# _rec HELPER ARGS... -> the RESULT lines that helper emitted
	( PGC_FAIL=0; PGC_CHECKS=0; PGC_PASSED=0; PGC_FAILED=0; PGC_UNRUN=0
	  "$@" 2>/dev/null | grep '^RESULT' )
}
_human() {	# _human HELPER ARGS... -> the human lines that helper emitted
	( PGC_FAIL=0; PGC_CHECKS=0; PGC_PASSED=0; PGC_FAILED=0; PGC_UNRUN=0
	  "$@" 2>/dev/null | grep -v '^RESULT' )
}

check "a passing check emits exactly one record" \
	"$(_rec check "a name" x x | wc -l)" "1"
check "and its verdict field says PASS" \
	"$(_rec check "a name" x x | cut -f4)" "PASS"
check "and its name field is the check's name, spaces intact" \
	"$(_rec check "a name" x x | cut -f3)" "a name"

check "a failing check emits exactly one record" \
	"$(_rec check "a name" x y | wc -l)" "1"
check "and its verdict field says FAIL" \
	"$(_rec check "a name" x y | cut -f4)" "FAIL"

check "an unrunnable check emits exactly one record" \
	"$(_rec check_unrunnable "a name" MISSING_DEPENDENCY "no jq" | wc -l)" "1"
check "and its verdict field says UNRUN, which is neither of the other two" \
	"$(_rec check_unrunnable "a name" MISSING_DEPENDENCY "no jq" | cut -f4)" "UNRUN"
check "and the REASON_CODE travels in the reason field, not in prose" \
	"$(_rec check_unrunnable "a name" MISSING_DEPENDENCY "no jq" | cut -f5)" "MISSING_DEPENDENCY"

# A reason code the enum does not contain is already a FAIL. It must record that
# verdict, not the one it was asked for.
check "a bogus reason code records FAIL, not UNRUN" \
	"$(_rec check_unrunnable "a name" NOT_A_REASON "x" | cut -f4)" "FAIL"

# ---- every helper, not just the two that were easy --------------------------
#
# check_text, check_num, check_ratio and pgc_require_tools each had their own
# counter bump and their own outcome line. Each is one place the pair could come
# apart, which is why the arm is over ALL of them rather than a sample.

check "check_text on an empty side emits one record" \
	"$(_rec check_text "n" "" "x" | wc -l)" "1"
check "and records FAIL, because nothing was compared" \
	"$(_rec check_text "n" "" "x" | cut -f4)" "FAIL"
check "check_num on a non-number emits one record" \
	"$(_rec check_num "n" "abc" "1" | wc -l)" "1"
check "and records FAIL" "$(_rec check_num "n" "abc" "1" | cut -f4)" "FAIL"
check "check_ratio on a non-number emits one record" \
	"$(_rec check_ratio "n" "abc" "1" "2" | wc -l)" "1"
check "check_ratio with a zero side emits one record" \
	"$(_rec check_ratio "n" "0" "1" "2" | wc -l)" "1"
check "check_ratio that forms a ratio emits one record" \
	"$(_rec check_ratio "n" "1" "1" "2" | wc -l)" "1"
check "and records PASS when the ratio is inside the bound" \
	"$(_rec check_ratio "n" "1" "1" "2" | cut -f4)" "PASS"
check "pgc_pass emits one record" "$(_rec pgc_pass "n" | wc -l)" "1"
check "pgc_fail emits one record" "$(_rec pgc_fail "n" "d" | wc -l)" "1"

# ---- the human lines must not have changed ----------------------------------
#
# 3,762 check sites, and suites, selftests and CI all grep `^FAIL` and `^PASS`.
# Adding a record beside them is only safe if the prose is byte-identical, so the
# arms pin the exact strings rather than trusting that a refactor was careful.

check "a passing check still prints its old line" \
	"$(_human check "a name" x x)" "PASS  a name"
check "a failing check still prints its old line" \
	"$(_human check "a name" x y)" "FAIL  a name: got [x] want [y]"
check "an unrunnable check still prints its old line" \
	"$(_human check_unrunnable "a name" MISSING_DEPENDENCY "no jq")" "UNRUN  a name: MISSING_DEPENDENCY: no jq"
check "check_text's empty-side line is unchanged" \
	"$(_human check_text "n" "" "x")" "FAIL  n: a side is empty, so nothing was compared: got [] want [x]"
check "check_num's non-measurement line is unchanged" \
	"$(_human check_num "n" "abc" "1")" "FAIL  n: not a measurement, so nothing was compared: got [abc] want [1]"

# ---- the count and the records cannot come apart ----------------------------
#
# They are one operation, so this cannot fail by drifting. It CAN fail if a
# helper is added that prints an outcome without recording it, which is exactly
# the expect_fail shape, so it is asserted rather than argued.

_n_calls=7
_recorded="$( ( PGC_FAIL=0; PGC_CHECKS=0; PGC_PASSED=0; PGC_FAILED=0; PGC_UNRUN=0
	check a x x; check b x y; check_text c "" x; check_num d abc 1
	check_ratio e 1 1 2; pgc_pass f; check_unrunnable g MISSING_DEPENDENCY h
	echo "COUNTED $PGC_CHECKS" ) )"
check "premise: the probe ran every helper shape once" \
	"$(printf '%s\n' "$_recorded" | grep -c '^RESULT')" "$_n_calls"
check "the record count equals the counter the summary reports" \
	"$(printf '%s\n' "$_recorded" | grep -c '^RESULT')" \
	"$(printf '%s\n' "$_recorded" | sed -n 's/^COUNTED //p')"

# ---- and the RUNNER must reconcile them -------------------------------------
#
# A suite's log states `checks run: N` and carries N record lines. Those are two
# artifacts of the same run and they can genuinely disagree: a suite killed
# mid-way, a truncated log, a helper that prints an outcome without recording it.

_rv="$PGC_TESTDIR/run_all_versions.sh"
check "the runner defines the record reconciliation" \
	"$(grep -c '^pgc_reconcile_records()' "$_rv")" "1"

eval "$(sed -n '/^pgc_reconcile_records()/,/^}/p' "$_rv")"
check "premise: it is callable" "$(type -t pgc_reconcile_records)" "function"

_rl="$PGC_WORKDIR/rec.log"
printf 'RESULT\ts\ta\tPASS\t\nRESULT\ts\tb\tPASS\t\nchecks run: 2\n' > "$_rl"
check "a log whose records match its stated count reconciles" \
	"$(pgc_reconcile_records "$_rl" >/dev/null 2>&1 && echo ok || echo mismatch)" "ok"

printf 'RESULT\ts\ta\tPASS\t\nchecks run: 2\n' > "$_rl"
check "a log with fewer records than it claims is caught" \
	"$(pgc_reconcile_records "$_rl" >/dev/null 2>&1 && echo ok || echo mismatch)" "mismatch"
check "and the two numbers are named, not just the verdict" \
	"$(pgc_reconcile_records "$_rl" 2>&1 | grep -c 'records=1 .*checks run: 2')" "1"

printf 'RESULT\ts\ta\tPASS\t\nRESULT\ts\tb\tPASS\t\nRESULT\ts\tc\tPASS\t\nchecks run: 2\n' > "$_rl"
check "a log with more records than it claims is caught too" \
	"$(pgc_reconcile_records "$_rl" >/dev/null 2>&1 && echo ok || echo mismatch)" "mismatch"

# A log with no `checks run:` line at all did not reach its summary. That is a
# different fault from a miscount and must not read as a clean reconciliation.
printf 'RESULT\ts\ta\tPASS\t\n' > "$_rl"
check "a log that never stated a count is not silently accepted" \
	"$(pgc_reconcile_records "$_rl" >/dev/null 2>&1 && echo ok || echo mismatch)" "mismatch"

check "the runner calls the record reconciliation, not merely defines it" \
	"$(grep -c '[^_[:alnum:]]pgc_reconcile_records "' "$_rv")" "1"
