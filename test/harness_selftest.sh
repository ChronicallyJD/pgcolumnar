#!/usr/bin/env bash
#
# Self-test for the harness's own cluster-identity guard.
#
# lib.sh retries a failed start on a fresh port, and pg_ctl -w only proves that
# *something* answers there. Without a guard, a suite whose port is already owned
# by another postmaster runs every statement against that cluster: its log grows a
# stray "database already exists" while this suite's own objects are invisible.
# That hides real failures as easily as it invents fake ones, so the guard is
# load-bearing and gets a test of its own.
#
# This stands up a squatter cluster on a known port, points a suite straight at
# it, and asserts the suite ends up on a cluster it owns, that the squatter is
# left alone, and that the suite's own objects are actually there.
#
# Usage:  test/harness_selftest.sh [PG_CONFIG]
# Written fresh for pgColumnar.


# portlib.sh alone, not lib.sh: this suite carries its own harness, and the port
# band is needed before any of it runs. Sourcing portlib twice is harmless.
. "$(dirname "${BASH_SOURCE[0]}")/portlib.sh"

set -uo pipefail

PGC_SELFTEST_PG_CONFIG="${1:-/usr/local/pg17/bin/pg_config}"

# REFUSE A pg_config THIS BOX DOES NOT HAVE, before anything is sourced (#934).
#
# `_bindir` used to be assigned from a command that had failed, and the suite then
# ran on with every PATH wrong. Part 010 took its own skip path, called `exit 0`,
# and because a part is SOURCED that exited the DRIVER -- 4 lines of output, no
# summary, status 0. A caller cannot tell that from the 610-check pass it looks
# like. Measured on main:
#
#     /usr/local/pg18a/bin/pg_config    rc=0  1246 lines  checks run: 610
#     /usr/local/pgNOPE/bin/pg_config   rc=0     4 lines  no summary at all
#
# The default above is `/usr/local/pg17`, which the audit container does not have,
# so the wrong invocation is the EASY one to make -- and it cost a whole mutation
# round, because the control and the mutation both reported rc=0 with zero FAIL
# lines, which reads exactly like "the mutation changed nothing".
#
# TWO PREDICATES, because one is not enough. A `pg_config` can exist and be
# executable and still answer nothing: that is the shape that produced the empty
# `_bindir`, so `-x` alone would have accepted it.
if [ ! -x "$PGC_SELFTEST_PG_CONFIG" ]; then
	echo "FATAL  no-pg-config: $PGC_SELFTEST_PG_CONFIG is not an executable pg_config"
	echo "       pass one as the first argument, e.g. /usr/local/pg18a/bin/pg_config"
	exit 2
fi
_bindir="$("$PGC_SELFTEST_PG_CONFIG" --bindir)"
if [ -z "$_bindir" ] || [ ! -d "$_bindir" ]; then
	echo "FATAL  no-pg-config: $PGC_SELFTEST_PG_CONFIG --bindir gave [$_bindir],"
	echo "       which is not a directory, so every PATH built from it would be wrong"
	exit 2
fi

# ---- the checks themselves live in test/selftest/, one file per subject ------
#
# They used to be appended here, and that is what #554 is about: three PRs in one
# day each added a block at the end of this file and each pair conflicted, while
# the one PR that edited the middle merged clean. It is the same failure this
# file argues about for SUITES, in the file that argues it -- "one per line, both
# appended at the end -> CONFLICT".
#
# The fix is the same shape as the SUITES fix: give an addition an insertion
# point decided by its content rather than by "the end". Here the unit is a FILE,
# so adding a subject touches no line anybody else is editing. The glob is
# sorted, so the order is the numeric prefix and not the order of the loop.
#
# Sourced, not executed: they share the squatter cluster, the helpers above and
# the check counter, exactly as they did when they were one file.
# The parts are SOURCED, so ${BASH_SOURCE[0]} inside one of them names the part,
# not this file: `dirname` would give test/selftest and every path built from it
# would miss by a directory. So the directory is resolved ONCE here and the parts
# use it. Measured the hard way -- the first split kept BASH_SOURCE in the parts,
# every helper lookup resolved to test/selftest/lib.sh, and the suite ran zero
# checks while every static check I had (byte-identity, parse, check-name order)
# still passed.
PGC_TESTDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for _sf in "$PGC_TESTDIR"/selftest/*.sh; do
	[ -e "$_sf" ] || { echo "FAIL  no selftest parts found; the suite would report zero checks"; PGC_FAIL=1; break; }
	# shellcheck source=/dev/null
	. "$_sf"
done

pgc_summary

