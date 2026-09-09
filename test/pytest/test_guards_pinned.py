"""Every refusal in the layer, pinned to its own message.

WHY THIS FILE EXISTS. @jdatcmd neutered each guard in turn and found 11 of 17
deletable with `test_layer.py` still green. Repeating the census over the whole
corpus after the ordered oracle landed gave 12 of 17 -- the two extra were guards
I had added myself, so this is not a defect of the original layer that later work
avoided.

TWO CAUSES, and they need the same remedy:

  * Never driven. `test_layer.py` never called `text()`, `at_least()`,
    `plan_marker()` or `cannot_run()` at all.
  * Driven, but pinned by nothing. Neuter `ordered_rows`'s both-empty guard and
    the UNOBSERVABLE guard fires on the same input: the inner run still fails,
    so an assertion on outcomes alone still passes. The guard is unreachable by
    subsumption rather than untested, and an arm that asserts only "something
    failed" cannot tell the difference.

So every arm here uses `expect.refusal`, which requires the message as well as
the failure. That is the same fix as asserting on a SQLSTATE rather than on prose
elsewhere in this tree: name the contract, not the symptom.
"""

CONF = "pytest_plugins = ['pgc_vacuity']"


def _inner(pytester, body):
    pytester.makeconftest(CONF)
    pytester.makepyfile(body)
    return pytester.runpytest("-p", "pgc_vacuity")


def test_num_refuses_a_string_that_looks_like_a_number(pytester, expect):
    """The psql-text-parsing defect this harness exists to remove. With the
    guard gone, `expect.num("100", "100", ...)` passes silently with count=1."""
    expect.refusal(_inner(pytester, '''
        def test_stringy(expect):
            expect.num("100", "100", "a count from text")
        '''), "num refuses a numeric-looking string", "needs numbers")


def test_num_accepts_real_numbers(pytester, expect):
    """Positive control: the guard must not reject the honest form."""
    result = _inner(pytester, '''
        def test_real(expect):
            expect.num(100, 100, "a real count")
        ''')
    expect.outcomes(result, "a genuine numeric comparison still passes",
                    passed=1, failed=0)


def test_text_refuses_an_empty_expectation(pytester, expect):
    expect.refusal(_inner(pytester, '''
        def test_empty_text(expect):
            expect.text("", "", "two empty strings")
        '''), "text refuses an empty expectation", "the expected text is empty")


def test_at_least_refuses_a_non_number(pytester, expect):
    expect.refusal(_inner(pytester, '''
        def test_bound_text(expect):
            expect.at_least("5", 1, "a bound from text")
        '''), "at_least refuses a non-number", "needs numbers")


def test_at_least_refuses_a_floor_of_zero(pytester, expect):
    """`at_least(0, 0, ...)` is satisfied by every possible value."""
    expect.refusal(_inner(pytester, '''
        def test_zero_floor(expect):
            expect.at_least(0, 0, "at least nothing")
        '''), "at_least refuses a zero floor", "is satisfied by any count")


def test_at_least_accepts_a_real_bound(pytester, expect):
    result = _inner(pytester, '''
        def test_real_bound(expect):
            expect.at_least(7, 3, "seven is at least three")
        ''')
    expect.outcomes(result, "a real bound passes", passed=1, failed=0)


def test_plan_node_refuses_no_criteria(pytester, expect):
    expect.refusal(_inner(pytester, '''
        def test_no_criteria(expect):
            expect.plan_node({"Plan": {"Node Type": "Seq Scan"}}, name="a plan")
        '''), "plan_node refuses no criteria", "needs node_type or provider")


def test_outcomes_refuses_no_expectation(pytester, expect):
    """This is the one that passed with the guard it is NAMED after deleted:
    the old arm asserted only a non-zero exit, and the next arm's refusal
    satisfied it."""
    expect.refusal(_inner(pytester, '''
        def test_no_expectation(expect):
            class R:
                def assert_outcomes(self, **k):
                    pass
            expect.outcomes(R(), "nothing expected")
        '''), "outcomes refuses an empty expectation", "asserts nothing")


