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
# THE PATTERN IS DEFINED ONCE. Four places used to carry a copy of this regex --
# the sweep and three probe arms -- and a copy is how a probe comes to test a
# pattern the sweep no longer uses. The arms below read this variable, so they go
# red when the sweep's own pattern drifts rather than passing against the old one.
#
# The leading [^|] excludes the `||` OPERATOR. Widening from the echo/printf
# form lost that exclusion for free: `[ "$rc" = 124 ] || grep -q PAT <<<"$out"`
# is a fallback branch reading a here-string -- no writer process, so no EPIPE --
# and the first version of the widened pattern flagged both fuzz suites for it.
_epipe_pat='[^|]\|[[:space:]]*grep[[:space:]]+-[a-zA-Z]*q'

# A PIPELINE CAN BE SPLIT ACROSS LINES, AND A LINE-ORIENTED SWEEP IS BLIND TO IT.
# Two shapes, both one pipeline to bash, neither visible to a grep that reads one
# line at a time:
#
#     q "$SQL" |                            the reader is on the NEXT line, so
#     grep -q 'Vectorized' && echo yes      the producer's line holds no reader
#
#     sed 's/x//' "$1" \
#     | grep -qE 'pgc_summary'              the reader's line BEGINS with the
#                                           operator, and at column 1 there is
#                                           no [^|] in front of it
#
# The first shape is invisible to a physical-line pattern, and six live sites were
# written that way: three in vector_agg_rescan_memory.sh, one each in
# unique_conc.sh, native_groupagg_batch.sh and bench/run_clickbench.sh.
#
# THE SECOND SHAPE IS NARROWER THAN IT LOOKS, and the measurement is recorded
# because the obvious reading is wrong. An INDENTED `| grep -q` continuation was
# never hidden: the leading whitespace satisfies [^|], so the physical pattern
# matches it on its own line, which is why selftest 390's deliberate twin needed
# the heredoc exemption rather than the joiner. Only an UNINDENTED one escapes,
# and the corpus holds none -- zero lines begin with `|` at column 1. Joining
# covers it anyway: the cost is nothing once the joiner exists, and "nobody writes
# it unindented" is a habit rather than a rule. unique_conc.sh is the one
# to read. The comment directly above it explains this exact trap, the output is
# already captured into a variable for that reason, and the next line pipes that
# variable into an early-exit reader anyway. Documenting a trap is not avoiding
# it, and a rule that cannot see the shape is how the note and the defect came to
# live two lines apart.
#
# So the sweep joins the continuation and applies the SAME pattern to the joined
# text. Three decisions in the joiner, each measured rather than reasoned about:
#
# PAIRWISE, one content line ahead, not a full logical-line assembly. `a |` /
# `b |` / `grep -q` needs no three-line join: the (b, grep) pair matches on its
# own and reports at b, which is the producer whose write takes the EPIPE and so
# is where the fix goes.
#
# BLANK AND COMMENT LINES ARE SKIPPED, because bash skips them after a `|`.
# Measured: `echo hi |` / blank / `# one` / blank / `grep -q hi` runs the reader
# and reports the match. A joiner that stopped at the first blank line would be
# blind to exactly the shape someone creates by annotating a long pipeline.
#
# A COMMENT IS NEVER A PRODUCER. Measured both ways: a comment line ending in `\`
# does not continue into the next line, and a comment line ending in `|` does not
# make the next line its reader. This matters here more than anywhere -- the file
# is full of comments that spell the forbidden shape out, and not one of them can
# become half of a hit.
_epipe_joined_lines() {
	awk '
		function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
		function content(s) { return s !~ /^[ \t]*$/ && s !~ /^[ \t]*#/ }
		# Reset per FILE, for the reason the heredoc scanner does: awk globals
		# outlive the input boundary, so a file whose last line ends in a pipe
		# would otherwise be joined to the first line of the file after it.
		FNR == 1 { pend = 0 }
		{
			# A pending producer skips blanks and comments and stays pending,
			# which is what bash does after a `|`.
			if (pend && !content($0)) next
			if (pend) {
				printf "%s:%d:%s %s\n", FILENAME, pline, ptext, trim($0)
				pend = 0
			}
			# ...and the line that closed one may open the next.
			if (!content($0)) next
			t = $0; sub(/[ \t]+$/, "", t)
			if (t ~ /\|$/ && t !~ /\|\|$/) { ptext = t; pline = FNR; pend = 1 }
			else if (t ~ /\\$/) { sub(/\\$/, "", t); ptext = t; pline = FNR; pend = 1 }
		}
	' "$@"
}
_epipe_logical="$(_epipe_joined_lines "${_epipe_globs[@]}" 2>/dev/null || true)"

# ONE pattern, TWO streams: the physical lines as grep -n reports them, and the
# logical lines the joiner builds. Keyed on file:line, so a site that matches in
# both streams is one site rather than two.
_epipe_hits="$(
	{
		# -H, not -n alone: grep omits the filename when it reads ONE file, and
		# the heredoc exemption below keys on file:line. A corpus that ever
		# narrowed to a single file would hand the exemption keys it cannot
		# match, and the sweep would silently stop exempting anything.
		grep -nHE "$_epipe_pat" "${_epipe_globs[@]}" 2>/dev/null
		printf '%s\n' "$_epipe_logical" | grep -E "$_epipe_pat"
	} | grep . \
	  | grep -vE '^[^:]+:[0-9]+:[[:space:]]*#' \
	  | awk -F: '!seen[$1 ":" $2]++' || true)"

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
# THE FILENAME EXCLUSION IS GONE, because it excluded nothing and this rule's own
# argument is that a filename list is the thing it exists to avoid. `grep -v
# '"'"'/harness_selftest.sh:'"'"'` entered with the rule itself (23c96c7, 2026-08-07), when
# harness_selftest.sh was the monolith and held 25 occurrences of `grep` inside its
# own explanation of the forbidden shape. #554 split that file into the parts in
# this directory three days later, and it has held none since: 60 lines, zero.
#
# What remains is the DERIVED exemption -- a line inside a quoted heredoc is text,
# whatever file it sits in -- which is the form the comment above already argues
# for. The arm below keeps the removal honest. Put a reader back into
# harness_selftest.sh and the sweep will flag it, which it should: that file runs
# its pipelines like any other.
check "premise: the file the old filename exclusion named holds no reader to exclude" \
	"$(grep -c 'grep' "$TESTDIR/harness_selftest.sh" || true)" "0"

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
	"$(grep -cE "$_epipe_pat" "$_epipe_probe")" "2"
