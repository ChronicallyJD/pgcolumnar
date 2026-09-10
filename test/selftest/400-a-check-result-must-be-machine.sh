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
# Tab separated, so a name containing spaces survives. Five columns after the
# RESULT marker: suite, part, name, verdict, reason. The reason carries phase 1's
# REASON_CODE, which is what makes this more than a reformat: an unrunnable check
# is distinguishable from a passing one without parsing prose. The verdict is one
# of PASS, FAIL, UNRUN or SKIP.
#
# No mutation column: that is the LEDGER's (#918). A record is one observation,
# not a history.

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
	"$(_rec check "a name" x x | cut -f5)" "PASS"
check "and its name field is the check's name, spaces intact" \
	"$(_rec check "a name" x x | cut -f4)" "a name"

# ---- and WHICH PART asked it ------------------------------------------------
#
# The suite is not enough. harness_selftest sources 40-odd parts into one shell,
# and its premises are phrased to be COPIED: "premise: the pytest layer is where
# THIS PART thinks it is" says "this part" so the same sentence works in any of
# them. main carries two copies of that one and two of another, and the count
# grows with every part anyone adds -- OffgridwithJD found all six of their own
# branches adding more.
#
# So (suite, name) is not a key of checks, it is a key of check NAMES. The part
# makes it a key of the thing it identifies, and it is derived from BASH_SOURCE
# rather than from a convention, so the next part written the same way is keyed
# correctly without anyone remembering.
check "the record names the part the check was asked from" \
	"$(_rec check "a name" x x | cut -f3)" "$(basename "${BASH_SOURCE[0]}" .sh)"
check "premise: and that is this fragment, not the suite" \
	"$([ "$(_rec check "n" x x | cut -f3)" != "$(_rec check "n" x x | cut -f2)" ] \
		&& echo different || echo same)" "different"

check "a failing check emits exactly one record" \
	"$(_rec check "a name" x y | wc -l)" "1"
check "and its verdict field says FAIL" \
	"$(_rec check "a name" x y | cut -f5)" "FAIL"

check "an unrunnable check emits exactly one record" \
	"$(_rec check_unrunnable "a name" MISSING_DEPENDENCY "no jq" | wc -l)" "1"
check "and its verdict field says UNRUN, which is neither of the other two" \
	"$(_rec check_unrunnable "a name" MISSING_DEPENDENCY "no jq" | cut -f5)" "UNRUN"
check "and the REASON_CODE travels in the reason field, not in prose" \
	"$(_rec check_unrunnable "a name" MISSING_DEPENDENCY "no jq" | cut -f6)" "MISSING_DEPENDENCY"

# A reason code the enum does not contain is already a FAIL. It must record that
# verdict, not the one it was asked for.
check "a bogus reason code records FAIL, not UNRUN" \
	"$(_rec check_unrunnable "a name" NOT_A_REASON "x" | cut -f5)" "FAIL"

# ---- every helper, not just the two that were easy --------------------------
#
# check_text, check_num, check_ratio and pgc_require_tools each had their own
# counter bump and their own outcome line. Each is one place the pair could come
# apart, which is why the arm is over ALL of them rather than a sample.

check "check_text on an empty side emits one record" \
	"$(_rec check_text "n" "" "x" | wc -l)" "1"
check "and records FAIL, because nothing was compared" \
	"$(_rec check_text "n" "" "x" | cut -f5)" "FAIL"
check "check_num on a non-number emits one record" \
	"$(_rec check_num "n" "abc" "1" | wc -l)" "1"
check "and records FAIL" "$(_rec check_num "n" "abc" "1" | cut -f5)" "FAIL"
check "check_ratio on a non-number emits one record" \
	"$(_rec check_ratio "n" "abc" "1" "2" | wc -l)" "1"
check "check_ratio with a zero side emits one record" \
	"$(_rec check_ratio "n" "0" "1" "2" | wc -l)" "1"
check "check_ratio that forms a ratio emits one record" \
	"$(_rec check_ratio "n" "1" "1" "2" | wc -l)" "1"
check "and records PASS when the ratio is inside the bound" \
	"$(_rec check_ratio "n" "1" "1" "2" | cut -f5)" "PASS"
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

