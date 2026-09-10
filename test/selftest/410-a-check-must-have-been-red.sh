# ---- a check must have been seen red, or be counted as debt -----------------
#
# Nothing recorded whether a check had ever been red. That is the gap that let 39
# checks across 35 suites ship unable to fail, three of them inside this very
# suite. The gate answered "did anything print FAIL" and had never answered
# "could anything print FAIL".
#
# WHAT THIS RECORDS, AND WHAT IT DOES NOT. It records that a named check WAS
# OBSERVED RED in a recorded run. It does NOT claim the check is proven able to
# fail: that needs a named mutation applied deliberately, and conflating the two
# would put a claim in the ledger that nothing measured.
#
# THE FIRST DESIGN DEADLOCKED AND THE SECOND DOES NOT. Bounding
# `checks_never_observed_red` means every added check breaks the gate, because a
# new check enters as `never` -- so the only way to land one was to raise a number
# the design said may only fall. It shipped at 614 rows, 614 never, ceiling 614.
# It is now a CENSUS, asserted to match the ledger; the CEILING is
# `suites_not_covered`, which adding a check does not move.
#
# WHAT THE GATE REFUSES is a check the committed ledger has never seen. Existing
# checks are grandfathered; a new one is named, and regenerating the ledger is the
# INTENDED fix rather than a forbidden edit.
# ---------------------------------------------------------------------------

_led="$PGC_TESTDIR/pgc_ledger.py"
_ledger="$PGC_TESTDIR/check_ledger.tsv"
_budget="$PGC_TESTDIR/check_ledger_budget.txt"

check "premise: the ledger tool exists" "$([ -f "$_led" ] && echo yes || echo no)" "yes"
check "premise: the ledger itself is a tracked file, not a variable" \
	"$([ -f "$_ledger" ] && echo yes || echo no)" "yes"
check "premise: the budget is a tracked file too" \
	"$([ -f "$_budget" ] && echo yes || echo no)" "yes"

_lw="$PGC_WORKDIR/ledger"; mkdir -p "$_lw"
_led_run() { python3 "$_led" "$@" 2>&1; }
_led_rc()  { python3 "$_led" "$@" >/dev/null 2>&1; echo $?; }

printf 'RESULT\tdemo\tpart1\tfirst check\tPASS\t\nRESULT\tdemo\tpart1\tsecond check\tPASS\t\nchecks run: 2\n' > "$_lw/green.log"
printf 'RESULT\tdemo\tpart1\tfirst check\tFAIL\t\nRESULT\tdemo\tpart1\tsecond check\tPASS\t\nchecks run: 2\n' > "$_lw/red.log"
printf 'demo\n' > "$_lw/registered"
printf 'suites_not_covered 0\n' > "$_lw/budget.txt"

# ---- fail closed. Every one of these returned rc=0 before -------------------
#
# read_records ignored unreadable files, empty ones and short records, so a gate
# over a NONEXISTENT log reported success. An integrity failure that reads as a
# clean run is worse than no gate, because it certifies. Reported by @linuxhikerpm.

: > "$_lw/empty.log"
printf 'RESULT\tdemo\tpart1\tname\n' > "$_lw/short.log"
: > "$_lw/l.tsv"
check "a gate over a nonexistent log is an integrity failure, not a pass" \
	"$(_led_rc gate --ledger "$_lw/l.tsv" --budget "$_lw/budget.txt" --registered "$_lw/registered" "$_lw/nope.log")" "2"
check "an empty log is one too, because there is nothing to reconcile" \
	"$(_led_rc gate --ledger "$_lw/l.tsv" --budget "$_lw/budget.txt" --registered "$_lw/registered" "$_lw/empty.log")" "2"
check "and a record missing its verdict" \
	"$(_led_rc gate --ledger "$_lw/l.tsv" --budget "$_lw/budget.txt" --registered "$_lw/registered" "$_lw/short.log")" "2"
