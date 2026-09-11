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
verdict="${1:?usage: nightly-report.sh <failure|success> [failed-job ...]}"
shift || true
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
existing="$(gh issue list --state open --limit 100 --json number,title \
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