check "and the heredoc exemption covers the one inside the heredoc, not the other" \
	"$(printf '%s' "$_epipe_probe_hd" | grep -c ':3:' || true)" "1"
check "and does not cover the live one above it" \
	"$(printf '%s' "$_epipe_probe_hd" | grep -c ':1:' || true)" "0"

# The widening itself, asserted. A producer that is neither echo nor printf must
# be caught, or the reversal above is prose and the 26 sites come back.
_epipe_wide="$PGC_WORKDIR/epipe_wide.sh"
printf 'ldd /bin/sh | grep -%s libc && echo yes || echo no\n' q > "$_epipe_wide"
check "the sweep catches a producer that is neither echo nor printf" \
	"$(grep -cE "$_epipe_pat" "$_epipe_wide")" "1"
check "premise: and the old echo/printf pattern did NOT catch it" \
	"$(grep -cE '(echo|printf)[^|]*\|[[:space:]]*grep -[a-zA-Z]*q' "$_epipe_wide")" "0"

# `||` IS NOT A PIPE. A fallback branch reading a here-string has no writer
# process and cannot take EPIPE. The first version of the widened pattern flagged
# both fuzz suites for exactly that, so it is pinned here rather than left to be
# rediscovered the next time the pattern is touched.
_epipe_oror="$PGC_WORKDIR/epipe_oror.sh"
printf '[ "$rc" = 124 ] || grep -%s PAT <<<"$out"\n' q > "$_epipe_oror"
check "the sweep does not mistake the || operator for a pipe" \
	"$(grep -cE "$_epipe_pat" "$_epipe_oror")" "0"