check "each says what was wrong with the input" \
	"$(_led_run gate --ledger "$_lw/l.tsv" --budget "$_lw/budget.txt" --registered "$_lw/registered" "$_lw/short.log" \
		| grep -c 'a record needs suite, part, name and verdict')" "1"

# The three must be distinguishable from a REAL refusal, or fail-closed just
# renames every outcome.
check "a real refusal is a different status from an integrity failure" \
	"$(_led_rc gate --ledger "$_lw/l.tsv" --budget "$_lw/budget.txt" --registered "$_lw/registered" "$_lw/green.log")" "1"

# --registered is required. Skipping it silently is how a gate reports success
# for a question it never asked.
check "the gate refuses to run without the registered suite list" \
	"$(_led_rc gate --ledger "$_lw/l.tsv" --budget "$_lw/budget.txt" "$_lw/green.log")" "2"

# ---- the census: a green run records debt and never a red observation -------

: > "$_lw/ledger.tsv"
_led_run merge --ledger "$_lw/ledger.tsv" --date 2026-09-10 "$_lw/green.log" >/dev/null
check "merging a green run records both checks" "$(grep -c . "$_lw/ledger.tsv")" "2"
check "and records neither as ever having been red" \
	"$(cut -f4 "$_lw/ledger.tsv" | sort -u | tr '\n' ' ')" "never "
check "every row has five fields and no trailing tab" \
	"$(awk -F'\t' 'NF!=5' "$_lw/ledger.tsv" | grep -c . || true)" "0"
check "and an empty mutation is a placeholder, not an empty last field" \
	"$(grep -cP '\t$' "$_lw/ledger.tsv" || true)" "0"

_led_run merge --ledger "$_lw/ledger.tsv" --date 2026-09-10 "$_lw/red.log" >/dev/null
check "a check observed red gains the date it was seen" \
	"$(awk -F'\t' '$3=="first check"{print $4}' "$_lw/ledger.tsv")" "2026-09-10"
check "and one that stayed green keeps its debt" \
	"$(awk -F'\t' '$3=="second check"{print $4}' "$_lw/ledger.tsv")" "never"
_led_run merge --ledger "$_lw/ledger.tsv" --date 2026-09-11 "$_lw/green.log" >/dev/null
check "a later green run does not erase an observation" \
	"$(awk -F'\t' '$3=="first check"{print $4}' "$_lw/ledger.tsv")" "2026-09-10"

# ---- the mutation column ACCUMULATES ----------------------------------------
#
# Last-write-wins records the most recent attack rather than the catalogue the
# column exists to become, which defeats its stated purpose rather than limiting
# it. And one --mutation value copied across several logs attributes a deliberate
# change to failures it had nothing to do with. Both reported by @linuxhikerpm.

: > "$_lw/mut.tsv"
_led_run merge --ledger "$_lw/mut.tsv" --date D --mutation 'SAOP limit 128 -> 0' "$_lw/red.log" >/dev/null
check "a named mutation is recorded against the check that reddened" \
	"$(awk -F'\t' '$3=="first check"{print $5}' "$_lw/mut.tsv")" "SAOP limit 128 -> 0"
check "and not against one that stayed green" \
	"$(awk -F'\t' '$3=="second check"{print $5}' "$_lw/mut.tsv")" "-"
_led_run merge --ledger "$_lw/mut.tsv" --date D --mutation 'bloom neutered' "$_lw/red.log" >/dev/null
check "a second mutation ACCUMULATES rather than replacing the first" \
	"$(awk -F'\t' '$3=="first check"{print $5}' "$_lw/mut.tsv")" "SAOP limit 128 -> 0;bloom neutered"
check "one --mutation cannot be attributed across several runs at once" \
	"$(_led_rc merge --ledger "$_lw/mut.tsv" --date D --mutation X "$_lw/red.log" "$_lw/green.log")" "2"

