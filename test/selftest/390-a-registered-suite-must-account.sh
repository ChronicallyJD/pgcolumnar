# ---- a registered suite must account for its checks, or say it cannot -------
#
# The matrix prints "suites that ran: N of M" and never checks it. Two different
# things hide behind that line.
#
# The first is arithmetic nobody does. ran + skipped + incomplete is printed
# beside M and never compared with it, so a suite whose verdict the tally loop
# drops leaves the sum short and the line still reads plausibly.
#
# The second is worse, because it is live today. pgc_classify_suite_rc maps rc=0
# to PASS with no further question, and ten registered suites exit 0 having never
# called pgc_summary. They assert things -- concurrency prints its own failure and
# exits non-zero -- but the harness cannot count their checks, and nothing says
# so. They are counted among the suites that "ran", which is the exact overcount
# #447 added that line to stop, one level further down.
#
# So the fix is NOT a number. A count cannot do this job: two errors of opposite
# sign cancel, and an exempt list maintained by hand makes the count agree by
# construction -- the check then measures the list, not the run.
#
# Instead, derive MEMBERSHIP from a property each suite carries, and assert set
# equality in BOTH directions:
#
#   declared  the suite's own text calls pgc_summary
#   observed  the suite's log carries the "accounting:" line pgc_summary prints
#             on every exit path, before it decides the status
#
# Neither is a number and neither is hand-maintained. A suite that stops calling
# pgc_summary moves between the sets on its own, and the two directions catch
# opposite mistakes: declared-but-not-observed is a suite that died before it
# could account, and observed-but-not-declared is a stale reading of the source.
#
# The functions are EVALLED OUT OF run_all_versions.sh, per selftest 320: a check
# that restates the rule tests the world instead of the code.
# ---------------------------------------------------------------------------

_rv="$PGC_TESTDIR/run_all_versions.sh"

check "premise: the runner defines the declaration reader this part evals" \
	"$(grep -c '^pgc_suite_declares_accounting()' "$_rv")" "1"
check "premise: the runner defines the observation reader this part evals" \
	"$(grep -c '^pgc_log_shows_accounting()' "$_rv")" "1"
check "premise: the runner defines the reconciliation this part evals" \
	"$(grep -c '^pgc_reconcile_accounting()' "$_rv")" "1"

eval "$(sed -n '/^pgc_suite_declares_accounting()/,/^}/p' "$_rv")"
eval "$(sed -n '/^pgc_log_shows_accounting()/,/^}/p' "$_rv")"
eval "$(sed -n '/^pgc_reconcile_accounting()/,/^}/p' "$_rv")"
check "premise: the declaration reader evalled out of the runner is callable" \
	"$(type -t pgc_suite_declares_accounting)" "function"
check "premise: the observation reader evalled out of the runner is callable" \
	"$(type -t pgc_log_shows_accounting)" "function"
check "premise: the reconciliation evalled out of the runner is callable" \
	"$(type -t pgc_reconcile_accounting)" "function"

_acc="$PGC_WORKDIR/acc"; mkdir -p "$_acc"

# ---- the declaration reader ------------------------------------------------

printf '. "$(dirname "$0")/lib.sh"\ncheck "x" a a\npgc_summary\n' > "$_acc/declares.sh"
check "a suite that calls pgc_summary declares accounting" \
	"$(pgc_suite_declares_accounting "$_acc/declares.sh")" "yes"

printf '. "$(dirname "$0")/lib.sh"\necho hi\nexit 0\n' > "$_acc/silent.sh"
check "a suite that never calls it does not" \
	"$(pgc_suite_declares_accounting "$_acc/silent.sh")" "no"

# A MENTION is not a call. The easy wrong implementation is a bare grep, and it
# reads a suite that only explains why it cannot account as though it does.
printf '. "$(dirname "$0")/lib.sh"\n# this suite cannot call pgc_summary: it has no cluster\nexit 0\n' \
	> "$_acc/mentions.sh"
check "a comment mentioning pgc_summary is not a declaration" \
	"$(pgc_suite_declares_accounting "$_acc/mentions.sh")" "no"

# Nor is a longer name that contains it.
printf '. "$(dirname "$0")/lib.sh"\npgc_summary_of_something\n' > "$_acc/prefix.sh"
check "a longer name containing pgc_summary is not a declaration" \
	"$(pgc_suite_declares_accounting "$_acc/prefix.sh")" "no"

