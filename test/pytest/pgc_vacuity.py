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

import itertools

import pytest

# The sentinel a failed query yields, mirroring lib.sh's `res="QUERY_ERROR.$seq"`.
#
# THE COMMENT HERE USED TO CLAIM "unique per occurrence so two failing queries can
# never compare equal", WHICH WAS FALSE OF A CONSTANT. `QUERY_ERROR == QUERY_ERROR`,
# so two failures that both assigned it compared EQUAL, and a test comparing one
# failed query against another passed. Measured before the fix: `expect.text`,
# `expect.rows`, `expect.row_set` and `expect.ordered_rows` all passed with the
# sentinel on both sides.
#
# lib.sh does not have this problem because its sentinel is PRODUCED, with a
# sequence number, by the one helper every suite calls. The port had the constant
# and no producer, so uniqueness was a sentence rather than a mechanism.
#
# QUERY_ERROR stays as the PREFIX every refusal matches on. `query_error()` is the
# producer, and it is what a caller should use.
QUERY_ERROR = "QUERY_ERROR"
EMPTY = "EMPTY"

_query_error_seq = itertools.count(1)


# THE PREFIX IS BOUND AT DEFINITION TIME, in a default argument, and that is the whole
# mechanism rather than a style choice.
#
# The first version read the module global `QUERY_ERROR` in both the producer and the
# refusal. Every `conftest.py` under test/pytest/ is imported before collection, so a
# corpus file can rewrite that global -- and because BOTH sides read it, they moved
# together and the refusal matched whatever the prefix had just been set to. The arm
# that was supposed to catch this minted its sentinels AFTER rewriting, so it could not
# fail for the property it named: tautological, and @jdatcmd measured it.
#
# The faithful hatch mints while armed and rewrites afterwards, which is what a corpus
# file actually does. Measured against the first version: with the rewrite, two minted
# sentinels were COMPARED instead of refused, and a corpus file doing it end to end
# reported `1 passed` over two failed queries -- `error-swallowed-to-empty`
# reintroduced through the hatch the change claimed to close.
#
# A default argument is evaluated once, when the function is defined, and is not read
# from the module namespace afterwards. So rewriting `pgc_vacuity.QUERY_ERROR` changes
# neither what is minted nor what is refused. `QUERY_ERROR` stays exported because the
# corpus names it in literals, and it is no longer what the mechanism reads.
def query_error(detail="", _prefix=QUERY_ERROR):
    """The value a failed query yields: unique per occurrence, by construction.

    Two failures can never compare equal, which is the whole mechanism -- a helper
    that turns every failure into one falsy value makes "both queries failed" look
    exactly like "both queries agreed". lib.sh closed this with a sequence number
    per failure and this is the port of that, not of the constant.

    The sequence is per process. Under xdist each worker is its own process, so two
    workers can mint the same number -- which is harmless, because a comparison only
    ever happens inside one test, and the refusals below match the PREFIX rather
    than any particular number.
    """
    n = next(_query_error_seq)
    return f"{_prefix}.{n}.{detail}" if detail else f"{_prefix}.{n}"


def _failed_query(v, _prefix=QUERY_ERROR):
    """Is this value a failed query's sentinel? Matches the prefix, at any depth.

    A sentinel arrives as a CELL inside a row as often as it arrives as a whole
    side -- `[(QUERY_ERROR,)]` is what a one-column query that failed looks like
    after a helper swallowed the error -- so the walk is the point rather than a
    convenience. Strings only: a tuple is walked, not tested.
    """
    if isinstance(v, str):
        return v.startswith(_prefix)
    if isinstance(v, (list, tuple, set, frozenset)):
        return any(_failed_query(x, _prefix) for x in v)
    return False

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