# ---- two runs of a check are not a duplicate of it --------------------------
#
# Merging the logs first cannot tell "the same check in two runs" from "the same
# name twice in one run", and reported the first as the second.

: > "$_lw/dup.tsv"
check "the same check in two logs is two runs, not a duplicate" \
	"$(_led_run merge --ledger "$_lw/dup.tsv" --date D "$_lw/green.log" "$_lw/green.log" | grep -c 'duplicate')" "0"
printf 'RESULT\tdemo\tpart1\tsame\tPASS\t\nRESULT\tdemo\tpart1\tsame\tFAIL\t\nchecks run: 2\n' > "$_lw/twice.log"
: > "$_lw/dup2.tsv"
check "the same name twice in ONE log is a duplicate, and is named" \
	"$(_led_run merge --ledger "$_lw/dup2.tsv" --date D "$_lw/twice.log" \
		| grep -c 'duplicate check name in one run, so one ledger row covers 2: demo	part1	same')" "1"

# ---- renames, grouped by part and scanned against ONE run -------------------
#
# A global positional pairing misses a real rename whenever unrelated movement in
# another part shifts the ordering. And given a before-log and an after-log
# together, the vanished name is present in the union and nothing appears to have
# gone -- a scan that silently finds nothing is worse than one that refuses.

: > "$_lw/ren.tsv"
printf 'RESULT\tdemo\tpart1\tthe old name\tFAIL\t\nRESULT\tdemo\tpart1\ta stable check\tPASS\t\nchecks run: 2\n' > "$_lw/before.log"
printf 'RESULT\tdemo\tpart1\tthe new name\tPASS\t\nRESULT\tdemo\tpart1\ta stable check\tPASS\t\nchecks run: 2\n' > "$_lw/after.log"
_led_run merge --ledger "$_lw/ren.tsv" --date 2026-09-01 "$_lw/before.log" >/dev/null
check "premise: the check has history before the rename" \
	"$(awk -F'\t' '$3=="the old name"{print $4}' "$_lw/ren.tsv")" "2026-09-01"
check "a name that appeared while another disappeared is reported as a rename" \
	"$(_led_run rename-scan --ledger "$_lw/ren.tsv" "$_lw/after.log" \
		| grep -c 'possible rename: the old name -> the new name')" "1"
check "and the history it is about to lose travels with it" \
	"$(_led_run rename-scan --ledger "$_lw/ren.tsv" "$_lw/after.log" | grep -c 'last red 2026-09-01')" "1"
check "the stable check is not reported" \
	"$(_led_run rename-scan --ledger "$_lw/ren.tsv" "$_lw/after.log" | grep -c 'a stable check')" "0"
check "a before-log and an after-log together are refused, not silently empty" \
	"$(_led_rc rename-scan --ledger "$_lw/ren.tsv" "$_lw/before.log" "$_lw/after.log")" "2"

# Movement in ANOTHER part must not consume this part's pairing. That is what a
# global positional zip gets wrong, and it fails silently.
: > "$_lw/ren2.tsv"
printf 'RESULT\tdemo\tpartA\told A\tPASS\t\nRESULT\tdemo\tpartB\tstable B\tPASS\t\nchecks run: 2\n' > "$_lw/b2.log"
printf 'RESULT\tdemo\tpartA\tnew A\tPASS\t\nRESULT\tdemo\tpartB\tstable B\tPASS\t\nRESULT\tdemo\tpartB\tadded B\tPASS\t\nchecks run: 3\n' > "$_lw/a2.log"
_led_run merge --ledger "$_lw/ren2.tsv" --date D "$_lw/b2.log" >/dev/null
check "a rename in one part survives an addition in another" \
	"$(_led_run rename-scan --ledger "$_lw/ren2.tsv" "$_lw/a2.log" \
		| grep -c 'possible rename: old A -> new A')" "1"
