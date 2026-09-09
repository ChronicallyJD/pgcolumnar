# ---- the pytest corpus must be documented, or the documentation is decoration -
#
# WHY THIS EXISTS. `test/pytest/TESTS.md` says its job is "what each test asserts,
# and why it exists". It went stale inside a single rework: the corpus grew from
# 25 tests in three files to 54 in five, and the two new files -- 29 tests, every
# one of them added by the rework that answered a review -- were named nowhere in
# it. The header still read "Twenty-five tests in three files".
#
# That is worse than an undocumented directory. A reader who opens a file whose
# stated purpose is completeness does not then go and count the tests, so a
# partial index reads as a total one. The header was not merely out of date, it
# was a false statement of coverage, which is the same defect class the vacuity
# layer in that corpus exists to refuse one level down.
#
# WHY HERE AND NOT IN THE CORPUS ITSELF. Nothing runs pytest. `SUITES` in
# run_all_versions.sh does not list it and no workflow in .github/ invokes it
# (README.md in that directory records the decision and its price). A guard
# written as a pytest test would therefore never run in the gate, and a guard
# that does not run is a comment. `harness_selftest` IS registered, so this is
# the only place the rule can actually bite. The corpus carries a twin of this
# check for anyone running it by hand; this copy is the one with teeth.
#
# WHAT IS POLICED. Three properties, each mechanical:
#   * every test_*.py file in the corpus is named in TESTS.md
#   * every `def test_` in those files is named in TESTS.md
#   * the totals TESTS.md states are the totals on disk
# The third is what the stale header got wrong, and neither of the first two
# would have caught it: a file can name every test and still miscount them.

_dcv_dir="$PGC_TESTDIR/pytest"
_dcv_doc="$_dcv_dir/TESTS.md"

check "premise: the pytest corpus is where this part thinks it is" \
	"$([ -d "$_dcv_dir" ] && echo yes || echo no)" "yes"

check "premise: the corpus carries the documentation this part polices" \
	"$([ -f "$_dcv_doc" ] && echo yes || echo no)" "yes"

# The sweep, as a function over a DIRECTORY and a DOC, so the arms below can run
# the identical logic over a fixture. A guard that can only be pointed at the
# real tree is proved by nothing: it passes today and there is no way to see it
# fire. selftest 320 makes the same move with the runner's classifier.
#
# Prints the offenders, capped, in the "[]" / "[n:...]" shape the other parts use
# so a failure names what is wrong rather than only that something is.
_dcv_missing() {	# _dcv_missing DIR DOC -> "[]" or "[n: a b c]"
	local dir="$1" doc="$2" f base name n=0 bad="" doctext
	doctext="$(cat "$doc" 2>/dev/null)"
	for f in "$dir"/test_*.py; do
		# Without nullglob an unmatched glob stays literal, so a corpus with no
		# test files would iterate once over a path that does not exist. The
		# file test guards that; the premise below asserts the sweep saw files.
		[ -f "$f" ] || continue
		base="${f##*/}"
		case "$doctext" in
			*"$base"*) ;;
			*) n=$((n + 1)); [ "$n" -le 6 ] && bad="$bad $base" ;;
		esac
		while IFS= read -r name; do
			[ -n "$name" ] || continue
			case "$doctext" in
				*"$name"*) ;;
				*) n=$((n + 1)); [ "$n" -le 6 ] && bad="$bad $name" ;;
			esac
		done < <(grep -oE '^def (test_[A-Za-z0-9_]+)' "$f" | sed 's/^def //')
	done
	[ "$n" -eq 0 ] && { printf '[]'; return; }
	printf '[%d:%s]' "$n" "$bad"
}

_dcv_count() {	# _dcv_count DIR -> "<tests> <files>"
	local dir="$1" f t=0 c=0
	for f in "$dir"/test_*.py; do
		[ -f "$f" ] || continue
		c=$((c + 1))
		t=$((t + $(grep -cE '^def test_' "$f")))
	done
	printf '%d %d' "$t" "$c"
}

