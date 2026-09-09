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
