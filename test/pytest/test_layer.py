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