def test_cannot_run_refuses_a_reason_outside_the_closed_list(pytester, expect):
    """The escape hatch takes a reason from a closed list precisely so it cannot
    become a way to green anything."""
    expect.refusal(_inner(pytester, '''
        def test_bad_reason(expect):
            expect.cannot_run("just because", "an unrunnable check")
        '''), "cannot_run refuses a reason off the list", "is not one of")


def test_hash_refuses_self_comparison(pytester, expect):
    expect.refusal(_inner(pytester, '''
        def test_self_hash(expect):
            expect.hash("abc", "abc", "a hash against itself")
        '''), "hash refuses self-comparison", "compared against itself")


def test_hash_refuses_a_LEFT_error_sentinel(pytester, expect):
    """The pattern names the SIDE, and that is what pins the guard.

    A census found both sentinel guards unheld while this arm asserted only
    "is a failed query". Neuter the left guard and the comparison itself still
    fails the inner run -- subsumption by the ordinary assertion, not by another
    guard -- so an arm that accepts either message cannot tell the two apart.
    With the side named, a left guard that stops working can no longer be
    covered by the right one or by the comparison.
    """
    expect.refusal(_inner(pytester, '''
        def test_error_left(expect):
            expect.hash("QUERY_ERROR.1", "abc", "a failed query on the left")
        '''), "hash refuses a left error sentinel",
                   "the left side is a failed query")


def test_hash_refuses_a_RIGHT_error_sentinel(pytester, expect):
    """The mirror, which the single arm above never covered at all."""
    expect.refusal(_inner(pytester, '''
        def test_error_right(expect):
            expect.hash("abc", "QUERY_ERROR.1", "a failed query on the right")
        '''), "hash refuses a right error sentinel",
                   "the right side is a failed query")


def test_hash_refuses_two_empties(pytester, expect):
    """Reachable only with two DISTINCT empty values.

    The self-comparison guard above it is `got is want`, an identity test, and
    CPython interns `""` -- so `expect.hash("", "", ...)` trips that guard
    instead and never reaches this one. Written the obvious way, this arm would
    have passed while asserting nothing about the guard it names. Prove an input
    can reach a guard before asserting the guard fires.
    """
    expect.refusal(_inner(pytester, '''
        def test_empty_hashes(expect):
            expect.hash("", None, "an empty hash against a missing one")
        '''), "hash refuses two empties", "both hashes are empty")


def test_refusal_itself_refuses_an_empty_pattern_list(pytester, expect):
    """The new helper must not become the defect it removes: `refusal(result,
    name)` with no pattern is an outcome-only assertion wearing a better name."""
    import pytest as _pytest
    from pgc_vacuity import VacuityError

    class _R:
        def assert_outcomes(self, **k):
            pass

    with _pytest.raises(VacuityError):
        expect.refusal(_R(), "no patterns given")
    expect.num(1, 1, "refusal() with no pattern is itself refused")


# ---------------------------------------------------------------------------
# plan_marker, which @jdatcmd named as the one to fix first (#897 review):
# "both of its arms can be deleted independently with the suite green. Under
# one of those mutations the premise can never fail, so the provider-trap test
# would silently be about an ordinary plan."
#
# He was right, and it is the worst place in the layer for it to be true.
# `plan_marker` is the faithful port of `pgc_is_columnar_scan`; test_connection
# calls it three times, once as the PREMISE that the vector aggregate engaged.
# A premise that cannot fail turns the provider-trap test into a test about an
# ordinary plan while it stays green.
#
# These arms are behavioural rather than refusals -- plan_marker's two arms
# raise AssertionError, not VacuityError, so `expect.refusal` does not apply and
# `expect.outcomes` is the right instrument. Their value is the removal proof in
# the commit message, not their own green.


def test_plan_marker_present_arm_fails_when_the_key_is_absent(pytester, expect):
    """The arm that makes 'did the columnar scan run' answerable."""
    result = _inner(pytester, '''
        PLAN = [{"Plan": {"Node Type": "Seq Scan"}}]

        def test_missing_marker(expect):
            expect.plan_marker(PLAN, "Columnar Projected Columns", name="scan ran")
        ''')
    expect.outcomes(result, "a plan without the key fails", failed=1, passed=0)
    result.stdout.fnmatch_lines(["*no node carries it*"])


