# ---- the binary under test must be built from this source, and the server must
# ---- be running it (#432 follow-up, jd)
#
# TWO QUESTIONS, AND THE HARNESS COULD ANSWER NEITHER.
#
# selftest 110 compares the INSTALLED .so against the one built in this tree, so a
# missed install and a foreign overwrite are caught. Nothing derived anything from
# the SOURCE TEXT, so both copies could agree with each other while both were stale
# against edited source. PGC_SKIP_BUILD opens that hole widest, because not
# rebuilding is its entire purpose.
#
# And a cp is not enough. shared_preload_libraries='pgcolumnar' maps the library at
# postmaster start, so `make install` over a running instance changes the file and
# nothing else: every backend keeps executing the code it already mapped. A binary
# can match the source exactly while the server runs something older.
#
# THE CONTROLLER SHAPE. Whoever builds records a fingerprint of the build inputs.
# Every suite in the batch recomputes it and compares, so it is one build per batch
# and one hash per suite rather than a rebuild per suite. Then, once the cluster is
# up, the suite compares the binary's mtime against pg_postmaster_start_time().
#
# The verdict functions are pure, taking their inputs as arguments, for the same
# reason pgc_build_needs_clean is: they can be exercised here without a build.
#
# THE MEASURED COST OF NOT HAVING THIS. A probe run under PGC_SKIP_BUILD=1 asserted
# its fix was "present" by grepping the SOURCE while measuring a .so a different
# worktree had installed. Its control failed, and the failure read as a product
# defect for several minutes.
#
# AND ONE FROM WRITING IT. The first revision wrote the stamp in the skip-build
# branch, so every run recorded the source it was about to compare against and a
# suite measuring an edited tree reported "matches the binary under test". The arm
# below that requires `stale` is what caught it.

check "a fingerprint equal to the record is fresh" \
	"$(pgc_freshness_verdict abc123abc123 abc123abc123)" "fresh"
check "a fingerprint different from the record is stale" \
	"$(pgc_freshness_verdict abc123abc123 def456def456)" "stale"
check "no record at all is unknown, not fresh" \
	"$(pgc_freshness_verdict "" abc123abc123)" "unknown"
check "and an uncomputable current fingerprint is unknown, not stale" \
	"$(pgc_freshness_verdict abc123abc123 "")" "unknown"

check "a server started after the binary is fresh" \
	"$(pgc_running_binary_verdict 1000 2000)" "fresh"
check "a server started at the same second is fresh" \
	"$(pgc_running_binary_verdict 1000 1000)" "fresh"
check "a server older than the binary predates it" \
	"$(pgc_running_binary_verdict 2000 1000)" "predates"
check "a missing binary timestamp is unknown, not predates" \
	"$(pgc_running_binary_verdict "" 1000)" "unknown"
check "a missing postmaster timestamp is unknown, not predates" \
	"$(pgc_running_binary_verdict 1000 "")" "unknown"
check "and a non-numeric timestamp is unknown rather than compared as text" \
	"$(pgc_running_binary_verdict 1000 "not-a-time")" "unknown"

# The fingerprint has to MOVE when a build input moves and STAY when nothing does.
# A fingerprint that never changes reports fresh forever, which is the failure this
# whole file exists to prevent, one level down.
_fp_dir="$(mktemp -d)"
mkdir -p "$_fp_dir/src"
printf 'int x;\n' > "$_fp_dir/src/a.c"
printf 'PG_CONFIG = pg_config\n' > "$_fp_dir/Makefile"
_fp_one="$(pgc_source_fingerprint "$_fp_dir")"
check "a fingerprint is 12 hex characters" \
	"$(printf '%s' "$_fp_one" | grep -cE '^[0-9a-f]{12}$')" "1"
check "the same tree fingerprints the same twice" \
	"$(pgc_source_fingerprint "$_fp_dir")" "$_fp_one"
printf 'int x; int y;\n' > "$_fp_dir/src/a.c"
check "editing a source file moves the fingerprint" \
	"$([ "$(pgc_source_fingerprint "$_fp_dir")" != "$_fp_one" ] && echo moved || echo same)" \
	"moved"
_fp_two="$(pgc_source_fingerprint "$_fp_dir")"
printf 'int x;\n' > "$_fp_dir/src/a.c"
check "and restoring it restores the fingerprint" \
	"$(pgc_source_fingerprint "$_fp_dir")" "$_fp_one"
printf 'notes\n' > "$_fp_dir/README-not-a-build-input"
check "a file that is not a build input does not move it" \
	"$(pgc_source_fingerprint "$_fp_dir")" "$_fp_one"
printf 'int z;\n' > "$_fp_dir/src/b.c"
check "adding a source file moves it" \
	"$([ "$(pgc_source_fingerprint "$_fp_dir")" != "$_fp_one" ] && echo moved || echo same)" \
	"moved"
rm -rf "$_fp_dir"

