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

# TESTS.md STATES NO TOTALS, AND THAT IS THE POINT (#908).
#
# It used to, and this part compared the stated pair against the corpus, which is
# what made it a claim rather than decoration. The problem was never the check: it
# was that the number was WRITTEN rather than DERIVED, and its correct value is a
# function of the MERGE rather than of either branch. It collided on essentially
# every rebase touching the corpus -- ten times in one day, both sides wrong every
# time, so there was no side to pick.
#
# REMOVING IT COSTS NOTHING, provably. The two sweeps are strictly stronger than
# any count: the arm above requires every test on disk to be NAMED here, and the
# reverse arm below requires every name here to EXIST on disk. Two subsets in
# opposite directions is set equality, so any count over the document equals the
# count over the corpus. A stated total was a derived value maintained by hand.
_dcv_stated="$(grep -oE '^\*\*[0-9]+ tests in [0-9]+ files\.\*\*' "$_dcv_doc" \
	| head -1 | grep -oE '[0-9]+' | tr '\n' ' ' | sed 's/ $//')"

check "TESTS.md states no totals line for a merge to get wrong" \
	"$([ -z "$_dcv_stated" ] && echo none || echo "$_dcv_stated")" "none"

# PREMISE: the reader must still be able to FIND a totals line, or the arm above
# passes because the parser is broken rather than because the line is gone --
# which is the shape this whole part exists to refuse.
# $_dcv_fix is not created until the failure-proof section below, and this file
# runs under `set -u`, so this fixture makes its own path rather than borrowing
# one that does not exist yet.
_dcv_ht="$PGC_WORKDIR/doccov-hastotals"; mkdir -p "$_dcv_ht"
printf '**7 tests in 3 files.** and prose\n' > "$_dcv_ht/HASTOTALS.md"
check "premise: the reader still finds a totals line when one is there" \
	"$(grep -oE '^\*\*[0-9]+ tests in [0-9]+ files\.\*\*' "$_dcv_ht/HASTOTALS.md" \
		| head -1 | grep -oE '[0-9]+' | tr '\n' ' ' | sed 's/ $//')" "7 3"

# And the counts still REACH a reader -- they move to this run's output, where
# they are computed from the corpus and cannot go stale.
echo "      CORPUS: $_dcv_seen (test functions, files)"

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

# Kept although the real document no longer states a total: it proves the
# comparison still works, so "no totals line" above is a fact about the document
# rather than about a broken reader.
check "a stated total that disagrees with disk is visible" \
	"$([ "$(grep -oE '^\*\*[0-9]+ tests in [0-9]+ files\.\*\*' "$_dcv_fix/GOOD.md" \
		| grep -oE '[0-9]+' | tr '\n' ' ' | sed 's/ $//')" = "$(_dcv_count "$_dcv_fix")" ] \
		&& echo agrees || echo differs)" "agrees"


# ---- and the sweep must go the OTHER way too (#908) -------------------------
#
# `_dcv_missing` above computes tests on disk the document fails to name. NOTHING
# computed the reverse, so a test DELETED or RENAMED while its entry survived was
# held by the totals line and by nothing else -- and that line is a merge target
# whose correct value is a function of the merge, so it is the half most likely to
# be removed. Removing it while this direction was uncovered would have retired a
# check silently, which is the move this part exists to prevent.
#
# IT FOUND TWO ON THE SHIPPED CORPUS. Section 3 named
# test_layer_rejects_an_absence_assertion_over_an_empty_plan and a control beside
# it, and neither had ever been written; the real work lives in
# test_guards_pinned.py under a different name and is documented correctly in its
# own section. Two rows claimed coverage under names nobody had written.
#
# A BACKTICKED NAME, not any occurrence. This document discusses fixtures and dead
# names in prose, and a bare-word sweep would report those as missing. Backticks
# are how it already marks a real identifier, so backticking a name IS the claim
# that it exists -- which is why the paragraph describing this defect writes the
# dead names without them.