check "and the addition in the other part is not called a rename" \
	"$(_led_run rename-scan --ledger "$_lw/ren2.tsv" "$_lw/a2.log" | grep -c 'added B')" "0"

# A check merely added, or merely removed, is not a rename.
printf 'RESULT\tdemo\tpart1\tthe old name\tPASS\t\nRESULT\tdemo\tpart1\ta stable check\tPASS\t\nRESULT\tdemo\tpart1\tbrand new\tPASS\t\nchecks run: 3\n' > "$_lw/added.log"
check "a check merely added is not reported as a rename" \
	"$(_led_run rename-scan --ledger "$_lw/ren.tsv" "$_lw/added.log" | grep -c 'possible rename')" "0"
printf 'RESULT\tdemo\tpart1\ta stable check\tPASS\t\nchecks run: 1\n' > "$_lw/removed.log"
check "nor is one merely removed" \
	"$(_led_run rename-scan --ledger "$_lw/ren.tsv" "$_lw/removed.log" | grep -c 'possible rename')" "0"

# ---- the gate refuses a check the ledger has never seen ---------------------

: > "$_lw/g.tsv"
_led_run merge --ledger "$_lw/g.tsv" --date D "$_lw/green.log" >/dev/null
printf 'suites_not_covered 0\n' > "$_lw/gb.txt"
check "a run whose checks are all ledgered passes the gate" \
	"$(_led_rc gate --ledger "$_lw/g.tsv" --budget "$_lw/gb.txt" --registered "$_lw/registered" "$_lw/green.log")" "0"
printf 'RESULT\tdemo\tpart1\tfirst check\tPASS\t\nRESULT\tdemo\tpart1\tsecond check\tPASS\t\nRESULT\tdemo\tpart1\tbrand new\tPASS\t\nchecks run: 3\n' > "$_lw/new.log"
check "a check the ledger has never seen is refused" \
	"$(_led_rc gate --ledger "$_lw/g.tsv" --budget "$_lw/gb.txt" --registered "$_lw/registered" "$_lw/new.log")" "1"
check "and it is named, so the author knows which one" \
	"$(_led_run gate --ledger "$_lw/g.tsv" --budget "$_lw/gb.txt" --registered "$_lw/registered" "$_lw/new.log" \
		| grep -c 'not in the ledger: demo	part1	brand new')" "1"
check "and the message says how to fix it, because regenerating is the intended action" \
	"$(_led_run gate --ledger "$_lw/g.tsv" --budget "$_lw/gb.txt" --registered "$_lw/registered" "$_lw/new.log" \
		| grep -c 'Regenerate it with')" "1"

# THE DEADLOCK THAT SHIPPED, as its own arm. Adding a check must not require an
# edit the design forbids.
_led_run merge --ledger "$_lw/g.tsv" --date D "$_lw/new.log" >/dev/null
check "regenerating the ledger lets the new check through" \
	"$(_led_rc gate --ledger "$_lw/g.tsv" --budget "$_lw/gb.txt" --registered "$_lw/registered" "$_lw/new.log")" "0"
check "and it entered as debt, not as an observation nothing made" \
	"$(awk -F'\t' '$3=="brand new"{print $4}' "$_lw/g.tsv")" "never"

# ---- the ceiling is monotone, mechanically ----------------------------------
#
# The file says the ceiling may only fall. Without this the sentence is prose:
# raising the number passed. Measured against a prior value from git rather than
# taken on trust.

check "the ceiling refuses being exceeded" \
	"$(printf 'suites_not_covered 0\n' > "$_lw/gb0.txt"
	   printf 'other\ndemo\n' > "$_lw/reg2"
	   _led_rc gate --ledger "$_lw/g.tsv" --budget "$_lw/gb0.txt" --registered "$_lw/reg2" "$_lw/new.log")" "1"