def _is_sqlstate(v):
    # Five characters of [0-9A-Z], per SQL/PostgreSQL. Explicit ranges rather than
    # str.isdigit(), which is True for other scripts' digits.
    return (isinstance(v, str) and len(v) == 5
            and all(("0" <= c <= "9") or ("A" <= c <= "Z") for c in v))


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
    def _refuse_failed_query(self, name, got, want):
        """Refuse a comparison where either side is a failed query.

        ONE definition, called by every comparison, so an assertion added later
        inherits it instead of being the next hole. `hash` had its own copy of this
        and four other assertions had none: `text`, `rows`, `row_set` (which
        delegates to `rows`) and `ordered_rows` each passed with the sentinel on
        both sides, which is `error-swallowed-to-empty` exactly -- two queries
        raise, a helper turns each into the same value, and they compare equal.
        """
        for side, v in (("left", got), ("right", want)):
            if _failed_query(v):
                raise VacuityError(
                    f"{name}: the {side} side is a failed query: {v!r}. Two failures "
                    f"compare equal, so this assertion cannot fail. Use "
                    f"query_error() so each failure is distinct, and assert the "
                    f"failure you expect rather than comparing two of them."
                )

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

    def row_set(self, got, want, name, allow_empty=None):
        """Compare two result sets as SETS, order deliberately ignored.

        The counterpart to ordered_rows, and the port of pgc_set_hash. It exists so
        that ignoring order is DECLARED rather than smuggled in by sorting at the
        call site: `ordered_rows(sorted(x), ...)` reads like an ordering claim and is
        not one, which is why the collection scan refuses it.

        pgc_check_ordered_oracle asserts three things, and this is the third: the set
        oracle must be order-blind BY DESIGN. Without a control proving the two
        instruments differ, an ordered oracle could quietly be implemented as a set
        one and every ordering test in the tree would go silent.
        """
        # BEFORE the repr mapping, not after. row_set hands `rows` a list of repr
        # STRINGS, and `repr(("QUERY_ERROR.1",))` is `"('QUERY_ERROR.1',)"` -- which
        # does not start with the prefix, so the refusal inside `rows` cannot see a
        # sentinel that arrived as a cell. Delegating an assertion does not delegate
        # its refusals when the delegation transforms the data.
        self._refuse_failed_query(name, got, want)
        self.rows(sorted(map(repr, got)), sorted(map(repr, want)), name,
                  allow_empty=allow_empty)

    # -- ordered sequences ---------------------------------------------------
    def ordered_rows(self, got, want, name):
        """Compare two sequences IN ORDER, refusing the cases where order says nothing.

        This is the port of `pgc_seq_hash` and `diff_query_ordered`, which the harness
        has had since #418 and this layer did not. It compares the sequences rather
        than hashing them, for the same reason `rows` does: a mismatch names the
        position, where a hash mismatch only says two hashes differ.

        THE REFUSAL THAT MATTERS IS THE SECOND ONE. A sequence whose elements are all
        equal reads the same forwards and backwards, so an ordering claim about it
        cannot fail. That is `pgc_check_ordered_oracle`'s premise inverted: the bash
        version proves its oracle order-sensitive by requiring forward != reverse on a
        known fixture, and the same requirement applied to a caller's data is what
        stops an ordered assertion being decorative.
        """
        g, w = list(got), list(want)
        if not g and not w:
            raise VacuityError(
                f"{name}: both sequences are empty, so this comparison could not "
                f"have failed. Use rows(..., allow_empty='why') if empty is the point."
            )
        self._refuse_failed_query(name, g, w)
        if len(set(map(repr, g))) < 2 and len(set(map(repr, w))) < 2:
            raise VacuityError(
                f"{name}: order cannot be observed in these sequences. Every element "
                f"is the same, so the reverse ordering is identical and the claim "
                f"asserts nothing beyond what rows() already asserts."
            )
        self._counted()
        if g != w:
            for i, (a, b) in enumerate(zip(g, w)):
                if a != b:
                    raise AssertionError(
                        f"{name}: first difference at position {i}: got {a!r} want {b!r}"
                    )
            raise AssertionError(
                f"{name}: same prefix, different length: got {len(g)} rows want {len(w)}"
            )

    def ordering_observable(self, forward, reverse, name):
        """Assert this fixture can distinguish order at all, before relying on it.

        `pgc_check_ordered_oracle` ported. Read the same rows both ways and require
        the two to differ: a fixture that reads identically forwards and backwards
        supports no ordering claim, and every ordered assertion over it is vacuous
        however carefully it is written.
        """
        # A FAILED QUERY ON EITHER SIDE, BEFORE ANYTHING ELSE. This assertion takes
        # (forward, reverse) rather than (got, want), so it sat outside the refusal --
        # and making the sentinel UNIQUE turned a loud red into a silent pass here.
        # Measured by @jdatcmd: with the old constant, two failed readings were
        # identical and this arm went RED; with two minted sentinels they differ, so it
        # went GREEN and greenlit every ordered assertion resting on the premise. That
        # was the one place the producer made the layer strictly weaker than before.
        self._refuse_failed_query(name, forward, reverse)
        f, r = list(forward), list(reverse)
        if not f and not r:
            raise VacuityError(f"{name}: both directions are empty.")
        self._counted()
        if f == r:
            raise AssertionError(
                f"{name}: the forward and reverse readings are identical, so nothing "
                f"in this fixture can detect an ordering error. Give it rows whose "
                f"order is observable before asserting order."
            )

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
        self._refuse_failed_query(name, got, want)
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
        # The same definition the others use. This was the only assertion that
        # refused a sentinel, and it did so with its own copy of the test.
        self._refuse_failed_query(name, got, want)
        if _empty(got) and _empty(want):
            raise VacuityError(f"{name}: both hashes are empty.")
        self._counted()
        if got != want:
            raise AssertionError(f"{name}: got {got!r} want {want!r}")

    # -- text --------------------------------------------------------------
    def text(self, got, want, name):
        """Compare text exactly. Refuses an empty expectation and a failed query."""
        self._refuse_failed_query(name, got, want)
        if _empty(want):
            raise VacuityError(
                f"{name}: the expected text is empty, so anything empty satisfies it."
            )
        self._counted()
        if got != want:
            raise AssertionError(f"{name}: got {got!r} want {want!r}")

    # -- SQLSTATE ----------------------------------------------------------
    def sqlstate(self, exc, want, name):
        """Assert a raised database error carries EXACTLY this SQLSTATE.

        `pytest.raises(psycopg.Error)` asserts that one of 254 SQLSTATEs arrived,
        across 42 SQLSTATE classes -- measured against psycopg 3.3.5 in the audit
        container by counting the classes in `psycopg.errors` that carry a
        `sqlstate` and subclass `psycopg.Error`. An unrelated failure of the same
        family satisfies it, and the worst case is not even a server error: a
        connect to a socket that does not exist raises `OperationalError` with
        `sqlstate` None, having never reached a server at all.

        So this is the typed field that says WHICH error, and it is the same move
        `plan_marker` makes: a typed field rather than a substring of a message.
        `str(exc.value).count("does not exist")` is the grep this layer exists to
        remove, wearing a different spelling.

        `want` may be a tuple when an error code legitimately differs across
        majors -- this tree supports 15 through 19. Every member is still checked
        to be a real SQLSTATE, so a tuple widens the claim by exactly the codes it
        names and no further.

        Refuses, rather than compares:

        - a `want` that is not five characters of [0-9A-Z]. `""` and `None` are
          satisfied by nothing, and `"42"` is a SQLSTATE CLASS -- a prefix claim
          wearing the spelling of an exact one.
        - an `exc` with no `sqlstate` attribute at all. The usual cause is passing
          pytest's `ExceptionInfo` instead of `exc.value`, which would otherwise
          compare `None` against a real SQLSTATE for ever.
        """
        wants = tuple(want) if isinstance(want, (tuple, list)) else (want,)
        if not wants:
            raise VacuityError(
                f"{name}: an empty set of SQLSTATEs is satisfied by nothing, so "
                f"this could not have passed and asserts nothing about which "
                f"error arrived."
            )
        for w in wants:
            if not _is_sqlstate(w):
                raise VacuityError(
                    f"{name}: {w!r} is not a SQLSTATE. A SQLSTATE is five "
                    f"characters of [0-9A-Z]; a two-character class is a prefix "
                    f"claim, and an empty one names no error."
                )
        if not hasattr(exc, "sqlstate"):
            raise VacuityError(
                f"{name}: a {type(exc).__name__} carries no sqlstate, so this "
                f"comparison is about the wrong object. Pass the exception itself: "
                f"`exc.value` inside a `with pytest.raises(...) as exc` block, not "
                f"`exc`."
            )
        self._counted()
        got = exc.sqlstate
        if got is None:
            raise AssertionError(
                f"{name}: a {type(exc).__name__} carrying no SQLSTATE, so the "
                f"failure never reached the server: {exc}. Wanted {want!r}."
            )
        if got not in wants:
            raise AssertionError(f"{name}: got SQLSTATE {got!r} want {want!r}")

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
    # Both, not just the argument: _RunShape may already have escalated this run
    # to 1 for a lost test, and `exitstatus` is the value from before that.
    if exitstatus == 0 and session.exitstatus == 0:
        session.exitstatus = EXIT_INCOMPLETE