# An ABSENT file is its own answer. Reported by OffgridwithJD reviewing #922:
# folding it into "no" classifies a registered suite whose .sh has vanished as
# exempt, and the reconciliation then reads clean -- a suite disappearing from
# the matrix, inside the check whose subject is suites going missing from the
# accounting.
check "a file that does not exist is reported absent, not exempt" \
	"$(pgc_suite_declares_accounting "$_acc/absent.sh")" "absent"
check "and absent is distinguishable from a present file that does not declare" \
	"$([ "$(pgc_suite_declares_accounting "$_acc/absent.sh")" \
		= "$(pgc_suite_declares_accounting "$_acc/silent.sh")" ] && echo same || echo different)" \
	"different"

# ---- the comment stripper follows the SHELL's rule -------------------------
#
# `sed 's/#.*$//'` strips from ANY hash, so a `#` inside a quoted string earlier
# on the line hides a pgc_summary call after it. Also reported by OffgridwithJD.
# The stripper now only treats a hash at line start or after whitespace as a
# comment, which is what the shell does.
printf '. "$(dirname "$0")/lib.sh"\nX=a#b; pgc_summary\n' > "$_acc/hashinword.sh"
check "a hash inside a word does not hide the call after it" \
	"$(pgc_suite_declares_accounting "$_acc/hashinword.sh")" "yes"

printf '. "$(dirname "$0")/lib.sh"\npgc_summary  # and a trailing comment\n' > "$_acc/trailing.sh"
check "a trailing comment after the call does not hide it" \
	"$(pgc_suite_declares_accounting "$_acc/trailing.sh")" "yes"

printf '. "$(dirname "$0")/lib.sh"\n  # pgc_summary is only mentioned here\nexit 0\n' > "$_acc/indented.sh"
check "an indented comment is still a comment" \
	"$(pgc_suite_declares_accounting "$_acc/indented.sh")" "no"

# The residual case the shell rule does NOT cover: a hash after whitespace INSIDE
# a quoted string. Measured over all 251 registered suites -- three carry a line
# with both a hash and pgc_summary, and in every one the hash starts the line. So
# no suite is misread today, and this arm keeps that true rather than leaving it
# to be rediscovered.
_hashline=0
while IFS= read -r _hs; do
	[ -f "$PGC_TESTDIR/${_hs}.sh" ] || continue
	if grep -nE '(^|[^_[:alnum:]])pgc_summary([^_[:alnum:]]|$)' "$PGC_TESTDIR/${_hs}.sh" \
		| grep -qE '^[0-9]+:[^#]*[^[:space:]]#'; then
		_hashline=$((_hashline + 1))
		echo "    a hash precedes a pgc_summary call in $_hs.sh"
	fi
done < <(listed_suites)
check "no registered suite has a hash before a pgc_summary call on the same line" \
	"$_hashline" "0"

# ---- the observation reader ------------------------------------------------
#
# pgc_summary prints the accounting line before every exit path, so it is present
# on a pass, a failure, a skip and an incomplete alike. That is what makes it the
# runtime twin of the declaration rather than a synonym for PASSED.

printf 'checks run: 3\nchecks unrunnable: 0\naccounting: 3 passed + 0 failed + 0 unrunnable = 3\nx.sh: PASSED\n' > "$_acc/pass.log"
check "a passing log shows accounting" "$(pgc_log_shows_accounting "$_acc/pass.log")" "yes"

printf 'accounting: 1 passed + 2 failed + 0 unrunnable = 3\nx.sh: FAILED\n' > "$_acc/fail.log"
check "and so does a failing one, which is the point" \
	"$(pgc_log_shows_accounting "$_acc/fail.log")" "yes"

printf 'accounting: 0 passed + 0 failed + 0 unrunnable = 0\nx.sh: SKIPPED (ran no checks)\n' > "$_acc/skip.log"
check "and a skip, which reached the summary and counted zero" \
	"$(pgc_log_shows_accounting "$_acc/skip.log")" "yes"

printf 'accounting: 2 passed + 0 failed + 1 unrunnable = 3\nx.sh: INCOMPLETE\n' > "$_acc/inc.log"
check "and an incomplete" "$(pgc_log_shows_accounting "$_acc/inc.log")" "yes"

printf 'x.sh: PASSED\n' > "$_acc/bare.log"
check "a log claiming PASSED without the accounting line shows none" \
	"$(pgc_log_shows_accounting "$_acc/bare.log")" "no"