_dcv_absent() {	# _dcv_absent DIR DOC -> "[]" or "[n: a b c]"
	local dir="$1" doc="$2" name n=0 bad=""
	local ondisk
	# Every function and every file the corpus actually has, one per line.
	ondisk="$( { grep -hoE '^def (test_[A-Za-z0-9_]+)' "$dir"/test_*.py 2>/dev/null \
	               | sed 's/^def //'
	             for f in "$dir"/test_*.py; do [ -f "$f" ] && printf '%s\n' "${f##*/}"; done
	           } | sort -u )"
	while IFS= read -r name; do
		[ -n "$name" ] || continue
		# grep -cxF on a here-string, NOT `printf ... | grep -qxF`. grep -q exits
		# the moment it matches, the printf takes EPIPE, and under this suite's
		# `set -o pipefail` the pipeline reports failure though the name WAS
		# present -- so a name in the corpus is reported absent. Selftest 080
		# states this rule and demonstrates it; its sweep is deliberately
		# non-recursive and never looked in here.
		#
		# It is not latent. It reddened #923's `suites (PG 17)` on a name that
		# exists, while PG 18 passed, and reproduces at this corpus size only
		# under load: 170 names, 400 trials on a busy machine, 6 false absences
		# piped and 0 on a here-string. An independent run of the same shape in
		# isolation gave 10 in 40, so the rate is load- and size-dependent rather
		# than fixed -- the two measurements bracket it.
		[ "$(grep -cxF "$name" <<<"$ondisk" || true)" -ne 0 ] && continue
		n=$((n + 1)); [ "$n" -le 6 ] && bad="$bad $name"
	done < <(grep -oE '`test_[A-Za-z0-9_]*(\.py)?`' "$doc" 2>/dev/null \
	         | tr -d '`' | sort -u)
	[ "$n" -eq 0 ] && { printf '[]'; return; }
	printf '[%d:%s]' "$n" "$bad"
}

check "premise: the reverse sweep reads backticked names at all" \
	"$([ "$(grep -coE '`test_[A-Za-z0-9_]*(\.py)?`' "$_dcv_doc")" -ge 20 ] \
		&& echo enough || echo too-few)" "enough"

check "every test the document names exists in the corpus" \
	"$(_dcv_absent "$_dcv_dir" "$_dcv_doc")" "[]"

# ---- and it must be able to FAIL, on a fixture rather than on the tree -------

printf 'def test_alpha(expect):\n    pass\n' > "$_dcv_fix/test_one.py"

printf '`test_one.py`: `test_alpha` and `test_beta`\n' > "$_dcv_fix/GHOST.md"
check "a documented test that does not exist is named, not passed over" \
	"$(_dcv_absent "$_dcv_fix" "$_dcv_fix/GHOST.md")" "[1: test_beta]"

printf '`test_one.py`: `test_alpha`\n' > "$_dcv_fix/REAL.md"
check "control: a document naming only what exists is clean" \
	"$(_dcv_absent "$_dcv_fix" "$_dcv_fix/REAL.md")" "[]"

printf '`test_one.py` and `test_gone.py`: `test_alpha`\n' > "$_dcv_fix/GONEFILE.md"
check "a documented file that does not exist is named" \
	"$(_dcv_absent "$_dcv_fix" "$_dcv_fix/GONEFILE.md")" "[1: test_gone.py]"

# A name in prose without backticks is not a claim, so it must NOT be reported --
# otherwise the document could never describe a test it removed.
printf 'the old test_beta was removed; `test_alpha` remains\n' > "$_dcv_fix/PROSE.md"
check "an unbackticked name in prose is not treated as a claim" \
	"$(_dcv_absent "$_dcv_fix" "$_dcv_fix/PROSE.md")" "[]"

unset -f _dcv_absent

# ---- and the names must be UNIQUE, or the equality argument does not hold ----
#
# The two sweeps give equality of the two NAME SETS. That is not equality of
# DEFINITION COUNTS, which is what a total counts: two files defining one name
# leave both arms green while the counts differ (@jdatcmd, against #919). It
# cannot happen today, so the conclusion was true in fact and not by
# construction -- the difference between an argument and a guard.
#
# It closes something real beyond the argument: `_dcv_missing` asks whether a
# name appears in the document AT ALL, so a test defined TWICE and documented
# ONCE reads as fully covered while pytest runs both.

_dcv_dupes() {	# _dcv_dupes DIR -> "" or the repeated names
	grep -hoE '^def (test_[A-Za-z0-9_]+)' "$1"/test_*.py 2>/dev/null \
		| sed 's/^def //' | sort | uniq -d
}

