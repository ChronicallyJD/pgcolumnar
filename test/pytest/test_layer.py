"""The vacuity-refusal layer, tested before it exists.

Every test here asserts that the layer REFUSES something bare pytest accepts.
Measured on pytest 9.1.1, all eight of the modes below exit 0 with no plugin
loaded, which is why each test asserts on the INNER run's outcome rather than on
its own arithmetic.
"""


def test_layer_rejects_a_test_with_no_assertion(pytester, expect):
    """A test body that concludes nothing must fail, not pass.

    Bare pytest: `1 passed`, exit 0. Measured.
    """
    pytester.makeconftest("pytest_plugins = ['pgc_vacuity']")
    pytester.makepyfile(
        """
        def test_asserts_nothing():
            x = 1 + 1
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "inner run outcomes", failed=1, passed=0)
    result.stdout.fnmatch_lines(["*made no counted assertion*"])


def test_a_counted_assertion_passes(pytester, expect):
    """The positive control. A guard that rejects good tests gets switched off.

    This must pass for the same plugin that fails the test above.
    """
    pytester.makepyfile(
        """
        def test_concludes_something(expect):
            expect.num(2 + 2, 4, "arithmetic still works")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "inner run outcomes", passed=1, failed=0)


def test_layer_rejects_two_empty_results(pytester, expect):
    """Empty compared with empty is the defect that produced issue #418.

    Bare pytest: `2 passed`, exit 0. Measured.
    """
    pytester.makepyfile(
        """
        def test_empty_vs_empty(expect):
            got, want = [], []
            expect.rows(got, want, "two empty results")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "inner run outcomes", failed=1, passed=0)
    result.stdout.fnmatch_lines(["*both sides are empty*"])


def test_layer_allows_an_empty_result_when_declared(pytester, expect):
    """An empty result is a legitimate expectation when the test says so.

    After a bare TRUNCATE the correct end state IS an empty projection, so this
    escape hatch has to exist. It requires a reason, so it cannot become the
    default by being easier to type.
    """
    pytester.makepyfile(
        """
        def test_empty_is_the_point(expect):
            expect.rows([], [], "empty after truncate", allow_empty="table was truncated")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "inner run outcomes", passed=1, failed=0)


def test_layer_rejects_a_self_comparison(pytester, expect):
    """Comparing a value against itself cannot fail, so it asserts nothing."""
    pytester.makepyfile(
        """
        def test_hash_against_itself(expect):
            h = "d41d8cd98f00b204e9800998ecf8427e"
            expect.hash(h, h, "oracle against itself")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "inner run outcomes", failed=1, passed=0)
    result.stdout.fnmatch_lines(["*compared against itself*"])


def test_layer_rejects_a_substring_plan_match(pytester, expect):
    """`"ColumnarScan" in plan` is exactly as wrong as `grep ColumnarScan`.

    The measured provider name is `PgColumnarScan`, so the substring passes while
    asserting the wrong thing. The helper takes a typed field and exact equality.
    """
    pytester.makepyfile(
        """
        PLAN = [{"Plan": {"Node Type": "Aggregate", "Plans": [
                    {"Node Type": "Custom Scan",
                     "Custom Plan Provider": "PgColumnarScan"}]}}]

        def test_substring_is_refused(expect):
            expect.plan_node(PLAN, provider="ColumnarScan")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "inner run outcomes", failed=1, passed=0)
    result.stdout.fnmatch_lines(["*no node whose*"])


