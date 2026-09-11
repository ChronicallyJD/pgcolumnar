# ---- a red nightly must be findable without knowing to look ----------------
#
# #973. The deep gate ran red two nights and nothing surfaced it; before that,
# 25 consecutive nights. Three properties compound and each is reasonable alone:
# a scheduled run has no pull request to be red on, the job that failed is named
# like a reporting step rather than a gate, and GitHub notifies the ACTOR of a
# schedule event -- whoever last touched the workflow file, not whoever broke it.
#
# So the workflow carries a `red-nightly` job that opens one issue on the first
# red, updates it on each red after, and CLOSES IT on the next green.
#
# WHAT THIS PART CAN AND CANNOT SEE, said first because the gap is the point of
# #973. It drives the reporter's composition through its dry run, and it asserts
# the WIRING structurally. It cannot see the issue being created, because that
# needs a live run -- and "a notifier never seen to fire is indistinguishable
# from none" is this issue's own sentence. The firing is demonstrated once, by a
# fire drill on a branch, and recorded in the PR rather than claimed here.

_rn_wf="$TESTDIR/../.github/workflows/nightly.yml"
_rn_sh="$TESTDIR/../.github/scripts/nightly-report.sh"

check "premise: the nightly workflow and the reporter are both present" \
	"$([ -r "$_rn_wf" ] && [ -x "$_rn_sh" ] && echo yes || echo no)" "yes"

# ---- the wiring, derived from the workflow rather than listed here ----------
#
# A job added later and NOT added to `needs` would be invisible to the reporter,
# and the reporter would report green while it burned. So the claim is
# set equality against every other job key, computed from the file.
_rn_jobs="$(awk '/^jobs:/{inj=1;next} inj && /^  [a-zA-Z_-]+:[[:space:]]*$/{
	k=$1; sub(/:$/,"",k); print k}' "$_rn_wf" | grep -v '^red-nightly$' | sort)"
_rn_n=$(printf '%s\n' "$_rn_jobs" | grep -c .)
check "premise: the other nightly jobs were parsed, so the comparison is real" \
	"$([ "${_rn_n:-0}" -ge 3 ] && echo yes || echo no)" "yes"

# `needs: [a, b, c]` on one line, which is how the job is written.
_rn_needs="$(sed -n 's/^    needs: \[\(.*\)\]$/\1/p' "$_rn_wf" |
	tr ',' '\n' | tr -d ' ' | grep -v '^$' | sort)"
check "premise: the reporter's needs list was parsed" \
	"$([ -n "$_rn_needs" ] && echo yes || echo empty)" "yes"

check "the reporter waits on EVERY other nightly job (#973)" \
	"$(printf '%s' "$_rn_jobs" | md5sum | cut -c1-12)" \
	"$(printf '%s' "$_rn_needs" | md5sum | cut -c1-12)"

# It must run on failure AND on success, or the close path never happens.
check "the reporter runs on every outcome, not only on failure" \
	"$(grep -c '^    if: always() &&' "$_rn_wf")" "1"

# Opening an issue needs the permission, and the workflow's default is read-only.
check "and it is granted issues: write, which the workflow default withholds" \
	"$(awk '/^  red-nightly:/{p=1} p&&/issues: write/{print "yes"; exit}' "$_rn_wf")" "yes"

# ---- the reporter's own composition, driven rather than read ---------------

_rn_fail="$(PGC_NIGHTLY_REPORT_DRYRUN=1 PGC_NIGHTLY_RUN_URL="https://example/run/7" \
	bash "$_rn_sh" failure "coverage report (PG 18)" 2>&1)"

check "a failure names the run so a reader can reach it" \
	"$(printf '%s' "$_rn_fail" | grep -c 'https://example/run/7')" "1"
check "and names the job that failed, not just that something did" \
	"$(printf '%s' "$_rn_fail" | grep -c 'coverage report (PG 18)')" "1"

# ONE ISSUE, NOT ONE PER RUN. A notifier that files a new issue nightly is one
# people filter, and a filtered notifier is the state this replaces. The title is
# what makes updates land on the same issue, so it must carry nothing variable.
check "the title carries no run number, so every red lands on one issue" \
	"$(printf '%s' "$_rn_fail" | sed -n 's/^title: //p' | grep -c '[0-9]')" "0"

_rn_ok="$(PGC_NIGHTLY_REPORT_DRYRUN=1 PGC_NIGHTLY_RUN_URL="https://example/run/8" \
	bash "$_rn_sh" success 2>&1)"
check "a green run composes the closing message, so the alert clears itself" \
	"$(printf '%s' "$_rn_ok" | grep -c 'green again')" "1"
check "and the green path reuses the same title, or it would close nothing" \
	"$(printf '%s' "$_rn_ok" | sed -n 's/^title: //p')" \
	"$(printf '%s' "$_rn_fail" | sed -n 's/^title: //p')"

# A VERDICT IT DOES NOT UNDERSTAND MUST NOT READ AS GREEN. If the caller changes
# and this does not, treating the unknown value as success restores exactly the
# silence #973 is about.
PGC_NIGHTLY_REPORT_DRYRUN=1 bash "$_rn_sh" probably >/dev/null 2>&1 && _rn_rc=0 || _rn_rc=$?
check "an unrecognised verdict is refused rather than treated as green" \
	"$_rn_rc" "2"

# A failure with no job name must say so rather than print an empty list, which
# a reader parses as "nothing failed".
_rn_bare="$(PGC_NIGHTLY_REPORT_DRYRUN=1 bash "$_rn_sh" failure 2>&1)"
check "a failure naming no job says so rather than printing an empty list" \
	"$(printf '%s' "$_rn_bare" | grep -c 'No job name was reported')" "1"

unset _rn_wf _rn_sh _rn_jobs _rn_n _rn_needs _rn_fail _rn_ok _rn_rc _rn_bare
