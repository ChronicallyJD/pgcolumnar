# ---- a count that grep never produced is not "present" (#929) ------------------
#
# #922 replaced roughly 28 `producer | grep -q PAT` tests with
# `[ "$(grep -c PAT … || true)" != 0 ]`, which fixed a real EPIPE race (#486). The
# replacement answers PRESENT where the original answered ABSENT whenever grep
# produces no stdout, and a pattern that does not compile is the way to get there.
#
#     grep -cE '[' file   ->  stdout is []   (empty, not "0")
#     [ "" != 0 ]         ->  TRUE           (a STRING comparison: "" is not "0")
#
# So the helper reported the pattern present for a question it never managed to ask.
# Every pattern in the tree is valid today, so no site was wrong -- the hazard is the
# DIRECTION of the next edit. A premise arm phrased to want `present`, and most are,
# turns GREEN when its pattern stops compiling: it passes BECAUSE the instrument
# broke. The old form failed the other way, red and loud.
#
# THE FIX IS A NUMERIC COMPARISON, and it is behaviour-preserving everywhere else.
# Measured: for a real count the two forms agree exactly; only the empty case differs,
# and there the numeric form is false AND writes to stderr.
#
#     input                      [ "$n" != 0 ]   [ "$n" -ne 0 ]   stderr
#     a real count: 0            false           false            no
#     a real count: 3            true            true             no
#     EMPTY (grep usage error)    TRUE            false           YES
#
# Both spellings failed the same way. `= 0` is an ABSENCE claim, and on empty it is
# false -- which does not assert absence, and is the safe direction once it is loud.

check "premise: a real count compares the same both ways, so the conversion is behaviour-preserving" \
	"$(_n=3; { [ "$_n" != 0 ] && [ "$_n" -ne 0 ]; } && echo same || echo differ)" "same"
check "premise: and a zero count does too" \
	"$(_n=0; { [ "$_n" != 0 ] || [ "$_n" -ne 0 ]; } && echo differ || echo same)" "same"
check "an empty count is not 'present' under a numeric comparison" \
	"$(_n=""; [ "$_n" -ne 0 ] 2>/dev/null && echo present || echo "not present")" "not present"
check "and the string comparison it replaces WOULD have said present" \
	"$(_n=""; [ "$_n" != 0 ] && echo present || echo "not present")" "present"
check "and the numeric form says so on stderr rather than silently" \
	"$(_n=""; { [ "$_n" -ne 0 ]; } 2>&1 >/dev/null | grep -c . || true)" "1"

# The mechanism, against real grep rather than a hand-written empty string.
_c929="$PGC_WORKDIR/c929.txt"
printf 'hello\n' > "$_c929"
check "premise: grep -c prints nothing at all on a pattern that does not compile" \
	"$(grep -cE '[' "$_c929" 2>/dev/null | wc -c | tr -d ' ')" "0"
check "premise: while a valid pattern prints a number" \
	"$(grep -cE 'hello' "$_c929" 2>/dev/null)" "1"

# ---- and the shape cannot come back ------------------------------------------
#
# HEREDOC-AWARE, like the exit-0 sweep in part 410: the suites generate fixture
# scripts, and a forbidden idiom inside a generated script is the fixture rather than
# an offence. Measured: 20 sites before this change and 0 after.
_c929_sweep() {
	awk '
		FNR == 1 { hd = "" }
		hd != "" { if ($0 == hd || $0 ~ "^[ \t]*" hd "[ \t]*$") hd = ""; next }
		/<<-?[ \t]*'\''?[A-Za-z_][A-Za-z0-9_]*'\''?[ \t]*$/ {
			if ($0 !~ /^[ \t]*#/) {
				t = $0; sub(/.*<<-?[ \t]*/, "", t); gsub(/'\''/, "", t)
				sub(/[ \t]*$/, "", t); hd = t; next
			}
		}
		/^[ \t]*#/ { next }
		/\[ "\$\(grep -c[a-zA-Z]*[^)]*\)" (!=|=) / { printf "%s:%d\n", FILENAME, FNR }
	' "$@"
}
_c929_files=("$PGC_SRCDIR"/test/*.sh "$PGC_SRCDIR"/test/selftest/*.sh)
check "premise: the sweep has a corpus to read" \
	"$([ "${#_c929_files[@]}" -ge 250 ] && echo yes || echo "no (${#_c929_files[@]})")" "yes"
# THE PLANTED SHAPES ARE ASSEMBLED, never written out, and the first version of this
# part got that wrong: spelling the forbidden idiom inside a `printf` made three of
# its own lines offences, and the corpus sweep reported 23 where the tree holds 20.
# The sweep flagging its own fixtures is the exact trap its comment cites. Passing the
# OPERATOR as an argument is enough -- the regex needs `!=` or `=` directly after the
# closing `)"`, and `%s` there is not either of them.
_c929_plant() {	# _c929_plant OP FILE -> a file holding the shape, assembled
	printf 'if [ "$(grep -c x f || true)" %s 0 ]; then :; fi\n' "$1" > "$2"
}
check "premise: and it finds a planted string comparison on a grep -c" \
	"$(_c929_plant '!=' "$PGC_WORKDIR/p929.sh"; _c929_sweep "$PGC_WORKDIR/p929.sh" | grep -c .)" "1"
check "premise: and the = 0 spelling too, which fails the same way" \
	"$(_c929_plant '=' "$PGC_WORKDIR/p929b.sh"; _c929_sweep "$PGC_WORKDIR/p929b.sh" | grep -c .)" "1"
check "premise: while a numeric comparison is not an offence" \
	"$(_c929_plant '-ne' "$PGC_WORKDIR/p929c.sh"; _c929_sweep "$PGC_WORKDIR/p929c.sh" | grep -c .)" "0"
check "premise: nor is one inside a generated fixture script" \
	"$({ printf 'cat > /tmp/x <<%sSH%s\n' "'" "'"
	     printf 'if [ "$(grep -c x f || true)" %s 0 ]; then :; fi\n' '!='
	     printf 'SH\n'; } > "$PGC_WORKDIR/p929d.sh"
	   _c929_sweep "$PGC_WORKDIR/p929d.sh" | grep -c .)" "0"
check "no count from grep -c is compared as a string, which answers present when grep could not answer" \
	"$(_c929_sweep "${_c929_files[@]}" | grep -c . || true)" "0"
