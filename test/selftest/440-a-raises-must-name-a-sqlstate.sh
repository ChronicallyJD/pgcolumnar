# ---- a broad pytest.raises must name a SQLSTATE, and hold one statement ------
#
# WHY THIS EXISTS. `pytest.raises(psycopg.Error)` claims that one of 254 SQLSTATEs
# arrived, across 42 SQLSTATE classes -- counted against psycopg 3.3.5 by asking
# how many classes in `psycopg.errors` carry a `sqlstate` and subclass that family.
# It does not claim even that much. Measured on the corpus before the guard landed:
#
#     with pytest.raises(psycopg.Error):
#         conn = psycopg.connect("host=/nonexistent-socket-dir dbname=pgc")
#         conn.execute("SELECT pgc_definitely_no_such_function()")
#     expect.num(1, 1, "the server rejected the call")
#
# reported `1 passed`, exit 0. What satisfied it was OperationalError with sqlstate
# None: the connect failed, nothing reached a server, and the statement the test is
# about never executed. Against a live PostgreSQL 18.4 the same shape raised
# InvalidName 42602 from the SETUP line while the statement under test raises
# UndefinedObject 42704 -- two different SQLSTATEs, one raises, one green test.
#
# So the layer refuses two things, and this part asserts both are still there:
# a broad family with no SQLSTATE pinned, and a block holding more than one
# statement whatever its class.
#
# THE TWO RULES CLOSE DIFFERENT AMOUNTS, and the arms below pin the asymmetry as
# well as the rules. The first CLOSES raises-too-broad. The second only MITIGATES
# raises-catches-setup, because it counts TOP-LEVEL statements: a call to a helper
# that performs the setup is one statement, and so is a `for` holding the setup and
# the statement under test. Those two shapes walk straight past it. So this part
# also requires the two arms that PIN the blind spots, and requires
# VACUITY_MODES.md to still list raises-catches-setup as open -- a guard that
# quietly grew into a claim of completeness is the failure being prevented.
#
# WHY THE CHECKS ARE STATIC, the same division as selftest 360 and 370. The
# behaviour is pinned by the arms in test/pytest/test_raises_sqlstate.py that
# run pytest inside pytest; those need pytest, psycopg and a virtualenv, and CI
# installs none of them. This half asserts the STRUCTURE they rest on, greppable
# from a checkout with nothing installed.
#
# THE TWO-COPY ARMS ARE THE POINT. Each offence string is written twice in
# pgc_vacuity.py: once where the scan PRODUCES it and once where the message
# assembly FILTERS for it. If those drift, the offence is still collected and
# produces no message, so the run is refused with an empty reason -- a guard that
# fires and says nothing. The phrase also has to survive on ONE source line: the
# producer was first split as `"... names no "` + `"SQLSTATE"`, which reads
# identically at runtime and made the arm below count 1 where it wanted 2.

_rq_vac="$PGC_TESTDIR/pytest/pgc_vacuity.py"
_rq_tst="$PGC_TESTDIR/pytest/test_raises_sqlstate.py"
_rq_doc="$PGC_TESTDIR/pytest/TESTS.md"

check "premise: the pytest layer is where the broad-raises part thinks it is" \
	"$([ -f "$_rq_vac" ] && echo yes || echo no)" "yes"

check "premise: the suite that pins the behaviour is where this part thinks it is" \
	"$([ -f "$_rq_tst" ] && echo yes || echo no)" "yes"

# ---- the broad list, read out of the file rather than restated here ----------
#
# A check that rewrites the list tests this file against itself: both copies could
# drift together and it would still pass. This parses the tuple and compares the
# NAMES, so adding a family is a deliberate edit here as well as there.
#
# THE LIST IS BOUND INSIDE THE SCAN, NOT AT MODULE LEVEL, so the pattern is
# indented. That placement is load-bearing rather than cosmetic: every conftest.py
# under test/pytest/ is imported before collection, so a module-level tuple is
# writable from the corpus the rule polices --
#
#     import pgc_vacuity
#     pgc_vacuity.<the tuple> = ()
#
# -- after which the scan reports zero offences for ever and the suite is green
# with the guard switched off. The arm after this one requires the name to be
# absent at module level, which is the half a reader would otherwise assume.
_rq_broad="$(sed -n 's/^[[:space:]]\{4\}broad_families = (\(.*\))[[:space:]]*$/\1/p' \
	"$_rq_vac" | tr -d ' "' | head -1)"

check "premise: the layer states a broad-family list this part could read" \
	"$([ -n "$_rq_broad" ] && echo yes || echo no)" "yes"

