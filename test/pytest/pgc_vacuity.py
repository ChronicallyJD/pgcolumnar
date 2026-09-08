"""pgColumnar pytest harness: the vacuity-refusal layer.

A vacuity defect is a test that reports PASS while asserting nothing. Bare pytest
permits it in eight measured ways, all exiting 0, so this plugin is loaded for
every pgColumnar test rather than offered as a convention. The measurements are in
design/ISSUE_432_PYTEST_HARNESS.md section 4.

Two rules run the file:

  1. A test passes only if it made at least one COUNTED assertion. Counted means it
     went through the `expect` recorder. A bare Python `assert` is not forbidden,
     it simply does not satisfy the requirement, so a body that computes and
     concludes nothing fails.
  2. Every comparison refuses its own degenerate cases. Both sides empty, a value
     against itself, a substring where a typed field was meant.

The bash harness earned each of these. `check_num`, `check_ratio` and `check_text`
were added for issue #418 after "empty compared with empty" printed PASS, and
`check_num` refuses two identical md5 hashes for the same reason.
"""

import numbers

import pytest

# The sentinel a failed query yields, mirroring pgc_set_hash's QUERY_ERROR.$seq.
# Unique per occurrence so two failing queries can never compare equal and pass.
QUERY_ERROR = "QUERY_ERROR"
EMPTY = "EMPTY"

# Reasons a test may declare itself unrunnable. Closed, exactly as lib.sh keeps it
# closed, so "skipped" cannot become a way to stop asserting things quietly.
UNRUNNABLE_REASONS = (
    "MISSING_DEPENDENCY",
    "UNSUPPORTED_MAJOR",
    "ABSENT_FIXTURE",
    "UNAVAILABLE_ENDPOINT",
    "UNMET_PRECONDITION",
)

# Keyed by nodeid rather than held on the item, so an xdist worker sees only its
# own tests and two workers cannot share a counter.
_RECORDERS = {}


class VacuityError(AssertionError):
    """Raised when an assertion could not have failed, or asserted nothing."""


def _is_number(v):
    # bool is an int in Python. A count that is True rather than 1 is a bug, not a
    # number, so it is refused rather than silently compared.
    return isinstance(v, numbers.Number) and not isinstance(v, bool)


def _empty(v):
    return v is None or (hasattr(v, "__len__") and len(v) == 0)


class Expect:
    """Records assertions, and refuses the ones that could not have failed."""

    def __init__(self, nodeid):
        self.nodeid = nodeid
        self.count = 0
        self.unrunnable = None

    # -- the recorder -------------------------------------------------------
    def _counted(self):
        self.count += 1

    # -- numbers -----------------------------------------------------------
    def num(self, got, want, name):
        """Compare two numbers. Refuses anything that is not a number.

        A string "100" compared with 100 is the psql-text-parsing bug this harness
        exists to remove, so it is refused rather than coerced.
        """
        if not _is_number(got) or not _is_number(want):
            raise VacuityError(
                f"{name}: num() needs numbers on both sides, got "
                f"{type(got).__name__}={got!r} and {type(want).__name__}={want!r}. "
                f"A text comparison here is the defect this harness removes."
            )
        self._counted()
        if got != want:
            raise AssertionError(f"{name}: got {got!r} want {want!r}")

    # -- row sets ----------------------------------------------------------
    def rows(self, got, want, name, allow_empty=None):
        """Compare two result sets. Refuses two empty sides unless declared.

        Both sides empty is issue #418: it passes while asserting nothing, because
        a query that failed to return anything looks exactly like one that
        correctly returned nothing. `allow_empty` takes a REASON, not a flag, so
        the escape hatch costs more to type than the honest assertion.
        """
        if _empty(got) and _empty(want) and not allow_empty:
            raise VacuityError(
                f"{name}: both sides are empty, so this comparison could not have "
                f"failed. If an empty result is the point, pass "
                f"allow_empty='why it is empty'."
            )
        self._counted()
        if list(got) != list(want):
            raise AssertionError(f"{name}: got {got!r} want {want!r}")

    # -- hashes and oracles ------------------------------------------------
    def hash(self, got, want, name):
        """Compare two oracle hashes. Refuses self-comparison and error sentinels."""
        if got is want:
            raise VacuityError(
                f"{name}: the same object is compared against itself, so this "
                f"could not have failed."
            )
        if isinstance(got, str) and got.startswith(QUERY_ERROR):
            raise VacuityError(f"{name}: the left side is a failed query: {got!r}")
        if isinstance(want, str) and want.startswith(QUERY_ERROR):
            raise VacuityError(f"{name}: the right side is a failed query: {want!r}")
        if _empty(got) and _empty(want):
            raise VacuityError(f"{name}: both hashes are empty.")
        self._counted()
        if got != want:
            raise AssertionError(f"{name}: got {got!r} want {want!r}")

    # -- text --------------------------------------------------------------
    def text(self, got, want, name):
        """Compare text exactly. Refuses an empty expectation."""
        if _empty(want):
            raise VacuityError(
                f"{name}: the expected text is empty, so anything empty satisfies it."
            )
        self._counted()
        if got != want:
            raise AssertionError(f"{name}: got {got!r} want {want!r}")

    # -- plans -------------------------------------------------------------
    def plan_node(self, plan, node_type=None, provider=None, name=None):
        """Assert a node exists, by EXACT equality on a typed EXPLAIN JSON field.

        `EXPLAIN (FORMAT JSON)` arrives from psycopg as parsed Python, so there is
        no text to grep. The provider of a columnar scan is `PgColumnarScan`, which
        is precisely why `grep ColumnarScan` was unfalsifiable: the wanted string
        is a substring of the real one. Equality on `Custom Plan Provider` cannot
        be satisfied by a superstring.
        """
        if node_type is None and provider is None:
            raise VacuityError(
                "plan_node() needs node_type or provider, or it asserts nothing."
            )
        label = name or f"plan has node_type={node_type!r} provider={provider!r}"

        def walk(node, depth=0):
            if isinstance(node, dict):
                yield node
                for key in ("Plan", "Plans"):
                    child = node.get(key)
                    if isinstance(child, dict):
                        yield from walk(child, depth + 1)
                    elif isinstance(child, list):
                        for entry in child:
                            yield from walk(entry, depth + 1)
            elif isinstance(node, list):
                for entry in node:
                    yield from walk(entry, depth + 1)

        seen_types, seen_providers = [], []
        for node in walk(plan):
            nt = node.get("Node Type")
            pv = node.get("Custom Plan Provider")
            if nt is not None:
                seen_types.append(nt)
            if pv is not None:
                seen_providers.append(pv)
            if node_type is not None and nt != node_type:
                continue
            if provider is not None and pv != provider:
                continue
            self._counted()
            return node

        raise AssertionError(
            f"{label}: no node whose fields match exactly. "
            f"Node Type values present: {seen_types!r}. "
            f"Custom Plan Provider values present: {seen_providers!r}."
        )

    # -- bounds -------------------------------------------------------------
    def at_least(self, got, floor, name):
        """Assert got >= floor. Both sides must be numbers.

        The bash harness spells this as a yes/no string built by `[ ... -ge N ]`,
        which turns a number into text and then compares text. Keeping it numeric
        means a non-number is refused instead of silently becoming "no".
        """
        if not _is_number(got) or not _is_number(floor):
            raise VacuityError(
                f"{name}: at_least() needs numbers, got "
                f"{type(got).__name__}={got!r} and {type(floor).__name__}={floor!r}"
            )
        if floor <= 0:
            raise VacuityError(
                f"{name}: a floor of {floor!r} is satisfied by any count, so this "
                f"asserts nothing."
            )
        self._counted()
        if not got >= floor:
            raise AssertionError(f"{name}: got {got!r}, wanted at least {floor!r}")

    # -- the layer's own tests ---------------------------------------------
    def outcomes(self, result, name, **want):
        """Assert on an INNER pytest run's outcomes, and count it.

        The layer's own tests run pytest inside pytest, so their assertions are
        about another run rather than about a query. They are still assertions and
        the rule still applies to them: the guard has no exemption for the tests
        that prove the guard. Adding one would be the first step to exempting
        everything else.
        """
        if not want:
            raise VacuityError(
                f"{name}: outcomes() with no expectation asserts nothing."
            )
        self._counted()
        result.assert_outcomes(**want)

    def run_failed(self, result, name):
        """Assert an inner run exited non-zero, and count it."""
        self._counted()
        if result.ret == 0:
            raise AssertionError(
                f"{name}: the inner run exited 0, so nothing refused it."
            )

    # -- the third state ---------------------------------------------------
    def cannot_run(self, reason, detail=""):
        """Declare this test unrunnable. Not a pass, and not a silent skip."""
        if reason not in UNRUNNABLE_REASONS:
            raise VacuityError(
                f"unrunnable reason {reason!r} is not one of {UNRUNNABLE_REASONS}"
            )
        self.unrunnable = (reason, detail)
        self._counted()