# THE RUN'S OWN SHAPE, HELD PER SESSION.
#
# Three modes remove many tests at once while the run reads green, so they are worth
# more than any per-assertion guard. Counting collected tests cannot see them: a
# crashed xdist worker loses its remaining tests and the collected count is still
# right. Measured under --max-worker-restart=0: 8 collected, summary "1 failed,
# 6 passed", one named test never reported, and pytest printed no warning.
#
# AN INSTANCE PER CONFIG, NOT MODULE GLOBALS. pytester.runpytest() runs the inner
# session IN-PROCESS, so module-level sets are shared between the layer's own tests
# and the sessions they drive. Measured before this was fixed: 44 tests passed and
# the run exited 1, because the outer session had inherited every inner run's
# collected ids and setup skips. State that belongs to a session has to live on the
# session.
class _RunShape:
    def __init__(self):
        self.collected = set()
        self.reported = set()
        self.setup_skips = []

    def pytest_collection_modifyitems(self, items):
        # Fires in the controller when running serially, and in each worker under
        # xdist. Harmless in a worker: the worker's own sessionfinish returns early.
        self.collected.update(i.nodeid for i in items)

    def pytest_deselected(self, items):
        """Deselection is not loss, and the difference is the whole guard.

        `pytest_collection_modifyitems` above fires before pytest's own -k and -m
        filtering has removed anything, so without this hook every deselected test
        looks like a test that vanished without reporting. Measured before the fix:
        `pytest -q test_layer.py -k refus` gave "1 passed, 15 deselected" and then
        exit 1 with "15 collected test(s) never reported an outcome". That is a
        false red on a healthy run, produced by the guard whose subject is false
        greens -- and the first thing anyone does about it is stop using -k.

        Asking for a subset is a deliberate act by whoever typed the command. A
        test lost to a crashed worker is not. This hook is where pytest tells the
        difference, so it is where the guard has to learn it.
        """
        self.collected.difference_update(i.nodeid for i in items)

    def pytest_xdist_node_collection_finished(self, node, ids):
        """Under xdist the WORKERS collect, not the controller.

        Measured: with -n 2 the controller's collected set stayed empty, so the
        reconciliation had nothing to compare and a crashed worker's lost tests went
        unreported -- the guard was there and blind. xdist hands the controller each
        node's collected ids through this hook, which is the only place the
        controller learns what was found.
        """
        self.collected.update(ids)

    def pytest_runtest_logreport(self, report):
        """Record that a test produced an outcome, and catch a skip during SETUP.

        A skip in setup is how one fixture removes every test that depends on it: a
        session fixture calling pytest.skip() turns "the cluster would not start"
        into exit 0. expect.cannot_run does not skip, it records a counted
        assertion, so any skip arriving here came from somewhere else.
        """
        if report.when == "call" or (report.when == "setup"
                                     and report.outcome != "passed"):
            self.reported.add(report.nodeid)
        if report.when == "setup" and report.skipped:
            self.setup_skips.append(report.nodeid)

    def pytest_sessionfinish(self, session, exitstatus):
        # Only the process holding the whole picture can reconcile: an xdist worker
        # sees a slice, and the controller receives every worker's reports.
        if hasattr(session.config, "workerinput"):
            return
        problems = []
        missing = sorted(self.collected - self.reported)
        if missing:
            problems.append(
                f"{len(missing)} collected test(s) never reported an outcome, so the "
                f"run lost them silently: " + ", ".join(missing[:5])
                + (" ..." if len(missing) > 5 else "")
            )
        if self.setup_skips:
            problems.append(
                f"{len(self.setup_skips)} test(s) were skipped during setup, which is "
                f"how one fixture removes every test that depends on it: "
                + ", ".join(sorted(self.setup_skips)[:5])
                + (" ..." if len(self.setup_skips) > 5 else "")
                + " -- use expect.cannot_run(REASON, detail) in the test instead"
            )
        if problems:
            print("\nVACUITY: " + " AND ".join(problems))
            session.exitstatus = 1