# A sweep that found nothing reports "nothing missing" and is indistinguishable
# from a sweep that works. Assert it saw the corpus before believing its verdict.
_dcv_seen="$(_dcv_count "$_dcv_dir")"
check "premise: the sweep found the corpus rather than an empty glob" \
	"$([ "${_dcv_seen%% *}" -ge 20 ] && [ "${_dcv_seen##* }" -ge 3 ] && echo enough || echo "$_dcv_seen")" \
	"enough"

check "every test file and every test in the corpus is named in TESTS.md" \
	"$(_dcv_missing "$_dcv_dir" "$_dcv_doc")" "[]"

# The count TESTS.md states, parsed out of it. Written in a fixed form precisely
# so it can be read back: prose that says "twenty-five" cannot be compared with
# anything, which is how the stale header survived being read many times.
_dcv_stated="$(grep -oE '^\*\*[0-9]+ tests in [0-9]+ files\.\*\*' "$_dcv_doc" \
	| head -1 | grep -oE '[0-9]+' | tr '\n' ' ' | sed 's/ $//')"

check "TESTS.md states its totals in a form that can be read back" \
	"$([ -n "$_dcv_stated" ] && echo yes || echo no)" "yes"

check "and the totals it states are the totals on disk" \
	"$_dcv_stated" "$_dcv_seen"

# ---- and the guard must be able to FAIL --------------------------------------
#
# Everything above passes on a healthy tree, which is exactly what a guard that
# does nothing also does. These arms run the same two functions over fixtures
# built to be wrong, so a future edit that neuters the sweep reddens here even
# while the real corpus stays clean.

_dcv_fix="$PGC_WORKDIR/doccov"; rm -rf "$_dcv_fix"; mkdir -p "$_dcv_fix"
printf 'def test_alpha(expect):\n    pass\ndef test_beta(expect):\n    pass\n' \
	> "$_dcv_fix/test_one.py"

# Documented completely: file named, both tests named, totals stated.
printf '**2 tests in 1 files.**\ntest_one.py: test_alpha and test_beta\n' \
	> "$_dcv_fix/GOOD.md"
check "control: a fully documented corpus reports nothing missing" \
	"$(_dcv_missing "$_dcv_fix" "$_dcv_fix/GOOD.md")" "[]"

# One test left out. This is the exact shape that shipped.
printf '**2 tests in 1 files.**\ntest_one.py: test_alpha\n' > "$_dcv_fix/PARTIAL.md"
check "an undocumented test is named rather than passed over" \
	"$(_dcv_missing "$_dcv_fix" "$_dcv_fix/PARTIAL.md")" "[1: test_beta]"

# A whole file left out, which is how 29 tests went missing at once.
printf '**2 tests in 1 files.**\nnothing about the corpus at all\n' > "$_dcv_fix/NONE.md"
check "an undocumented file is caught along with the tests inside it" \
	"$(_dcv_missing "$_dcv_fix" "$_dcv_fix/NONE.md")" "[3: test_one.py test_alpha test_beta]"

# The count arm, proved separately: a doc can name every test and still state a
# wrong total, which is precisely what the stale header did.
check "the sweep counts the fixture's tests and files" \
	"$(_dcv_count "$_dcv_fix")" "2 1"

check "a stated total that disagrees with disk is visible" \
	"$([ "$(grep -oE '^\*\*[0-9]+ tests in [0-9]+ files\.\*\*' "$_dcv_fix/GOOD.md" \
		| grep -oE '[0-9]+' | tr '\n' ' ' | sed 's/ $//')" = "$(_dcv_count "$_dcv_fix")" ] \
		&& echo agrees || echo differs)" "agrees"

unset _dcv_dir _dcv_doc _dcv_seen _dcv_stated _dcv_fix
unset -f _dcv_missing _dcv_count

# ---- the mode inventory must count itself, and the count must be checkable ----
#
# WHY THIS EXISTS. `test/pytest/VACUITY_MODES.md` and `test/pytest/README.md`
# stated different numbers for how many vacuity modes the layer refuses -- 27 and
# 23 -- and a reviewer could check NEITHER, because the document offered no rule
# for what counts as a mode. That is the defect this whole directory exists to
# refuse, committed by the document that describes the refusal: a number nobody
# can recompute is an assertion, not a measurement.
#
# Section 1a now states the rule: a mode is a backticked kebab-case identifier of
# three or more words. These arms hold the document to its own rule.
#
# WHAT IS POLICED. Four properties:
#   * section 1a's "refused today" total is the count of ids in section 2
#   * its "not refused" total is the count in section 3
#   * its document total is the sum of the two
#   * README.md quotes the same refused number, so the two cannot drift again
# The enumeration run's own 79 is history, not a property of the tree: nothing
# here pretends to check it. What IS checked is that the gap the document admits
# to equals the run total minus what was actually written down.

_mi_doc="$PGC_TESTDIR/pytest/VACUITY_MODES.md"
_mi_readme="$PGC_TESTDIR/pytest/README.md"

check "premise: the mode inventory is where this part thinks it is" \
	"$([ -f "$_mi_doc" ] && echo yes || echo no)" "yes"

# Distinct ids matching section 1a's rule, within one "## <prefix>" section.
# A function over FILE and PREFIX so the fixture arms below run the same logic.
_mi_ids() {	# _mi_ids FILE PREFIX -> count
	local f="$1" pre="$2"
	awk -v p="^## $pre" '
		$0 ~ p        { inside = 1; next }
		/^## /        { inside = 0 }
		inside        { print }
	' "$f" 2>/dev/null \
		| grep -oE '`[a-z0-9]+(-[a-z0-9]+){2,}`' \
		| sort -u | wc -l | tr -d ' '
}

# A stated row from the section 1a table. The label is a substring of the cell,
# not the whole of it, so this matches the cell rather than anchoring to its start.
#
# Take the VALUE cell, not the first number on the line. The labels themselves
# contain digits -- "named in section 2, refused today" -- so the obvious
# `grep -oE '[0-9]+' | head -1` returns the 2 from "section 2" and never the
# total. It did, and it read 2 and 3 for totals of 21 and 51. The fixture below
# could not see it because there the label digit and the value were both 2, so
# there is now an arm whose whole job is to tell those two readings apart.
_mi_row() {	# _mi_row FILE LABEL -> the number, or "" if the row is absent
	local f="$1" label="$2"
	grep -E "^\|[^|]*${label}[^|]*\|" "$f" 2>/dev/null | head -1 \
		| awk -F'|' 'NF > 2 { v = $(NF - 1); gsub(/[^0-9]/, "", v); print v }'
}

# Section 3 keeps a back-reference to every mode that moved into section 2
# ("`X` is now closed"), so a mode can be named in both. Section 2 wins, and
# section 3's total is what it names MINUS what section 2 claims. Counting the
# back-references as unrefused puts one mode in two states: measured at 25 + 50
# against 72 named, which is three ids counted twice.
_mi_idlist() {	# _mi_idlist FILE PREFIX -> the ids themselves, one per line, sorted
	local f="$1" pre="$2"
	awk -v p="^## $pre" '
		$0 ~ p        { inside = 1; next }
		/^## /        { inside = 0 }
		inside        { print }
	' "$f" 2>/dev/null \
		| grep -oE '`[a-z0-9]+(-[a-z0-9]+){2,}`' \
		| sort -u
}

_mi_ref="$(_mi_ids "$_mi_doc" '2\.')"
_mi_not="$(comm -23 <(_mi_idlist "$_mi_doc" '3\.') <(_mi_idlist "$_mi_doc" '2\.') \
	| grep -c . || true)"

# The same trap as the sweep above: a counter that finds nothing agrees with a
# document that claims nothing, and both look like success.
check "premise: the counting rule finds modes at all" \
	"$([ "$_mi_ref" -ge 15 ] && [ "$_mi_not" -ge 30 ] && echo enough || echo "$_mi_ref/$_mi_not")" \
	"enough"

check "section 1a's refused total is the count of ids in section 2" \
	"$(_mi_row "$_mi_doc" 'refused today')" "$_mi_ref"

check "section 1a's not-refused total is the count of ids in section 3" \
	"$(_mi_row "$_mi_doc" 'not refused')" "$_mi_not"

check "section 1a's document total is the sum of its two sections" \
	"$(_mi_row "$_mi_doc" 'named in this document')" "$((_mi_ref + _mi_not))"

check "the admitted gap is the run total minus what is written down" \
	"$(_mi_row "$_mi_doc" 'named nowhere here')" \
	"$(( $(_mi_row "$_mi_doc" 'produced by the enumeration run') \
	     - $(_mi_row "$_mi_doc" 'named in this document') ))"

# README.md is the file that drifted. It must quote the inventory's number rather
# than carry one of its own.
check "README.md quotes the number of modes the inventory names as refused" \
	"$(grep -cE "$_mi_ref refused" "$_mi_readme")" "1"

# ---- and these arms must be able to FAIL -------------------------------------

_mi_fix="$PGC_WORKDIR/modecount"; rm -rf "$_mi_fix"; mkdir -p "$_mi_fix"
{
	printf '## 2. refused\n'
	printf 'text `alpha-beta-gamma` and `delta-epsilon-zeta` here\n'
	printf '## 3. not refused\n'
	printf '`eta-theta-iota`\n'
	printf '## 4. table\n'
	printf '| named in section 2, refused today | 2 |\n'
	printf '| named in section 3, not refused | 1 |\n'
	printf '| **named in this document** | **3** |\n'
} > "$_mi_fix/GOOD.md"

check "the counter counts a fixture's section 2" "$(_mi_ids "$_mi_fix/GOOD.md" '2\.')" "2"
check "the counter counts a fixture's section 3" "$(_mi_ids "$_mi_fix/GOOD.md" '3\.')" "1"

# Two-word and one-word ids are not modes under section 1a's rule, and a counter
# that took them would inflate every total in the document.
printf '## 2. refused\n`one-two` and `single` and `alpha-beta-gamma`\n' > "$_mi_fix/SHORT.md"
check "an id of fewer than three words is not counted as a mode" \
	"$(_mi_ids "$_mi_fix/SHORT.md" '2\.')" "1"

# An id named twice is one mode. Section 2 names several ids in more than one row.
printf '## 2. refused\n`alpha-beta-gamma` again `alpha-beta-gamma`\n' > "$_mi_fix/DUP.md"
check "an id named twice counts once" "$(_mi_ids "$_mi_fix/DUP.md" '2\.')" "1"

# The section boundary must hold: ids after the next heading belong to it.
printf '## 2. refused\n`alpha-beta-gamma`\n## 3. not\n`delta-epsilon-zeta`\n' > "$_mi_fix/BOUND.md"
check "the counter stops at the next heading" "$(_mi_ids "$_mi_fix/BOUND.md" '2\.')" "1"

# A wrong stated total is visible. This is the shape that shipped in two files.
printf '## 2. refused\n`alpha-beta-gamma`\n## 4. t\n| named in section 2, refused today | 9 |\n' \
	> "$_mi_fix/WRONG.md"
check "a stated total that disagrees with the ids is visible" \
	"$([ "$(_mi_row "$_mi_fix/WRONG.md" 'refused today')" = "$(_mi_ids "$_mi_fix/WRONG.md" '2\.')" ] \
		&& echo agrees || echo differs)" "differs"

check "and the same comparison agrees on the fixture that is right" \
	"$([ "$(_mi_row "$_mi_fix/GOOD.md" 'refused today')" = "$(_mi_ids "$_mi_fix/GOOD.md" '2\.')" ] \
		&& echo agrees || echo differs)" "agrees"

# A missing row must not read as a passing comparison.
printf '## 2. refused\n`alpha-beta-gamma`\n' > "$_mi_fix/NOROW.md"
# The label contains a digit and the value is a different digit, so a reader that
# takes the first number on the line and one that takes the value cell give
# different answers. This is the arm that would have caught the helper's own bug.
printf '## 4. t\n| named in section 2, refused today | 7 |\n' > "$_mi_fix/LABELDIGIT.md"
check "the row's value is read, not a digit inside its label" \
	"$(_mi_row "$_mi_fix/LABELDIGIT.md" 'refused today')" "7"

check "an absent total is empty rather than a number that happens to match" \
	"$([ -z "$(_mi_row "$_mi_fix/NOROW.md" 'refused today')" ] && echo absent || echo present)" \
	"absent"

# The table is not the only place a total lives. Three sentences outside it still
# asserted the run's 23 after the table said 21: section 2's opening, the closing
# paragraph, and TESTS.md. Gating the table alone just moves the drift into prose.
#
# The run's own 23 appears once on purpose, as history, and is not gated. What is
# gated is every sentence stating what the layer refuses TODAY.
_mi_prose() {	# _mi_prose FILE REGEX -> the captured number, or ""
	local f="$1" re="$2"
	grep -oE "$re" "$f" 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1
}

_mi_tests="$PGC_TESTDIR/pytest/TESTS.md"

check "section 2's opening states the counted number of refused modes" \
	"$(_mi_prose "$_mi_doc" '[0-9]+ of the 79, counted')" "$_mi_ref"

check "the closing paragraph states the counted number too" \
	"$(_mi_prose "$_mi_doc" 'known to refuse [0-9]+ demonstrated modes')" "$_mi_ref"

check "TESTS.md states the counted number as well" \
	"$(_mi_prose "$_mi_tests" 'This layer refuses [0-9]+')" "$_mi_ref"

# And the prose reader must be able to fail, on a fixture rather than on the tree.
printf 'the layer is known to refuse 99 demonstrated modes here\n' > "$_mi_fix/PROSE.md"
check "a prose total that disagrees with the ids is visible" \
	"$(_mi_prose "$_mi_fix/PROSE.md" 'known to refuse [0-9]+ demonstrated modes')" "99"

check "an absent prose total is empty rather than a stray number" \
	"$([ -z "$(_mi_prose "$_mi_fix/GOOD.md" 'known to refuse [0-9]+ demonstrated modes')" ] \
		&& echo absent || echo present)" "absent"

unset _mi_doc _mi_readme _mi_ref _mi_not _mi_fix _mi_tests
unset -f _mi_ids _mi_row _mi_prose