_lg="$_lw/repo"; rm -rf "$_lg"; mkdir -p "$_lg"
( cd "$_lg" && git init -q . && git config user.email t@t && git config user.name t
  printf 'suites_not_covered 5\n' > b.txt && git add b.txt && git commit -qm base ) >/dev/null 2>&1
check "premise: the scratch repo has a prior ceiling committed" \
	"$(cd "$_lg" && git show HEAD:b.txt | grep -c 'suites_not_covered 5')" "1"
printf 'suites_not_covered 9\n' > "$_lg/b.txt"
check "raising the ceiling above its committed value is refused" \
	"$(cd "$_lg" && _led_rc gate --ledger "$_lw/g.tsv" --budget b.txt \
		--registered "$_lw/registered" --against HEAD "$_lw/new.log")" "1"
check "and the refusal names both values" \
	"$(cd "$_lg" && _led_run gate --ledger "$_lw/g.tsv" --budget b.txt \
		--registered "$_lw/registered" --against HEAD "$_lw/new.log" \
		| grep -c 'was raised from 5 to 9')" "1"
printf 'suites_not_covered 3\n' > "$_lg/b.txt"
check "lowering it is allowed, which is the direction the burn-down goes" \
	"$(cd "$_lg" && _led_rc gate --ledger "$_lw/g.tsv" --budget b.txt \
		--registered "$_lw/registered" --against HEAD "$_lw/new.log")" "0"

# ---- and the RUNNER must invoke it ------------------------------------------
#
# A gate nothing runs is a comment, which is selftest 350's phrasing about its own
# subject. Nothing in the repository called this tool: zero references in
# .github/, zero in the runner. Reported by @linuxhikerpm and by OffgridwithJD
# independently.

check "the runner invokes the ledger gate" \
	"$(grep -c 'pgc_ledger.py" gate' "$_rv")" "1"
check "and it runs before the build directory is removed, which is the only place it can" \
	"$([ "$(grep -n 'pgc_ledger.py" gate' "$_rv" | cut -d: -f1)" -lt \
	    "$(grep -n 'rm -rf "\$builddir"' "$_rv" | tail -1 | cut -d: -f1)" ] && echo before || echo after)" "before"
check "and a refused gate fails the major" \
	"$(grep -A8 'pgc_ledger.py" gate' "$_rv" | grep -c 'verfail=1')" "1"

# ---- the committed files agree ----------------------------------------------

_l_total="$(grep -c . "$_ledger" || true)"
_l_red="$(awk -F'\t' '$4!="never"' "$_ledger" | grep -c . || true)"
_l_never="$(awk -F'\t' '$4=="never"' "$_ledger" | grep -c . || true)"
echo "  ledger: inputs=$_l_total | observed red=$_l_red, never=$_l_never | sum=$((_l_red + _l_never))"
check "the ledger partitions into observed and never" "$((_l_red + _l_never))" "$_l_total"
check "premise: the ledger is not empty, so the partition means something" \
	"$([ "$_l_total" -gt 0 ] && echo yes || echo no)" "yes"
check "every committed row has five fields" \
	"$(awk -F'\t' 'NF!=5' "$_ledger" | grep -c . || true)" "0"
check "and none of them ends in a tab" "$(grep -cP '\t$' "$_ledger" || true)" "0"
check "the committed census matches the committed ledger" \
	"$(sed -n 's/^checks_never_observed_red //p' "$_budget")" "$_l_never"
check "the budget names a ceiling and a census, and says which is which" \
	"$(grep -cE '^(suites_not_covered|checks_never_observed_red) [0-9]+$' "$_budget")" "2"

# ---- the gate cannot refuse a check in a suite it has never seen -------------
#
# The suite restriction is the MEANING of suites_not_covered, not a softening of
# the refusal. Without it the gate refuses every check of all 250 uncovered
# suites and reddens the whole matrix on its first run -- a gate somebody turns
# off within the week, which is the failure this issue family exists to prevent.
#
# It tightens on its own as suites are seeded, and the ceiling forces that
# direction.