check "the broad list is exactly the four families that name no SQLSTATE" \
	"$_rq_broad" "Error,DatabaseError,Exception,BaseException"

# A rule's own parameters must not be reachable from the tree the rule polices.
# Any module-level binding of this list is one importable line away from being
# emptied, so the name must not appear at column zero at all.
check "and the list is not a module global a conftest could empty" \
	"$(grep -cE '^[A-Za-z_]*[Bb][Rr][Oo][Aa][Dd][A-Za-z_]*[[:space:]]*=' "$_rq_vac")" "0"

# Warning and InterfaceError cover ZERO SQLSTATEs, measured, so demanding one of
# them would be a guard nobody could satisfy. An unsatisfiable guard is how a
# guard gets switched off, so their ABSENCE is load-bearing and gets an arm.
check "and it does not demand a SQLSTATE of a family that has none" \
	"$(printf '%s' "$_rq_broad" | grep -cE 'Warning|InterfaceError')" "0"

# ---- the scan itself ---------------------------------------------------------

check "the layer carries the raises scan" \
	"$(grep -c '^def _raises_sites(' "$_rq_vac")" "1"

# PARSED, NOT GREPPED. test_raises_sqlstate.py writes the refused shape inside a
# pytester.makepyfile string in every one of its arms, so a line regex refuses the
# file that proves the guard -- the false positive the broad-except scan paid for
# once already (#905 era). The scan's body must reach ast.parse and must not reach
# for a regex.
_rq_body="$(awk '/^def _raises_sites\(/{f=1} f&&/^def /&&!/_raises_sites/{exit} f' \
	"$_rq_vac")"

check "premise: the scan's body was actually cut out of the file" \
	"$([ "$(printf '%s\n' "$_rq_body" | wc -l)" -ge 20 ] && echo yes || echo "too short")" "yes"

check "the scan parses the file with ast rather than matching lines" \
	"$(printf '%s\n' "$_rq_body" | grep -c 'ast\.parse')" "1"

check "and reaches for no regex, which cannot tell code from a string literal" \
	"$(printf '%s\n' "$_rq_body" | grep -c 're\.')" "0"

# The first half: a broad family with nothing pinned.
check "the scan keeps the arm that refuses a broad family with no SQLSTATE" \
	"$(printf '%s\n' "$_rq_body" | grep -c 'bound not in pinned')" "1"

# The second half: raises-catches-setup. Narrow and pinned is still vacuous when
# the block holds the setup that raised.
check "the scan keeps the arm that refuses more than one statement in the block" \
	"$(printf '%s\n' "$_rq_body" | grep -c 'len(node.body) != 1')" "1"

# A TUPLE IS THE SHAPE PEOPLE ACTUALLY WRITE, and it is how a narrow claim gets
# widened under pressure. @jdatcmd found exactly this hole in the broad-except
# scan: `except Exception` refused, `except (ValueError, Exception)` passed.
check "a tuple member is read, so a broad class cannot hide inside one" \
	"$(grep -c 'arg.elts if isinstance(arg, ast.Tuple)' "$_rq_vac")" "1"

# ---- and the scan has to be WIRED, or it is a function nobody calls ----------
check "the collection hook calls the scan" \
	"$(grep -c 'offenders.extend(_raises_sites(f))' "$_rq_vac")" "1"

# Each offence string exists twice: produced by the scan, then filtered for by the
# message assembly. Drift leaves the offence collected with no message, so the run
# is refused with an empty reason. Counted PER REGION rather than over the file, so
# a third mention somewhere else is not a false red -- a guard that reddens on
# growth gets switched off.
_rq_hook="$(awk '/^def pytest_collection_modifyitems\(/{f=1} f' "$_rq_vac")"

check "premise: the collection hook's body was cut out of the file" \
	"$([ "$(printf '%s\n' "$_rq_hook" | wc -l)" -ge 20 ] && echo yes || echo "too short")" "yes"

check "the scan produces the broad-family offence" \
	"$(printf '%s\n' "$_rq_body" | grep -cF 'names no SQLSTATE')" "1"

check "and the message assembly filters for that same spelling" \
	"$(printf '%s\n' "$_rq_hook" | grep -cF 'names no SQLSTATE')" "1"

check "the scan produces the setup-in-the-block offence" \
	"$(printf '%s\n' "$_rq_body" | grep -cF 'which one raised is not pinned')" "1"

check "and the message assembly filters for that spelling too" \
	"$(printf '%s\n' "$_rq_hook" | grep -cF 'which one raised is not pinned')" "1"

# ---- expect.sqlstate, the honest form the refusal points at ------------------
check "the layer carries the SQLSTATE assertion itself" \
	"$(grep -c 'def sqlstate(self, exc, want, name)' "$_rq_vac")" "1"

