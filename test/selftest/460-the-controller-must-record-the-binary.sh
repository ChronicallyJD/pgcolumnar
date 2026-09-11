# ---- the controller must record the BINARY, not only the source -------------
#
# #961. #960 made a suite able to refuse a binary it has not examined, by recording
# the installed library's digest in the source stamp. Nothing asserted that the
# MATRIX CONTROLLER records it, and the failure if it stops is green.
#
# `run_all_versions.sh` builds once per major and runs every child with
# `PGC_SKIP_BUILD=1`. If the controller's stamp write loses its third argument,
# every child reaches `source-only` and PASSES -- because `source-only` is also the
# state of every stamp written before #959, so it cannot be a failure. The whole
# matrix degrades to UNVERIFIED with a green rollup on both majors.
#
# THE DEFECT IS A DROPPED ARGUMENT AT A CALL SITE, so an arm that calls
# `pgc_write_source_stamp` itself proves nothing: the function would be correct and
# the caller wrong. The block must RUN. @jdatcmd asked for this arm while approving
# #960, on the ground that the failure it catches is green.
#
# WHY IT COSTS NO BUILD. The controller's stamp block reads the installed library
# and fingerprints a tree; it does not compile. So the block is extracted from the
# runner and evaluated against a COPY of this tree, with `builddir` and `pgc` set
# the way the controller sets them. 24M at 31ms a copy, against minutes for a real
# per-major build, and what runs is the real call site's own text.
#
# WHAT THIS CANNOT SEE, stated because the gap is the point of #961: that the
# controller REACHES that line. The `make install` guard above it could start
# failing closed and this part would not notice. It asserts what the line does, not
# that control flow arrives there.

_c961_rav="$TESTDIR/run_all_versions.sh"
_c961_tab="$(printf '\t')"

check "premise: the matrix controller is present and parses" \
	"$([ -r "$_c961_rav" ] && bash -n "$_c961_rav" 2>/dev/null && echo yes || echo no)" "yes"

# THE PG_CONFIG THIS SUITE WAS GIVEN, by the name the harness uses. The first
# version of this part read `$PG_CONFIG`, which no part sets: under `set -u` that
# aborted the command substitution the driver runs in, and both arms below reported
# `got []`. An empty result is not a value, and an arm whose inputs are unchecked
# reports the same emptiness for "the controller is broken" and "I misspelled a
# variable". So the input is asserted before it is used.
_c961_pgc="${PGC_SELFTEST_PG_CONFIG:-}"
check "premise: this part was given an executable pg_config to read the prefix from" \
	"$([ -n "$_c961_pgc" ] && [ -x "$_c961_pgc" ] && echo yes || echo no)" "yes"

# The subshell block, from `if (` to `); then`. A LITERAL TAB, not `\t`: GNU grep's
# BRE does not read `\t` as a tab, and the first version of this premise counted 0
# and would have let the arms below run against an empty block.
_c961_block="$(awk -v t="$_c961_tab" '
	$0 == t "if (" {f=1} f {print} f && $0 == t "); then" {exit}' "$_c961_rav")"