# ---- the timing helpers reported an outcome that nothing counted -------------
#
# check_timing and check_ratio_needs_quiet_machine, under PGC_SKIP_TIMING=1,
# printed a human SKIP line and returned. Driven before the fix:
#
#     SKIP  a timing check (PGC_SKIP_TIMING: wall-clock measurement)
#     SKIP  a ratio check (PGC_SKIP_TIMING: wall-clock ratio)
#     -> PGC_CHECKS=0 PGC_PASSED=0 PGC_FAILED=0 PGC_UNRUN=0
#
# Two outcomes a reader sees, nothing counted, no record. That is the hole this
# part's whole argument cannot have, and NOTHING here reached those branches:
# removing both emitters left every arm above green. Found by @linuxhikerpm.
#
# SKIP IS A FOURTH OUTCOME, counted like the other three. `checks run: N` now
# reports the checks a suite ENCOUNTERED rather than the ones it managed to
# evaluate, and pgc_summary reconciles four counters against it instead of three
# -- the same shape, one term wider.
#
# It is NOT check_unrunnable. That third state exists for a check whose INPUT was
# absent and it exits the suite INCOMPLETE, which would turn every CI run red the
# moment PGC_SKIP_TIMING is set -- and CI sets it on every run. A wall-clock check
# on a shared runner is deliberately not asked, which is a different thing from a
# check that could not be answered.

_tm() {	# _tm SKIPFLAG HELPER ARGS... -> records emitted
	( PGC_FAIL=0; PGC_CHECKS=0; PGC_PASSED=0; PGC_FAILED=0; PGC_UNRUN=0; PGC_SKIPPED=0
	  PGC_SKIP_TIMING="$1"; shift; "$@" 2>/dev/null | grep '^RESULT' )
}
_tmh() {	# _tmh SKIPFLAG HELPER ARGS... -> the human lines
	( PGC_FAIL=0; PGC_CHECKS=0; PGC_PASSED=0; PGC_FAILED=0; PGC_UNRUN=0; PGC_SKIPPED=0
	  PGC_SKIP_TIMING="$1"; shift; "$@" 2>/dev/null | grep -v '^RESULT' )
}
_tmc() {	# _tmc SKIPFLAG HELPER ARGS... -> "CHECKS/PASSED/SKIPPED"
	( PGC_FAIL=0; PGC_CHECKS=0; PGC_PASSED=0; PGC_FAILED=0; PGC_UNRUN=0; PGC_SKIPPED=0
	  PGC_SKIP_TIMING="$1"; shift; "$@" >/dev/null 2>&1
	  echo "$PGC_CHECKS/$PGC_PASSED/$PGC_SKIPPED" )
}

check "a skipped timing check emits exactly one record" \
	"$(_tm 1 check_timing "a timing check" 1 1 | wc -l)" "1"
check "and its verdict is SKIP" \
	"$(_tm 1 check_timing "a timing check" 1 1 | cut -f5)" "SKIP"
check "and it is counted, so checks run: reports it" \
	"$(_tmc 1 check_timing "a timing check" 1 1)" "1/0/1"
check "and its human line is unchanged" \
	"$(_tmh 1 check_timing "a timing check" 1 1)" \
	"SKIP  a timing check (PGC_SKIP_TIMING: wall-clock measurement)"

check "the same timing check, ENABLED, emits one record and passes" \
	"$(_tm 0 check_timing "a timing check" 1 1 | cut -f5)" "PASS"
check "and is counted as a pass, not a skip" \
	"$(_tmc 0 check_timing "a timing check" 1 1)" "1/1/0"

check "a skipped ratio check emits exactly one record" \
	"$(_tm 1 check_ratio_needs_quiet_machine "a ratio check" 1 1 2 | wc -l)" "1"
check "and its verdict is SKIP" \
	"$(_tm 1 check_ratio_needs_quiet_machine "a ratio check" 1 1 2 | cut -f5)" "SKIP"
check "and it is counted" \
	"$(_tmc 1 check_ratio_needs_quiet_machine "a ratio check" 1 1 2)" "1/0/1"