check "no test name is defined twice in the corpus" \
	"$(_dcv_dupes "$_dcv_dir" | tr '\n' ' ' | sed 's/ $//')" ""

# And it must be able to FAIL, on a fixture rather than on the tree.
printf 'def test_shared_shape(expect):\n    pass\n' > "$_dcv_fix/test_a.py"
printf 'def test_shared_shape(expect):\n    pass\n' > "$_dcv_fix/test_b.py"
check "a name defined in two files is named, not passed over" \
	"$(_dcv_dupes "$_dcv_fix" | tr '\n' ' ' | sed 's/ $//')" "test_shared_shape"
rm -f "$_dcv_fix/test_a.py" "$_dcv_fix/test_b.py"

check "control: distinct names in the same corpus report no duplicate" \
	"$(_dcv_dupes "$_dcv_dir" | tr '\n' ' ' | sed 's/ $//')" ""

unset -f _dcv_dupes


# ---- and every table-of-contents link must RESOLVE ---------------------------
#
# WHY THIS EXISTS. TESTS.md's contents list gained an entry whose anchor stripped
# the underscores out of the file name -- "#14-testharnessdepspy-..." against a
# heading GitHub renders as "#14-test_harness_depspy-..." -- so the link silently
# went nowhere. Eleven entries above it keep the underscores, so the document
# already stated the convention and the new entry simply disagreed with it.
#
# NEITHER EXISTING ARM COULD SEE IT. Both sweep for NAMES; an anchor is not a
# name, and a broken link is still a string containing the file name it points at.
# A reader finds out by clicking.
#
# THE RULE IS GITHUB'S, and it is mechanical: lowercase the heading text, drop
# every character that is not a letter, digit, space, hyphen or underscore, then
# turn spaces into hyphens. So the dot in ".py" and the colon after it disappear
# and the underscores stay. Over the three documents in this directory the sweep
# reports nothing, and over the document as it shipped it reported exactly the one
# entry -- which is the whole false-positive budget, measured rather than assumed.
#
# ONE DIRECTION ON PURPOSE: every link must reach a heading. The reverse, every
# heading must be linked, is a different property, and "## Contents" is itself a
# heading that no entry links to -- so the reverse needs an exemption list, which
# is the hand-maintained value this file keeps removing.

_toc_anchor() {	# _toc_anchor TEXT -> the anchor GitHub derives from it
	printf '%s' "$1" | tr 'A-Z' 'a-z' | sed -e 's/[^a-z0-9 _-]//g' -e 's/ /-/g'
}

_toc_unresolved() {	# _toc_unresolved DOC -> "[]" or "[n: a b c]"
	local doc="$1" anchor n=0 bad="" anchors
	# Every anchor the document's own headings produce, one per line.
	# Through _toc_anchor, so GitHub's rule has ONE definition here. The stream
	# form was a second copy of the same sed program, and two copies drift.
	anchors="$(while IFS= read -r _h; do [ -n "$_h" ] && _toc_anchor "$_h" && echo; done \
		< <(grep -E '^#{2,} ' "$doc" 2>/dev/null | sed -e 's/^#* //'))"
	while IFS= read -r anchor; do
		[ -n "$anchor" ] || continue
		# grep -cxF on a here-string, for the reason given in _dcv_absent above.
		[ "$(grep -cxF "$anchor" <<<"$anchors" || true)" -ne 0 ] && continue
		n=$((n + 1)); [ "$n" -le 6 ] && bad="$bad $anchor"
	done < <(grep -oE '\]\(#[A-Za-z0-9_-]+\)' "$doc" 2>/dev/null \
	         | sed -e 's/^](#//' -e 's/)$//' | sort -u)
	[ "$n" -eq 0 ] && { printf '[]'; return; }
	printf '[%d:%s]' "$n" "$bad"
}

# PREMISE: the sweep found links at all. A document whose links it cannot parse
# reports "nothing broken", which is what a correct document reports too.
check "premise: the sweep reads the contents list's links" \
	"$([ "$(grep -coE '\]\(#[A-Za-z0-9_-]+\)' "$_dcv_doc")" -ge 15 ] \
		&& echo enough || echo too-few)" "enough"