printf 'this suite prints the word accounting: in prose\n' > "$_acc/prose.log"
check "and prose containing the word does not count as the line" \
	"$(pgc_log_shows_accounting "$_acc/prose.log")" "no"

check "an absent log shows no accounting rather than erroring" \
	"$(pgc_log_shows_accounting "$_acc/absent.log")" "no"

# ---- the reconciliation, in both directions --------------------------------

_declared="$_acc/declared"; _observed="$_acc/observed"

printf 'alpha\nbeta\ngamma\n' > "$_declared"
printf 'alpha\nbeta\ngamma\n' > "$_observed"
check "equal sets reconcile" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" >/dev/null 2>&1 && echo ok || echo asymmetric)" "ok"

# The direction that catches the false green: a suite said it would account and
# no accounting line appeared, so it died before reaching pgc_summary. Today that
# reads PASS whenever the shell happened to exit 0.
printf 'alpha\nbeta\n' > "$_observed"
check "a declared suite that produced no accounting is caught" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" >/dev/null 2>&1 && echo ok || echo asymmetric)" "asymmetric"
check "and it is NAMED, so the reader does not have to diff two lists" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" 2>&1 | grep -c '^[[:space:]]*declared but never accounted: gamma$')" "1"

# The opposite direction: an accounting line from a suite whose source says it
# cannot produce one. That means the reading of the source is stale, and it is
# the failure an exempt list maintained by hand can never report.
printf 'alpha\nbeta\n' > "$_declared"
printf 'alpha\nbeta\ngamma\n' > "$_observed"
check "an undeclared suite that DID account is caught too" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" >/dev/null 2>&1 && echo ok || echo asymmetric)" "asymmetric"
check "and it is named as the opposite fault, not the same one" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" 2>&1 | grep -c '^[[:space:]]*accounted but never declared: gamma$')" "1"

# Both at once must report both. One error masking the other is how a count
# passes while two suites are wrong in opposite directions -- the exact failure
# a count cannot distinguish from correctness.
printf 'alpha\ndelta\n' > "$_declared"
printf 'alpha\ngamma\n' > "$_observed"
check "opposite errors do not cancel: both directions are reported" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" 2>&1 | grep -cE '^[[:space:]]*(declared but never accounted: delta|accounted but never declared: gamma)$')" "2"

# inputs == sum(buckets), printed from the data, per the house rule.
printf 'alpha\nbeta\ngamma\n' > "$_declared"
printf 'beta\ngamma\ndelta\n' > "$_observed"
check "the reconciliation prints inputs == sum(buckets)" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" 2>&1 | grep -c 'inputs=4 .*both=2.*declared only=1.*accounted only=1.*sum=4')" "1"

# ---- and the RUNNER must call it, not merely define it ----------------------
#
# Selftest 320 records what testing a function and not its caller costs here: the
# classifier was right and the loop threw the answer away. So pin the call site
# and pin that its result can fail the major.

# Count CALLS, not mentions. The first version of this arm matched the comment
# on the definition line as readily as the call below it -- the same
# mention-for-a-call mistake pgc_suite_declares_accounting exists to refuse,
# committed by the arm that asserts it.
check "the runner calls the reconciliation, not merely defines it" \
	"$(grep -c '[^_[:alnum:]]pgc_reconcile_accounting "' "$_rv")" "1"
check "premise: and that count excludes the definition line, which mentions it" \
	"$(grep -c '^pgc_reconcile_accounting()' "$_rv")" "1"
check "and a failed reconciliation sets the per-major failure flag" \
	"$(grep -A6 'pgc_reconcile_accounting "\$_acc_declared"' "$_rv" | grep -c 'verfail=1')" "1"

# ---- the suites the driver deliberately never ran ---------------------------
#
# PGC_SKIP_TIMING drops four suites on every CI run. They call pgc_summary and
# correctly produce no accounting line, because nothing executed them. Without a
# term for that the reconciliation goes red for the one reason that is not a
# defect, and a check that cries wolf on every CI run is a check nobody reads.
#
# The driver records the decision where it makes it. These arms hold that the
# term EXCUSES only what the driver actually recorded, and cannot be used to
# excuse anything else.

_notdisp="$_acc/notdispatched"

printf 'alpha\nbeta\ngamma\n' > "$_declared"
printf 'alpha\nbeta\n' > "$_observed"
printf 'gamma\n' > "$_notdisp"
check "a declared suite the driver never dispatched reconciles" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" "$_notdisp" >/dev/null 2>&1 && echo ok || echo asymmetric)" "ok"

