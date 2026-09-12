# ---- a skipped arm must record under the name it would have used ------------
#
# #994. Four sites skipped a whole block under ONE name that none of the arms
# inside it had. When the condition failed, those arms produced no record at all:
# a reader could not tell WHICH did not run, and the ledger could not tell a
# skipped arm from a deleted one, because a skipped arm's row has no matching
# record -- exactly as a removed check's would.
#
# The convention that fixes it was already in the tree: skip under each arm's own
# name, in a loop. This part asserts the loop stays in agreement with the arms.
#
# WHY A GUARD AND NOT JUST THE FIX. The loop DUPLICATES the arm names, so a rename
# in the sibling branch silently desynchronises them and the skip records under a
# name nothing emits -- which is the exact failure the fix exists to remove,
# reintroduced by an edit nobody thought was risky.
#
# That is not hypothetical. Writing #994 I put a name in the loop that a DIFFERENT
# open PR renames, and the set comparison below is what caught it before it
# shipped. #982's renames are still landing, so this drifts again the moment one
# of them touches these files.
#
# DERIVED, NOT LISTED. The sweep finds every `for VAR in ... check_skip "$VAR"`
# loop in the corpus, so a fifth site added later is covered on the day it is
# written rather than when somebody remembers this file.

_sk_sweep() {	# _sk_sweep -> "file:var" per skip loop, derived
	grep -rlE 'check_skip "\$[a-z_]+"' "$TESTDIR"/*.sh "$TESTDIR"/selftest/*.sh 2>/dev/null |
	while read -r _f; do
		grep -oE 'check_skip "\$[a-z_]+"' "$_f" | sed 's/.*"\$\(.*\)"/\1/' | sort -u |
		while read -r _v; do
			grep -qE "for $_v in" "$_f" && printf '%s:%s\n' "$_f" "$_v"
		done
	done
}

_sk_loop_names() {	# _sk_loop_names FILE VAR -> the names the loop skips under
	awk -v v="$2" '$0 ~ ("for " v " in") {i=1} i {print} i && /; do$/ {exit}' "$1" |
		grep -oE '"[^"]*"' | tr -d '"' | grep -v '^$' | sort -u
}

_sk_arm_names() {	# _sk_arm_names FILE VAR -> the names the sibling branch emits
	awk -v v="$2" '$0 ~ ("for " v " in") {f=1}
		f && /^[[:space:]]*else/{i=1;f=0;next}
		i && /^[[:space:]]*fi[[:space:]]*$/{exit} i' "$1" |
		grep -oE '^[[:space:]]*(check|check_num|check_text|check_ratio|ansp|ansq?|diff_query|diff_query_ordered)[[:space:]]+"[^"]*"' |
		sed 's/.*"\(.*\)"/\1/' | sort -u
}

_sk_sites="$(_sk_sweep)"
_sk_n=$(printf '%s\n' "$_sk_sites" | grep -c . || true)

# THE POPULATION IS THE PREMISE. A sweep that matched nothing reports the same
# zero mismatches as a corpus in perfect agreement, and only one of those is news.
check "premise: the sweep found skip loops to compare" \
	"$([ "${_sk_n:-0}" -ge 4 ] && echo yes || echo "only $_sk_n")" "yes"

_sk_bad=""
_sk_pairs=0
for _sk_site in $_sk_sites; do
	_sk_f="${_sk_site%:*}"; _sk_v="${_sk_site##*:}"
	_sk_l="$(_sk_loop_names "$_sk_f" "$_sk_v")"
	_sk_a="$(_sk_arm_names "$_sk_f" "$_sk_v")"
	# A loop guarding a block with no named arms is fine -- the skip IS the record
	# and nothing else claimed to run. Only a loop with arms to agree with is compared.
	[ -z "$_sk_a" ] && continue
	_sk_pairs=$((_sk_pairs + 1))
	if [ "$_sk_l" != "$_sk_a" ]; then
		_sk_bad="$_sk_bad $(basename "$_sk_f")"
	fi
done

check "premise: at least four loops had arms to be compared against" \
	"$([ "$_sk_pairs" -ge 4 ] && echo yes || echo "only $_sk_pairs")" "yes"

check "every skip loop names exactly the arms its sibling branch would emit (#994)" \
	"$(printf '%s' "$_sk_bad" | sed 's/^ //')" ""

unset _sk_sites _sk_n _sk_bad _sk_pairs _sk_site _sk_f _sk_v _sk_l _sk_a
unset -f _sk_sweep _sk_loop_names _sk_arm_names
