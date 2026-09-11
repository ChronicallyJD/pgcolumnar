"""Every counted assertion produces a record, and the count is derived from them.

#937. The shell harness records every check outcome as a machine-readable line,
and `pgc_record` counts and records in one call so no path can do either alone.
`pgc_reconcile_records` then reconciles the record count against `checks run:`.

THE PYTEST HALF REACHED THE SAME PROPERTY THROUGH PYTHON RATHER THAN THROUGH THE
SHELL'S FORMAT, which is what "parallel in functionality only" requires. Nothing
here reads, sources or derives from `test/*.sh`; `test_harness_deps.py` proves
that for the whole corpus rather than this file asserting it about itself.

AND IT IS STRONGER THAN THE SHELL'S, because Python can remove the possibility
instead of policing it. The shell keeps a counter and a record stream honest by
reconciling two variables that could drift. Here the count IS the record stream:

    @property
    def count(self):
        return len(self._records)

A derived count cannot be incremented without a record existing. That is property
1 of #937 reached by construction rather than by discipline, and the arms below
attack the construction rather than trusting the sentence.

Measured before this file existed: `_counted()` at 15 call sites, `self.count`
incremented by one line and read by one (`pytest_runtest_call`), and ZERO
per-assertion records anywhere.
"""

import pgc_vacuity


def test_each_counted_assertion_appends_exactly_one_record(expect):
    """Three assertions, three records. The premise is that a fresh recorder has
    none, or the arm would pass on a recorder that ignored every call."""
    e = pgc_vacuity.Expect("records::one-each")
    expect.num(len(e.records), 0, "premise: a fresh recorder holds no records")
    e.num(1, 1, "first")
    e.num(2, 2, "second")
    e.num(3, 3, "third")
    expect.num(len(e.records), 3, "three assertions left three records")


def test_the_count_is_the_record_stream(expect):
    """Not "the count agrees with the records" -- that is the shell's property,
    and it needs a reconciliation because the two can drift. Here they are the
    same object, so the arm asserts identity of the NUMBER at every step rather
    than equality at the end."""
    e = pgc_vacuity.Expect("records::derived")
    seen = []
    for i in range(4):
        e.num(i, i, f"assertion {i}")
        seen.append((e.count, len(e.records)))
    expect.rows([f"{c}/{r}" for c, r in seen],
                ["1/1", "2/2", "3/3", "4/4"],
                "the count tracks the records at every step")


def test_the_count_cannot_be_moved_without_a_record(expect):
    """THE CONSTRUCTION PROOF, and the reason this is not just a second counter.

    A test that only checked `count == len(records)` after a run would pass on an
    implementation that keeps two variables and happens to update both. This
    asserts the count cannot be written at all, which is what makes the agreement
    structural rather than maintained.
    """
    e = pgc_vacuity.Expect("records::readonly")
    e.num(1, 1, "one assertion")
    try:
        e.count = 99
    except AttributeError:
        expect.num(e.count, 1, "the count refused to be written and did not move")
    else:
        raise AssertionError(
            "the count was assignable, so it is a second variable that can drift "
            "from the records rather than being derived from them"
        )


def test_a_record_names_the_assertion_that_made_it(expect):
    """A record that cannot be traced to a call site answers no question worth
    asking. The names are asserted IN ORDER, because the order is what lets a
    later phase say which assertion failed."""
    e = pgc_vacuity.Expect("records::named")
    e.num(1, 1, "the first question")
    e.text("a", "a", "the second question")
    e.num(2, 2, "the third question")
    expect.ordered_rows([r.name for r in e.records],
                        ["the first question", "the second question",
                         "the third question"],
                        "each record carries the name its call site gave")


def test_a_refused_assertion_leaves_no_record(expect):
    """A VacuityError means the assertion never ran, so it is not an outcome.

    This is the arm that stops the record stream becoming a log of attempts. It
    matters for the reconciliation in phase 5: a refused assertion that left a
    record would make the totals disagree with what the run reported.
    """
    e = pgc_vacuity.Expect("records::refused")
    try:
        e.num("100", 100, "a text comparison")
    except pgc_vacuity.VacuityError:
        expect.num(len(e.records), 0, "a refused assertion recorded nothing")
    else:
        raise AssertionError("num() accepted a string, so this arm tested nothing")