check "premise: and the line really does hold the reader it must not flag" \
	"$(grep -c 'grep -q PAT' "$_epipe_oror")" "1"

# ---- the joiner itself, asserted ---------------------------------------------
#
# A sweep whose joiner joins nothing is the line-oriented sweep with extra prose,
# and it reports zero hits exactly as a clean one does. Measured at 5,559 logical
# lines built from two or more physical lines. A FLOOR, not a ceiling: the number
# grows with every continuation anyone writes, and a hand-written ceiling is what
# went red at 2,502 heredoc lines in a corpus that was entirely healthy.
_epipe_joins="$(printf '%s' "$_epipe_logical" | grep -c . || true)"
echo "  epipe sweep: logical lines joined from two or more physical lines=$_epipe_joins"
check "premise: the joiner joined continuations, so the sweep is not still line-oriented" \
	"$([ "${_epipe_joins:-0}" -ge 500 ] && echo yes || echo "no ($_epipe_joins)")" "yes"

# THE JOINER IS NOT HEREDOC-AWARE, and it does not need to be while no line that
# opens a heredoc also continues. `cat <<'"'"'X'"'"' |` puts the body on the next line, so
# the join would pair the producer with a line of TEXT instead of with its reader
# -- a false negative, which is the direction this whole rule exists to prevent.
#
# Measured: zero of the 179 heredoc-opening lines in the corpus end in a bare `|`
# or a `\`. So this arm is the premise INSTEAD OF the machinery. If it goes red,
# the joiner needs to skip to the terminator; writing that now would be an
# instrument with nothing exercising it, which is how twelve suites came to
# maintain a check counter that nothing read.
_epipe_hd_cont="$(grep -nE "(^|[^<])<<-?['\"]?[A-Za-z_]" "${_epipe_globs[@]}" 2>/dev/null \
	| grep -cE '([^|]\||\\)[[:space:]]*$' || true)"
check "premise: no line opens a heredoc AND continues, which is what lets the joiner ignore bodies" \
	"$_epipe_hd_cont" "0"

# A `\` CONTINUATION JOINS THE NEXT PHYSICAL LINE, with no skipping: bash removes
# the backslash-newline before it tokenizes, so a comment on the following line
# comments out the rest of the command and a blank line ends it. The joiner skips
# blanks and comments for BOTH forms, which is bash for `|` and is NOT bash for
# `\`, and that difference can only produce a wrong answer where such a line
# exists. None does, and it is not luck: a comment placed between `check "..." \`
# and its argument swallowed that check's arguments in selftest 420, the part died
# before pgc_summary, and `bash -n` was happy about all of it. The shape is a
# defect on its own, so the arm earns its keep whichever way it goes red.
_epipe_bs_gap="$(awk '
	FNR == 1 { prev = 0 }
	{
		if (prev && ($0 ~ /^[ \t]*$/ || $0 ~ /^[ \t]*#/)) print FILENAME ":" FNR
		t = $0; sub(/[ \t]+$/, "", t)
		prev = (t ~ /\\$/ && t !~ /^[ \t]*#/)
	}' "${_epipe_globs[@]}" 2>/dev/null | grep -c . || true)"
check "premise: no backslash continuation is followed by a blank or a comment" \
	"$_epipe_bs_gap" "0"

# ---- the two split shapes, as fixtures --------------------------------------
#
# Assembled from fragments rather than written out, for the reason the probe above
# is: a literal here would be a site the sweep then has to exempt.
_epipe_two="$PGC_WORKDIR/epipe_twoline.sh"
{
	printf 'q "$SQL" %s\n' '|'
	printf '\tgrep -%s PATTERN && echo yes || echo no\n' q
} > "$_epipe_two"
check "the sweep sees a pipeline split AFTER the pipe, which all six live sites were" \
	"$(_epipe_joined_lines "$_epipe_two" | grep -cE "$_epipe_pat" || true)" "1"
check "and reports it at the PRODUCER's line, which is the line that has to change" \
	"$(_epipe_joined_lines "$_epipe_two" | grep -E "$_epipe_pat" | cut -d: -f2)" "1"

_epipe_bsplit="$PGC_WORKDIR/epipe_backslash.sh"
{
	printf 'sed %ss/x//%s "$1" \\\n' "'" "'"
	printf '%s grep -%sE PATTERN && echo yes || echo no\n' '|' q
} > "$_epipe_bsplit"
check "and a pipeline split BEFORE the pipe, with the operator at column 1" \
	"$(_epipe_joined_lines "$_epipe_bsplit" | grep -cE "$_epipe_pat" || true)" "1"
check "premise: and the physical-line pattern alone saw neither of those two" \
	"$(grep -hcE "$_epipe_pat" "$_epipe_two" "$_epipe_bsplit" | awk '{ s += $1 } END { print s + 0 }')" "0"

# THE SAME SPLIT, INDENTED, WAS NEVER INVISIBLE. This arm exists because the first
# version of the one above claimed both shapes were hidden and went red saying so:
# one tab in front of the reader is a [^|], so the physical pattern matches it
# unaided. Pinning the narrower claim keeps the next reader from re-deriving the
# wrong one.
_epipe_bsind="$PGC_WORKDIR/epipe_backslash_indented.sh"
{
	printf 'sed %ss/x//%s "$1" \\\n' "'" "'"
	printf '\t%s grep -%sE PATTERN && echo yes || echo no\n' '|' q
} > "$_epipe_bsind"
check "premise: indent that same reader by a tab and the physical-line pattern sees it unaided" \
	"$(grep -cE "$_epipe_pat" "$_epipe_bsind" || true)" "1"
check "premise: the physical stream names the file even when it reads only one of them" \
	"$(grep -nHE "$_epipe_pat" "$_epipe_bsind" | cut -d: -f1)" "$_epipe_bsind"
check "premise: and without -H it reports a line number where the key wants a path" \
	"$(grep -nE "$_epipe_pat" "$_epipe_bsind" | cut -d: -f1)" "2"
# And the consequence, stated rather than left to be noticed: an indented split
# site is reported TWICE, once at the reader by the physical stream and once at the
# producer by the joiner. Two hits, one pipeline. That is noise in a red report,
# not blindness in a green one, and either line is a line the fix touches -- so it
# is pinned here instead of being suppressed with a third stream to maintain.
check "and an indented split is reported twice, at the reader and at the producer" \
	"$({ grep -nHE "$_epipe_pat" "$_epipe_bsind"
	     _epipe_joined_lines "$_epipe_bsind" | grep -E "$_epipe_pat"
	   } | awk -F: '!seen[$1 ":" $2]++' | grep -c . || true)" "2"

# THE KEY IS EXERCISED, by the one shape that matches twice at the SAME line: a
# pipeline that matches on its own line and also ends in a pipe, so the join
# restates it. Without the key the sweep would count one site as two here.
_epipe_dup="$PGC_WORKDIR/epipe_dup.sh"
{
	printf 'echo "$a" %s grep -%s X %s\n' '|' q '|'
	printf '\tgrep -%s Y\n' q
} > "$_epipe_dup"
check "premise: that shape matches in both streams at one line, which is what the key is for" \
	"$({ grep -nHE "$_epipe_pat" "$_epipe_dup"
	     _epipe_joined_lines "$_epipe_dup" | grep -E "$_epipe_pat"
	   } | grep -c . || true)" "2"