check "and its human line is unchanged" \
	"$(_tmh 1 check_ratio_needs_quiet_machine "a ratio check" 1 1 2)" \
	"SKIP  a ratio check (PGC_SKIP_TIMING: wall-clock ratio)"

check "the same ratio check, ENABLED, emits one record and passes" \
	"$(_tm 0 check_ratio_needs_quiet_machine "a ratio check" 1 1 2 | cut -f5)" "PASS"
check "and is counted as a pass, not a skip" \
	"$(_tmc 0 check_ratio_needs_quiet_machine "a ratio check" 1 1 2)" "1/1/0"

# ---- and the accounting line carries the fourth term ------------------------

_acct_line() {	# _acct_line SKIPFLAG -> pgc_summary's accounting line
	( PGC_FAIL=0; PGC_CHECKS=0; PGC_PASSED=0; PGC_FAILED=0; PGC_UNRUN=0; PGC_SKIPPED=0
	  PGC_SKIP_TIMING="$1"
	  check "an ordinary check" x x
	  check_timing "a timing check" 1 1
	  pgc_summary ) 2>/dev/null | sed -n 's/^\(accounting: .*\)$/\1/p'
}
check "the accounting line reconciles four outcomes against the count" \
	"$(_acct_line 1)" "accounting: 1 passed + 0 failed + 0 unrunnable + 1 skipped = 2"
check "and with timing enabled the skipped term is zero, not absent" \
	"$(_acct_line 0)" "accounting: 2 passed + 0 failed + 0 unrunnable + 0 skipped = 2"

# A suite whose every check was skipped has evaluated nothing, so it must not
# report PASSED. Before the fourth counter it could not reach this state at all,
# because a skipped check left PGC_CHECKS at zero.
_allskip() {
	( PGC_FAIL=0; PGC_CHECKS=0; PGC_PASSED=0; PGC_FAILED=0; PGC_UNRUN=0; PGC_SKIPPED=0
	  PGC_SKIP_TIMING=1
	  check_timing "a timing check" 1 1
	  pgc_summary ) 2>/dev/null | grep -oE ': (PASSED|FAILED|SKIPPED \(ran no checks\)|INCOMPLETE)$'
}
check "a suite that skipped every check did not pass" \
	"$(_allskip)" ": SKIPPED (ran no checks)"

# ---- a check inside a pipeline loses its count, and the message must say so --
#
# `printf ... | while read n; do check "$n" a a; done` runs the loop body in a
# SUBSHELL, so the counter bump dies with it while the outcome and the record are
# both printed to the parent's stdout. Driven:
#
#     four checks print PASS, four RESULT lines appear, PGC_CHECKS=2
#
# pgc_reconcile_records catches it -- that is what it is for -- but it reported
# `records=3 but the log states checks run: 1`, which is the BOOKKEEPING rather
# than the cause. A reader who has not met this before has no way from that line
# to the pipeline. Raised by OffgridwithJD.
#
# Latent today: four piped loops in the tree, none with a check inside. So the
# sweep below reports zero, and a fixture proves it can fire -- a rule whose only
# evidence is that the corpus is currently clean is not a rule.

eval "$(sed -n '/^pgc_reconcile_records()/,/^}/p' "$_rv")"
_pl="$PGC_WORKDIR/piped.log"
printf 'RESULT\ts\tp\ta\tPASS\t\nRESULT\ts\tp\tb\tPASS\t\nRESULT\ts\tp\tc\tPASS\t\nchecks run: 1\n' > "$_pl"
check "more records than counted checks names the cause, not just the arithmetic" \
	"$(pgc_reconcile_records "$_pl" 2>&1 | grep -c 'a check ran in a subshell')" "1"
check "and still reports the two numbers" \
	"$(pgc_reconcile_records "$_pl" 2>&1 | grep -c 'records=3 .*checks run: 1')" "1"

# Fewer records than checks is the OPPOSITE fault -- a counted check that emitted
# no record -- and must not be described as a subshell.
printf 'RESULT\ts\tp\ta\tPASS\t\nchecks run: 3\n' > "$_pl"
check "fewer records than counted checks is not described as a subshell" \
	"$(pgc_reconcile_records "$_pl" 2>&1 | grep -c 'a check ran in a subshell')" "0"