def pytest_configure(config):
    # Two independent per-session mechanisms, both registered here because a
    # plugin module may define pytest_configure only once.
    collector = _UnrunnableCollector()
    config.pluginmanager.register(collector, "pgc_unrunnable_collector")
    config.pgc_unrunnable = collector
    config.pluginmanager.register(_RunShape(), f"pgc_runshape_{id(config)}")


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
# An ordered claim whose inputs were SORTED cannot fail on order.
#
# ordered_rows is order-sensitive, so the vacuity is introduced at the call site:
# `expect.ordered_rows(sorted(got), sorted(want))` compares two sequences that were
# just put in the same order. This is the collapse VACUITY_MODES.md records as
# set-oracle-on-an-ordered-claim, and lib.sh has no equivalent because bash has no
# sorted() to reach for.
#
# Parsed, not grepped, for the same reason as the except scan below.
_ORDER_KILLERS = ("sorted", "set", "frozenset")


def _order_killed_names(fn):
    """Names bound to an order-killing value earlier in one function body.

    -> {name: (lineno, how)}

    The inline spelling is only the shortest way to write the collapse. These two
    are the same defect and read as more careful code, which is worse:

        g = sorted(got)                 # bound to an order-killing call
        expect.ordered_rows(g, want)

        got.sort()                      # killed in place
        expect.ordered_rows(got, want)

    WHAT THIS DOES NOT SEE, stated because a guard's blind spots are part of its
    meaning: it is one function deep, so a helper that sorts and returns is invisible;
    it does not follow aliases (`h = g`), attributes (`self.rows.sort()`), branches,
    or a name re-bound to something honest after being killed. It is a floor, not a
    proof of order-sensitivity. The suite's own removal proofs are what establish
    that an ordered claim can actually fail on order.
    """
    killed = {}
    for node in ast.walk(fn):
        # X = sorted(...) / set(...) / frozenset(...)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Name) and f.id in _ORDER_KILLERS:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        killed.setdefault(t.id, (node.lineno, f"{f.id}()"))
        # X.sort() -- in place, and the name keeps its spelling at the call site
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            f = node.value.func
            if (isinstance(f, ast.Attribute) and f.attr == "sort"
                    and isinstance(f.value, ast.Name)):
                killed.setdefault(f.value.id, (node.lineno, ".sort()"))
    return killed


