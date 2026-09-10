# ---- no suite pipes a captured string into an early-exit reader (#486) -------
#
# `echo "$s" | grep -q PATTERN` under `set -o pipefail` answers "not found" when
# the WRITER fails, whatever the string contained. The reader exits as soon as it
# has its answer, the writer takes EPIPE, and pipefail calls the pipeline failed.
# The `&&` arm never runs and the helper reports absence.
#
# This is not theoretical and it is not new here. #473 found it in this file's own
# membership test, and it came back in native_agg.sh, where it reported "the
# metadata aggregate node did not run" on PG18 CI for a plan that contained the
# node -- a red that reads exactly like a planner regression in the area #133 and
# #140 live in. The tell was a `Broken pipe` line beside a result the same run's
# summary contradicted.
#
# The failure direction is what makes it worth a rule: it always reports the
# thing you were looking for as ABSENT, which is the answer that sends someone
# looking for a defect that is not there.
#
# The control below runs first, because a rule with no demonstrated failure is a
# style preference, and this one is not.
_epipe_demo="$PGC_WORKDIR/epipe_demo.sh"
cat > "$_epipe_demo" <<'DEMO'
set -uo pipefail
big="MATCHME
$(head -c 300000 /dev/zero | tr '\0' 'y')"
piped() { echo "$1" | grep -q 'MATCHME' && echo yes || echo no; }
cased() { case "$1" in *MATCHME*) echo yes ;; *) echo no ;; esac; }
echo "piped=$(piped "$big" 2>/dev/null) cased=$(cased "$big")"
DEMO
_epipe_result="$(bash "$_epipe_demo" 2>/dev/null)"

# The string CONTAINS the pattern, on its first line, in both arms. Only the
# answers differ. Written large on purpose: at a few kilobytes the write fits in
# the pipe buffer and completes before the reader can exit, which is why this
# shape passes almost every time and then does not.
check "control: piping a large string into grep -q reports a match as absent" \
	"$_epipe_result" "piped=no cased=yes"