def test_layer_matches_the_exact_provider(pytester, expect):
    """The positive control for the plan helper: the real name must match."""
    pytester.makepyfile(
        """
        PLAN = [{"Plan": {"Node Type": "Aggregate", "Plans": [
                    {"Node Type": "Custom Scan",
                     "Custom Plan Provider": "PgColumnarScan"}]}}]

        def test_exact_provider(expect):
            expect.plan_node(PLAN, provider="PgColumnarScan")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "inner run outcomes", passed=1, failed=0)


def test_layer_rejects_a_bare_skip(pytester, expect):
    """A bare skip exits 0 and reports success. Measured: `2 skipped`, exit 0.

    A skip has to name a reason from the closed list, so a suite cannot quietly
    stop testing anything.
    """
    pytester.makepyfile(
        """
        import pytest
        @pytest.mark.skip(reason="not today")
        def test_quietly_gone():
            assert False
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(result, "a bare skip must not produce a zero exit")
    # A UsageError is written to stderr, not stdout. Asserting on the wrong stream
    # would have made this test pass on ret alone, which any collection error also
    # satisfies -- so the message assertion is what makes it honest.
    result.stderr.fnmatch_lines(["*bare skip*"])


def test_layer_fails_on_a_collected_count_mismatch(pytester, expect):
    """A filtered or truncated run must not be green.

    Measured: `-k` that matches nothing exits 5, and 5 is routinely treated as
    acceptable by wrappers. Collecting fewer tests than expected is the same
    accident with a zero exit, so the layer compares collected against expected.
    """
    pytester.makepyfile(
        """
        def test_one(expect): expect.num(1, 1, "one")
        def test_two(expect): expect.num(2, 2, "two")
        """
    )
    good = pytester.runpytest("-p", "pgc_vacuity", "--pgc-expect-tests", "2")
    expect.outcomes(good, "the honest run is green", passed=2, failed=0)

    short = pytester.runpytest("-p", "pgc_vacuity", "--pgc-expect-tests", "2",
                               "-k", "test_one")
    expect.run_failed(short, "a run that collected fewer than expected must fail")
    # stderr, not stdout: a UsageError is written there. Getting this wrong twice
    # while building the layer is why every message assertion here names its stream.
    short.stderr.fnmatch_lines(["*collected 1 test*expected 2*"])


def test_layer_refuses_a_zero_expectation(pytester, expect):
    """--pgc-expect-tests 0 would make the guard vacuous, so it is refused."""
    pytester.makepyfile("def test_one(expect): expect.num(1, 1, 'one')")
    result = pytester.runpytest("-p", "pgc_vacuity", "--pgc-expect-tests", "0")
    expect.run_failed(result, "an expectation of zero asserts nothing")


# ---------------------------------------------------------------------------
# THE THIRD STATE. `cannot_run` declared a test unrunnable and the run reported
# it as a PASS, exit 0: `self.unrunnable` was written and read nowhere. That is
# a write-only field, the same shape selftest 320 polices in the runner ("no
# write-only failure flag survives"), and it made the layer's own escape hatch
# the largest vacuity hole in it -- a bare skip FAILS the run, while the
# supposedly honest alternative greened silently.
#
# lib.sh has kept this state honest since #418: an unrunnable check counts
# toward checks run, is reported separately, and the suite exits
# PGC_EXIT_INCOMPLETE (67) so no runner can call it a pass. These four arms are
# the pytest mirror of selftest 320's four, including which state dominates.


def test_an_unrunnable_test_does_not_leave_the_run_green(pytester, expect):
    """The defect itself. Measured before the fix: `1 passed`, exit 0."""
    pytester.makeconftest("pytest_plugins = ['pgc_vacuity']")
    pytester.makepyfile(
        """
        def test_cannot(expect):
            expect.cannot_run("ABSENT_FIXTURE", "the parquet corpus was not built")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.num(result.ret, 67, "an unrunnable test exits INCOMPLETE, not 0")


def test_an_unrunnable_test_names_its_reason_and_its_detail(pytester, expect):
    """A third state that does not say why is a skip with better manners.

    The reason travels with the state, exactly as lib.sh prints
    `UNRUN  <name>: <REASON>: <detail>`.
    """
    pytester.makeconftest("pytest_plugins = ['pgc_vacuity']")
    pytester.makepyfile(
        """
        def test_cannot(expect):
            expect.cannot_run("ABSENT_FIXTURE", "the parquet corpus was not built")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    result.stdout.fnmatch_lines(
        ["*UNRUN*test_cannot*ABSENT_FIXTURE*the parquet corpus was not built*"])
    expect.num(result.ret, 67, "and it is still not a pass")


def test_a_real_failure_outranks_an_unrunnable_test(pytester, expect):
    """Which state dominates, asserted rather than left to fall out.

    lib.sh: a suite with both a FAIL and an UNRUN is FAILED, because the failure
    is the more urgent fact. Exit 1, not 67.
    """
    pytester.makeconftest("pytest_plugins = ['pgc_vacuity']")
    pytester.makepyfile(
        """
        def test_cannot(expect):
            expect.cannot_run("ABSENT_FIXTURE", "no corpus")
        def test_fails(expect):
            expect.num(1, 2, "one is not two")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.num(result.ret, 1, "a failure outranks an unrunnable test")


def test_a_run_with_nothing_unrunnable_still_exits_zero(pytester, expect):
    """Control. A guard that reddens a healthy run gets switched off, and then
    the guard it replaced is gone too."""
    pytester.makeconftest("pytest_plugins = ['pgc_vacuity']")
    pytester.makepyfile(
        """
        def test_ok(expect):
            expect.num(2 + 2, 4, "arithmetic still works")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.num(result.ret, 0, "an ordinary green run is untouched")


def test_layer_rejects_psycopgs_no_count_sentinel(pytester, expect):
    """cursor.rowcount is -1 when no count is available, and 1 for an unfetched
    SELECT. Both are numbers, so expect.num compares them happily."""
    pytester.makepyfile(
        """
        def test_rowcount_sentinel(expect):
            expect.rowcount(-1, -1, "a count that is not a count")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "the -1 sentinel is refused", failed=1, passed=0)
    result.stdout.fnmatch_lines(["*no row count available*"])


def test_layer_rejects_a_broad_except_in_a_test_file(pytester, expect):
    """The layer forbade this in a comment, which enforces nothing.

    After any failed statement psycopg raises InFailedSqlTransaction for every
    later one, so one `except Exception` hides the real error and all its
    successors. Measured: a test using the forbidden shape passed with no complaint.
    """
    pytester.makepyfile(
        """
        def test_swallows(expect):
            try:
                raise RuntimeError("the real failure")
            except Exception:
                pass
            expect.num(1, 1, "and then asserts something harmless")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(result, "a broad except must not be collectable")
    result.stderr.fnmatch_lines(["*catches Exception broadly*"])

# ---- an A/B whose arms do not differ measures nothing -------------------------
#
# `mutation-arm-unobservable` in VACUITY_MODES.md section 3.5: both arms of an A/B
# produce the identical answer and both are green, because the assertion that would
# catch it -- that the arms must DIFFER -- is the one nobody writes.
#
# Measured before building: the layer had EIGHT helpers asserting equality and ONE
# asserting inequality, `ordering_observable`, which is specific to a forward/reverse
# pair. Two sites in the corpus hand-rolled the general case as
# `expect.num(int(after != before), 1, ...)`, which throws both values away: when it
# fails it says `got 0 want 1` and the reader cannot see what the two arms were.


def test_layer_requires_ab_arms_to_differ(pytester, expect):
    """Two arms that agree cannot show that the thing between them did anything.

    Bare pytest: the test passes, because nothing was asserted about the pair.
    """
    pytester.makeconftest("pytest_plugins = ['pgc_vacuity']")
    pytester.makepyfile(
        """
        def test_the_mutation_changed_nothing(expect):
            baseline = [(1, 'a'), (2, 'b')]
            mutated = [(1, 'a'), (2, 'b')]
            expect.differ(baseline, mutated, "the mutation moved the result")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    # `expect.refusal` rather than `fnmatch_lines`, and one token per call. The raw
    # matcher searches the inner run's WHOLE stdout, and pytest prints the failing
    # function's SOURCE in the traceback -- so a pattern naming a value in the test
    # matches the source line rather than anything the guard produced. The arm below
    # passed that way before this change, against a layer with no `differ` at all.
    expect.refusal(result, "two identical arms do not pass", r"arms-do-not-differ")


def test_differ_names_both_arms_when_they_agree(pytester, expect):
    """The hand-rolled idiom this replaces printed `got 0 want 1`.

    A reader of that cannot tell whether the arms were both empty, both wrong, or
    correctly identical -- which is three different defects with one message.
    """
    pytester.makepyfile(
        """
        def test_identical_arms(expect):
            expect.differ("PLAN-A", "PLAN-A", "the GUC changed the plan")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    # ANCHORED, because the value is written in the test body: with `fnmatch_lines`
    # this arm passed against an AttributeError from a `differ` that did not exist,
    # satisfied by its own source printed in the traceback. Measured, not reasoned.
    expect.refusal(result, "the refusal names the value both arms carried", r"PLAN-A")
    expect.refusal(result, "and names the mode", r"arms-do-not-differ")


def test_differ_passes_when_the_arms_differ(pytester, expect):
    """The positive control. A guard that rejects real A/B tests gets switched off."""
    pytester.makepyfile(
        """
        def test_arms_differ(expect):
            expect.differ([(1,), (2,)], [(2,), (1,)], "reversing changes the order")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "differing arms pass", passed=1, failed=0)


def test_differ_counts_as_an_assertion(pytester, expect):
    """A test whose only assertion is `differ` has concluded something.

    Without this the no-assertion guard fires instead, and the arm above would pass
    for the wrong reason -- a failure, but not the one it names.
    """
    pytester.makepyfile(
        """
        def test_only_a_differ(expect):
            expect.differ(1, 2, "one is not two")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "differ alone is a counted assertion", passed=1, failed=0)


def test_differ_refuses_a_failed_query_on_either_side(pytester, expect):
    """TWO FAILED QUERIES ARE NOT TWO OBSERVABLE ARMS, and this is the inverse of the
    trap #930 closed.

    `query_error()` produces a value unique per occurrence, precisely so that two
    failures cannot compare EQUAL and pass an equality assertion. That uniqueness
    makes them compare UNEQUAL, so an arms-differ assertion passes on a pair of
    statements that both blew up -- the same defect arriving through the fix for it.

    Measured: `query_error()` twice gives `QUERY_ERROR.1.<detail>` and
    `QUERY_ERROR.2.<detail>`, which are `!=`.
    """
    for side in ("left", "right"):
        pytester.makeconftest("pytest_plugins = ['pgc_vacuity']")
        args = ('pgc_vacuity.query_error("a"), "PLAN-B"' if side == "left"
                else '"PLAN-A", pgc_vacuity.query_error("b")')
        pytester.makepyfile(
            f"""
            import pgc_vacuity

            def test_one_arm_failed(expect):
                expect.differ({args}, "the arms differ")
            """
        )
        result = pytester.runpytest("-p", "pgc_vacuity")
        expect.refusal(result, f"a failed query on the {side} is not an arm",
                       r"failed query")


def test_differ_refuses_two_failed_queries(pytester, expect):
    """The shape the uniqueness fix created, written out.

    Both arms raised, both sentinels are distinct, and without the refusal the
    assertion reports that the mutation was observable.
    """
    pytester.makeconftest("pytest_plugins = ['pgc_vacuity']")
    pytester.makepyfile(
        """
        import pgc_vacuity

        def test_both_arms_failed(expect):
            a = pgc_vacuity.query_error("baseline blew up")
            b = pgc_vacuity.query_error("mutated blew up")
            expect.differ(a, b, "the mutation moved the result")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.refusal(result, "two failures are not two arms", r"failed query")

# ---- and the hand-rolled idiom cannot come back --------------------------------
#
# A helper nobody is required to use is a convention, not a mechanism, and this
# directory has a standing rule that a mode counts as refused only when a mechanism
# refuses it. `differ` on its own leaves the old spelling available, so the scan below
# makes the class unavailable rather than fixing the two instances -- which is the same
# argument as "fix the class, not the instance".
#
# AST, NOT A LINE REGEX. The two paragraphs in this tree that DESCRIBE the old idiom
# quote it verbatim, so a text sweep flags its own documentation; `ast` sees code only.
# That is the same trap the `pytest.raises` scan records, where a regex version
# refused the layer's own test suite with 22 invented offences.

_INEQ_MSG = "int() of a comparison, passed to an expect call"


def _hand_rolled_inequalities(source, filename="<probe>"):
    """-> ["file:line", ...] for `expect.X(int(a != b), ...)` and friends.

    The shape is `int(<Compare>)` appearing as an ARGUMENT to a call on `expect`. A
    bare `int(a != b)` assigned to a name is not flagged: it asserts nothing by
    itself, and flagging it would be a claim about arithmetic rather than about an
    assertion.
    """
    import ast

    found = []

    class V(ast.NodeVisitor):
        def visit_Call(self, node):
            target = node.func
            is_expect = (isinstance(target, ast.Attribute)
                         and isinstance(target.value, ast.Name)
                         and target.value.id in ("expect", "e"))
            if is_expect:
                for arg in node.args:
                    if (isinstance(arg, ast.Call)
                            and isinstance(arg.func, ast.Name)
                            and arg.func.id == "int"
                            and len(arg.args) == 1
                            and isinstance(arg.args[0], ast.Compare)
                            and any(isinstance(op, (ast.NotEq, ast.Eq))
                                    for op in arg.args[0].ops)):
                        found.append(f"{filename}:{arg.lineno}")
            self.generic_visit(node)

    V().visit(ast.parse(source))
    return found


def test_the_inequality_scan_finds_a_planted_offence(expect):
    """The scan must fire on the exact shape the two converted sites used."""
    planted = _hand_rolled_inequalities(
        "def test_x(expect):\n"
        "    expect.num(int(after != before), 1, 'moved')\n",
        "planted.py")
    expect.num(len(planted), 1, "the scan finds a hand-rolled inequality")
    expect.text(planted[0], "planted.py:2", "and names where it is")
    # at_least as well as num, because the other converted site used that one.
    expect.num(len(_hand_rolled_inequalities(
        "def test_y(expect):\n"
        "    expect.at_least(int(a != b), 1, 'moved')\n")), 1,
        "and finds it through at_least too")
    # THE INVERTED SPELLING, which is the one the manual count missed. The third site
    # wrote `int(stated == disk) == 0` -- the same assertion with the comparison
    # flipped -- so a scan that looked only for `!=` would have left it in place and
    # reported a clean corpus. Without this arm, dropping `ast.Eq` from the scan is
    # invisible.
    expect.num(len(_hand_rolled_inequalities(
        "def test_z(expect):\n"
        "    expect.num(int(stated == disk), 0, 'disagrees')\n")), 1,
        "and finds the int(a == b) spelling, not only int(a != b)")


def test_the_inequality_scan_does_not_flag_honest_code(expect):
    """The false-positive budget, which a static guard needs before it ships."""
    for label, src in (
        ("a bare int()", "def t(expect):\n    expect.num(int(x), 1, 'n')\n"),
        ("a comparison not wrapped in int()",
         "def t(expect):\n    expect.differ(a, b, 'arms')\n"),
        ("an int(compare) bound to a name first",
         "def t(expect):\n    flag = int(a != b)\n    expect.num(flag, 1, 'n')\n"),
        # PASSED TO A CALL THAT IS NOT AN ASSERTION, which is what makes the
        # expect-context condition load-bearing. Without this shape, dropping that
        # condition changed nothing and the arm stayed green -- found by mutating it.
        # The scan's subject is assertions, not arithmetic: `print(int(a != b))`
        # asserts nothing and flagging it would be a false red.
        ("an int(compare) passed to a call that is not an expect",
         "def t(expect):\n    print(int(a != b))\n    expect.num(1, 1, 'n')\n"),
        ("the idiom inside a comment",
         "def t(expect):\n    # expect.num(int(a != b), 1, 'moved')\n"
         "    expect.num(1, 1, 'n')\n"),
        ("the idiom inside a string",
         "def t(expect):\n    s = \"expect.num(int(a != b), 1, 'x')\"\n"
         "    expect.text(s, s, 'n')\n"),
    ):
        expect.num(len(_hand_rolled_inequalities(src)), 0,
                   f"not flagged: {label}")


def test_no_test_in_this_corpus_hand_rolls_an_inequality(expect):
    """The population, which is what makes the two arms above worth having.

    Two sites used the idiom before `differ` existed. Both are converted, so this is
    zero -- and the arms above are why a zero here means the scan looked rather than
    that it cannot see.
    """
    import pathlib

    here = pathlib.Path(__file__).parent
    files = sorted(here.glob("test_*.py"))
    expect.at_least(len(files), 10, "premise: the scan has a corpus to read")
    offences = []
    for f in files:
        offences += _hand_rolled_inequalities(f.read_text(encoding="utf-8"), f.name)
    expect.text(repr(offences), "[]", "no test hand-rolls an inequality")


# ---- the layer's own names are reachable from the tree it polices (#924) ----
#
# pytest imports `conftest.py` FROM THE POLICED DIRECTORY into the policing
# interpreter, before collection, with no opt-out. So every module-level name in
# pgc_vacuity is writable by the code it judges. That is not a bug in pytest; it
# is what conftest is for. It is a defect here because this layer's whole job is
# to refuse, and a refusal that can be deleted in two lines is a suggestion.
#
# #958 closed the datum one exploit used (`_ORDER_KILLERS`) by binding it in a
# default argument. The three scans that READ such data are module-level names
# themselves, one frame further out, and each is a two-line conftest away from
# being a no-op. Measured on main 226f805 with the pinned runner:
#
#     GUARD               no conftest    with the rebind
#     order collapse      REFUSED rc=4   PASSED rc=0
#     broad except        REFUSED rc=4   PASSED rc=0
#     raises not pinned   REFUSED rc=4   PASSED rc=0
#
# The fix is not another name moved out of reach. It is the layer noticing that
# one of its own bindings changed, which covers the names added after this was
# written as well as the 47 present when it was.


def _rebind(name):
    """A conftest that switches one scan off, and nothing else. Two lines."""
    return (
        "import pgc_vacuity\n"
        f"pgc_vacuity.{name} = lambda path: []\n"
    )


def test_a_conftest_cannot_switch_off_the_order_collapse_scan(pytester, expect):
    """#924, the route still open after #958."""
    pytester.makepyfile(
        """
        def test_order_collapsed(expect):
            got = ["b", "a"]
            g = sorted(got)
            expect.ordered_rows(g, ["a", "b"], "rows in order")
        """
    )
    plain = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(plain, "premise: the collapse is refused when nobody rebinds")
    plain.stderr.fnmatch_lines(["*order-killed*"])

    pytester.makeconftest(_rebind("_sorted_ordered_sites"))
    hatched = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(hatched, "and it is still refused after the scan is rebound")
    hatched.stderr.fnmatch_lines(["*_sorted_ordered_sites*"])


def test_a_conftest_cannot_switch_off_the_broad_except_scan(pytester, expect):
    """The same hatch, a different scan. Named separately because a fix that
    closed only the scan #924 happens to name would leave this one open, which
    is how #924 came back after #958."""
    pytester.makepyfile(
        """
        def test_broad(expect):
            try:
                x = 1
            except Exception:
                pass
            expect.num(x, 1, "x is one")
        """
    )
    plain = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(plain, "premise: the broad except is refused")
    plain.stderr.fnmatch_lines(["*catches Exception broadly*"])

    pytester.makeconftest(_rebind("_broad_except_sites"))
    hatched = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(hatched, "and it is still refused after the scan is rebound")
    hatched.stderr.fnmatch_lines(["*_broad_except_sites*"])


def test_a_conftest_cannot_switch_off_the_raises_scan(pytester, expect):
    """The third. The body holds a compound statement rather than a broad
    exception class, because that arm needs no driver installed and this file
    runs in the database-free job.

    My first version of this premise used `pytest.raises(ValueError)` around one
    statement, which the rule does not refuse -- so the PREMISE printed `1 passed`
    and the arm could not have shown anything being switched off.
    """
    pytester.makepyfile(
        """
        import pytest

        def test_raises_compound(expect):
            with pytest.raises(ValueError):
                for i in [1]:
                    raise ValueError("boom")
            expect.num(1, 1, "ran")
        """
    )
    plain = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(plain, "premise: an unpinned compound raises block is refused")
    plain.stderr.fnmatch_lines(["*not pinned*"])

    pytester.makeconftest(_rebind("_raises_sites"))
    hatched = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(hatched, "and it is still refused after the scan is rebound")
    hatched.stderr.fnmatch_lines(["*_raises_sites*"])


def test_a_conftest_cannot_stub_an_expect_method_so_a_false_claim_passes(pytester, expect):
    """#967. #964 snapshots module bindings. `Expect.num = a stub` is not a
    rebind of `Expect` -- the name still points at the same class -- so a false
    claim reports as a pass if the stub still increments the count.

    The three rows the issue named, and a fix must keep 1 and 3 while turning 2
    into a refusal:

        no conftest                         failed, correctly
        Expect.num stubbed, still counting  PASSED -- the hatch
        Expect._record stubbed              failed, count 0 (separate control)
    """
    pytester.makepyfile(
        """
        def test_one_equals_two(expect):
            expect.num(1, 2, "one equals two, which it does not")
        """
    )
    plain = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(plain, "premise: a false claim fails when nobody stubs",
                    failed=1, passed=0)

    import pgc_vacuity
    original = pgc_vacuity.Expect.num
    pytester.makeconftest(
        "import pgc_vacuity\n"
        "pgc_vacuity.Expect.num = "
        "lambda self, got, want, name: self._record(name)\n"
    )
    try:
        hatched = pytester.runpytest("-p", "pgc_vacuity")
    finally:
        pgc_vacuity.Expect.num = original
    expect.run_failed(hatched, "stubbing Expect.num so it still counts is refused")
    hatched.stderr.fnmatch_lines(["*Expect.num*"])


def test_stubbing_the_recorder_still_fails_closed_by_count(pytester, expect):
    """#967 row 3. Stubbing `_record` leaves the count at 0, so the test is
    refused for making no counted assertion. That is a different mechanism from
    the public-method snapshot, and it must stay the one that fires -- a snapshot
    of `_record` would swallow this into a collection-time refusal and the
    control would no longer mean what it says.
    """
    pytester.makepyfile(
        """
        def test_one_is_one(expect):
            expect.num(1, 1, "one is one")
        """
    )
    import pgc_vacuity
    original = pgc_vacuity.Expect._record
    pytester.makeconftest(
        "import pgc_vacuity\n"
        "pgc_vacuity.Expect._record = lambda self, name: None\n"
    )
    try:
        result = pytester.runpytest("-p", "pgc_vacuity")
    finally:
        # pytester is in-process: the inner conftest writes the shared class.
        # This arm deliberately does not snapshot `_record`, so nothing restores
        # it for us -- and the outer expect.outcomes would then count nothing.
        pgc_vacuity.Expect._record = original
    expect.outcomes(result, "stubbing _record is refused by count 0, not by snapshot",
                    failed=1, passed=0)
    result.stdout.fnmatch_lines(["*no counted assertion*"])


def test_the_refusal_names_the_binding_that_changed(pytester, expect):
    """A refusal that does not say what was rebound sends the reader to the
    wrong file. The offending test here is HONEST -- the only thing wrong with
    the run is the conftest -- so nothing but the tamper check can refuse it."""
    pytester.makepyfile(
        """
        def test_honest(expect):
            expect.num(1, 1, "one is one")
        """
    )
    plain = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(plain, "premise: an honest test passes", passed=1, failed=0)

    pytester.makeconftest(_rebind("_broad_except_sites"))
    hatched = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(hatched, "a rebound layer name refuses a run of honest tests")
    hatched.stderr.fnmatch_lines(["*_broad_except_sites*"])


def test_a_new_attribute_on_the_layer_is_not_a_rebind(pytester, expect):
    """The control, and it is LOAD-BEARING rather than hygiene (@OffgridwithJD).

    A guard that fired on anything touching the module would be the
    false-positive engine this layer's own budget forbids -- but it would also
    turn four EXISTING tests red, because each writes a name that has never been
    a module attribute:

        _ORDER_KILLERS    test_ordered.py:148, :169     (removed by #958)
        _BROAD_RAISES     test_raises_sqlstate.py:584
        broad_families    test_raises_sqlstate.py:585
        BROAD_RAISES      test_raises_sqlstate.py:586

    A snapshot comparison cannot flag any of them, because there is no prior
    binding to differ from. So this arm is what keeps an ADD from being tightened
    into tampering by someone who reads the check as incomplete. Verified: only
    `QUERY_ERROR` (test_failed_query_sentinel.py:321, :352) rebinds a name that
    exists, and it restores it in a `finally` without driving an inner collection.
    """
    pytester.makepyfile(
        """
        def test_honest(expect):
            expect.num(1, 1, "one is one")
        """
    )
    pytester.makeconftest(
        "import pgc_vacuity\n"
        "pgc_vacuity._a_name_the_layer_never_had = 1\n"
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "a NEW attribute is not a changed binding",
                    passed=1, failed=0)


def test_the_rebind_does_not_leak_into_this_session(pytester, expect):
    """pytester runs the inner session IN-PROCESS, on the same module object, so
    a conftest that rebinds a scan leaves it rebound for every test that follows
    -- including the ones in this file. The layer already paid for that once
    (see `_RunShape`: 'AN INSTANCE PER CONFIG, NOT MODULE GLOBALS').

    So the refusal restores the binding before raising, and this asserts it by
    USING the scan afterwards rather than by comparing identities: a no-op lambda
    returns [] for everything, and the real scan finds the planted offence.
    """
    pytester.makepyfile(
        """
        def test_honest(expect):
            expect.num(1, 1, "one is one")
        """
    )
    pytester.makeconftest(_rebind("_broad_except_sites"))
    expect.run_failed(pytester.runpytest("-p", "pgc_vacuity"),
                      "the inner run is refused")

    import pgc_vacuity
    planted = pytester.makepyfile(
        planted="""
        def test_planted(expect):
            try:
                x = 1
            except Exception:
                pass
            expect.num(x, 1, "x is one")
        """
    )
    expect.num(len(pgc_vacuity._broad_except_sites(str(planted))), 1,
               "the real scan is back and still finds the offence")
