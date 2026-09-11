#!/usr/bin/env bash
# Make a red nightly FINDABLE WITHOUT KNOWING TO LOOK (#973).
#
# The deep gate ran red two nights and nothing surfaced it; before that, 25
# consecutive nights. Three properties compound and each is reasonable alone: a
# scheduled run has no pull request to be red on, the failing job is named like a
# reporting step rather than a gate, and GitHub notifies the *actor* of a
# schedule event -- whoever last touched the workflow file, not whoever broke it.
#
# So this puts the verdict where somebody already looks: one issue, opened on the
# first red, updated on every red after it, and CLOSED BY THE NEXT GREEN.
#
# ONE ISSUE, NOT ONE PER RUN. A notifier that files a new issue nightly is a
# notifier people filter, and a filtered notifier is the state this replaces.
# The issue is found by its exact title, which is why the title carries no run
# number, no date and no job name -- everything variable goes in the body.
#
# IT CLOSES ITSELF. An alert that must be closed by hand becomes an alert nobody
# closes, and then a stale one nobody believes. The green path is as load-bearing
# as the red path and has its own arm.
#
# DRY RUN IS THE TESTED PATH, not a debugging aid: PGC_NIGHTLY_REPORT_DRYRUN=1
# prints the verdict, the title and the body to stdout and calls no `gh`. The
# selftest drives exactly this, so what the arms read is what CI composes.
set -euo pipefail

TITLE="${PGC_NIGHTLY_REPORT_TITLE:-nightly deep gate is red}"

# THE VERDICT IS DERIVED HERE, FROM THE `needs` CONTEXT, AND THAT IS THE POINT.
#
# The first version computed it in the workflow from four named environment
# variables, which made TWO lists: `needs: [...]`, guarded by a set-equality arm
# in selftest 450, and the env block, guarded by nothing. A contributor adding a
# gate was COMPELLED by the arm to update the guarded list and told nothing about
# the one the verdict actually came from -- so the new gate could burn while this
# reported green. #973 reintroduced inside the fix for #973, found by
# @OffgridwithJD, who added a fifth job to a copy of the branch and got a fully
# green tree with a nightly whose failure the reporter could not see.
#
# `toJSON(needs)` carries every entry, so there is one list and nothing to keep in
# agreement -- which beats a guard asserting that two lists agree.
#
# AND IT MAKES THE DECISION TESTABLE. The workflow can only be read; this can be
# DRIVEN, so selftest 450 feeds it tuples and the fire drill exercises the real
# decision path instead of overriding the answer.
verdict_from_needs() {	# verdict_from_needs <json> -> failure|success
	local json="$1" results r
	# `skipped` is not a failure: a fork run, and a fire drill, skip every gate.
	results="$(printf '%s' "$json" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if not isinstance(d, dict) or not d:
    sys.exit(3)
for v in d.values():
    print((v or {}).get("result", "missing"))
' 2>/dev/null)" || return 3
	[ -n "$results" ] || return 3
	for r in $results; do
		case "$r" in
			failure|cancelled|timed_out) echo failure; return 0 ;;
			success|skipped) ;;
			# A result this does not know is NOT a pass. It means the platform
			# grew a state while this did not, and treating it as green restores
			# the silence #973 is about.
			*) echo failure; return 0 ;;
		esac
	done
	echo success
}

if [ "${1:-}" = "--from-needs" ]; then
	# AN EMPTY OR UNPARSEABLE CONTEXT IS REFUSED, not defaulted. `needs` empty
	# means the job list changed shape; reporting green on that is the failure
	# mode this whole file exists to remove.
	if ! verdict="$(verdict_from_needs "${2:?usage: --from-needs <toJSON(needs)>}")"; then
		echo "nightly-report: the needs context was empty or unparseable" >&2
		exit 3
	fi
	shift 2
else
	verdict="${1:?usage: nightly-report.sh <failure|success|--from-needs JSON> [job ...]}"
	shift || true
fi
failed=("$@")

run_url="${PGC_NIGHTLY_RUN_URL:-${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}}"

case "$verdict" in
	failure|success) ;;
	*)
		# NOT a silent default. A verdict this script does not understand means the
		# caller changed and this did not; treating it as success would restore the
		# exact silence the issue is about.
		echo "nightly-report: verdict [$verdict] is neither failure nor success" >&2
		exit 2
		;;
esac

body_failure() {
	printf '%s\n' "The nightly deep gate failed."
	printf '\n'
	printf 'Run: %s\n' "$run_url"
	printf '\n'
	if [ "${#failed[@]}" -gt 0 ]; then
		printf 'Jobs that did not succeed:\n\n'
		printf '  - %s\n' "${failed[@]}"
	else
		# The caller reported a failure and named no job. Say so rather than
		# printing an empty list, which reads as "nothing failed".
		printf 'No job name was reported with this failure, which is itself worth looking at.\n'
	fi
	printf '\n'
	printf 'This issue is opened by the nightly on its first red, updated on each red\n'
	printf 'after it, and closed automatically by the next green run.\n'
}

body_success() {
	printf '%s\n' "The nightly deep gate is green again."
	printf '\n'
	printf 'Run: %s\n' "$run_url"
	printf '\n'
	printf 'Closing automatically. An alert that must be closed by hand becomes one\n'
	printf 'nobody closes, and then a stale one nobody believes.\n'
}

if [ "${PGC_NIGHTLY_REPORT_DRYRUN:-0}" = 1 ]; then
	printf 'verdict: %s\n' "$verdict"
	printf 'title: %s\n' "$TITLE"
	printf -- '--- body ---\n'
	if [ "$verdict" = failure ]; then body_failure; else body_success; fi
	exit 0
fi

# EXACT TITLE MATCH, not a search-relevance match. `gh issue list --search` is a
# full-text query and would find any issue mentioning these words -- including
# the ones the two of us have filed ABOUT this mechanism.
# NARROWED SERVER-SIDE, THEN MATCHED EXACTLY HERE. A bare `--limit 100` silently
# misses the target once the tracker holds more than a hundred open issues, the
# lookup returns empty, and every red opens a NEW issue -- which is precisely "a
# notifier people filter", the thing this design rests on not being
# (@OffgridwithJD). The search narrows the window; the exact match is still done
# here, because `--search` is full-text and would also find the issues the two of
# us have filed ABOUT this mechanism.
existing="$(gh issue list --state open --limit 100 --search "\"$TITLE\" in:title" \
	--json number,title \
	--jq "map(select(.title == \"$TITLE\")) | .[0].number // empty")"

if [ "$verdict" = failure ]; then
	if [ -n "$existing" ]; then
		gh issue comment "$existing" --body "$(body_failure)"
		echo "nightly-report: commented on #$existing"
	else
		gh issue create --title "$TITLE" --body "$(body_failure)"
		echo "nightly-report: opened a new issue"
	fi
else
	if [ -n "$existing" ]; then
		gh issue comment "$existing" --body "$(body_success)"
		gh issue close "$existing" --reason completed
		echo "nightly-report: closed #$existing"
	else
		echo "nightly-report: green, and nothing open to close"
	fi
fi