# The same inputs WITHOUT the record must still be caught, or the term is not
# doing any work and the arm above is satisfied by a function that ignores it.
check "and without that record the same run is still caught" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" >/dev/null 2>&1 && echo ok || echo asymmetric)" "asymmetric"

# A suite cannot both have reached its summary and not have been dispatched.
# Taking the union would absorb this silently, so it is asserted on its own.
printf 'alpha\nbeta\n' > "$_declared"
printf 'alpha\nbeta\n' > "$_observed"
printf 'beta\n' > "$_notdisp"
check "a suite recorded as never dispatched that DID account is caught" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" "$_notdisp" >/dev/null 2>&1 && echo ok || echo asymmetric)" "asymmetric"
check "and it is named as that fault, not as one of the other two" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" "$_notdisp" 2>&1 \
		| grep -c '^[[:space:]]*both accounted and recorded as never dispatched: beta$')" "1"

# The record cannot excuse a suite that never declared accounting in the first
# place: that is still the stale-reading direction.
printf 'alpha\n' > "$_declared"
printf 'alpha\n' > "$_observed"
printf 'zeta\n' > "$_notdisp"
check "the record cannot introduce a suite the source never declared" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" "$_notdisp" 2>&1 \
		| grep -c '^[[:space:]]*accounted but never declared: zeta$')" "1"

# ---- and the DRIVER must write that record ---------------------------------
#
# The term is only honest if the branch that decides not to run a suite is the
# thing that records it. Pin the write to that branch, beside the forged log it
# sits next to.

check "the skip branch records the suite it did not dispatch" \
	"$(grep -A8 'echo "\$s.sh: SKIPPED (ran no checks)" >"\$builddir/\${s}.log"' "$_rv" \
		| grep -c 'accounting.notdispatched')" "1"
check "and the reconciliation is given that record" \
	"$(grep -c 'pgc_reconcile_accounting "\$_acc_declared" "\$_acc_observed" "\$_acc_notdisp"' "$_rv")" "1"

# ---- and the identity must be able to FAIL ---------------------------------
#
# inputs == sum(buckets) is printed beside every reconciliation, per the house
# rule. Printing it is not the same as checking it, and asserting it is worth
# nothing unless something can make it false.
#
# Measured, not argued. Two mutations:
#
#   compute _inputs from the buckets instead of from the files -- the arithmetic
#   above becomes P + D + O == P + D + O, and NOTHING reddens. That is why
#   _inputs is counted from the two files by a separate route.
#
#   drop the sort before comm -- comm then reports garbage buckets, and the
#   totals diverge. That is the fault this identity actually guards, and it is
#   selftest 070's subject arriving in a second place.
#
# So the arm is the second mutation, applied to a twin evalled here.

eval "$(sed -n '/^pgc_reconcile_accounting()/,/^}/p' "$_rv" \
	| sed 's|LC_ALL=C sort -u "$_decl" 2>/dev/null|cat "$_decl" 2>/dev/null|' \
	| sed 's|LC_ALL=C sort -u "$_obs"  2>/dev/null|cat "$_obs" 2>/dev/null|' \
	| sed 's/^pgc_reconcile_accounting()/pgc_reconcile_unsorted_twin()/')"

check "premise: the unsorted twin is callable" \
	"$(type -t pgc_reconcile_unsorted_twin)" "function"
# A clean pass reads the same whether the code is load-bearing or the mutation
# never applied, so assert the twin really lost its sort.
check "premise: the mutation applied -- the twin no longer sorts its inputs" \
	"$(type pgc_reconcile_unsorted_twin | grep -c 'LC_ALL=C sort -u \"\$_decl\"')" "0"
check "premise: and the real function still does" \
	"$(type pgc_reconcile_accounting | grep -c 'LC_ALL=C sort -u \"\$_decl\"')" "1"

printf 'gamma\nbeta\nalpha\n' > "$_declared"
printf 'delta\ngamma\nbeta\n' > "$_observed"
check "the identity catches comm reading unsorted input" \
	"$(pgc_reconcile_unsorted_twin "$_declared" "$_observed" 2>&1 | grep -c 'does not add up')" "1"
check "and the real function reconciles the same input, so the arm is not noise" \
	"$(pgc_reconcile_accounting "$_declared" "$_observed" 2>&1 | grep -c 'does not add up')" "0"

