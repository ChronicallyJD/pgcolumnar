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

# ---- ONE LIST, and the verdict driven rather than read ---------------------
#
# The first version computed the verdict in the workflow from four named
# environment variables. That made two lists: `needs:`, guarded by the arm above,
# and the env block, guarded by nothing -- so a contributor adding a gate was
# COMPELLED to update the guarded one and told nothing about the one that decided
# the verdict. @OffgridwithJD added a fifth job to a copy of this branch,
# registered it in `needs` as the arm above demands and named it in testing.md as
# 240 demands, and got a fully green tree with a nightly gate whose failure the
# reporter could not see. #973 reintroduced inside the fix for #973.
#
# `toJSON(needs)` carries every entry, so there is nothing to keep in agreement.
# The arms below drive the derivation, which the old shape could only be read.
check "the verdict comes from the whole needs context, not a second list" \
	"$(grep -c 'NEEDS_JSON: \${{ toJSON(needs) }}' "$_rn_wf")" "1"
# A ZERO-COUNT ARM CARRIES ITS OWN POSITIVE CASE. A pattern that matches nothing
# and a tree that contains nothing both report 0, and only one of those is the
# claim. This reintroduces the old shape into a copy and requires the pattern to
# see it -- which is not hypothetical care: probing this very file with an
# UNESCAPED `${{` read 0 against a line that plainly contains it, because `$`
# before `{` is not literal to GNU grep. That one reddened. In a zero-count arm
# the same slip passes.
_rn_probe="$(mktemp)"; cp "$_rn_wf" "$_rn_probe"
printf '          SUITES: ${{ needs.suites.result }}\n' >> "$_rn_probe"
check "premise: the per-job-variable pattern sees that shape when it is present" \
	"$(grep -cE '^ +[A-Z]+: \$\{\{ needs\.[a-z-]+\.result \}\}' "$_rn_probe")" "1"
check "and no per-job result variable survives to drift from the context" \
	"$(grep -cE '^ +[A-Z]+: \$\{\{ needs\.[a-z-]+\.result \}\}' "$_rn_wf")" "0"
rm -f "$_rn_probe"

_rn_v() {	# _rn_v JSON -> the derived verdict
	PGC_NIGHTLY_REPORT_DRYRUN=1 bash "$_rn_sh" --from-needs "$1" 2>&1 |
		sed -n 's/^verdict: //p'
}
check "every gate green is a green verdict" \
	"$(_rn_v '{"a":{"result":"success"},"b":{"result":"success"}}')" "success"
check "one gate failing is a red verdict" \
	"$(_rn_v '{"a":{"result":"success"},"b":{"result":"failure"}}')" "failure"
check "a cancelled gate is a red verdict, not a shrug" \
	"$(_rn_v '{"a":{"result":"success"},"b":{"result":"cancelled"}}')" "failure"
check "all skipped is green, which is a fork run and a fire drill" \
	"$(_rn_v '{"a":{"result":"skipped"},"b":{"result":"skipped"}}')" "success"

# THE ARM THAT MAKES THE ONE-LIST CLAIM REAL. A job this file has never heard of
# is covered the day it is added, because the derivation reads the context rather
# than a list anyone maintains. Under the old shape this could not be expressed:
# the verdict came from four names and a fifth was invisible to it.
check "a gate nobody listed here still decides the verdict (#973)" \
	"$(_rn_v '{"a":{"result":"success"},"b":{"result":"success"},"brand-new-gate":{"result":"failure"}}')" \
	"failure"

# A RESULT THE SCRIPT DOES NOT KNOW IS NOT A PASS. The platform growing a state
# while this did not is exactly how a reporter goes quiet.
check "an unrecognised result is refused rather than treated as green" \
	"$(_rn_v '{"a":{"result":"brand_new_state"}}')" "failure"

# An empty context means the job list changed shape. Reporting green on that is
# the failure this whole file exists to remove.
PGC_NIGHTLY_REPORT_DRYRUN=1 bash "$_rn_sh" --from-needs '{}' >/dev/null 2>&1 && _rn_erc=0 || _rn_erc=$?
check "an empty needs context is refused, not defaulted to green" \
	"$_rn_erc" "3"

# A REFUSAL MUST READ AS A REFUSAL, NOT AS A CRASH. The parse dumped a Python
# traceback before the script's own message (@OffgridwithJD). Behaviour was right
# -- rc 3, never green -- but in a CI log a traceback sends the reader after a bug
# in the reporter instead of after the job list changing shape, and this
# mechanism's whole value is that a reader can tell at a glance what happened.
_rn_noise="$(PGC_NIGHTLY_REPORT_DRYRUN=1 bash "$_rn_sh" --from-needs 'not json' 2>&1 || true)"
check "an unparseable context says so without a traceback" \
	"$(printf '%s' "$_rn_noise" | grep -c 'Traceback\|JSONDecodeError')" "0"
check "and it still says what went wrong, rather than saying nothing" \
	"$(printf '%s' "$_rn_noise" | grep -c 'empty or unparseable')" "1"

# A DRILL MUST SAY IT IS A DRILL. Drill 3 did not: rewriting the step to derive
# the verdict from the needs context dropped the marker, the job list came back
# empty, and the issue body read exactly like a genuine red. An alert that cries
# wolf teaches a reader to discount it, which is the state #973 exists to leave.
check "a fire drill identifies itself in the issue it opens" \
	"$(grep -c 'fire drill for #973: no gate actually failed' "$_rn_wf")" "1"
check "and that marker reaches the job list the reporter prints" \
	"$(grep -c 'names+=("\$drill_name")' "$_rn_wf")" "1"

# ---- the issue lookup must not go blind on a busy tracker ------------------
#
# `--limit 100` silently misses the target once more than a hundred issues are
# open: the lookup returns empty and every red opens a NEW issue, the "notifier
# people filter" this design rests on not being (@OffgridwithJD).
#
# AND `--search` IS THE WRONG FIX, measured rather than reasoned: GitHub's search
# index is eventually consistent, and immediately after a close it still reported
# the issue open. A lag the other way misses a freshly-opened issue and opens a
# duplicate -- the same failure by another route. The plain list reads the REST
# collection, which is strongly consistent, and gh paginates past 100 itself.
check "the issue lookup reads past the first hundred open issues" \
	"$(grep -c 'gh issue list --state open --limit 1000' "$_rn_sh")" "1"
check "and does not use the eventually-consistent search index" \
	"$(grep -c 'in:title' "$_rn_sh")" "0"

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

unset _rn_wf _rn_sh _rn_jobs _rn_n _rn_needs _rn_fail _rn_ok _rn_rc _rn_bare _rn_erc _rn_probe _rn_noise
unset -f _rn_v