# The rule itself. A pipeline whose left side is a shell builtin writing a
# captured string, and whose right side is a reader that exits early AND whose
# EXIT STATUS is the answer being read. That last part is the whole rule: the
# damage is a wrong verdict, not a wrong message.
#
# So `grep -q` is in scope and `| head -1` inside a diagnostic string is not.
# Those exist here (analyze_stats.sh prints a plan's first line that way) and
# they can lose their pipeline's status without changing any check, because the
# substitution is used as text. They are left alone on purpose rather than
# missed; the worst they do is print to stderr.
#
# Scoped to echo and printf deliberately for the same reason. A pipeline out of
# psql or a file is a different question with a different answer, and a rule that
# flagged those too would be argued with rather than kept.
# bench/ IS SCANNED TOO, and it was not. The PATTERN scoping to echo and printf
# is a stated decision above. The DIRECTORY scoping to test/ was never a decision
# at all -- it fell out of writing "$TESTDIR"/*.sh -- and bench/ held six
# instances of the exact shape this rule forbids, one of them guarding a premise
# loop with `|| continue`, in files the rule never looked at.
#
# They were latent rather than live: each writer is a printf of a few arm names,
# far under the 64 KB pipe buffer, so it completes before grep -q exits and never
# takes EPIPE. That is precisely the "passes almost every time and then does not"
# the control above demonstrates, which is the reason to fix them rather than to
# record that they happen to work.
#
# NON-RECURSIVE, one glob per directory, which is what the original did: it
# passed "$TESTDIR"/*.sh, so its -r never applied. Handing grep the DIRECTORIES
# instead would activate it and sweep test/selftest/ -- where this file's own
# explanation of the rule, and the deliberate piped() demo above, both match the
# pattern they exist to describe. Sweeping the file that enforces a rule for
# instances of that rule is selftest 260's mistake once removed.
# test/selftest/ IS SCANNED TOO, AND IT WAS NOT, for the same reason bench/ was
# not: the directory scoping was never a decision, it fell out of writing
# "$TESTDIR"/*.sh. Three fragments held the exact shape this rule forbids --
# 350's corpus membership test, 300's directory-coverage test, 340's Makefile
# sweep -- inside the directory that enforces the rule.
#
# NOT LATENT. 350's reddened #923's `suites (PG 17)` on a pytest name that
# exists, while PG 18 passed the same commit. At corpus size the writer is small
# enough to win the race on an idle machine, which is why it survived: measured
# at 170 names over 400 trials, 0 false absences idle and 6 under load, against 0
# either way for the here-string form.
#
# The exemption is DERIVED, not listed. This file's own control below is inside a
# quoted heredoc, and so is any other deliberate demonstration of the shape; a
# line inside one is text being written to a file, not a pipeline this suite
# runs. A filename allowlist would have to be maintained, and this rule exists
# because things that must be maintained are not.
_epipe_globs=("$TESTDIR"/*.sh)
[ -d "$TESTDIR/../bench" ] && _epipe_globs+=("$TESTDIR"/../bench/*.sh)
[ -d "$TESTDIR/selftest" ] && _epipe_globs+=("$TESTDIR"/selftest/*.sh)

# file:line pairs that sit inside a quoted heredoc, computed from the files.
_epipe_heredoc_lines() {
	awk '
		# Reset per FILE. awk keeps globals across inputs, so an unterminated
		# heredoc in one file leaves the scanner inside one for every file after
		# it -- and a later line that happens to equal the stale tag closes it in
		# the wrong place. Measured: without this, 080s own line 26 fell OUTSIDE
		# the exemption when the sweep ran over all 302 files, and inside it when
		# the same function ran over that file alone.
		FNR == 1 { inhd = 0; tag = "" }
		!inhd && match($0, /<<[-]?'"'"'[A-Za-z_][A-Za-z0-9_]*'"'"'/) {
			tag = substr($0, RSTART, RLENGTH)
			gsub(/^<<[-]?'"'"'/, "", tag); gsub(/'"'"'$/, "", tag)
			inhd = 1; next
		}
		inhd {
			t = $0; gsub(/^[ \t]+|[ \t]+$/, "", t)
			if (t == tag) { inhd = 0; next }
			# FNR, not NR. NR is cumulative across inputs, so the second file
			# onwards reports line numbers from a running total and no key ever
			# matches the grep -n output it is compared against. It is the
			# neighbouring question answered plausibly: single-file runs agree,
			# because there NR == FNR.
			print FILENAME ":" FNR ":"
		}
	' "$@"
}
_epipe_hd="$(_epipe_heredoc_lines "${_epipe_globs[@]}" 2>/dev/null || true)"
# Comment lines are excluded first. A comment is not a pipeline this suite runs,
# and the rule's own explanation -- and the note beside every site that was fixed
# -- necessarily spells the shape out. A sweep that counts its own documentation
# is selftest 260's mistake.
# ANY PRODUCER, not just echo and printf. This reverses a scoping decision
# recorded above, so the reason is recorded too.
#
# The rule's own stated principle is a reader that exits early AND whose EXIT
# STATUS is the answer being read. That is producer-independent: the writer takes
# EPIPE whether it is a builtin, a psql, an ldd or an ss. Scoping to echo and
# printf was a narrower implementation than the principle, justified by "a
# pipeline out of psql or a file is a different question" -- which is true of
# `| head -1` used as TEXT, and false of `| grep -q` used as a VERDICT.
#
# Twenty-six sites were outside the old pattern, two of them in lib.sh and shared
# by every suite that asks whether a plan is a columnar scan. The worst was
# native_vecskip.sh's "premise: and it is not the scalar scan", which WANTS "no":
# a spurious EPIPE answer makes that premise pass for the wrong reason, so the
# race is vacuity there rather than a false red.
#
# NOT CLAIMED TO BE LYING TODAY. Measured by OffgridwithJD, 200 trials per size on
# a loaded box, match always on line one so the answer is knowably yes:
#
#     1,892 bytes (EXPLAIN-sized)   0/200 wrong
#     8,893 bytes                   1/200   <- first observed lie
#    66,894 bytes                  21/40
#   288,894 bytes                  40/40
#   control, match on the LAST line so grep reads to EOF: 0/200 at every size
#
# It is LATENT, and the mechanism has no floor -- the probability rises with size
# rather than crossing a threshold, which refuted a clean pipe-capacity
# hypothesis. Reasoning about "small enough" is how #473, #476 and selftest 350
# each survived, so the rule sweeps instead.
# The leading [^|] excludes the `||` OPERATOR. Widening from the echo/printf
# form lost that exclusion for free: `[ "$rc" = 124 ] || grep -q PAT <<<"$out"`
# is a fallback branch reading a here-string -- no writer process, so no EPIPE --
# and the first version of the widened pattern flagged both fuzz suites for it.
_epipe_hits="$(grep -nE '[^|]\|[[:space:]]*grep[[:space:]]+-[a-zA-Z]*q' \
	"${_epipe_globs[@]}" 2>/dev/null \
	| grep -v '/harness_selftest.sh:' \
	| grep -vE '^[^:]+:[0-9]+:[[:space:]]*#' || true)"
# Drop hits whose file:line is inside a quoted heredoc.
if [ -n "$_epipe_hd" ] && [ -n "$_epipe_hits" ]; then
	_epipe_hits="$(printf '%s\n' "$_epipe_hits" | while IFS= read -r _eh; do
		_ehk="${_eh%%:*}:$(printf '%s' "$_eh" | cut -d: -f2):"
		[ "$(grep -cxF "$_ehk" <<<"$_epipe_hd" || true)" != 0 ] || printf '%s\n' "$_eh"
	done)"
fi
_epipe_count="$(printf '%s' "$_epipe_hits" | grep -c . || true)"
[ -n "$_epipe_hits" ] || _epipe_count=0
check "no suite pipes a captured string into an early-exit reader" \
	"$_epipe_count" "0"
[ "$_epipe_count" = "0" ] || printf '%s\n' "$_epipe_hits" | sed 's/^/      /' | head -20

# And the scan has to be looking at something. A glob that matched nothing, or a
# TESTDIR that moved, would report zero hits and read as compliance.
#
# BOTH premises below are computed from ONE list of the files the sweep actually
# read, rather than from two independent re-derivations. That is the whole point:
# a premise that recomputes its condition tests the world, not the code.
_epipe_files="$(grep -lE 'grep' "${_epipe_globs[@]}" 2>/dev/null || true)"
_epipe_scanned="$(printf '%s' "$_epipe_files" | grep -c . || true)"
check "and the scan examined the suites rather than finding nothing to read" \
	"$([ "${_epipe_scanned:-0}" -ge 20 ] && echo yes || echo "no (scanned $_epipe_scanned)")" "yes"

# bench/ IS SEPARATELY ASSERTED, and the check above cannot stand in for it.
# The bench glob is added conditionally, so if $TESTDIR/../bench ever stops
# resolving -- bench moved or renamed, this file relocated, a differently laid
# out worktree -- the && quietly drops it and the sweep reverts to test/ only.
#
# The count premise does not notice: test/*.sh alone matches 'grep' in 159 files
# against a threshold of 20, so it passes with bench/ silently absent. A count of
# files scanned is a premise that the sweep read SOMETHING. It is not a premise
# that it read the directory this rule was widened to cover, and it cannot tell
# "scanned test/ and bench/" from "scanned test/ and gave up on bench/".
#
# Which is this rule's own failure mode one level up: coverage narrowing with
# nothing able to see that it narrowed.
# Counted from the FILES READ, not from the glob list, and this is the third
# version of this one check. Each earlier one was a step short:
#
#   v1  globbed bench/*.sh again here      -> asserted bench/ EXISTS
#   v2  counted entries in _epipe_globs    -> asserted bench/ is LISTED
#   v3  counts bench paths among the files actually read
#
# v2 was one step short because bash leaves an UNMATCHED GLOB LITERAL unless
# nullglob is set, and nothing in this harness sets it. So a bench/ holding no
# .sh files still contributes one array entry -- the literal ".../bench/*.sh" --
# and v2 passes while the sweep read nothing from it. Verified: an array built
# over a nonexistent directory has size 1, not 0.
_epipe_bench="$(printf '%s' "$_epipe_files" | grep -c '/bench/' || true)"
check "and bench/ was in the scan, which is the hole this rule had" \
	"$([ "${_epipe_bench:-0}" -ge 1 ] && echo yes || echo "no (bench files read: $_epipe_bench)")" "yes"

# selftest/ gets its own arm for exactly the reason bench/ does: its glob is
# added conditionally, and the file-count premise above passes with it silently
# absent.
_epipe_self="$(printf '%s' "$_epipe_files" | grep -c '/selftest/' || true)"
check "and selftest/ was in the scan, which is the hole that reddened #923" \
	"$([ "${_epipe_self:-0}" -ge 5 ] && echo yes || echo "no (selftest files read: $_epipe_self)")" "yes"

# The heredoc exemption must EXEMPT something and must not exempt everything.
# Without the first, the control below is unreachable and this file cannot hold
# its own rule; without the second, the sweep is switched off and reports zero.
_epipe_hd_count="$(printf '%s' "$_epipe_hd" | grep -c . || true)"
check "premise: the heredoc exemption found heredoc lines to exempt" \
	"$([ "${_epipe_hd_count:-0}" -ge 1 ] && echo yes || echo "no ($_epipe_hd_count)")" "yes"
# A PROPORTION, not a guessed ceiling. The first version of this arm used a bare
# 2000 and went red at 2,502 heredoc lines in a corpus that was entirely healthy
# -- a hand-written number failing for the reason hand-written numbers fail here.
_epipe_total_lines="$(cat "${_epipe_globs[@]}" 2>/dev/null | grep -c '' || true)"
echo "  epipe sweep: total lines=$_epipe_total_lines, inside a quoted heredoc=$_epipe_hd_count"
check "premise: the sweep read lines to classify" \
	"$([ "${_epipe_total_lines:-0}" -ge 1000 ] && echo yes || echo "no ($_epipe_total_lines)")" "yes"
check "premise: and the exemption covers a minority of them, not the corpus" \
	"$([ "$((_epipe_hd_count * 2))" -lt "${_epipe_total_lines:-0}" ] && echo yes \
		|| echo "no ($_epipe_hd_count of $_epipe_total_lines)")" "yes"

# The rule must still SEE a violation that is not in a heredoc. A sweep whose
# exemption is too broad reports zero for the same reason a correct one does.
_epipe_probe="$PGC_WORKDIR/epipe_probe.sh"
# The shape is assembled from a fragment rather than written out, so these
# generator lines do not themselves match the sweep and need no exemption.
_epipe_shape='x() { printf "%s" "$1" | grep -%s PATTERN; }'
{
	printf '%s\n' "$(printf "$_epipe_shape" '%s' q)"
	printf 'cat > /dev/null <<%sDEMO%s\n' "'" "'"
	printf '%s\n' "$(printf "$_epipe_shape" '%s' q)"
	printf 'DEMO\n'
} > "$_epipe_probe"
_epipe_probe_hd="$(_epipe_heredoc_lines "$_epipe_probe" 2>/dev/null || true)"
check "the sweep's pattern sees both lines of the probe" \
	"$(grep -cE '[^|]\|[[:space:]]*grep[[:space:]]+-[a-zA-Z]*q' "$_epipe_probe")" "2"
check "and the heredoc exemption covers the one inside the heredoc, not the other" \
	"$(printf '%s' "$_epipe_probe_hd" | grep -c ':3:' || true)" "1"
check "and does not cover the live one above it" \
	"$(printf '%s' "$_epipe_probe_hd" | grep -c ':1:' || true)" "0"

# The widening itself, asserted. A producer that is neither echo nor printf must
# be caught, or the reversal above is prose and the 26 sites come back.
_epipe_wide="$PGC_WORKDIR/epipe_wide.sh"
printf 'ldd /bin/sh | grep -%s libc && echo yes || echo no\n' q > "$_epipe_wide"
check "the sweep catches a producer that is neither echo nor printf" \
	"$(grep -cE '[^|]\|[[:space:]]*grep[[:space:]]+-[a-zA-Z]*q' "$_epipe_wide")" "1"
check "premise: and the old echo/printf pattern did NOT catch it" \
	"$(grep -cE '(echo|printf)[^|]*\|[[:space:]]*grep -[a-zA-Z]*q' "$_epipe_wide")" "0"

# `||` IS NOT A PIPE. A fallback branch reading a here-string has no writer
# process and cannot take EPIPE. The first version of the widened pattern flagged
# both fuzz suites for exactly that, so it is pinned here rather than left to be
# rediscovered the next time the pattern is touched.
_epipe_oror="$PGC_WORKDIR/epipe_oror.sh"
printf '[ "$rc" = 124 ] || grep -%s PAT <<<"$out"\n' q > "$_epipe_oror"
check "the sweep does not mistake the || operator for a pipe" \
	"$(grep -cE '[^|]\|[[:space:]]*grep[[:space:]]+-[a-zA-Z]*q' "$_epipe_oror")" "0"
check "premise: and the line really does hold the reader it must not flag" \
	"$(grep -c 'grep -q PAT' "$_epipe_oror")" "1"