printf 'RESULT\tother\tpartX\tsomething\tPASS\t\nchecks run: 1\n' > "$_lw/othersuite.log"
printf 'demo\nother\n' > "$_lw/reg_both"
printf 'suites_not_covered 1\n' > "$_lw/gb1.txt"
check "a check in an UNCOVERED suite is not refused" \
	"$(_led_rc gate --ledger "$_lw/g.tsv" --budget "$_lw/gb1.txt" --registered "$_lw/reg_both" "$_lw/othersuite.log")" "0"
check "but that suite is counted as not covered, which is the debt" \
	"$(_led_run gate --ledger "$_lw/g.tsv" --budget "$_lw/gb1.txt" --registered "$_lw/reg_both" "$_lw/othersuite.log" \
		| grep -c 'not covered=1')" "1"

# And once the suite IS covered, a new check in it is refused again -- the
# restriction tightens rather than exempting the suite forever.
_led_run merge --ledger "$_lw/g.tsv" --date D "$_lw/othersuite.log" >/dev/null
printf 'RESULT\tother\tpartX\tsomething\tPASS\t\nRESULT\tother\tpartX\tnewly added\tPASS\t\nchecks run: 2\n' > "$_lw/other2.log"
printf 'suites_not_covered 0\n' > "$_lw/gb2.txt"
check "once the suite is covered, a new check in it IS refused" \
	"$(_led_rc gate --ledger "$_lw/g.tsv" --budget "$_lw/gb2.txt" --registered "$_lw/reg_both" "$_lw/other2.log")" "1"
check "and it is the new one that is named, not the one already ledgered" \
	"$(_led_run gate --ledger "$_lw/g.tsv" --budget "$_lw/gb2.txt" --registered "$_lw/reg_both" "$_lw/other2.log" \
		| grep -c 'not in the ledger: other	partX	newly added')" "1"

# ---- the monotone check, in the REAL tree, with the REAL path ---------------
#
# The scratch-repo arms above prove the TOOL. They do not prove the WIRING, and
# the two came apart exactly the way the gate-nothing-invokes finding did one
# level down. OffgridwithJD measured it on the shipped form:
#
#   the runner's exact invocation, no --against    rc=0   the raise is not refused
#   --against HEAD, absolute path                  rc=0   "no prior ceiling to compare"
#   --against HEAD, repo-relative path             rc=1   correctly refused
#
# The middle line is the dangerous one: asked to compare, unable to compare, and
# it printed a note that reads like a pass. `git show REF:PATH` needs a
# repo-relative path, and the runner passes an absolute one inside a copied build
# directory.
#
# So the tool resolves the path itself, and every failure to resolve it is an
# ERROR rather than a shrug. These arms use the REAL budget at its real path.

_mono_budget="$PGC_TESTDIR/check_ledger_budget.txt"
_mono_reg="$_lw/mono_reg"
cut -f1 "$_ledger" | sort -u > "$_mono_reg"
_mono_log="$_lw/mono.log"
awk -F'\t' 'NR<=2 {printf "RESULT\t%s\t%s\t%s\tPASS\t\n", $1, $2, $3}' "$_ledger" > "$_mono_log"

check "premise: the real budget is inside a git repository" \
	"$(git -C "$PGC_TESTDIR" rev-parse --show-toplevel >/dev/null 2>&1 && echo yes || echo no)" "yes"
check "premise: the fixture log names checks the real ledger already knows" \
	"$(_led_rc gate --ledger "$_ledger" --budget "$_mono_budget" --registered "$_mono_reg" "$_mono_log")" "0"

# The absolute path the runner passes must WORK, not fail open.
check "an absolute budget path resolves against git rather than shrugging" \
	"$(_led_run gate --ledger "$_ledger" --budget "$_mono_budget" --registered "$_mono_reg" \
		--against HEAD "$_mono_log" | grep -c 'ceiling against HEAD')" "1"