check "and a SQLSTATE is validated as five characters rather than trusted" \
	"$(grep -c '^def _is_sqlstate(v)' "$_rq_vac")" "1"

check "it refuses an empty set of codes, so the tuple hatch is not the hole" \
	"$(grep -cF 'an empty set of SQLSTATEs is satisfied by nothing' "$_rq_vac")" "1"

check "it refuses an object with no sqlstate, which is exc instead of exc.value" \
	"$(grep -cF 'carries no sqlstate' "$_rq_vac")" "1"

check "and a psycopg error carrying no SQLSTATE fails rather than comparing" \
	"$(grep -cF 'carrying no SQLSTATE' "$_rq_vac")" "1"

# ---- the residual is a measurement, not a sentence --------------------------
#
# raises-catches-setup is MITIGATED by the statement count, not closed. Two shapes
# walk past it, and each has an arm asserting the scan reports NOTHING on it. An
# arm that pins a known blind spot is what stops the blind spot from being
# rediscovered as a bug, so their ABSENCE is a failure here.
check "the suite pins the helper-call blind spot the statement rule cannot see" \
	"$(grep -c '^def test_a_helper_hiding_the_setup_is_not_refused(' "$_rq_tst")" "1"

check "and pins the compound-statement blind spot as well" \
	"$(grep -c '^def test_a_compound_statement_hiding_the_setup_is_not_refused(' \
		"$_rq_tst")" "1"

# The scan's own docstring has to name both shapes, because the next person to read
# the guard is the one who would otherwise assume the sibling mode is handled.
check "the scan's docstring names the helper shape it cannot see" \
	"$(grep -cF 'a call to a helper that performs the setup counts' "$_rq_vac")" "1"

# A backtick needs no escape inside single quotes -- bash does no escape
# processing there, so `\`` was a literal backslash in the pattern and matched
# nothing while reporting a clean 0.
check "and names the compound statement it cannot see either" \
	"$(grep -cF 'a single `for` or `if` holding several' "$_rq_vac")" "1"

# And the document must still call the mode OPEN. A guard that grew into a claim of
# completeness is exactly what this arm is for.
_rq_vm="$PGC_TESTDIR/pytest/VACUITY_MODES.md"

check "premise: the vacuity-mode document is where this part thinks it is" \
	"$([ -f "$_rq_vm" ] && echo yes || echo no)" "yes"

check "raises-catches-setup is still listed as a mode this layer does NOT refuse" \
	"$([ "$(grep -c 'raises-catches-setup' "$_rq_vm")" -ge 1 ] && echo listed || echo gone)" \
	"listed"

# The conftest arm is the one that proves the placement above is load-bearing.
check "the suite pins that a conftest cannot switch the family list off" \
	"$(grep -c '^def test_a_conftest_cannot_switch_the_broad_family_list_off(' \
		"$_rq_tst")" "1"

# ---- the suite and the document ---------------------------------------------
#
# The red test VACUITY_MODES.md section 5 item 4 named, by name. A guard whose red
# test was renamed away is a guard with no subject.
check "the named red test exists in the corpus" \
	"$(grep -c '^def test_raises_requires_a_sqlstate(' "$_rq_tst")" "1"

# Every test in the new file has to be named in TESTS.md. The pytest corpus gates
# this too; this copy is the one that runs where pytest is not installed.
_rq_n="$(grep -c '^def test_' "$_rq_tst")"
check "premise: the suite defines tests at all, so the sweep is not empty" \
	"$([ "$_rq_n" -ge 10 ] && echo yes || echo "$_rq_n")" "yes"

_rq_named=0
for _rq_t in $(sed -n 's/^def \(test_[A-Za-z0-9_]*\)(.*/\1/p' "$_rq_tst"); do
	grep -qF "\`$_rq_t\`" "$_rq_doc" && _rq_named=$((_rq_named + 1))
done
check "every test in the suite is named in TESTS.md" "$_rq_named" "$_rq_n"

check "and TESTS.md names the file as well" \
	"$([ "$(grep -cF 'test_raises_sqlstate.py' "$_rq_doc")" -ge 1 ] && echo yes || echo no)" \
	"yes"

# ---- and these greps must be able to FAIL -----------------------------------
#
# Every arm above passes on a healthy tree, which a grep that matches nothing also
# does. Each fixture below is the real shape with EXACTLY ONE property removed, and
# the mirror arm re-runs the same pattern on the real file so a zero means a missing
# guard rather than a broken pattern.