def test_plan_marker_present_arm_passes_when_the_key_is_there(pytester, expect):
    """Control. A guard that reddens on a real plan gets switched off."""
    result = _inner(pytester, '''
        PLAN = [{"Plan": {"Node Type": "Custom Scan",
                          "Columnar Projected Columns": 3}}]

        def test_marker_present(expect):
            expect.plan_marker(PLAN, "Columnar Projected Columns", name="scan ran")
        ''')
    expect.outcomes(result, "a plan carrying the key passes", passed=1, failed=0)


def test_plan_marker_absent_arm_fails_when_the_key_is_present(pytester, expect):
    """The other arm. `absent=True` is how the vector-aggregate trap is pinned,
    so a mutation that makes it unable to fail would make that test vacuous."""
    result = _inner(pytester, '''
        PLAN = [{"Plan": {"Node Type": "Custom Scan",
                          "Columnar Projected Columns": 3}}]

        def test_marker_should_be_absent(expect):
            expect.plan_marker(PLAN, "Columnar Projected Columns",
                               name="aggregate absorbed the scan", absent=True)
        ''')
    expect.outcomes(result, "an absence claim over a present key fails",
                    failed=1, passed=0)
    result.stdout.fnmatch_lines(["*the key is present and should not be*"])


def test_plan_marker_absent_arm_passes_on_a_plan_that_lacks_the_key(pytester, expect):
    """Control for the arm above, on a plan that really did arrive."""
    result = _inner(pytester, '''
        PLAN = [{"Plan": {"Node Type": "Custom Scan",
                          "Columnar Vectorized Aggregates": 1}}]

        def test_marker_absent(expect):
            expect.plan_marker(PLAN, "Columnar Projected Columns",
                               name="aggregate absorbed the scan", absent=True)
        ''')
    expect.outcomes(result, "an absence claim over a real plan passes",
                    passed=1, failed=0)


def test_plan_marker_refuses_an_absence_claim_over_an_empty_plan(pytester, expect):
    """The hole underneath both arms: an absence claim is satisfied by nothing
    being there at all.

    A plan that failed to arrive looks exactly like a plan that legitimately
    lacks the node, and `absent=True` cannot tell them apart -- so the arm that
    pins the vector-aggregate trap would pass against `[]`. Measured before the
    fix: `1 passed`, exit 0.

    This is a REFUSAL rather than an assertion, because the input is degenerate
    rather than wrong, which is the same distinction `rows()` makes for two
    empty sides.
    """
    expect.refusal(_inner(pytester, '''
        def test_absent_on_nothing(expect):
            expect.plan_marker([], "Columnar Projected Columns", absent=True)
        '''), "plan_marker refuses an absence claim over an empty plan",
                   "plan has no nodes")


# The ordered oracle's own guards. These live here rather than in the base
# branch's copy of this file because the guards they pin do not exist until the
# ordered oracle does.
#
# BOTH ARE UNREACHABLE BY SUBSUMPTION, which is why they need the message and
# not just the outcome. Neuter either one and a NEIGHBOURING refusal fires on
# the same input, so the inner run still fails and an arm asserting only
# `failed=1` still passes. A census over the full stack found exactly these two
# unheld after the rest of the layer was pinned.


def test_ordered_rows_both_empty_names_its_own_refusal(pytester, expect):
    """Neutered, the UNOBSERVABLE guard fires on `[], []` instead: every element
    of an empty sequence is trivially the same, so that guard also matches."""
    expect.refusal(_inner(pytester, '''
        def test_two_empty(expect):
            expect.ordered_rows([], [], "two empty sequences")
        '''), "ordered_rows names its own both-empty refusal",
                   "both sequences are empty")


def test_ordering_observable_both_empty_names_its_own_refusal(pytester, expect):
    """Neutered, the `forward == reverse` AssertionError fires instead, because
    two empty readings are equal."""
    expect.refusal(_inner(pytester, '''
        def test_empty_directions(expect):
            expect.ordering_observable([], [], "no rows either way")
        '''), "ordering_observable names its own both-empty refusal",
                   "both directions are empty")