check "and the sweep counts it once, because a hit is keyed on file:line" \
	"$({ grep -nHE "$_epipe_pat" "$_epipe_dup"
	     _epipe_joined_lines "$_epipe_dup" | grep -E "$_epipe_pat"
	   } | awk -F: '!seen[$1 ":" $2]++' | grep -c . || true)" "1"

# The gap form gets its own fixture because bash's behaviour here is the whole
# reason the joiner skips: a reader separated from its producer by blank and
# comment lines still runs.
_epipe_gap="$PGC_WORKDIR/epipe_gap.sh"
{
	printf 'q "$SQL" %s\n' '|'
	printf '\n'
	printf '\t# why this pipeline is shaped the way it is\n'
	printf '\n'
	printf '\tgrep -%s PATTERN && echo yes || echo no\n' q
} > "$_epipe_gap"
check "and it follows the pipe across blank and comment lines" \
	"$(_epipe_joined_lines "$_epipe_gap" | grep -cE "$_epipe_pat" || true)" "1"
# Run, not scanned, and deliberately NOT with an early-exit reader: `wc -c` reads
# to EOF, so this demonstration cannot take the EPIPE it is demonstrating around.
# Joined, the reader receives four bytes. Unjoined, it would be its own command
# reading /dev/null and the output would carry the producer's text instead.
_epipe_gap_demo="$PGC_WORKDIR/epipe_gap_demo.sh"
{
	printf "printf '%%s' abcd %s\n" '|'
	printf '\n'
	printf '\t# a comment in the middle of a pipeline\n'
	printf '\n'
	printf '\twc -c\n'
} > "$_epipe_gap_demo"
check "premise: bash joins a pipeline across blank and comment lines, which is why the joiner must" \
	"$(bash "$_epipe_gap_demo" </dev/null | tr -d ' ')" "4"