def test_a_name_carrying_a_separator_survives_the_record(expect):
    """#937 property 3, asserted rather than assumed.

    The shell had to strip tabs and newlines from a check name because its record
    is a tab-separated line: a name with a tab gave four fields, and a name with a
    newline gave two lines. The record here is an object, so there is no separator
    to smuggle -- but that must be a test, because the moment somebody formats
    these into a line the class of defect comes back and nothing would say so.
    """
    e = pgc_vacuity.Expect("records::separators")
    nasty = "a name with\ta tab and\na newline"
    e.num(1, 1, nasty)
    expect.num(len(e.records), 1, "a name with separators made exactly one record")
    expect.text(e.records[0].name, nasty, "and the name came back byte-identical")


# ---- phase 2: the verdict is resolved where the outcome is known -------------
#
# The first version of this file's comment argued the verdict could be resolved
# from the exception in `pytest_runtest_call`, because assertions are sequential
# and a raise ends the test. @OffgridwithJD refuted it, and this corpus is what
# refutes it: proving a guard REFUSES means catching the AssertionError, which
# five tests do. Measured before the fix:
#
#     count before/mid/after: 0 / 1 / 2
#       record 0  'this comparison must fail'   verdict PASS   <- this one RAISED
#       record 1  'and the test continues'      verdict PASS
#     1 passed
#
# A genuinely failed assertion stayed PASS, in a passing test, with nothing
# reaching the hook to correct it. So the verdict is set on the COMPARISON's own
# path instead, where the outcome is known and no propagation is needed.


def test_a_failed_assertion_records_fail_even_when_the_test_catches_it(expect):
    """THE ARM FOR THE REFUTATION, and the shape five tests in this corpus use.

    Catching the AssertionError is how a test proves a guard refuses. If catching
    it also erased the verdict, every one of those tests would be reporting on a
    record stream that says its deliberate failure passed.
    """
    e = pgc_vacuity.Expect("verdict::caught")
    try:
        e.num(1, 2, "this comparison must fail")
    except AssertionError:
        pass
    expect.num(len(e.records), 1, "premise: the failed assertion was still counted")
    expect.text(e.records[0].verdict, "FAIL",
                "and it is recorded as FAIL, not as a pass the catcher hid")


def test_the_failure_reason_is_the_assertions_own_message(expect):
    """A verdict with no reason sends the reader back to the source to find out
    what happened. The message is the one the assertion already produces, not a
    second one written for the record -- two messages for one failure is how they
    drift."""
    e = pgc_vacuity.Expect("verdict::reason")
    try:
        e.num(1, 2, "one equals two")
    except AssertionError as exc:
        raised = str(exc)
    expect.text(e.records[0].reason, raised,
                "the recorded reason is the message the assertion raised")


def test_the_assertions_before_a_failure_keep_their_verdicts(expect):
    """The verdicts are per assertion, not per test. A test that fails its third
    assertion made two real claims first, and a stream that marked the whole test
    would lose them."""
    e = pgc_vacuity.Expect("verdict::ordering")
    e.num(1, 1, "first, true")
    e.num(2, 2, "second, true")
    try:
        e.num(3, 4, "third, false")
    except AssertionError:
        pass
    e.num(5, 5, "fourth, after the catch")
    expect.ordered_rows([r.verdict for r in e.records],
                        ["PASS", "PASS", "FAIL", "PASS"],
                        "each assertion carries its own verdict, in order")


def test_a_delegated_assertion_records_fail_too(expect):
    """`outcomes` and `refusal` hand the comparison to pytest's own
    `assert_outcomes`, so the AssertionError is raised by code this layer does not
    write and carries a message it did not compose.

    That is the case a verdict passed in at the call site could not cover, and it
    is why the resolution wraps the comparison rather than describing it.
    """
    e = pgc_vacuity.Expect("verdict::delegated")

    class _FakeResult:
        ret = 0

        def assert_outcomes(self, **want):
            raise AssertionError("Outcomes do not match: expected passed=1")

    try:
        e.outcomes(_FakeResult(), "a delegated comparison", passed=1)
    except AssertionError:
        pass
    expect.num(len(e.records), 1, "premise: the delegated assertion was counted")
    expect.text(e.records[0].verdict, "FAIL",
                "and a failure raised by pytest's own code is still recorded")