check "premise: the controller's stamp block was extracted exactly once" \
	"$(printf '%s\n' "$_c961_block" | grep -c "^${_c961_tab}if ($")" "1"
check "premise: and it holds exactly one stamp write" \
	"$(printf '%s\n' "$_c961_block" | grep -c 'pgc_write_source_stamp')" "1"

# _c961_drive BLOCK -> "<claim> <stampline-count>"
#
# The block names `builddir` and `pgc`, which is why setting those is enough to run
# it. Evaluated with the leading tab stripped so the heredoc-free `eval` parses.
_c961_drive() {
	local block="$1" tmp builddir pgc stamp src_v bin_v claim lines
	tmp="$(mktemp -d "${TMPDIR:-/tmp}/pgc-c961.XXXXXX")"
	mkdir -p "$tmp/copy"
	cp -a "$TESTDIR/../." "$tmp/copy/" 2>/dev/null
	builddir="$tmp/copy"
	pgc="$_c961_pgc"
	if [ -z "$pgc" ] || [ ! -d "$builddir/test" ]; then
		# A SENTINEL, NOT EMPTY. `driver-could-not-run` cannot be mistaken for a
		# verdict, so no arm below can pass or fail for a reason that is about this
		# part rather than about the controller.
		printf 'driver-could-not-run 0\n'
		rm -rf "$tmp"
		return 0
	fi
	eval "$(printf '%s\n' "$block" | sed "s/^${_c961_tab}//")
	:
else
	echo 'the controller block reported failure' >&2
fi" >/dev/null 2>&1
	stamp="$(pgc_source_stamp_path "$builddir" "$pgc")"
	if [ ! -f "$stamp" ]; then
		printf 'no-stamp 0\n'
		rm -rf "$tmp"
		return 0
	fi
	lines="$(grep -c . "$stamp")"
	src_v="$(pgc_freshness_verdict "$(pgc_read_source_stamp "$stamp")" \
		"$(pgc_source_fingerprint "$builddir")")"
	bin_v="$(pgc_binary_identity_verdict "$(pgc_read_installed_stamp "$stamp")" \
		"$(pgc_installed_library_digest "$pgc")")"
	claim="$(pgc_freshness_claim "$src_v" "$bin_v")"
	printf '%s %s\n' "$claim" "$lines"
	rm -rf "$tmp"
}

_c961_real="$(_c961_drive "$_c961_block")"

check "the controller's stamp carries BOTH fields (#961)" \
	"$(printf '%s' "$_c961_real" | awk '{print $2}')" "2"
check "so a child suite under PGC_SKIP_BUILD reaches verified, not source-only (#961)" \
	"$(printf '%s' "$_c961_real" | awk '{print $1}')" "verified"

# THE CONTROL, because an arm asserting `verified` passes for any reason that makes
# the claim verified, including a driver that never ran the block. Drop the third
# argument -- the careless edit #961 describes -- and the SAME driver must reach
# `source-only`. Without this the two arms above could both be vacuous.
_c961_mut="$(printf '%s\n' "$_c961_block" \
	| sed '/pgc_installed_library_digest/d' \
	| sed "s|\"\$(pgc_source_fingerprint \"\$builddir\")\" \\\\|\"\$(pgc_source_fingerprint \"\$builddir\")\"|")"
check "premise: the mutation removed the installed-digest argument" \
	"$(printf '%s\n' "$_c961_mut" | grep -c 'pgc_installed_library_digest')" "0"

_c961_degraded="$(_c961_drive "$_c961_mut")"
check "control: without that argument the same driver degrades to source-only (#961)" \
	"$(printf '%s' "$_c961_degraded" | awk '{print $1}')" "source-only"
check "control: and the stamp carries one field rather than two" \
	"$(printf '%s' "$_c961_degraded" | awk '{print $2}')" "1"

# ---- and the same argument at every other call site -------------------------
#
# A static sweep, which is weaker than driving and is the right shape here: the
# other two callers are `pgc_setup` (every suite's own build) and `devloop.sh` (a
# developer tool), and driving either costs a build. CONTINUATIONS ARE JOINED
# first, because every one of these calls is written across four lines and a
# per-line grep would find the function name on a line carrying no arguments at
# all -- a guard that passes because it read half a statement.
_c961_joined="$(
	for f in "$TESTDIR/lib.sh" "$TESTDIR/devloop.sh" "$_c961_rav"; do
		sed -e :a -e '/\\$/N; s/\\\n//; ta' "$f"
	done
)"
_c961_calls="$(printf '%s\n' "$_c961_joined" | grep -c 'pgc_write_source_stamp .*pgc_source_stamp_path')"
check "premise: all three stamp call sites were found with their arguments joined" \
	"$_c961_calls" "3"
check "every caller records the installed library's digest (#961)" \
	"$(printf '%s\n' "$_c961_joined" | grep 'pgc_write_source_stamp .*pgc_source_stamp_path' \
		| grep -c 'pgc_installed_library_digest')" "3"

unset _c961_rav _c961_tab _c961_pgc _c961_block _c961_real _c961_mut _c961_degraded _c961_joined _c961_calls
unset -f _c961_drive