# AND THE SWEEP MUST HAVE SWEPT. Without nullglob an unmatched glob stays literal,
# the [ -f ] skips it, and the loop below runs NO checks while the part still
# reports every check it did run as passing. A clean sweep needs a coverage premise.
_toc_n=0
for _toc_f in "$_dcv_dir"/*.md; do
	[ -f "$_toc_f" ] || continue
	_toc_n=$((_toc_n + 1))
	check "every in-document link in ${_toc_f##*/} reaches a heading" \
		"$(_toc_unresolved "$_toc_f")" "[]"
done
check "premise: the link sweep saw the directory's documents" \
	"$([ "$_toc_n" -ge 3 ] && echo enough || echo "$_toc_n")" "enough"
unset _toc_f _toc_n

# ---- and it must be able to FAIL, on a fixture rather than on the tree -------

printf '## 14. test_harness_deps.py: the harness\n- [14. x](#14-test_harness_depspy-the-harness)\n' \
	> "$_dcv_fix/ANCHOR_GOOD.md"
check "control: an anchor that keeps the underscores resolves" \
	"$(_toc_unresolved "$_dcv_fix/ANCHOR_GOOD.md")" "[]"

# The exact shape that shipped: the underscores stripped out of the file name.
printf '## 14. test_harness_deps.py: the harness\n- [14. x](#14-testharnessdepspy-the-harness)\n' \
	> "$_dcv_fix/ANCHOR_BAD.md"
check "an anchor that strips the underscores is named, not passed over" \
	"$(_toc_unresolved "$_dcv_fix/ANCHOR_BAD.md")" \
	"[1: 14-testharnessdepspy-the-harness]"

# And the derivation itself, on the heading this defect was found in: the dot and
# the colon go, the underscores stay.
check "the anchor rule drops punctuation and keeps underscores" \
	"$(_toc_anchor '14. test_harness_deps.py: the harness must self-test')" \
	"14-test_harness_depspy-the-harness-must-self-test"

unset -f _toc_anchor _toc_unresolved


# ---- the harness must self-test without a database, and the gate must run it --
#
# THE MEMBERSHIP DECISION AND THE CONFTEST IMPORT ARE NOT CHECKED HERE, and that is
# jd's rule rather than an omission: the shell harness and the pytest corpus are
# PARALLEL IN FUNCTIONALITY and must not call, import or reference each other. An
# earlier version of this part read test/pytest/conftest.py and INVOKED
# test_harness_deps.py with `python3 ... --disagree`, which is the coupling, not a
# second measurement: a shell arm driving the python decider agrees with it by
# construction and can never report it wrong.
#
# Both properties are asserted in the corpus, where they are native:
#   conftest imports no driver at module scope
#       test_harness_deps.py::test_conftest_imports_no_database_driver_at_module_scope
#   the declaration is exactly the database-free half, both directions
#       test_harness_deps.py::test_the_declaration_is_exactly_the_database_free_half
#   the partition accounts for every file, and the three report cases
#       test_harness_deps.py and test_harness_deps_classifier.py
#
# What stays here is the CI WORKFLOW, which belongs to neither harness.

_hd_ci="$PGC_SRCDIR/.github/workflows/ci.yml"


check "premise: the CI workflow is where this part thinks it is" \
	"$([ -f "$_hd_ci" ] && echo yes || echo no)" "yes"

check "the gate runs the harness guards" \
	"$([ "$(grep -c 'pytest-guards:' "$_hd_ci")" -ge 1 ] && echo yes || echo no)" "yes"

# DERIVED, NOT REPEATED. A second copy of the file list is the defect this repo
# spent a day removing from TESTS.md.
check "and it derives the file list rather than repeating it" \
	"$([ "$(grep -c 'from test_harness_deps import NO_CLUSTER' "$_hd_ci")" -ge 1 ] \
		&& echo yes || echo no)" "yes"

# Presence, not a count: the comment block above the job names this file too,
# and an exact count would be an assertion about the prose as much as the code.
check "and derives the pins from requirements-test.txt" \
	"$([ "$(grep -c 'requirements-test.txt' "$_hd_ci")" -ge 1 ] && echo yes || echo no)" "yes"

# ---- and the DECLARATION must be decided, not declaimed ----------------------
#
unset _hd_ci

unset _dcv_dir _dcv_doc _dcv_seen _dcv_stated _dcv_fix _dcv_ht
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