check "and names its own cause instead" \
	"$(pgc_reconcile_records "$_pl" 2>&1 | grep -c 'counted without emitting a record')" "1"

# ---- and the shape is swept, the way selftest 080 sweeps its cousin ----------

_pipeloop_sites() {	# _pipeloop_sites FILE... -> file:line of a check inside a piped loop
	# Two refinements, both from measuring rather than reading. Requiring the
	# closing `done` to be alone on its line left the scanner inside a loop for
	# the rest of any file whose loop ended `done)"` -- 27 hits against a true
	# zero. And a loop written entirely on ONE line, inside a command
	# substitution, opened a block that never closed, flagging every later check.
	#
	# So: open only on a line that opens the loop and does NOT close it, and close
	# on a `done` token wherever it sits. Comments are stripped first, because the
	# rule's own explanation necessarily spells the shape out.
	awk '
		FNR == 1 { inloop = 0 }
		{ line = $0; sub(/^[[:space:]]*#.*/, "", line) }
		line ~ /\|[[:space:]]*(while|for)[[:space:]]/ && line ~ /(^|[[:space:];])do([[:space:]]|$)/ \
			&& line !~ /(^|[[:space:]();])done([[:space:]();]|$)/ { inloop = 1; next }
		inloop && line ~ /(^|[[:space:]();])done([[:space:]();]|$)/ { inloop = 0; next }
		inloop && line ~ /(^|[^_[:alnum:]])(check|check_num|check_text|check_ratio|check_unrunnable|pgc_pass|pgc_fail)[[:space:]]/ {
			print FILENAME ":" FNR
		}
	' "$@"
}

_pl_fx="$PGC_WORKDIR/plfx"; mkdir -p "$_pl_fx"
_pl_call="$(printf '%s "$n" a a' check)"
{ printf 'printf "a\\nb\\n" | while IFS= read -r n; do\n'; printf '\t%s\n' "$_pl_call"; printf 'done\n'; } \
	> "$_pl_fx/bad.sh"
{ printf 'while IFS= read -r n; do\n'; printf '\t%s\n' "$_pl_call"; printf 'done < <(printf "a\\nb\\n")\n'; } \
	> "$_pl_fx/good.sh"
{ printf 'printf "a\\nb\\n" | while IFS= read -r n; do\n'; printf '\techo "$n"\n'; printf 'done\n'; } \
	> "$_pl_fx/nocheck.sh"

check "premise: the fixtures carry the shapes this sweep is about" \
	"$(grep -lc 'while IFS= read' "$_pl_fx"/*.sh | grep -c .)" "3"
check "the sweep finds a check inside a PIPED loop" \
	"$(_pipeloop_sites "$_pl_fx/bad.sh" | grep -c .)" "1"
check "and not one inside a process-substitution loop, which keeps its shell" \
	"$(_pipeloop_sites "$_pl_fx/good.sh" | grep -c .)" "0"
check "and not a piped loop with no check in it" \
	"$(_pipeloop_sites "$_pl_fx/nocheck.sh" | grep -c .)" "0"

# A loop written entirely on one line inside a command substitution opens and
# closes in the same place. The first version of this sweep opened a block there
# and never closed it, flagging every check after it -- which is how twelve of
# its twenty-seven false hits were in this very file.
{ printf 'x="$(printf "a\\n" | while IFS= read -r n; do echo "$n"; done)"\n'
  printf '%s\n' "$_pl_call"; } > "$_pl_fx/oneline.sh"
check "and not a check after a one-line piped loop that already closed" \
	"$(_pipeloop_sites "$_pl_fx/oneline.sh" | grep -c .)" "0"

_pl_hits="$(_pipeloop_sites "$PGC_TESTDIR"/*.sh "$PGC_TESTDIR"/selftest/*.sh 2>/dev/null | grep -c . || true)"
[ "${_pl_hits:-0}" = 0 ] || _pipeloop_sites "$PGC_TESTDIR"/*.sh "$PGC_TESTDIR"/selftest/*.sh | sed 's/^/    /'
check "no suite calls a check inside a piped loop" "${_pl_hits:-0}" "0"