def _sorted_ordered_sites(path):
    try:
        tree = ast.parse(pathlib.Path(path).read_text())
    except (OSError, SyntaxError):
        return []
    out = []
    name = pathlib.Path(path).name
    # Per function, because a killed name means nothing outside the body that
    # killed it, and a module-level walk would carry one test's `g` into the next.
    fns = [n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in fns:
        killed = _order_killed_names(fn)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr in ("ordered_rows",
                                                                "ordering_observable")):
                continue
            for arg in node.args:
                if (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                        and arg.func.id in _ORDER_KILLERS):
                    out.append(
                        f"{name}:{node.lineno} {arg.func.id}() feeds an ordered claim"
                    )
                elif isinstance(arg, ast.Name) and arg.id in killed:
                    where, how = killed[arg.id]
                    # Only a kill that already happened. A name sorted AFTER the
                    # claim was made did not affect it, and flagging that would be
                    # a false red -- the thing this whole layer exists to refuse.
                    if where < node.lineno:
                        out.append(
                            f"{name}:{node.lineno} {arg.id} was order-killed by "
                            f"{how} at line {where} and feeds an ordered claim"
                        )
    return out


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


def _walk_own(node):
    """Walk one function body, NOT descending into a nested def or lambda.

    A nested function is its own scope. `ast.walk` would attribute its `with`
    blocks to the outer function as well, reporting one site twice under two
    different sets of pinned names.
    """
    stack = list(getattr(node, "body", []))
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        stack.extend(ast.iter_child_nodes(child))


def _raises_class_names(arg):
    """The tail identifiers a pytest.raises() first argument names.

    `psycopg.Error` -> ["Error"]. `(ValueError, psycopg.Error)` -> both.

    A TUPLE IS THE SHAPE PEOPLE ACTUALLY WRITE, and it is how a narrow claim gets
    widened under pressure. The broad-except scan paid for that lesson already:
    it looked only at a bare `ast.Name`, so `except Exception` was refused while
    `except (ValueError, Exception)` passed (@jdatcmd, #905 review). Same hole,
    same shape, closed here before it was shipped rather than after.
    """
    out = []
    for node in (arg.elts if isinstance(arg, ast.Tuple) else [arg]):
        if isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
    return out


def _root_name(node):
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _sqlstate_pinned_names(fn):
    """Names whose SQLSTATE this function body ASSERTS something about.

    Two spellings, because both are honest and the scan must accept whichever the
    caller chose:

        expect.sqlstate(exc.value, "42883", name)        # the helper
        expect.text(exc.value.sqlstate, "42883", name)   # the field, read directly

    THE ATTRIBUTE HAS TO REACH A CALL. The first version counted any `ast.Attribute`
    named `sqlstate` anywhere in the body, so MENTIONING the field switched the rule
    off. Measured, both collecting clean against the first version and both being the
    exact vacuity this rule is named for -- any of the 254 SQLSTATEs satisfies them:

        exc.value.sqlstate                    # a bare expression, asserts nothing
        code = exc.value.sqlstate             # assigned, never read

    Reported by @jdatcmd, who ran the scanner over six constructed files rather than
    reading it.

    So a read counts when it is an ARGUMENT to a call, and one hop of assignment is
    followed -- `code = exc.value.sqlstate` then `expect.text(code, ...)` is honest and
    common, and refusing it would be a false positive on a form nobody should have to
    stop writing. A second hop is not followed: this is a floor, and the floor is
    stated rather than implied.
    """
    pinned = set()
    # Names a sqlstate read was assigned to, and names that appear as call arguments.
    assigned_from_sqlstate = {}
    call_arg_names = set()
    for node in _walk_own(fn):
        if isinstance(node, ast.Call):
            for arg in list(node.args) + [k.value for k in node.keywords]:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Name):
                        call_arg_names.add(sub.id)
                    if isinstance(sub, ast.Attribute) and sub.attr == "sqlstate":
                        root = _root_name(sub.value)
                        if root:
                            pinned.add(root)
        if isinstance(node, ast.Assign):
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Attribute) and sub.attr == "sqlstate":
                    root = _root_name(sub.value)
                    for t in node.targets:
                        if isinstance(t, ast.Name) and root:
                            assigned_from_sqlstate[t.id] = root
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "sqlstate"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name):
                    pinned.add(sub.id)
    # One hop: assigned from a sqlstate read, and later handed to a call.
    for local, root in assigned_from_sqlstate.items():
        if local in call_arg_names:
            pinned.add(root)
    return pinned


