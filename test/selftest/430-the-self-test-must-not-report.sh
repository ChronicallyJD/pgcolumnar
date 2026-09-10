# ---- the self-test must not report success having evaluated nothing (#934) ----
#
# Handed a `pg_config` that does not exist, this suite printed four lines, never
# reached its summary, and EXITED 0. Measured on main before this part:
#
#     bash test/harness_selftest.sh /usr/local/pg18a/bin/pg_config   rc=0  1246 lines  checks run: 610
#     bash test/harness_selftest.sh /usr/local/pgNOPE/bin/pg_config  rc=0     4 lines  no summary at all
#
# TWO CAUSES, and the second is the one that generalises. `_bindir` was assigned
# from a command that failed, so every later PATH was wrong -- and part 010, which
# is SOURCED, then took its own skip path and called `exit 0`, which exits the
# DRIVER rather than the part. A caller cannot tell that from a real pass.
#
# IT COST A MEASUREMENT ROUND TO FIND. A control and a mutation both reported rc=0
# with zero FAIL lines, which reads exactly like "the mutation changed nothing" --
# the conclusion the run existed to test. The log being 4 lines instead of 1246 is
# the only thing that gave it away.
#
# The default is `/usr/local/pg17/bin/pg_config`, which this box does not have, so
# the wrong invocation is the EASY one to make.

_hs="$PGC_TESTDIR/harness_selftest.sh"
check "premise: the driver this part is about is where it is expected" \
	"$([ -f "$_hs" ] && echo yes || echo no)" "yes"

# A pg_config that does not exist. The guard has to refuse BEFORE sourcing any
# part, so this cannot recurse: it dies at the argument check.
_h934_absent="$(bash "$_hs" /usr/local/pgNOPE934/bin/pg_config 2>&1)"
_h934_absent_rc=$?
check "handed a pg_config that does not exist, the self-test refuses instead of exiting 0" \
	"$([ "$_h934_absent_rc" != 0 ] && echo refused || echo "exited 0")" "refused"
# NOT just the path: bash's own "No such file or directory" already named it, so an
# arm matching the path alone passed before the guard existed. The token is what
# makes this arm about the refusal rather than about bash's diagnostics.
check "and the refusal is the guard's own, naming the path it could not use" \
	"$(printf '%s' "$_h934_absent" | grep -c 'no-pg-config.*pgNOPE934')" "1"
check "and it does not pretend to have run checks" \
	"$(printf '%s' "$_h934_absent" | grep -cE '^checks run:')" "0"

# A pg_config that EXISTS and answers nothing. This is the shape that produced the
# empty `_bindir`: the command succeeded, so `[ -x ]` alone would accept it.
_h934_stub="$PGC_WORKDIR/pg_config_silent_934"
printf '#!/bin/sh\nexit 0\n' > "$_h934_stub"
chmod +x "$_h934_stub"
_h934_silent="$(bash "$_hs" "$_h934_stub" 2>&1)"
_h934_silent_rc=$?
check "premise: the stub is executable, so an -x test alone would accept it" \
	"$([ -x "$_h934_stub" ] && echo yes || echo no)" "yes"
check "premise: and it answers --bindir with nothing" \
	"$("$_h934_stub" --bindir | wc -c)" "0"
check "a pg_config whose --bindir is empty is refused too, not run with a broken PATH" \
	"$([ "$_h934_silent_rc" != 0 ] && echo refused || echo "exited 0")" "refused"

# THE CONTROL, without running the whole suite again. Invoking the driver with a
# GOOD pg_config would re-run every part, so the control is the two predicates the
# guard tests, applied to the pg_config THIS run was given -- plus the existence of
# this run, which is the guard having accepted it.
check "control: the pg_config this run was handed satisfies the first predicate" \
	"$([ -x "$PGC_SELFTEST_PG_CONFIG" ] && echo yes || echo no)" "yes"
check "control: and the second, so a good pg_config is not refused" \
	"$([ -d "$("$PGC_SELFTEST_PG_CONFIG" --bindir)" ] && echo yes || echo no)" "yes"

