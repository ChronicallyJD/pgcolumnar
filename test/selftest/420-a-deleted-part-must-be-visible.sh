# ---- a deleted selftest part must not shrink the run silently ---------------
#
# WHY THIS EXISTS. harness_selftest sources `selftest/*.sh`. A glob cannot notice
# a deletion: the file goes, the loop runs one fewer time, the suite reports a
# smaller number, and every remaining check still passes. Measured on #918 -- a
# log with all 96 records of part 410 removed, and `checks run:` adjusted to
# match, reconciled with itself AND merged into the ledger at rc=0. Nothing in
# either harness could tell that from a run where part 410 simply had less to
# say. Reported by @linuxhikerpm.
#
# THE MANIFEST IS INDEPENDENT OF THE GLOB, which is the entire point. Comparing
# the glob against itself is what the runner already does; comparing it against a
# COMMITTED list makes deleting a part a two-line diff a reviewer sees rather
# than a number that quietly falls.
#
# This lives in a part rather than in the driver because selftest 200 requires
# the driver to hold no checks -- they all live in parts -- and that rule is
# right: an assertion in the driver is one nobody looks for.

_dp_dir="$PGC_TESTDIR/selftest"
_dp_manifest="$_dp_dir/parts.manifest"

check "the parts manifest exists, because without it a deletion is invisible" \
	"$([ -f "$_dp_manifest" ] && echo present || echo missing)" "present"

_dp_ondisk="$(cd "$_dp_dir" && ls -1 ./*.sh 2>/dev/null | sed 's|^\./||' | sort)"
_dp_listed="$(grep -v '^[[:space:]]*$' "$_dp_manifest" 2>/dev/null | sort)"

check "premise: the manifest names something, so the comparison has two sides" \
	"$([ "$(printf '%s\n' "$_dp_listed" | grep -c .)" -ge 20 ] && echo yes || echo no)" "yes"

_dp_only_disk="$(comm -23 <(printf '%s\n' "$_dp_ondisk") <(printf '%s\n' "$_dp_listed"))"
_dp_only_list="$(comm -13 <(printf '%s\n' "$_dp_ondisk") <(printf '%s\n' "$_dp_listed"))"

check "every part on disk is named in the manifest" \
	"$(printf '%s' "$_dp_only_disk" | grep -c . || true)" "0"
[ -z "$_dp_only_disk" ] || printf '      on disk but unlisted: %s\n' $_dp_only_disk

check "and every name in the manifest is a part on disk, so a deletion reddens" \
	"$(printf '%s' "$_dp_only_list" | grep -c . || true)" "0"
[ -z "$_dp_only_list" ] || printf '      listed but gone: %s\n' $_dp_only_list

# inputs == sum(buckets), printed from the data rather than retyped.
_dp_both="$(comm -12 <(printf '%s\n' "$_dp_ondisk") <(printf '%s\n' "$_dp_listed") | grep -c . || true)"
_dp_n_disk="$(printf '%s\n' "$_dp_ondisk" | grep -c . || true)"
echo "  parts: on disk=$_dp_n_disk | in both=$_dp_both, only on disk=$(printf '%s' "$_dp_only_disk" | grep -c . || true), only in the manifest=$(printf '%s' "$_dp_only_list" | grep -c . || true)"
check "the three buckets account for every part on disk" \
	"$((_dp_both + $(printf '%s' "$_dp_only_disk" | grep -c . || true)))" "$_dp_n_disk"

# THE COMPARISON MUST BE ABLE TO FAIL, on a fixture rather than on the tree.
_dp_fix="$PGC_WORKDIR/deletedpart"; rm -rf "$_dp_fix"; mkdir -p "$_dp_fix"
printf '%s\n' aaa.sh bbb.sh ccc.sh > "$_dp_fix/manifest"
printf '%s\n' aaa.sh ccc.sh > "$_dp_fix/ondisk"
check "premise: a part present in the manifest and missing on disk is named" \
	"$(comm -13 "$_dp_fix/ondisk" "$_dp_fix/manifest" | tr -d '[:space:]')" "bbb.sh"
printf '%s\n' aaa.sh bbb.sh ccc.sh ddd.sh > "$_dp_fix/ondisk"
check "premise: and a part added without listing it is named too" \
	"$(comm -23 "$_dp_fix/ondisk" "$_dp_fix/manifest" | tr -d '[:space:]')" "ddd.sh"

# WHAT THIS DOES NOT CATCH, stated rather than implied. A part that still exists
# and contributes nothing -- an early return, a condition that never fires -- is
# invisible here. A runtime "every part contributed at least one check" arm was
# written first and REMOVED: parts 010 and 020 legitimately contribute none, 020
# because it is setup with no check calls at all and 010 because its only checks
# are on its failure path. A rule with two false positives on a healthy tree is
# not a rule, and the deletion this part exists for is caught above.
unset _dp_dir _dp_manifest _dp_ondisk _dp_listed _dp_only_disk _dp_only_list \
	_dp_both _dp_n_disk _dp_fix