# Every statement that can HOLD other statements. Built by lookup rather than
# written out, because `TryStar` and `Match` exist only on newer Pythons and a
# missing name would be a NameError at import rather than a rule that quietly does
# less. The inventory named only the `for` spelling; a rule catching only that one
# would leave three spellings of the same shape, which is closing an example rather
# than a mode.
_COMPOUND_STATEMENTS = tuple(
    c for c in (getattr(ast, n, None) for n in (
        "For", "AsyncFor", "While", "If", "With", "AsyncWith", "Try", "TryStar",
        "Match",
    )) if c is not None
)


def _raises_sites(path):
    """Every `with pytest.raises(...)` in one file, and what is wrong with it.

    PARSED, NOT GREPPED, and `test_layer.py` is why. The layer's own tests drive an
    inner pytest run, so the forbidden shape appears inside a `pytester.makepyfile`
    STRING in the very file that proves the guard. A line regex fires on it. That
    is the false positive the broad-except scan already paid for once, and a guard
    that rejects legitimate tests gets switched off -- after which the thing it
    replaced is gone too. A call inside a string literal is not an `ast.Call`.

    WHAT THIS DOES NOT SEE, stated because a guard's blind spots are part of its
    meaning. It reads `with` blocks inside functions, so a `raises` at module level
    or used as a plain call (`pytest.raises(E, fn, arg)`) is invisible. It counts
    TOP-LEVEL statements in the block, so a single `for` or `if` holding several
    statements counts as one, and a call to a helper that performs the setup counts
    as one as well -- those two shapes are why `raises-catches-setup` stays open in
    `VACUITY_MODES.md` section 3.4, and each has an arm in
    `test_raises_sqlstate.py` asserting this scan reports nothing on it. It does
    not follow a SQLSTATE pin into a helper, and it matches a pin by name, so an
    unrelated argument that happens to share the bound name's spelling would
    satisfy it. It is a floor, not a proof that the assertion is about the
    statement under test.
    """
    # A BROAD pytest.raises IS SATISFIED BY AN UNRELATED FAILURE OF THE SAME FAMILY.
    #
    # Measured against psycopg 3.3.5 in the audit container, by counting the classes
    # in `psycopg.errors` that carry a `sqlstate` and subclass each family:
    #
    #     psycopg.Error             254 SQLSTATEs   42 SQLSTATE classes
    #     psycopg.DatabaseError     254             42
    #     psycopg.OperationalError   88             15
    #     psycopg.DataError          68              1
    #     psycopg.ProgrammingError   57             10
    #     psycopg.InternalError      20              5
    #     psycopg.IntegrityError      7              1
    #     psycopg.NotSupportedError   1              1
    #     psycopg.Warning             0              0
    #     psycopg.InterfaceError      0              0
    #
    # `pytest.raises(psycopg.Error)` therefore claims "one of 254 server errors
    # arrived", and does not even claim that: measured on this tree, a connect to a
    # socket that does not exist raises OperationalError with sqlstate None, so
    #
    #     with pytest.raises(psycopg.Error):
    #         conn = psycopg.connect("host=/nonexistent-socket-dir dbname=pgc")
    #         conn.execute("SELECT pgc_definitely_no_such_function()")
    #
    # reported `1 passed`, exit 0, with the statement under test never executed.
    #
    # WHY THIS LIST AND NOT THE WHOLE FAMILY, and it is the measurement above
    # deciding it rather than taste. `Warning` and `InterfaceError` cover ZERO
    # SQLSTATEs, so demanding one of them would be a guard nobody could satisfy --
    # and an unsatisfiable guard is how a guard gets switched off. The four
    # intermediate DB-API classes are not refused either: narrowing to one of them
    # is already a real claim about the error, and OperationalError legitimately
    # arrives with no SQLSTATE when the connection itself failed.
    #
    # WHY IT IS BOUND HERE AND NOT AT MODULE LEVEL. A rule's own parameters must not
    # be reachable from the tree the rule polices. Any `conftest.py` under
    # `test/pytest/` is imported before collection, so a module-level tuple can be
    # rewritten from the corpus:
    #
    #     import pgc_vacuity
    #     pgc_vacuity.<the tuple> = ()
    #
    # after which this scan reports zero offences for ever and the suite is green.
    # Bound inside the function, those lines do nothing -- the name is not looked up
    # in the module namespace at all. (Rebinding this FUNCTION from a conftest is
    # still possible. That is true of every name in every Python plugin and is not
    # something the placement of a tuple can fix. What notices a scan that stopped
    # being CALLED is selftest 440, which requires the wiring line in the collection
    # hook, plus the 5 arms in `test_raises_sqlstate.py` that match the refusal on
    # stderr -- measured, as mutation M5 of that suite's removal proof: deleting the
    # wiring reddens those same 5. `test_guards_pinned.py` is the layer's census of
    # "every refusal pinned to its own message" and does NOT yet carry these two;
    # adding them there is the honest next step, and saying so is better than citing
    # a file that does not mention them.)
    broad_families = ("Error", "DatabaseError", "Exception", "BaseException")

    try:
        tree = ast.parse(pathlib.Path(path).read_text())
    except (OSError, SyntaxError):
        return []
    out = []
    name = pathlib.Path(path).name
    # EVERY FUNCTION THIS FILE DEFINES, nested ones included. A `pytest.raises` block
    # whose one statement calls one of these is the helper shape: the helper can run
    # any number of statements and nothing in the block says which of them failed. A
    # call to an IMPORTED function, or a method, is the thing under test -- which is
    # the shape all five blocks in this corpus use, so the rule turns on where the
    # function is DEFINED rather than on the statement being a call.
    local_defs = {n.name for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        pinned = _sqlstate_pinned_names(fn)
        for node in _walk_own(fn):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            sites = []
            for item in node.items:
                call = item.context_expr
                if not isinstance(call, ast.Call):
                    continue
                f = call.func
                tail = (f.attr if isinstance(f, ast.Attribute)
                        else f.id if isinstance(f, ast.Name) else None)
                if tail != "raises":
                    continue
                # THE CLASS MAY ARRIVE BY KEYWORD. `not call.args` skipped the item
                # BEFORE it was appended, so `pytest.raises(expected_exception=E)`
                # was checked by neither rule -- and the statement rule was therefore
                # silently conditional on the class being positional, which the
                # documentation stated unconditionally. Reported by @jdatcmd, who
                # built the positional and keyword forms as a pair that differ in
                # nothing else: the positional one was an offence and the keyword one
                # was clean.
                expected = None
                if call.args:
                    expected = call.args[0]
                else:
                    for kw in call.keywords:
                        if kw.arg == "expected_exception":
                            expected = kw.value
                            break
                if expected is None:
                    continue
                sites.append(item)
                bound = (item.optional_vars.id
                         if isinstance(item.optional_vars, ast.Name) else None)
                broad = [c for c in _raises_class_names(expected)
                         if c in broad_families]
                if broad and (bound is None or bound not in pinned):
                    # THE OFFENCE PHRASE STAYS ON ONE SOURCE LINE, and the reason
                    # has CHANGED. It was selftest 440, which grepped this source for
                    # the phrase and counted the copies, so a split into
                    # `"... names no " f"SQLSTATE"` read identically at runtime while
                    # the count saw one where it wanted two. **Selftest 440 no longer
                    # exists** -- #927 deleted it under the harness-independence rule,
                    # because a shell part asserting a text pin cannot prove a python
                    # arm is caught. Nothing greps this source for the phrase today, so
                    # the one-line form is now a convention rather than a guarded
                    # property. What IS still load-bearing is the RUNTIME string: the
                    # arms in test_raises_sqlstate.py match it against stderr, and a
                    # split f-string would not change that at all.
                    where = f"{name}:{call.lineno}"
                    out.append(
                        f"{where} pytest.raises({broad[0]}) names no SQLSTATE"
                    )
            # THE RAISER HAS TO BE THE STATEMENT UNDER TEST. Once per `with`, not
            # once per item: two raises in one `with` share one body.
            if sites and len(node.body) != 1:
                # One source line for this phrase too, for the reason above.
                held = f"{name}:{node.lineno} the pytest.raises block holds"
                out.append(
                    f"{held} {len(node.body)} statements, "
                    f"so which one raised is not pinned"
                )
            # AND ONE STATEMENT IS NOT ENOUGH, which is the half `raises-catches-setup`
            # stayed open on. Two shapes are one top-level statement and still hide the
            # setup inside the block, so the count rule above saw nothing:
            #
            #     with pytest.raises(...): _setup_then_run(conn)   # a helper call
            #     with pytest.raises(...):                         # a compound
            #         for stmt in (setup, under_test): run(stmt)
            #
            # Both were measured reporting `1 passed`, exit 0, zero offences, with the
            # setup raising and the statement under test never running. The fix is not a
            # RECURSIVE count -- that would also refuse a legitimate single-statement
            # loop -- it is a claim about which statement raised.
            elif sites:
                only = node.body[0]
                kind = type(only).__name__
                if isinstance(only, _COMPOUND_STATEMENTS):
                    # One source line for the phrase, as above.
                    out.append(
                        f"{name}:{node.lineno} the pytest.raises block holds a {kind}, "
                        f"so which statement inside it raised is not pinned"
                    )
                else:
                    # ANYWHERE IN THE STATEMENT, not only as the whole of it: a helper
                    # hides just as well in `x = _helper()` or `assert _helper()` as it
                    # does in a bare call.
                    called = sorted({
                        n.func.id for n in ast.walk(only)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in local_defs
                    })
                    if called:
                        out.append(
                            f"{name}:{node.lineno} the pytest.raises block calls "
                            f"{called[0]}(), defined in this file, so which statement "
                            f"raised is not pinned"
                        )
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
            mk = item.get_closest_marker(marker)
            if mk is None:
                continue
            why = str(mk.kwargs.get("reason", "")) or (str(mk.args[0]) if mk.args else "")
            if "empty parameter set" in why:
                continue    # reported below, with a message about the real cause
            offenders.append(f"{item.name} carries a bare @pytest.mark.{marker}")
        f = str(getattr(item, "fspath", "") or "")
        if f and f not in seen_files:
            seen_files.add(f)
            for site in _broad_except_sites(f):
                offenders.append(f"{site} catches Exception broadly")
            offenders.extend(_sorted_ordered_sites(f))
            offenders.extend(_raises_sites(f))

    # An empty parametrize is not a bare skip and deserves its own message: pytest
    # generates ONE skipped placeholder for an empty argvalues list, so a corpus glob
    # that matched nothing turns a data-driven suite into a single "s" and exit 0.
    empty_params = []
    for item in items:
        m = item.get_closest_marker("skip")
        reason = ""
        if m is not None:
            reason = str(m.kwargs.get("reason", "")) or (
                str(m.args[0]) if m.args else "")
        if "empty parameter set" in reason:
            empty_params.append(f"{item.name}: {reason}")
    if empty_params:
        raise pytest.UsageError(
            "the pgColumnar vacuity layer refuses this run: a parametrize over an "
            "empty parameter set produces one skipped placeholder and exits 0, so a "
            "corpus that matched nothing reads as a suite that ran: "
            + "; ".join(empty_params)
            + " -- assert the corpus is non-empty before parametrizing over it."
        )
    if offenders:
        # One hook, two offences, so the message must say which. An earlier version
        # reused the skip wording and told a reader with a broad `except` to call
        # expect.cannot_run, which would not have helped them.
        skips = [o for o in offenders if "@pytest.mark." in o]
        excepts = [o for o in offenders if "catches Exception broadly" in o]
        ordered = [o for o in offenders if "feeds an ordered claim" in o]
        raises_broad = [o for o in offenders if "names no SQLSTATE" in o]
        # THE FILTER IS THE COMMON TAIL OF ALL THREE PHRASES. It was the exact
        # sentence of the statement-COUNT rule, so the two rules added for the helper
        # and compound shapes refused the run and then printed NOTHING -- the layer
        # said "refuses this run: ." and the arms could not tell a fired rule from an
        # unfired one. Measured: both new arms reddened on a missing message while the
        # refusal itself was working.
        raises_setup = [o for o in offenders if "raised is not pinned" in o]
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
        if ordered:
            parts.append(
                "sorted() or set() feeding an ordered claim removes the very "
                "ordering it asserts: "
                + "; ".join(ordered)
                + " -- pass the rows in the order the query returned them"
            )
        if raises_broad:
            parts.append(
                "pytest.raises over a whole error family is satisfied by an "
                "unrelated failure of the same family, and psycopg.Error covers "
                "254 SQLSTATEs while a failed connect carries none at all: "
                + "; ".join(raises_broad)
                + " -- pin the error with expect.sqlstate(exc.value, '42883', name)"
                  ", or name the specific exception class"
            )
        if raises_setup:
            parts.append(
                "a pytest.raises block must say WHICH statement raised, or a "
                "failure in the SETUP passes for a failure in the statement under "
                "test -- more than one statement, a compound statement holding "
                "several, or a call to a helper defined in the same file all hide it: "
                + "; ".join(raises_setup)
                + " -- move the setup above the block, leaving the statement under "
                  "test alone inside it"
            )
        raise pytest.UsageError(
            "the pgColumnar vacuity layer refuses this run: " + ". ".join(parts) + "."
        )