_rq_fix="$PGC_WORKDIR/raisessqlstate"; rm -rf "$_rq_fix"; mkdir -p "$_rq_fix"

# 1. The broad list emptied: the refusal is present and fires on nothing.
printf '    broad_families = ()\n' > "$_rq_fix/emptylist.py"
_rq_e="$(sed -n 's/^[[:space:]]\{4\}broad_families = (\(.*\))[[:space:]]*$/\1/p' \
	"$_rq_fix/emptylist.py" | tr -d ' "' | head -1)"
check "an emptied broad list is visible rather than absorbed" \
	"$([ "$_rq_e" = "Error,DatabaseError,Exception,BaseException" ] \
		&& echo same || echo "differs:[$_rq_e]")" "differs:[]"

# 2. The same list widened to a family that can never carry a SQLSTATE. The arm
#    that forbids it must notice, or the guard becomes unsatisfiable quietly.
printf '    broad_families = ("Error", "Warning")\n' > "$_rq_fix/widened.py"
_rq_w="$(sed -n 's/^[[:space:]]\{4\}broad_families = (\(.*\))[[:space:]]*$/\1/p' \
	"$_rq_fix/widened.py" | tr -d ' "' | head -1)"
check "a list widened to a zero-SQLSTATE family is caught" \
	"$(printf '%s' "$_rq_w" | grep -cE 'Warning|InterfaceError')" "1"

# 2b. The same list hoisted back to module level, which is where a conftest can
#     reach it. The arm that forbids a module-level binding has to notice, and the
#     INDENTED pattern must stop matching -- a fixture that failed both ways would
#     not tell the two arms apart.
printf 'broad_families = ("Error", "DatabaseError", "Exception", "BaseException")\n' \
	> "$_rq_fix/hoisted.py"
check "a list hoisted to module level is caught" \
	"$(grep -cE '^[A-Za-z_]*[Bb][Rr][Oo][Aa][Dd][A-Za-z_]*[[:space:]]*=' \
		"$_rq_fix/hoisted.py")" "1"

check "premise: and the indented pattern no longer finds it there" \
	"$(sed -n 's/^[[:space:]]\{4\}broad_families = (\(.*\))[[:space:]]*$/\1/p' \
		"$_rq_fix/hoisted.py" | wc -l)" "0"

check "premise: while the real file binds it indented, where no conftest reaches" \
	"$([ -n "$_rq_broad" ] && echo indented || echo missing)" "indented"

# 3. The broad arm neutered, the rest of the scan intact.
printf '        if False and broad and (bound is None or b not in p):\n' \
	> "$_rq_fix/nobroad.py"
check "a neutered broad-family arm is caught" \
	"$(grep -c 'bound not in pinned' "$_rq_fix/nobroad.py")" "0"

# 4. The statement-count arm neutered.
printf '            if sites and len(node.body) >= 1:\n' > "$_rq_fix/nosetup.py"
check "a neutered statement-count arm is caught" \
	"$(grep -c 'len(node.body) != 1' "$_rq_fix/nosetup.py")" "0"

# 5. The tuple read dropped, so a broad member hides inside a tuple.
printf '    for node in [arg]:\n' > "$_rq_fix/notuple.py"
check "a dropped tuple read is caught" \
	"$(grep -c 'arg.elts if isinstance(arg, ast.Tuple)' "$_rq_fix/notuple.py")" "0"

# 6. The scan unwired: present, called by nobody.
printf '            offenders.extend(_sorted_ordered_sites(f))\n' > "$_rq_fix/unwired.py"
check "an unwired scan is caught" \
	"$(grep -c 'offenders.extend(_raises_sites(f))' "$_rq_fix/unwired.py")" "0"

# 7. The two copies of one offence string, drifted. Produced one way, filtered
#    another: the offence is collected and the message comes out empty.
{
	printf 'def _raises_sites(path):\n'
	printf '    out.append(f"{name} pytest.raises({b}) names no SQLSTATE")\n'
	printf 'def pytest_collection_modifyitems(config, items):\n'
	printf '    broad = [o for o in offenders if "names no sqlstate" in o]\n'
} > "$_rq_fix/drifted.py"
_rq_dh="$(awk '/^def pytest_collection_modifyitems\(/{f=1} f' "$_rq_fix/drifted.py")"
check "a drifted offence string is caught by the filter-side arm" \
	"$(printf '%s\n' "$_rq_dh" | grep -cF 'names no SQLSTATE')" "0"

check "premise: while the producer side of that same fixture does carry it" \
	"$(grep -cF 'names no SQLSTATE' "$_rq_fix/drifted.py")" "1"