# `||` IS NOT A PIPE ACROSS A LINE BREAK EITHER. The single-line case is pinned
# above; joining gives it a second way to be wrong, because a fallback reader on
# the following line sits in the same shape a split pipeline does.
_epipe_oror2="$PGC_WORKDIR/epipe_oror_two.sh"
{
	printf '[ "$rc" = 124 ] %s\n' '||'
	printf '\tgrep -%s PAT <<<"$out"\n' q
} > "$_epipe_oror2"
check "the joiner does not mistake a two-line || fallback for a split pipeline" \
	"$(_epipe_joined_lines "$_epipe_oror2" | grep -cE "$_epipe_pat" || true)" "0"
check "premise: and its second line really does hold the reader it must not flag" \
	"$(grep -c 'grep -q PAT' "$_epipe_oror2")" "1"

# A COMMENT IS NOT A PRODUCER, which is what stops the sweep being fed its own
# documentation. This file alone spells the forbidden shape out a dozen times.
_epipe_cmt="$PGC_WORKDIR/epipe_comment.sh"
{
	printf '# a comment line that ends in a pipe %s\n' '|'
	printf '%s grep -%s PATTERN\n' '|' q
} > "$_epipe_cmt"
check "a comment ending in a pipe is not a producer" \
	"$(_epipe_joined_lines "$_epipe_cmt" | grep -cE "$_epipe_pat" || true)" "0"
check "premise: and bash agrees -- with no command to continue, the reader alone will not parse" \
	"$(bash -n "$_epipe_cmt" 2>&1 | grep -c 'syntax error' || true)" "1"

# ---- the one false positive the JOIN CREATES, and why it is accepted --------
#
# Every fixture above reveals a pipeline that was always there. This one is the
# other kind, and it can be constructed: a double-quoted string continued across
# a line break, whose first line happens to end in a bare `|`, reads as a
# pipeline once the two lines are concatenated.
#
#     note="a pipeline like foo |
#     grep -q bar is banned"
#
# bash sees one assignment of a two-line string. The joiner sees a producer and a
# reader, and the sweep flags it.
#
# ACCEPTED rather than fixed, and the reason is the DIRECTION of the failure.
# Telling the two apart needs quote state carried across lines through $'"'"'...'"'"',
# escapes and nesting -- a new instrument with its own failure modes, replacing
# one that fails LOUD. A false positive names the file and the line and turns the
# gate red; the blindness it replaces printed nothing and went green for six live
# sites. The corpus holds zero of these today, which is what the zero-hit arm
# above measures, and rewriting one if it ever appears costs a line.
_epipe_str="$PGC_WORKDIR/epipe_string.sh"
{
	printf 'note="a pipeline like foo %s\n' '|'
	printf 'grep -%s bar is banned"\n' q
} > "$_epipe_str"
check "the join CREATES a hit on a two-line quoted string, the sweep's one false positive" \
	"$(_epipe_joined_lines "$_epipe_str" | grep -cE "$_epipe_pat" || true)" "1"
check "premise: and bash runs that file as one assignment -- no reader, no output, rc 0" \
	"$(bash "$_epipe_str" </dev/null 2>&1; echo "rc=$?")" "rc=0"
