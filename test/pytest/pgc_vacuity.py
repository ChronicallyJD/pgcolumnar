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

import ast
import numbers
import pathlib

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

# lib.sh:58 PGC_EXIT_INCOMPLETE. The same number deliberately: a suite that could
# not evaluate something exits 67 there, and a runner that learns the code learns
# it once. pytest itself uses 0-6 (`pytest.ExitCode`), so 67 collides with
# nothing.
EXIT_INCOMPLETE = 67


class VacuityError(AssertionError):
    """Raised when an assertion could not have failed, or asserted nothing."""


def _is_number(v):
    # bool is an int in Python. A count that is True rather than 1 is a bug, not a
    # number, so it is refused rather than silently compared.
    return isinstance(v, numbers.Number) and not isinstance(v, bool)


def _empty(v):
    return v is None or (hasattr(v, "__len__") and len(v) == 0)


def _plan_nodes(node):
    """Every node of an EXPLAIN (FORMAT JSON) tree, as parsed by psycopg."""
    if isinstance(node, dict):
        yield node
        for key in ("Plan", "Plans"):
            child = node.get(key)
            if isinstance(child, dict):
                yield from _plan_nodes(child)
            elif isinstance(child, list):
                for entry in child:
                    yield from _plan_nodes(entry)
    elif isinstance(node, list):
        for entry in node:
            yield from _plan_nodes(entry)


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

    # -- row counts ---------------------------------------------------------
    def rowcount(self, got, want, name):
        """Compare a row count, refusing psycopg's "no count available" sentinel.

        cursor.rowcount is -1 when the statement produced no count, and measured on
        a live server it is 1 for an unfetched SELECT -- neither is a number of
        rows. Both are numbers, so expect.num compares them happily: num(-1, -1)
        passes. A count that matters should come from count(*) or from len() of the
        rows actually fetched.
        """
        for side, v in (("left", got), ("right", want)):
            if v == -1:
                raise VacuityError(
                    f"{name}: the {side} side is -1, which is psycopg's "
                    f"\"no row count available\" and not a number of rows."
                )
        self.num(got, want, name)

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
        no text to grep, and equality on a typed field cannot be satisfied by a
        superstring the way `grep ColumnarScan` was by `PgColumnarScan`.

        BUT `provider="PgColumnarScan"` DOES NOT MEAN "a columnar SCAN". Measured:
        the vectorized aggregate node reuses the scan's registered methods
        (`columnar_vector.c:806` assigns `&pgcolumnar_scan_methods`), so every
        pgcolumnar node reports that provider. With the vector aggregate engaged
        there is a single Custom Scan node carrying `Columnar Vectorized
        Aggregates` and NO `Columnar Projected Columns`, and this predicate still
        says yes. `pgc_is_columnar_scan` says no, because it greps for the marker.

        So use `plan_marker` to ask "did the columnar SCAN run". Use this to ask
        "is there a pgcolumnar node at all", which is a weaker and rarer question.
        """
        if node_type is None and provider is None:
            raise VacuityError(
                "plan_node() needs node_type or provider, or it asserts nothing."
            )
        label = name or f"plan has node_type={node_type!r} provider={provider!r}"

        seen_types, seen_providers = [], []
        for node in _plan_nodes(plan):
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
    def refusal(self, result, name, *patterns):
        """The inner run failed, AND it failed for the REASON named.

        `outcomes(result, failed=1)` alone is satisfied by any refusal, so a
        guard whose neighbour catches the same input is pinned by nothing. A
        mutation census over this layer found 12 of 17 guards deletable with the
        corpus still green, and two of those were UNREACHABLE-by-subsumption
        rather than untested: neuter `ordered_rows`'s both-empty guard and the
        unobservable guard fires on the same input, so the inner run still fails
        and an outcome-only assertion still passes (@jdatcmd, #897 review).

        Every pattern must appear. Naming the message is what makes the arm
        about one guard instead of about the layer in general.
        """
        if not patterns:
            raise VacuityError(
                f"{name}: refusal() with no pattern asserts only that something "
                f"failed, which is the defect it exists to remove."
            )
        self._counted()
        result.assert_outcomes(failed=1, passed=0)
        # ANCHORED TO pytest's ERROR-LINE PREFIX, and that is the whole point.
        #
        # This was `f"*{p}*"`, which searches the inner run's WHOLE stdout --
        # and pytest prints the enclosing function's SOURCE in a traceback,
        # including lines that never executed. So the pattern matched the
        # guard's own string literal in the traceback rather than anything the
        # guard produced. Measured: with `hash()`'s left-sentinel guard
        # neutered, the inner output still contains
        #
        #     raise VacuityError(f"{name}: the left side is a failed query: ...")
        #     E  AssertionError: a failed query on the left: got ... want ...
        #
        # and `*the left side is a failed query*` matched the first line. Every
        # message in a function is printed whenever anything in it fails.
        #
        # THAT IS THE DEFECT THIS HELPER EXISTS TO PREVENT, IN THIS HELPER.
        # `outcomes(failed=1)` is satisfied by any refusal; requiring the message
        # was meant to fix it, and matching printed source meant it did not --
        # it was satisfied by any failure in a function whose source contains the
        # phrase. A census over the layer found SEVEN guards unheld this way.
        #
        # `E` is the prefix pytest puts on the raised-exception lines of a
        # traceback, so the phrase must now appear in a message rather than
        # anywhere in the file.
        result.stdout.fnmatch_lines([f"E*{p}*" for p in patterns])

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

    def plan_marker(self, plan, key, name=None, absent=False):
        """Assert a plan node carries (or does not carry) a Columnar property KEY.

        This is the faithful port of `pgc_is_columnar_scan` (`lib.sh`), which greps
        `EXPLAIN` output for `Columnar Projected Columns`. That marker is emitted
        only by the scan's explain callback (`columnar_customscan.c:3631`) and never
        by either aggregate callback, so its presence is what distinguishes a
        columnar scan from a vectorized aggregate that absorbed one.

        Presence of a KEY, not equality of a VALUE, because the marker's value is a
        count that legitimately varies. `absent=True` asserts the opposite, which is
        how a test pins that a plan is NOT a scan.
        """
        label = name or f"plan {'lacks' if absent else 'carries'} {key!r}"
        nodes = list(_plan_nodes(plan))

        # A PLAN THAT DID NOT ARRIVE LOOKS EXACTLY LIKE ONE THAT LACKS THE NODE.
        # With `absent=True` that is a pass: the claim "nothing here carries the
        # marker" is satisfied by there being nothing here. Measured before this
        # guard: `expect.plan_marker([], "Columnar Projected Columns",
        # absent=True)` gave `1 passed`, exit 0.
        #
        # That is the worst place in this layer for a silent pass. `absent=True`
        # is how the vector-aggregate trap is pinned, and test_connection.py uses
        # plan_marker as the PREMISE that the aggregate engaged -- a premise that
        # cannot fail turns its test into one about an ordinary plan.
        #
        # Refused for the present arm too, and deliberately: an empty plan means
        # the EXPLAIN did not arrive, so neither question can be answered. The
        # present arm would fail anyway, but it would fail with "no node carries
        # it, Columnar keys present: []", which diagnoses the wrong thing.
        if not nodes:
            raise VacuityError(
                f"{label}: the plan has no nodes, so nothing here could carry "
                f"or lack {key!r}. An EXPLAIN that did not arrive is not an "
                f"answer to either question."
            )

        found, seen = False, set()
        for node in nodes:
            seen.update(k for k in node if k.startswith("Columnar"))
            if key in node:
                found = True

        self._counted()
        if absent and found:
            raise AssertionError(f"{label}: the key is present and should not be.")
        if not absent and not found:
            raise AssertionError(
                f"{label}: no node carries it. Columnar keys present: {sorted(seen)!r}"
            )

    # -- the third state ---------------------------------------------------
    def cannot_run(self, reason, detail=""):
        """Declare this test unrunnable. Not a pass, and not a silent skip.

        THE STATE HAS TO COST SOMETHING OR IT IS A SKIP WITH BETTER MANNERS. It
        did not, at first: this wrote `self.unrunnable` and nothing read it, so a
        test calling this reported `1 passed` and exit 0. A write-only field --
        the same shape selftest 320 polices in the runner, where an INCOMPLETE
        branch set a flag the verdict never read. It made the layer's own escape
        hatch its largest hole: a bare `@pytest.mark.skip` FAILS the run, while
        the honest-looking alternative greened silently.

        The run now ends `EXIT_INCOMPLETE` unless something failed outright, and
        the reason and detail are printed. See `_UnrunnableCollector` below.
        """
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


class _UnrunnableCollector:
    """Gathers the unrunnable declarations of ONE session.

    Held on the config rather than in a module global, because `pytester` runs
    the layer's own tests IN-PROCESS: an inner run imports this same module, so a
    module-level list would leak the inner run's declarations into the outer
    session and exit the whole corpus INCOMPLETE. One collector per config is one
    per session, inner runs included.
    """

    def __init__(self):
        self.items = []

    def pytest_runtest_logreport(self, report):
        # This hook fires on the CONTROLLER for reports received from xdist
        # workers, which is why the declaration travels as a user_property
        # rather than in a variable the worker process owns. A worker's own
        # exit status is discarded by xdist; the controller's is the run's.
        if report.when != "call":
            return
        for key, value in getattr(report, "user_properties", ()):
            if key == "pgc_unrunnable":
                reason, _, detail = value.partition("\n")
                self.items.append((report.nodeid, reason, detail))


def pytest_configure(config):
    collector = _UnrunnableCollector()
    config.pluginmanager.register(collector, "pgc_unrunnable_collector")
    config.pgc_unrunnable = collector


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """Carry an unrunnable declaration out on the report itself.

    `user_properties` is serialised across the xdist boundary; an attribute of
    our own would not be.
    """
    report = yield
    if call.when == "call":
        rec = _RECORDERS.get(item.nodeid)
        if rec is not None and rec.unrunnable:
            reason, detail = rec.unrunnable
            report.user_properties.append(("pgc_unrunnable", f"{reason}\n{detail}"))
    return report


def pytest_terminal_summary(terminalreporter):
    """Print the third state, in lib.sh's shape.

    `UNRUN  <name>: <REASON>: <detail>`, then the count. A state that does not
    say why is a skip with better manners, and a state with no count cannot be
    reconciled against the total.
    """
    collector = getattr(terminalreporter.config, "pgc_unrunnable", None)
    if collector is None or not collector.items:
        return
    terminalreporter.write_line("")
    for nodeid, reason, detail in collector.items:
        terminalreporter.write_line(f"UNRUN  {nodeid}: {reason}: {detail}")
    terminalreporter.write_line(f"checks unrunnable: {len(collector.items)}")


def pytest_sessionfinish(session, exitstatus):
    """An unrunnable test must not leave the run green.

    FAILURE STILL DOMINATES, exactly as in lib.sh: a run with both a failure and
    an unrunnable test is a failure, because the failure is the more urgent fact.
    So this only ever moves a run OFF zero, and never off a non-zero status.
    """
    collector = getattr(session.config, "pgc_unrunnable", None)
    if collector is None or not collector.items:
        return
    if exitstatus == 0:
        session.exitstatus = EXIT_INCOMPLETE


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


# A broad except in a test swallows the failure the test exists to find.
#
# After ANY failed statement psycopg raises InFailedSqlTransaction for every later
# one, so a single `except Exception` around a test body hides the real error AND
# every error after it. The layer used to forbid this in a comment, which enforces
# nothing: measured, a test using the forbidden shape passed with no complaint.
#
# PARSED, NOT GREPPED. The first version matched lines with a regex and immediately
# fired on this file's own tests, because they contain the forbidden shape inside a
# `pytester.makepyfile` string. A guard that rejects a legitimate test is a guard
# somebody switches off, and a line regex over source cannot tell code from a string
# literal -- the same mistake as matching a plan by substring. ast can: a handler
# inside a string is not an ExceptHandler node.
def _broad_except_sites(path):
    try:
        tree = ast.parse(pathlib.Path(path).read_text())
    except (OSError, SyntaxError):
        return []
    out = []
    name = pathlib.Path(path).name
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        t = node.type
        if t is None:
            out.append(f"{name}:{node.lineno} bare except")
            continue
        # A TUPLE HANDLER IS THE SHAPE PEOPLE ACTUALLY WRITE.
        #
        # This looked only at a bare `ast.Name`, so `except Exception:` was
        # refused and `except (ValueError, Exception):` passed (@jdatcmd, #905
        # review). Measured against the real layer, three spellings of one
        # swallow:
        #
        #     except Exception:               -> refused
        #     except (ValueError, Exception): -> PASSED   <- the hole
        #     except BaseException:           -> refused
        #
        # A tuple is how this gets written when someone starts with a specific
        # exception and widens it under pressure, which is the exact moment the
        # guard is for -- so the hole was in the case the guard most needed to
        # cover. Any member of the tuple being broad makes the handler broad.
        members = t.elts if isinstance(t, ast.Tuple) else [t]
        for m in members:
            if isinstance(m, ast.Name) and m.id in ("Exception", "BaseException"):
                out.append(f"{name}:{node.lineno} except {m.id}")
                break
    return out


def pytest_collection_modifyitems(config, items):
    """Refuse a bare skip, which exits 0 and reads as success.

    Measured: two skipped tests report `2 skipped` and exit 0. A skip is allowed
    only through expect.cannot_run(), which names a reason from a closed list.
    """
    offenders = []
    seen_files = set()
    for item in items:
        for marker in ("skip", "skipif"):
            if item.get_closest_marker(marker) is not None:
                offenders.append(f"{item.name} carries a bare @pytest.mark.{marker}")
        f = str(getattr(item, "fspath", "") or "")
        if f and f not in seen_files:
            seen_files.add(f)
            for site in _broad_except_sites(f):
                offenders.append(f"{site} catches Exception broadly")
    if offenders:
        # One hook, two offences, so the message must say which. An earlier version
        # reused the skip wording and told a reader with a broad `except` to call
        # expect.cannot_run, which would not have helped them.
        skips = [o for o in offenders if "@pytest.mark." in o]
        excepts = [o for o in offenders if "catches Exception broadly" in o]
        parts = []
        if skips:
            parts.append(
                "a bare skip is refused, because it exits 0 and reads as success: "
                + "; ".join(skips)
                + " -- use expect.cannot_run(REASON, detail) so the run cannot go quiet"
            )
        if excepts:
            parts.append(
                "a broad except swallows the failure the test exists to find, and "
                "after one failed statement psycopg raises for every later one: "
                + "; ".join(excepts)
                + " -- catch the specific exception class instead"
            )
        raise pytest.UsageError(
            "the pgColumnar vacuity layer refuses this run: " + ". ".join(parts) + "."
        )