# ---- every directory the build recurses into is in the fingerprint -----------
#
# THE PROPERTY, NOT A LIST. The first fingerprint read $dir/src only, so editing
# objstore/columnar_objstore_module.c -- a SEPARATE shared library the top-level
# Makefile builds and installs by recursion -- left it unchanged, and three
# objstore suites could measure a stale module while the run printed "matches
# the binary under test" (@jdatcmd, #898 review).
#
# Naming objstore/ here would fix today and fail the next time a module is added,
# so this arm reads the recursion out of the Makefile and requires every target
# directory to be covered. If someone adds `$(MAKE) -C $(FOO_DIR)` and FOO_DIR
# has no Makefile of its own, or is otherwise missed, this reddens.
_bd_root="$PGC_SRCDIR"
_bd_covered="$(pgc_source_build_dirs "$_bd_root" | sed "s|^$_bd_root/||" | sort)"

check "PREMISE the fingerprint covers at least src" \
	"$(printf '%s\n' "$_bd_covered" | grep -cx 'src')" "1"

# Every `$(MAKE) -C $(SOMETHING_DIR)` in the top-level Makefile, resolved to the
# directory name that variable ends with.
_bd_missing=""
_bd_seen=0
while IFS= read -r _bd_var; do
	[ -n "$_bd_var" ] || continue
	_bd_val="$(sed -n "s/^[[:space:]]*$_bd_var[[:space:]]*=[[:space:]]*\(.*\)$/\1/p" \
		"$_bd_root/Makefile" | head -1)"
	_bd_name="${_bd_val##*/}"
	[ -n "$_bd_name" ] || continue
	_bd_seen=$(( _bd_seen + 1 ))
	printf '%s\n' "$_bd_covered" | grep -qx "$_bd_name" || \
		_bd_missing="$_bd_missing $_bd_name"
done <<EOF
$(grep -oE '\$\(MAKE\) -C \$\([A-Z_]+\)' "$_bd_root/Makefile" \
	| sed -E 's/.*\$\(([A-Z_]+)\)$/\1/' | sort -u)
EOF

# A guard that found nothing to check has not passed, it has abstained. The
# Makefile recurses today; if this ever reads zero the parser broke, not the
# Makefile.
check "PREMISE the Makefile's recursion was actually parsed" \
	"$([ "$_bd_seen" -ge 1 ] && echo yes || echo no)" "yes"
check "every directory the Makefile builds from is in the fingerprint" \
	"$([ -z "$_bd_missing" ] && echo none || echo "missing:$_bd_missing")" "none"

# And the consequence, end to end: a change under a recursed directory must move
# the fingerprint. Asserted against the real tree rather than a fixture, because
# the defect was that the real tree's objstore/ was not being read.
_bd_probe="$_bd_root/objstore/.pgc_fingerprint_probe.c"
_bd_before="$(pgc_source_fingerprint "$_bd_root")"
printf 'int pgc_fingerprint_probe;\n' > "$_bd_probe"
check "a new source file under objstore moves the fingerprint" \
	"$([ "$(pgc_source_fingerprint "$_bd_root")" != "$_bd_before" ] && echo moved || echo same)" \
	"moved"
rm -f "$_bd_probe"
check "and removing it restores the fingerprint" \
	"$(pgc_source_fingerprint "$_bd_root")" "$_bd_before"

# ---- the postmaster arm must be able to FIRE, not just to compute -----------
#
# The arms above feed pgc_running_binary_verdict fixture values and prove its
# arithmetic. They do not prove anything calls it. Every suite initdb's a fresh
# cluster and starts it AFTER the install, so through any shipped path the
# postmaster is always newer than the .so: `predates` is unreachable, and the
# call site could have been deleted with every check still passing
# (@jdatcmd, #898 review).
#
# These arms drive the real call site against the REAL running cluster. The stat,
# the pg_postmaster_start_time() query, the verdict and the refusal all execute;
# only the path is redirected, so nothing has to touch the installed library to
# prove the guard fires.
_rb_dir="$(mktemp -d)"
_rb_so="$_rb_dir/pgcolumnar.so"

# A file written now is newer than a postmaster that started earlier: predates.
: > "$_rb_so"
touch -d "+1 hour" "$_rb_so"
_rb_out="$(pgc_check_running_binary "$_rb_so" 2>&1)"; _rb_rc=$?
check "a library newer than the running server is REFUSED" "$_rb_rc" "1"
check "and the refusal says the server must be restarted" \
	"$(printf '%s\n' "$_rb_out" | grep -c 'Restart the cluster')" "1"

# The control: same call, same server, a library older than the postmaster.
touch -d "-1 hour" "$_rb_so"
_rb_out2="$(pgc_check_running_binary "$_rb_so" 2>&1)"; _rb_rc2=$?
check "a library older than the running server is accepted" "$_rb_rc2" "0"
check "and it says so rather than staying silent" \
	"$(printf '%s\n' "$_rb_out2" | grep -c 'started after the binary was installed')" "1"

# A path that does not exist must read unknown, not fresh and not a crash.
rm -f "$_rb_so"
_rb_out3="$(pgc_check_running_binary "$_rb_so" 2>&1)"; _rb_rc3=$?
check "an unreadable library is not a failure" "$_rb_rc3" "0"
check "but it says which question went unanswered" \
	"$(printf '%s\n' "$_rb_out3" | grep -c 'could not compare')" "1"
rm -rf "$_rb_dir"