def test_a_refusal_still_leaves_no_record(expect):
    """The boundary, restated for phase 2 because the resolution wraps a region
    that a refusal must stay outside of.

    Verified statically as well as here: in every recording method, each
    `VacuityError` is raised BEFORE the record is taken, so no refusal is ever
    inside the wrapped region. That is what keeps a refusal out of the stream
    without a special case for `VacuityError` being a subclass of AssertionError.
    """
    e = pgc_vacuity.Expect("verdict::refusal")
    try:
        e.num("100", 100, "a text comparison")
    except pgc_vacuity.VacuityError:
        expect.num(len(e.records), 0, "a refused assertion still records nothing")
    else:
        raise AssertionError("num() accepted a string, so this arm tested nothing")


def test_every_refusal_precedes_its_record(expect):
    """The static half of the arm above, so the invariant cannot drift silently.

    If somebody adds a `VacuityError` after the record is taken, the refusal lands
    inside the wrapped region and starts being recorded as a failed assertion.
    Nothing else in the corpus would notice.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(pgc_vacuity))
    scanned = []
    offenders = []
    for cls in ast.walk(tree):
        if not (isinstance(cls, ast.ClassDef) and cls.name == "Expect"):
            continue
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            recs = [n.lineno for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "_record"]
            if not recs:
                continue
            scanned.append(fn.name)
            for n in ast.walk(fn):
                if (isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
                        and isinstance(n.exc.func, ast.Name)
                        and n.exc.func.id == "VacuityError"
                        and n.lineno > min(recs)):
                    offenders.append(f"{fn.name}:{n.lineno}")
    # THE PREMISE IS THE POPULATION, and it is the difference between "no method
    # offends" and "the scan matched no methods". An empty offender list is the
    # answer to both, and only one of them is good news.
    expect.at_least(len(scanned), 15, "premise: the scan found the recording methods")
    expect.rows(offenders, [], "no refusal is raised after its record is taken",
                allow_empty=True)


def test_every_recording_method_resolves_its_verdict(expect):
    """THE LIST CANNOT DRIFT. A method that takes a record and is not wrapped
    records a PASS it never revisits, so its failures are invisible in the stream
    while the test still fails normally -- nothing else in the corpus would
    notice.

    Derived from the module, not from a list written here: the population is every
    method that calls `_record`, and the claim is that all of them are wrapped.
    A list would have to be updated by whoever adds the sixteenth, which is
    exactly the person who would forget.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(pgc_vacuity))
    recording = []
    for cls in ast.walk(tree):
        if not (isinstance(cls, ast.ClassDef) and cls.name == "Expect"):
            continue
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "_record" for n in ast.walk(fn)):
                recording.append(fn.name)

    expect.at_least(len(recording), 15,
                    "premise: the scan found the recording methods")
    unwrapped = sorted(
        nm for nm in recording
        if not getattr(getattr(pgc_vacuity.Expect, nm), "_pgc_resolves_verdict", False)
    )
    expect.rows(unwrapped, [], "every method that takes a record resolves its verdict",
                allow_empty=True)


def test_a_recording_method_takes_exactly_one_record_per_call(expect):
    """THE INVARIANT THE RESOLUTION RESTS ON, pinned because a mutation showed it
    was assumed.

    `_resolving` marks `self._records[taken]`. Replacing that with
    `self._records[-1]` left the whole corpus green, because one call appends at
    most one record and the two always name it. That is a property of the methods,
    not of the wrapper, and nothing was asserting it.

    If a method ever records twice, `[taken]` and `[-1]` stop agreeing, the
    wrapper marks the first and the second keeps a verdict nobody set. This is the
    arm that says so, rather than the comment.
    """
    e = pgc_vacuity.Expect("records::one-per-call")
    calls = [
        lambda: e.num(1, 1, "num"),
        lambda: e.text("a", "a", "text"),
        lambda: e.rows(["a"], ["a"], "rows"),
        lambda: e.ordered_rows(["a", "b"], ["a", "b"], "ordered_rows"),
        lambda: e.at_least(5, 1, "at_least"),
        lambda: e.differ("x", "y", "differ"),
        lambda: e.row_set(["a"], ["a"], "row_set -- delegates to rows"),
    ]
    deltas = []
    for call in calls:
        before = e.count
        call()
        deltas.append(e.count - before)
    expect.rows([str(d) for d in deltas], ["1"] * len(calls),
                "every call, including the delegating one, took exactly one record")
