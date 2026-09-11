# ---- the two harnesses must agree about the third state ----------------------
#
# WHY THIS EXISTS. `expect.cannot_run(REASON, detail)` in the pytest corpus is the
# counterpart of `check_unrunnable` here, and the two sides share three things that
# are WRITTEN DOWN TWICE, once in each language: the INCOMPLETE exit code, the
# closed list of reasons, and the one-line shape an unrunnable check prints. A
# value duplicated across a language boundary drifts, and the drift is invisible --
# the corpus would exit 67, a runner would compare against something else, and an
# INCOMPLETE run would read as a failure or as a pass depending on which way it
# moved.
#
# WHAT THIS PART DOES **NOT** DO ANY MORE (#432). It used to also pin the SHAPE of
# `pgc_vacuity.py`: that the unrunnable field is written, that something reads it,
# that the read reaches `session.exitstatus`, and that the override is conditional.
# Eleven arms, every one a text pin on the other harness's source. Those are gone.
# A shell arm asserting a grep matches cannot prove a python arm is CAUGHT -- #927's
# precedent -- and the behaviour is pinned where it can actually be observed, by four
# arms in `test/pytest/test_layer.py` that run pytest inside pytest and assert on the
# inner run's exit status.
#
# THE OLD REASON FOR KEEPING THEM WAS TRUE AND IS NOT ANY MORE. It said those arms
# "need pytest, psycopg and a virtualenv; CI installs none of them". CI now has a
# `pytest-guards` job that installs pytest pinned from `requirements-test.txt`,
# asserts psycopg is absent, and runs the database-free file list -- which includes
# `test_layer.py`. So the behavioural half runs in CI and this half is not its last
# line of defence.
#
# MEASURED BEFORE DELETING ANYTHING, because "the other side covers it" is a claim.
# With `session.exitstatus = EXIT_INCOMPLETE` made unreachable in `pgc_vacuity.py`
# -- the defect exactly as it shipped -- those four arms go from `4 passed` to
# `2 failed, 2 passed`. Two, not four, and that is correct rather than partial: the
# other two assert exit 1 for a run with a real failure and exit 0 for a run with
# nothing unrunnable, and neither of those outcomes moves. The file was restored and
# compared byte-for-byte afterwards.
#
# WHAT IS LEFT IS THE ONE PERMITTED CROSS-REFERENCE, in CONTEXT.md's sense: a
# property that IS the relationship between the two harnesses and so cannot be
# expressed from one side. Each of the three agreements below is PARSED OUT OF BOTH
# FILES rather than written here. A check that restates the value tests this file
# against itself: both copies could drift together and it would still pass.
#
# AND THE LIST AND THE SHAPE ARE NEW. The part checked the exit code only, while
# two more duplications sat beside it unchecked -- including the reason list, whose
# whole purpose is to be closed on both sides.

_ts_lib="$PGC_TESTDIR/lib.sh"
_ts_vac="$PGC_TESTDIR/pytest/pgc_vacuity.py"

check "premise: the harness library is where this part thinks it is" \
	"$([ -f "$_ts_lib" ] && echo yes || echo no)" "yes"

check "premise: the pytest layer is where this part thinks it is" \
	"$([ -f "$_ts_vac" ] && echo yes || echo no)" "yes"

# ---- agreement 1: the INCOMPLETE exit code ----------------------------------

_ts_sh_code="$(sed -n 's/^PGC_EXIT_INCOMPLETE=\([0-9]\{1,\}\).*/\1/p' "$_ts_lib" | head -1)"
_ts_py_code="$(sed -n 's/^EXIT_INCOMPLETE[[:space:]]*=[[:space:]]*\([0-9]\{1,\}\).*/\1/p' "$_ts_vac" | head -1)"

check "premise: lib.sh states an INCOMPLETE exit code this part could read" \
	"$([ -n "$_ts_sh_code" ] && echo yes || echo no)" "yes"

check "premise: the pytest layer states one too" \
	"$([ -n "$_ts_py_code" ] && echo yes || echo no)" "yes"

check "the two harnesses agree on the INCOMPLETE exit code" \
	"$_ts_py_code" "$_ts_sh_code"

# ---- agreement 2: the closed list of reasons --------------------------------
#
# Sorted, because the two files are free to list them in different orders and an
# order difference is not a drift. Compared as one string so the failure prints
# both lists side by side and names which token moved.

