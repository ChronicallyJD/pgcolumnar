# ---- an unrunnable pytest test must not leave the run green ------------------
#
# WHY THIS EXISTS. `expect.cannot_run(REASON, detail)` is the pytest corpus's
# third state, the counterpart of `check_unrunnable` here. It wrote
# `self.unrunnable` and NOTHING READ IT, so a test that declared itself
# unrunnable reported `1 passed` and exit 0. Measured, before the fix.
#
# That is the write-only-flag shape selftest 320 already polices one level up,
# where the runner's INCOMPLETE branch set a variable the verdict never read. It
# mattered more here: a bare `@pytest.mark.skip` FAILS the pytest run, so the
# layer refused the cheap dishonest escape and permitted the expensive-looking
# one. An escape hatch that costs nothing is the default.
#
# WHY THE CHECKS ARE STATIC. The behaviour itself is pinned in the corpus, by
# four arms in test/pytest/test_layer.py that run pytest inside pytest and assert
# on the inner run's exit status. Those need pytest, psycopg and a virtualenv;
# CI installs none of them, and `pgc_skip` treats a missing dependency as a
# failure rather than a skip. So the behavioural half lives where it can run and
# this half asserts the STRUCTURE that behaviour rests on, which is greppable
# from a checkout with nothing installed. Same division as selftest 320's last
# two arms, which grep the runner for the call and for the absence of the flag.
#
# THE NUMBER IS THE POINT OF THE FIRST ARM. 67 now lives in two files. A number
# duplicated across a language boundary is a number that drifts, and the drift
# is invisible: the corpus would exit 67, the runner would compare against
# something else, and an INCOMPLETE run would read as a failure or as a pass
# depending on which way it moved.

_ts_lib="$PGC_TESTDIR/lib.sh"
_ts_vac="$PGC_TESTDIR/pytest/pgc_vacuity.py"

check "premise: the harness library is where this part thinks it is" \
	"$([ -f "$_ts_lib" ] && echo yes || echo no)" "yes"

check "premise: the pytest layer is where this part thinks it is" \
	"$([ -f "$_ts_vac" ] && echo yes || echo no)" "yes"

# Parsed out of each file rather than written here. A check that restates the
# number tests this file against itself: both copies could drift together and it
# would still pass.
_ts_sh_code="$(sed -n 's/^PGC_EXIT_INCOMPLETE=\([0-9]\{1,\}\).*/\1/p' "$_ts_lib" | head -1)"
_ts_py_code="$(sed -n 's/^EXIT_INCOMPLETE[[:space:]]*=[[:space:]]*\([0-9]\{1,\}\).*/\1/p' "$_ts_vac" | head -1)"

check "premise: lib.sh states an INCOMPLETE exit code this part could read" \
	"$([ -n "$_ts_sh_code" ] && echo yes || echo no)" "yes"

check "premise: the pytest layer states one too" \
	"$([ -n "$_ts_py_code" ] && echo yes || echo no)" "yes"

check "the two harnesses agree on the INCOMPLETE exit code" \
	"$_ts_py_code" "$_ts_sh_code"

# ---- the field must be READ, which is the defect this part is named after ---
#
# Counted as two populations rather than asserted as a boolean, so the failure
# says which side is missing.
_ts_writes="$(grep -c 'self\.unrunnable[[:space:]]*=' "$_ts_vac")"
_ts_reads="$(grep -c 'rec\.unrunnable' "$_ts_vac")"

check "the layer still writes the unrunnable state" \
	"$([ "$_ts_writes" -ge 1 ] && echo yes || echo "$_ts_writes")" "yes"

check "and something READS it, rather than only writing it" \
	"$([ "$_ts_reads" -ge 1 ] && echo yes || echo "$_ts_reads")" "yes"

# ---- and the read has to reach the run's exit status ------------------------
#
# Reading the field into a list nothing acts on would satisfy the arm above and
# leave the defect exactly where it was.
check "the layer ends a session by setting its exit status" \
	"$(grep -c 'session\.exitstatus[[:space:]]*=' "$_ts_vac")" "1"

# Failure dominates, the same rule lib.sh keeps: a run with a failure AND an
# unrunnable test is a failure. So the override must be conditional on a
# currently-clean run. Unconditional, it would MASK failures as INCOMPLETE.
check "and only ever moves a run off zero, so a failure still dominates" \
	"$(grep -c 'exitstatus == 0' "$_ts_vac")" "1"

# The state says why. A third state that does not name its reason is a skip.
check "the layer prints the unrunnable reason in lib.sh's shape" \
	"$(grep -c 'UNRUN.*{reason}' "$_ts_vac")" "1"

# ---- and these greps must be able to FAIL -----------------------------------
#
# Every arm above passes on a healthy tree, which a grep that matches nothing
# also does -- against an EMPTY file, `grep -c` returns 0 and every `-ge 1` arm
# would read "no" while every `-c ... "1"` arm would read 0. Those would be
# visible. The dangerous case is the opposite: a pattern that is subtly wrong
# still matching. So the fixtures below are the real code with ONE property
# removed, and the arms assert the greps notice.

_ts_fix="$PGC_WORKDIR/thirdstate"; rm -rf "$_ts_fix"; mkdir -p "$_ts_fix"

# The defect as it shipped: the field is written and never read.
{
	printf 'EXIT_INCOMPLETE = 67\n'
	printf 'class Expect:\n'
	printf '    def cannot_run(self, reason, detail=""):\n'
	printf '        self.unrunnable = (reason, detail)\n'
} > "$_ts_fix/writeonly.py"

check "a write-only unrunnable field is caught" \
	"$(grep -c 'rec\.unrunnable' "$_ts_fix/writeonly.py")" "0"

check "premise: and that same fixture does show the write, so the arm is not blind" \
	"$(grep -c 'self\.unrunnable[[:space:]]*=' "$_ts_fix/writeonly.py")" "1"

# The exit code drifted. Both files parse; the values differ.
printf 'EXIT_INCOMPLETE = 66\n' > "$_ts_fix/drifted.py"
_ts_drift="$(sed -n 's/^EXIT_INCOMPLETE[[:space:]]*=[[:space:]]*\([0-9]\{1,\}\).*/\1/p' "$_ts_fix/drifted.py" | head -1)"
check "a drifted exit code is visible rather than absorbed" \
	"$([ "$_ts_drift" = "$_ts_sh_code" ] && echo agrees || echo "differs:$_ts_drift/$_ts_sh_code")" \
	"differs:66/67"

# An unconditional override, which would mask a failing run as INCOMPLETE.
printf '    session.exitstatus = EXIT_INCOMPLETE\n' > "$_ts_fix/unconditional.py"
check "an unconditional exit override is caught by the dominance arm" \
	"$(grep -c 'exitstatus == 0' "$_ts_fix/unconditional.py")" "0"

check "premise: while the real layer satisfies that same arm" \
	"$(grep -c 'exitstatus == 0' "$_ts_vac")" "1"

unset _ts_lib _ts_vac _ts_sh_code _ts_py_code _ts_writes _ts_reads _ts_fix _ts_drift