# 8. The phrase split across two source lines. Identical at runtime, invisible to
#    the arm above -- the correction this part already needed once.
{
	printf 'def _raises_sites(path):\n'
	printf '    out.append(f"{name} pytest.raises({b}) names no "\n'
	printf '               f"SQLSTATE")\n'
	printf 'def pytest_collection_modifyitems(config, items):\n'
	printf '    broad = [o for o in offenders if "names no SQLSTATE" in o]\n'
} > "$_rq_fix/split.py"
_rq_sp="$(awk '/^def _raises_sites\(/{f=1} f&&/^def /&&!/_raises_sites/{exit} f' \
	"$_rq_fix/split.py")"
check "a producer split across two lines is caught by the producer-side arm" \
	"$(printf '%s\n' "$_rq_sp" | grep -cF 'names no SQLSTATE')" "0"

# 9. A line-regex scan: it would match the forbidden shape inside a string, which
#    is what every arm of the real suite writes. The arm that forbids `re.` inside
#    the scan has to notice.
# grep -c counts LINES, not occurrences: the first spelling of this fixture put
# both uses of `re.` on one line and the arm counted 1 where it wanted 2. Two
# lines, so the count is a count of what the arm claims to count.
{
	printf 'def _raises_sites(path):\n'
	printf '    import re\n'
	printf '    _rx = re.compile(r"pytest[.]raises")\n'
	printf '    return [l for l in path.read_text().splitlines() if re.search(_rx, l)]\n'
	printf 'def _next(): pass\n'
} > "$_rq_fix/regexscan.py"
_rq_rb="$(awk '/^def _raises_sites\(/{f=1} f&&/^def /&&!/_raises_sites/{exit} f' \
	"$_rq_fix/regexscan.py")"
check "a regex-based scan is caught" \
	"$(printf '%s\n' "$_rq_rb" | grep -c 're\.')" "2"

check "premise: and the same awk cut finds no regex in the real scan" \
	"$(printf '%s\n' "$_rq_body" | grep -c 're\.')" "0"

# 10. expect.sqlstate with its want validation removed, so "42" would pass.
printf '    def sqlstate(self, exc, want, name):\n' > "$_rq_fix/novalidate.py"
check "a sqlstate helper with no five-character check is caught" \
	"$(grep -c '^def _is_sqlstate(v)' "$_rq_fix/novalidate.py")" "0"

# 11. A test file whose tests are not in the document. The sweep must count the
#     shortfall rather than report every name as documented.
printf 'def test_wg440_not_in_any_document(expect):\n    pass\n' \
	> "$_rq_fix/undocumented.py"
_rq_fn="$(grep -c '^def test_' "$_rq_fix/undocumented.py")"
_rq_fnamed=0
for _rq_t in $(sed -n 's/^def \(test_[A-Za-z0-9_]*\)(.*/\1/p' "$_rq_fix/undocumented.py"); do
	grep -qF "\`$_rq_t\`" "$_rq_doc" && _rq_fnamed=$((_rq_fnamed + 1))
done
check "an undocumented test is counted short rather than passed over" \
	"$_rq_fnamed/$_rq_fn" "0/1"

check "premise: while the real suite's own names are all found by that same sweep" \
	"$_rq_named/$_rq_n" "$_rq_n/$_rq_n"

# 12. A suite with the residual arms deleted. The blind spot would then be
#     undocumented AND unpinned, which is how a known gap returns as a surprise.
printf 'def test_a_helper_hiding_the_setup_is_NOT_here(expect):\n\tpass\n' \
	> "$_rq_fix/noresidual.py"
check "a suite missing the helper blind-spot arm is caught" \
	"$(grep -c '^def test_a_helper_hiding_the_setup_is_not_refused(' \
		"$_rq_fix/noresidual.py")" "0"

check "premise: while the real suite carries it" \
	"$(grep -c '^def test_a_helper_hiding_the_setup_is_not_refused(' "$_rq_tst")" "1"

# 13. A document that stopped listing the mode as open, which is the failure the
#     document arm exists for: the guard claiming more than it closes.
printf 'Nothing here mentions the sibling mode at all.\n' > "$_rq_fix/nomode.md"
check "a document that stopped calling the mode open is caught" \
	"$([ "$(grep -c 'raises-catches-setup' "$_rq_fix/nomode.md")" -ge 1 ] \
		&& echo listed || echo gone)" "gone"

unset _rq_vac _rq_tst _rq_doc _rq_vm _rq_broad _rq_body _rq_hook _rq_fix _rq_e \
	_rq_w _rq_n _rq_named _rq_t _rq_rb _rq_dh _rq_sp _rq_fn _rq_fnamed