_ts_sh_reasons="$(sed -n 's/^PGC_UNRUN_REASONS="\([^"]*\)".*/\1/p' "$_ts_lib" \
	| head -1 | tr ' ' '\n' | grep -E '^[A-Z_]+$' | sort | tr '\n' ' ')"
_ts_py_reasons="$(sed -n '/^UNRUNNABLE_REASONS = (/,/^)/p' "$_ts_vac" \
	| grep -oE '"[A-Z_]+"' | tr -d '"' | sort | tr '\n' ' ')"

check "premise: lib.sh states a closed list of unrunnable reasons" \
	"$([ -n "$_ts_sh_reasons" ] && echo yes || echo no)" "yes"

check "premise: the pytest layer states a closed list too" \
	"$([ -n "$_ts_py_reasons" ] && echo yes || echo no)" "yes"

check "the two harnesses agree on the closed list of unrunnable reasons" \
	"$_ts_py_reasons" "$_ts_sh_reasons"

# ---- agreement 3: the line an unrunnable check prints -----------------------
#
# Normalised, not compared raw: one side interpolates `$name` and the other
# `{nodeid}`, which is a difference between two languages rather than between two
# behaviours. Every interpolation becomes `%`, so what is compared is the literal
# text around them -- the part a log reader and `pgc_record` actually see.

_ts_shape_of() {	# _ts_shape_of LINE -> the literal text with interpolations as %
	printf '%s\n' "$1" \
		| grep -oE 'UNRUN  [^"]*' \
		| sed -e 's/\$[A-Za-z_][A-Za-z_0-9]*/%/g' -e 's/{[A-Za-z_][A-Za-z_0-9]*}/%/g' \
		| head -1
}

# THE LINE HAS TO BE THE CODE, NOT THE PROSE ABOUT IT. The first version matched
# `UNRUN  ` anywhere and took `pgc_vacuity.py`'s DOCSTRING, which spells the shape
# out as `UNRUN  <name>: <REASON>: <detail>` for a reader and then keeps talking --
# so the arm compared a sentence against a format string and failed. Requiring a
# quote immediately before the marker selects the quoted string in both languages
# and excludes the prose, which opens with a backtick. The premise arms below could
# not have caught this: the sentence is not empty.
_ts_sh_shape="$(_ts_shape_of "$(grep -m1 '"UNRUN  ' "$_ts_lib")")"
_ts_py_shape="$(_ts_shape_of "$(grep -m1 '"UNRUN  ' "$_ts_vac")")"

check "premise: lib.sh prints a line for an unrunnable check" \
	"$([ -n "$_ts_sh_shape" ] && echo yes || echo no)" "yes"

check "premise: the pytest layer prints one too" \
	"$([ -n "$_ts_py_shape" ] && echo yes || echo no)" "yes"

check "the two harnesses print an unrunnable check in the same shape" \
	"$_ts_py_shape" "$_ts_sh_shape"

# ---- and each comparison must be able to FAIL -------------------------------
#
# Three agreements that pass on a healthy tree, which three comparisons of an
# empty string against an empty string also do. The premises above refuse the
# empty case; these fixtures are the drifted case, which is the one that matters,
# because a reader cannot tell an agreement from a pair of blanks.

_ts_fix="$PGC_WORKDIR/thirdstate"; rm -rf "$_ts_fix"; mkdir -p "$_ts_fix"

printf 'EXIT_INCOMPLETE = 66\n' > "$_ts_fix/drifted.py"
_ts_drift="$(sed -n 's/^EXIT_INCOMPLETE[[:space:]]*=[[:space:]]*\([0-9]\{1,\}\).*/\1/p' "$_ts_fix/drifted.py" | head -1)"
check "a drifted exit code is visible rather than absorbed" \
	"$([ "$_ts_drift" = "$_ts_sh_code" ] && echo agrees || echo "differs:$_ts_drift/$_ts_sh_code")" \
	"differs:66/67"

{
	printf 'UNRUNNABLE_REASONS = (\n'
	printf '    "MISSING_DEPENDENCY",\n'
	printf '    "UNSUPPORTED_MAJOR",\n'
	printf ')\n'
} > "$_ts_fix/shortlist.py"
_ts_short="$(sed -n '/^UNRUNNABLE_REASONS = (/,/^)/p' "$_ts_fix/shortlist.py" \
	| grep -oE '"[A-Z_]+"' | tr -d '"' | sort | tr '\n' ' ')"
check "a reason dropped from one side only is visible" \
	"$([ "$_ts_short" = "$_ts_sh_reasons" ] && echo agrees || echo differs)" "differs"

check "premise: and that fixture is a real list rather than an empty parse" \
	"$(printf '%s' "$_ts_short" | wc -w)" "2"

# Two spaces after UNRUN, as the real shape has: the drift under test is the lost
# colons, not a lost space. The first fixture wrote ONE space, so the parse found
# nothing and the comparison was empty-against-real -- which "differs", for the
# wrong reason. Its own premise arm caught that, which is what the premise is for.
printf '    terminalreporter.write_line(f"UNRUN  {nodeid} {reason} {detail}")\n' \
	> "$_ts_fix/drifted_shape.py"
_ts_shape_drift="$(_ts_shape_of "$(grep -m1 '"UNRUN  ' "$_ts_fix/drifted_shape.py")")"
check "a drifted print shape is visible" \
	"$([ "$_ts_shape_drift" = "$_ts_sh_shape" ] && echo agrees || echo differs)" "differs"

check "premise: and that fixture parses to a shape rather than to nothing" \
	"$([ -n "$_ts_shape_drift" ] && echo yes || echo no)" "yes"

unset _ts_lib _ts_vac _ts_sh_code _ts_py_code _ts_sh_reasons _ts_py_reasons \
	_ts_sh_shape _ts_py_shape _ts_fix _ts_drift _ts_short _ts_shape_drift
unset -f _ts_shape_of
