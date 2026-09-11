# ---- the pytest cluster helpers must derive, and must clean up --------------
#
# WHY THIS EXISTS. Two findings from @linuxhikerpm on #897, both reproduced
# against the branch before they were fixed, and both about the harness's own
# infrastructure rather than about coverage.
#
#   1. source_fingerprint() read src/ only, so editing objstore/ -- a separately
#      built module the top-level Makefile reaches by recursion -- left the hash
#      unchanged and build_once certified a STALE MODULE AS CURRENT. That is the
#      same gap #898 closes in lib.sh, but this is an INDEPENDENT Python
#      implementation, so rebasing #898 would not have fixed it.
#
#   2. make_cluster() created its temporary tree with mkdtemp and then ran
#      initdb, start and is_ours with no cleanup guard, so a failed setup leaked
#      the directory -- and conftest.py cannot clean up after it, because
#      `cluster, root = make_cluster(...)` never completes when the call raises.
#
# WHAT THIS PART COVERS, AND WHAT MOVED (#432). Finding 1 is here: its subject is
# test/pgc_fingerprint.py, which lib.sh runs with the system interpreter and which
# is NOT part of the pytest harness, so checking it is this part's own business.
#
# FINDING 2 HAS MOVED. Its subject is test/pytest/pgc_cluster.py, and the arms that
# read it as text are now source checks in test/pytest/test_build_refusal.py, beside
# the behavioural arm that provokes a real failed setup and asserts no directory is
# left. Python reading its own module is not a cross-harness reference; a shell part
# grepping it is the one CONTEXT.md refuses.
#
# AND THE OLD REASON FOR KEEPING THEM HERE IS STALE. It said those arms "need pytest,
# psycopg and a virtualenv that CI does not install". CI has a `pytest-guards` job
# that installs pytest pinned from requirements-test.txt, asserts psycopg is absent,
# and runs the database-free file list, which contains test_build_refusal.py.
#
# MEASURED BEFORE MOVING ANYTHING. Five mutations of pgc_cluster.py, each asserted to
# have applied and each leaving the file well-formed: BaseException narrowed to
# Exception, cluster.stop() removed, the bare re-raise turned into pass, a private
# hashlib.md5 added, and shutil.rmtree(root) removed. Every one reddens on the python
# side -- three of them only the source arm, two of them the behavioural arm as well.
# Restored byte-for-byte after each.
#
# THE DERIVATION IS THE POINT OF THE FIRST GROUP. Hard-coding objstore/ would fix
# today and fail the next time a module is added, so the arms below require the
# GLOB rather than the name -- and require that the name does NOT appear, which
# is the only way to tell a derivation from a list that happens to be complete.


# THE FINGERPRINT MOVED (#907). It was an independent Python implementation in
# pgc_cluster.py and an independent shell one in lib.sh; the pair produced four
# defects in a day. Both now delegate to test/pgc_fingerprint.py, so these arms
# follow the property to where it lives. Left pointed at pgc_cluster.py they
# would have gone GREEN by finding nothing to object to, which is why each one
# below is mirrored against a fixture that must make it red.
_pc_fp="$PGC_TESTDIR/pgc_fingerprint.py"

check "premise: the one fingerprint implementation is where this part thinks it is" \
	"$([ -f "$_pc_fp" ] && echo yes || echo no)" "yes"

check "the fingerprint derives its build directories from a Makefile on disk" \
	"$(grep -c '_is_plain_file(d / "Makefile")' "$_pc_fp")" "1"

# A list would pass the arm above if someone added the derivation AND kept a name.
check "and it names no module directory, so it is a derivation and not a list" \
	"$(grep -c '"objstore"' "$_pc_fp")" "0"

# src/module.c and objstore/module.c are different inputs. Hashing the bare name
# would make them interchangeable, which is a collision the derivation cannot
# prevent by itself.
check "the hash mixes in each file's path relative to the tree, not its name" \
	"$(grep -c 'relative_to(root)' "$_pc_fp")" "1"

check "and no longer mixes in the bare filename" \
	"$(grep -c 'h.update(path.name.encode())' "$_pc_fp")" "0"

# AND NEITHER CALLER MAY KEEP A PRIVATE COPY. This is the arm that would catch

check "and the shell keeps none either" \
	"$(grep -cE 'md5sum < |xargs -0 cat' "$PGC_TESTDIR/lib.sh")" "0"

# STDLIB ONLY, AND NOTHING FROM test/pytest/. lib.sh runs this module with the
# SYSTEM interpreter; an import from the pytest tree or a third-party package
# would make every bash suite unrunnable until somebody installed pytest.
check "the module imports nothing from the pytest tree" \
	"$(grep -cE '^(import|from) +(pgc_|conftest|pytest|psycopg)' "$_pc_fp")" "0"


# ---- and these greps must be able to FAIL -----------------------------------

_pc_fix="$PGC_WORKDIR/clusterhelpers"; rm -rf "$_pc_fix"; mkdir -p "$_pc_fix"


printf '    dirs = [root / "src"]\n' > "$_pc_fix/srconly.py"
check "a fingerprint that reads src only is caught" \
	"$(grep -c '_is_plain_file(d / "Makefile")' "$_pc_fix/srconly.py")" "0"

# And the private-copy arms must be able to redden too, or "0" above means only
# that the pattern matches nothing anywhere.
printf 'import hashlib\nh = hashlib.md5(b"")\n' > "$_pc_fix/privatecopy.py"
check "a caller that reimplements the digest is caught" \
	"$(grep -cE 'hashlib\.md5' "$_pc_fix/privatecopy.py")" "1"

printf 'from pgc_cluster import x\n' > "$_pc_fix/badimport.py"
check "an import from the pytest tree is caught" \
	"$(grep -cE '^(import|from) +(pgc_|conftest|pytest|psycopg)' "$_pc_fix/badimport.py")" "1"

printf '    dirs = [srcdir / "src", srcdir / "objstore"]\n' > "$_pc_fix/listed.py"
check "and a hard-coded module list is caught by the name arm" \
	"$(grep -c '"objstore"' "$_pc_fix/listed.py")" "1"

# The mirror: the same three greps on the REAL file, so a zero above is a missing
# guard rather than a pattern that matches nothing anywhere.
# The mirror: the same greps on the REAL files, so a zero above is a missing
# guard rather than a pattern that matches nothing anywhere.
check "premise: while the real module satisfies the derivation arm" \
	"$(grep -cE '_is_plain_file\(d / "Makefile"\)' "$_pc_fp")" "1"


unset _pc_fp _pc_fix