@pytest.fixture
def expect(request):
    rec = Expect(request.node.nodeid)
    _RECORDERS[request.node.nodeid] = rec
    yield rec
    _RECORDERS.pop(request.node.nodeid, None)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """Fail a test that concluded nothing, after its body has run.

    After the body, deliberately. A test that raised has already failed, and its
    assertion count is not the interesting fact about it.
    """
    result = yield
    rec = _RECORDERS.get(item.nodeid)
    if rec is None or rec.count == 0:
        raise VacuityError(
            f"vacuity guard: {item.name} made no counted assertion. "
            f"A test that concludes nothing must not report a pass. "
            f"Use the `expect` fixture, or declare it unrunnable with a reason."
        )
    return result


def pytest_addoption(parser):
    parser.addoption(
        "--pgc-expect-tests",
        action="store",
        type=int,
        default=None,
        help="how many tests this run must collect; a mismatch fails the run",
    )


def pytest_collection_finish(session):
    """Assert the run's own shape, so a filtered or truncated run cannot be green.

    lib.sh does the equivalent in pgc_summary, which reconciles passed plus failed
    plus unrunnable against the total and fails when the arithmetic does not close.
    """
    want = session.config.getoption("--pgc-expect-tests")
    if want is None:
        return
    if want <= 0:
        raise pytest.UsageError(
            f"--pgc-expect-tests {want} would be satisfied by a run that collected "
            f"nothing, so it asserts nothing. Give the real number."
        )
    got = len(session.items)
    if got != want:
        raise pytest.UsageError(
            f"collected {got} test(s) but expected {want}. A run that quietly "
            f"collects fewer tests than it should is a green that means nothing."
        )


def pytest_collection_modifyitems(config, items):
    """Refuse a bare skip, which exits 0 and reads as success.

    Measured: two skipped tests report `2 skipped` and exit 0. A skip is allowed
    only through expect.cannot_run(), which names a reason from a closed list.
    """
    offenders = []
    for item in items:
        for marker in ("skip", "skipif"):
            if item.get_closest_marker(marker) is not None:
                offenders.append(f"{item.name} carries a bare @pytest.mark.{marker}")
    if offenders:
        raise pytest.UsageError(
            "bare skip is refused by the pgColumnar vacuity layer: "
            + "; ".join(offenders)
            + ". Use expect.cannot_run(REASON, detail) so the run cannot go quiet."
        )