# ---- and no part may exit 0, because a part is SOURCED ------------------------
#
# `exit 0` in a sourced part exits the DRIVER, before `pgc_summary`, with a status
# that says success. Part 010 did it on both of its skip paths -- and its own
# comment, four lines above the first one, says why that is the hazard: "a quiet
# skip means the guard stops being tested that run without anyone noticing".
#
# HEREDOC-AWARE, because the parts generate fixture scripts that legitimately end
# in `exit 0`, and a flat grep counts those as offences.
#
# THE REAL NUMBERS ARGUE IT BETTER THAN A ROUND ONE. An earlier version of this
# comment said a flat grep sees "13 either way", which is true of main and false of
# the branch it ships in: on this head it sees 22, because the fixtures BELOW add ten
# `exit 0` lines of their own. So the flat count moves for a reason that has nothing
# to do with the defect, which is the argument:
#
#     heredoc-aware sweep    2 before the fix, 0 after
#     flat grep -c 'exit 0'  13 before, 24 after
#
# Reported by @jdatcmd, who checked the number against the tree rather than the
# sentence.
#
# WHICH SPELLINGS THIS SEES, stated because a rule about the literal `0` is not the
# whole of "a sourced part must not end the driver claiming success". It sees
# `exit 0` and a BARE `exit`, which ends with the last command's status and is very
# often 0. It cannot decide `exit $?` or `exit "$rc"`, where the status is computed:
# flagging those would refuse a part that legitimately exits non-zero. Measured on
# this head, each of the three is **zero**, so nothing is open -- but the next reader
# should not assume the class is closed. Raised by @jdatcmd.
_h934_sweep() {
	awk '
		FNR == 1 { hd = "" }
		hd != "" { if ($0 == hd || $0 ~ "^[ \t]*" hd "[ \t]*$") hd = ""; next }
		/<<-?[ \t]*'\''?[A-Za-z_][A-Za-z0-9_]*'\''?[ \t]*$/ {
			if ($0 !~ /^[ \t]*#/) {
				t = $0; sub(/.*<<-?[ \t]*/, "", t); gsub(/'\''/, "", t)
				sub(/[ \t]*$/, "", t); hd = t; next
			}
		}
		/^[ \t]*exit[ \t]+0[ \t]*$/ { printf "%s:%d\n", FILENAME, FNR }
		/^[ \t]*exit[ \t]*$/ { printf "%s:%d\n", FILENAME, FNR }
	' "$@"
}
check "premise: the sweep reads every selftest part" \
	"$([ "$(ls "$PGC_TESTDIR"/selftest/*.sh | wc -l)" -ge 30 ] && echo yes || echo no)" "yes"
check "premise: and it finds a planted exit 0 outside a heredoc" \
	"$(printf 'echo hi\nexit 0\n' > "$PGC_WORKDIR/p934.sh"; _h934_sweep "$PGC_WORKDIR/p934.sh" | grep -c .)" "1"
check "premise: and a BARE exit too, which ends with the last status and is usually 0" \
	"$(printf 'echo hi\nexit\n' > "$PGC_WORKDIR/p934e.sh"; _h934_sweep "$PGC_WORKDIR/p934e.sh" | grep -c .)" "1"
check "premise: while a deliberate non-zero exit is not an offence" \
	"$(printf 'echo hi\nexit 66\n' > "$PGC_WORKDIR/p934f.sh"; _h934_sweep "$PGC_WORKDIR/p934f.sh" | grep -c .)" "0"
check "premise: while a fixture script ending in exit 0 inside a heredoc is not an offence" \
	"$({ printf 'cat > /tmp/x <<%sEOF%s\n' "'" "'"; printf 'exit 0\n'; printf 'EOF\n'; } > "$PGC_WORKDIR/p934b.sh"; _h934_sweep "$PGC_WORKDIR/p934b.sh" | grep -c .)" "0"
# THE LITERAL AND THE CONSTANT MUST AGREE. Part 010 spells 66 rather than
# $PGC_EXIT_SKIPPED because lib.sh arrives in part 020 and 010 runs first. A second
# copy of a constant is a thing that drifts, so the copy is asserted against the
# original instead of being trusted.
check "part 010's skip status is the one lib.sh calls PGC_EXIT_SKIPPED" \
	"$(grep -cE '^PGC_EXIT_SKIPPED=66$' "$PGC_TESTDIR/lib.sh")" "1"
# `[[:space:]]` AND NOT `\t`: in POSIX ERE a backslash-t is a literal `t`, so the
# first version of this arm searched for "texit 66" and reported 0 against a file
# holding two. Third time that has cost me a measurement today, in three different
# sweeps.
check "and part 010 exits with exactly that status on its skip paths" \
	"$(grep -cE '^[[:space:]]+exit 66$' "$PGC_TESTDIR/selftest/010-stand-up-a-squatter-on-a.sh")" "2"
# ECHO LINES ONLY. Counting the phrase anywhere found three: the two the part emits
# and the one inside the comment above them explaining why they are there. A sweep
# that counts its own documentation is the trap the raises scan records.
check "and pairs each with the marker the runners require beside the status" \
	"$(grep -cE '^[[:space:]]+echo .*SKIPPED \(ran no checks\)' "$PGC_TESTDIR/selftest/010-stand-up-a-squatter-on-a.sh")" "2"

check "no selftest part exits 0, which would exit the driver before its summary" \
	"$(_h934_sweep "$PGC_TESTDIR"/selftest/*.sh | grep -c . || true)" "0"