# ---- the readers, run over the REAL population ------------------------------
#
# Everything above uses fixtures. A reader that works on four synthetic files and
# not on the 251 registered suites has been tested against the world it was
# written for. So run the declaration reader over the actual list and print the
# partition, per the rule that a list-derived claim shows inputs == sum(buckets).
#
# No count is asserted. The number of exempt suites is not a fact about
# correctness, and pinning it here would make this arm a second copy of a
# hand-maintained list -- which is the thing the whole design removes.

# THREE buckets, not two. Folding "absent" into "does not declare" is the
# conflation the reader was just fixed for, and repeating it here would leave the
# real population the one place it still happened.
_reg=0; _decl_n=0; _exempt_n=0; _absent_n=0
while IFS= read -r _s; do
	_reg=$((_reg + 1))
	case "$(pgc_suite_declares_accounting "$PGC_TESTDIR/${_s}.sh")" in
		yes)	_decl_n=$((_decl_n + 1)) ;;
		absent)	_absent_n=$((_absent_n + 1)); echo "    registered but has no file: $_s.sh" ;;
		*)	_exempt_n=$((_exempt_n + 1)) ;;
	esac
done < <(listed_suites)

echo "  registered=$_reg | declares accounting=$_decl_n, does not=$_exempt_n, absent=$_absent_n | sum=$((_decl_n + _exempt_n + _absent_n))"

check "premise: the registered list is not empty, so the partition means something" \
	"$([ "$_reg" -gt 0 ] && echo yes || echo no)" "yes"
check "the partition over the real suite list adds up" \
	"$((_decl_n + _exempt_n + _absent_n))" "$_reg"
check "every registered suite has a file" "$_absent_n" "0"

# Both buckets must be occupied, or the reader is answering the same way for
# everything and the arms above would pass just as happily.
check "the reader does not answer yes for every registered suite" \
	"$([ "$_exempt_n" -gt 0 ] && echo yes || echo no)" "yes"
check "nor no for every one of them" \
	"$([ "$_decl_n" -gt 0 ] && echo yes || echo no)" "yes"

# ---- the declaration reader must survive `set -o pipefail` ------------------
#
# A REGRESSION ARM. The first version of pgc_suite_declares_accounting piped sed
# into `grep -q`, and this file runs under `set -o pipefail`. grep -q exits the
# moment it matches, closing the pipe while sed is still writing; sed takes EPIPE
# and exits non-zero, and pipefail reports the whole pipeline as failed even
# though grep matched. The function then answered "no" for a suite that plainly
# calls pgc_summary.
#
# It was caught here, and only here: on the real population the two longest
# suites -- analyze_function and hilbert_curve -- read as not declaring
# accounting inside this run and as declaring it outside. Selftest 040 carries
# the same story from #473 and #476, where it named different innocent suites on
# every run.
#
# The arm is a file long enough to lose the race, with the call at the TOP so a
# matcher that exits early exits early.
_bigsuite="$_acc/big.sh"
{
	printf '. "$(dirname "$0")/lib.sh"\npgc_summary\n'
	_i=0
	while [ "$_i" -lt 40000 ]; do printf 'echo padding line %s\n' "$_i"; _i=$((_i + 1)); done
} > "$_bigsuite"

check "premise: pipefail is on, which is the condition the bug needs" \
	"$(set -o | grep -cE '^pipefail[[:space:]]+on$')" "1"
check "premise: the fixture is long enough to lose the race" \
	"$([ "$(wc -l < "$_bigsuite")" -gt 10000 ] && echo yes || echo no)" "yes"

check "a long suite that calls pgc_summary still declares accounting" \
	"$(pgc_suite_declares_accounting "$_bigsuite")" "yes"

# And prove the arm can fail. The twin is the SHAPE that was wrong, restated
# here rather than extracted, because the wrong version is no longer in the tree.
_grepq_twin() {	# the original shape, restated as tightly as it can be
	sed 's/#.*$//' "$1" \
		| grep -qE '(^|[^_[:alnum:]])pgc_summary([^_[:alnum:]]|$)' && echo yes || echo no
}
check "premise: the grep -q twin is a different function from the real one" \
	"$(type -t _grepq_twin)" "function"
check "the grep -q shape is the one that gets this wrong under pipefail" \
	"$(_grepq_twin "$_bigsuite")" "no"
check "and it agrees with the real reader on a SHORT file, which is why it survived review" \
	"$(_grepq_twin "$_acc/declares.sh")" "$(pgc_suite_declares_accounting "$_acc/declares.sh")"