check "and the comparison passes when the ceiling did not rise" \
	"$(_led_rc gate --ledger "$_ledger" --budget "$_mono_budget" --registered "$_mono_reg" \
		--against HEAD "$_mono_log")" "0"

# A raise in the real tracked file, at its real path, must redden.
_mono_raised="$PGC_TESTDIR/check_ledger_budget.txt.raised"
sed 's/^suites_not_covered [0-9]*$/suites_not_covered 9999/' "$_mono_budget" > "$_mono_raised"
check "premise: the raised copy really does carry a higher ceiling" \
	"$(sed -n 's/^suites_not_covered //p' "$_mono_raised")" "9999"
check "premise: and it is a file git has never seen, which is the case that used to fail open" \
	"$(git -C "$PGC_TESTDIR" show "HEAD:test/check_ledger_budget.txt.raised" >/dev/null 2>&1 && echo tracked || echo untracked)" "untracked"
check "a budget git does not know is an integrity failure, not a note" \
	"$(_led_rc gate --ledger "$_ledger" --budget "$_mono_raised" --registered "$_mono_reg" \
		--against HEAD "$_mono_log")" "2"
check "and it says it was asked to compare and could not" \
	"$(_led_run gate --ledger "$_ledger" --budget "$_mono_raised" --registered "$_mono_reg" \
		--against HEAD "$_mono_log" | grep -c 'does not exist at HEAD')" "1"
rm -f "$_mono_raised"

# And the raise itself, on the tracked path, by rewriting it in place and putting
# it back byte-exact.
_mono_orig="$_lw/budget.orig"
cp "$_mono_budget" "$_mono_orig"
sed -i 's/^suites_not_covered [0-9]*$/suites_not_covered 9999/' "$_mono_budget"
_mono_rc="$(_led_rc gate --ledger "$_ledger" --budget "$_mono_budget" --registered "$_mono_reg" \
	--against HEAD "$_mono_log")"
_mono_out="$(_led_run gate --ledger "$_ledger" --budget "$_mono_budget" --registered "$_mono_reg" \
	--against HEAD "$_mono_log" | grep -c 'was raised from')"
cp "$_mono_orig" "$_mono_budget"
check "raising the ceiling in the tracked file is refused" "$_mono_rc" "1"
check "and the refusal names the raise" "$_mono_out" "1"
check "premise: the budget was restored byte-exact" \
	"$(cmp -s "$_mono_orig" "$_mono_budget" && echo same || echo CHANGED)" "same"

# ---- and the RUNNER must pass --against, or none of the above is wired -------

# The ref is a variable, chosen above the call and pinned by the three arms at
# the end of this part. What matters here is that the call site passes one at all:
# without --against the monotone block never runs, which is how the tool was right
# and the wiring was not.
check "the runner passes --against to the gate" \
	"$(grep -A5 'pgc_ledger.py" gate' "$_rv" | grep -c -- '--against')" "1"

# ---- and WHICH ref the runner compares against is a decision, not a default --
#
# `--against HEAD` compares a committed file against itself: for any change that
# is already committed, the working budget and HEAD's are identical, so it catches
# only an UNCOMMITTED raise. The property that matters is that a branch may not
# raise the ceiling relative to MAIN, which needs origin/main as the ref.
#
# The runner therefore chooses, and prints the choice when it falls back. A silent
# fallback to the weaker ref would be a gate quietly enforcing less than it says,
# which is the shape this whole change exists to refuse.

check "the runner prefers origin/main as the ceiling's reference" \
	"$(grep -c '_led_ref=origin/main' "$_rv")" "1"
check "and falls back to HEAD only after saying so" \
	"$(grep -A3 '_led_ref=HEAD' "$_rv" | grep -c 'catches an uncommitted raise only')" "1"
check "and the gate is given that ref rather than a literal" \
	"$(grep -c -- '--against "\$_led_ref"' "$_rv")" "1"
