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
