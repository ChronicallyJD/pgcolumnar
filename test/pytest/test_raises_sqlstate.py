"""A raised database error must name WHICH error, and the block must hold one statement.

`VACUITY_MODES.md` section 3.4 listed `raises-too-broad` and `raises-catches-setup`
together, and the measurement that opened this file shows why they belong together.
Run on unmodified main at de8fca4, with the layer loaded and nothing skipped:

    with pytest.raises(psycopg.Error):
        conn = psycopg.connect("host=/nonexistent-socket-dir dbname=pgc")
        conn.execute("SELECT pgc_definitely_no_such_function()")
    expect.num(1, 1, "the server rejected the call")

reported `2 passed`, exit 0. The error that satisfied the claim was
`OperationalError` with `sqlstate` None -- it never reached a server, and the
statement the test is about never executed. Against a live PostgreSQL 18.4 the same
shape raised `InvalidName` 42602 from the SETUP line while the statement under test
raises `UndefinedObject` 42704: two different SQLSTATEs satisfy one `raises`.

So there are two properties, and each needs its own arm:

  1. a broad family must be narrowed to a SQLSTATE -- `psycopg.Error` covers 254 of
     them across 42 SQLSTATE classes, measured against psycopg 3.3.5;
  2. the block must hold exactly one statement, or nothing says which one raised.

THE TWO PROPERTIES CLOSE DIFFERENT AMOUNTS, and that asymmetry is the reason the
last three arms exist. Property 1 CLOSES `raises-too-broad`: a broad family with
nothing pinned cannot be collected. Property 2 only MITIGATES
`raises-catches-setup`, because it counts TOP-LEVEL statements: a call to a helper
that performs the setup is one statement, and so is a `for` holding the setup and
the statement under test. `test_a_helper_hiding_the_setup_is_not_refused` and
`test_a_compound_statement_hiding_the_setup_is_not_refused` assert this scan
reports NOTHING on those two shapes, which is why `raises-catches-setup` stays in
`VACUITY_MODES.md` section 3.4 rather than moving to section 2.

THE SCAN IS AST, NOT A LINE REGEX, and this file is the reason. Every arm below
writes the forbidden shape inside a `pytester.makepyfile` string, because that is
how the layer's own tests drive an inner run. A line regex fires on this file and
refuses it -- the false positive the broad-except scan already paid for once.
`test_the_raises_scan_reads_code_not_a_string_literal` pins that.
"""

CONF = "pytest_plugins = ['pgc_vacuity']"


def _inner(pytester, body):
    pytester.makeconftest(CONF)
    pytester.makepyfile(body)
    return pytester.runpytest("-p", "pgc_vacuity")


# ---------------------------------------------------------------------------
# The static scan: which error, and which statement.
# ---------------------------------------------------------------------------

def test_raises_requires_a_sqlstate(pytester, expect):
    """The red test VACUITY_MODES.md section 5 item 4 names, and the real offender.

    Byte for byte the shape measured as `2 passed` on main. It is refused before
    collection finishes, so it cannot run at all rather than running and passing.
    """
    pytester.makepyfile(
        """
        import psycopg
        import pytest

        def test_an_unknown_function_is_rejected(expect):
            with pytest.raises(psycopg.Error):
                conn = psycopg.connect("host=/nonexistent-socket-dir dbname=pgc")
                conn.execute("SELECT pgc_definitely_no_such_function()")
            expect.num(1, 1, "the server rejected the call")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(result, "a broad raises with no SQLSTATE must not be collectable")
    result.stderr.fnmatch_lines(["*pytest.raises(Error) names no SQLSTATE*"])


def test_a_raises_that_pins_the_sqlstate_is_accepted(pytester, expect):
    """The positive control, and the one that matters most.

    A guard that rejects the honest form gets switched off. The honest form is the
    same `pytest.raises(psycopg.Error)` with the error named afterwards, and it
    must collect and pass.
    """
    result = _inner(pytester, '''
        import psycopg
        import pytest

        def test_an_unknown_function_is_42883(expect):
            with pytest.raises(psycopg.Error) as exc:
                raise psycopg.errors.UndefinedFunction("no such function")
            expect.sqlstate(exc.value, "42883", "an unknown function is 42883")
        ''')
    expect.outcomes(result, "the honest form collects and passes", passed=1, failed=0)


def test_a_raises_pinned_by_reading_the_field_is_accepted(pytester, expect):
    """The second honest spelling: the field read directly rather than through the
    helper. Both are claims about a typed field, so the scan accepts both."""
    result = _inner(pytester, '''
        import psycopg
        import pytest

        def test_the_field_itself(expect):
            with pytest.raises(psycopg.Error) as exc:
                raise psycopg.errors.UndefinedFunction("no such function")
            expect.text(exc.value.sqlstate, "42883", "the SQLSTATE field itself")
        ''')
    expect.outcomes(result, "reading the field counts as pinning it",
                    passed=1, failed=0)


def test_a_narrow_raises_needs_no_sqlstate(pytester, expect):
    """Control for the scope of the rule. A single-SQLSTATE class already names
    the error, so demanding a second spelling of the same claim would be noise."""
    result = _inner(pytester, '''
        import psycopg
        import pytest

        def test_narrow(expect):
            with pytest.raises(psycopg.errors.UndefinedFunction):
                raise psycopg.errors.UndefinedFunction("no such function")
            expect.num(1, 1, "the narrow class is the claim")
        ''')
    expect.outcomes(result, "a one-SQLSTATE class is not refused", passed=1, failed=0)


def test_a_raises_tuple_hides_a_broad_member(pytester, expect):
    """@jdatcmd's #905 hole, in the guard written after it.

    The broad-except scan looked only at a bare name, so `except Exception` was
    refused and `except (ValueError, Exception)` passed. A tuple is how a narrow
    claim gets widened under pressure, which is the exact moment the guard is for.
    """
    pytester.makepyfile(
        """
        import psycopg
        import pytest

        def test_tuple(expect):
            with pytest.raises((ValueError, psycopg.Error)):
                raise psycopg.errors.UndefinedFunction("no such function")
            expect.num(1, 1, "something of some family failed")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(result, "a broad member of a tuple is still broad")
    result.stderr.fnmatch_lines(["*pytest.raises(Error) names no SQLSTATE*"])


def test_raises_exception_is_refused_like_a_broad_except(pytester, expect):
    """`except Exception` is already uncollectable; `pytest.raises(Exception)` was
    not, and it swallows the same failures for the same reason."""
    pytester.makepyfile(
        """
        import pytest

        def test_anything_at_all(expect):
            with pytest.raises(Exception):
                raise RuntimeError("the real failure")
            expect.num(1, 1, "something went wrong")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(result, "pytest.raises(Exception) must not be collectable")
    result.stderr.fnmatch_lines(["*pytest.raises(Exception) names no SQLSTATE*"])


def test_setup_inside_a_raises_block_is_refused(pytester, expect):
    """`raises-catches-setup`, in the spelling this rule DOES close. The block is
    narrow AND pinned, and still vacuous: two statements inside it, so the failure
    may be either one.

    THE INNER FILE IS SELF-CONTAINED ON PURPOSE. Written against a bare `conn` it
    failed with `NameError`, which satisfies `run_failed` without anything having
    refused it -- the arm would have been green on a tree with no guard at all.
    With the stub below and no guard, the inner run reports `1 passed`: the SET
    raises 42704, the pin accepts it, and the ALTER the test is named for never
    runs. That is the defect, and it is what this arm has to redden.
    """
    pytester.makepyfile(
        """
        import psycopg
        import pytest

        class _Conn:
            def execute(self, sql):
                raise psycopg.errors.UndefinedObject("no such object: " + sql)

        conn = _Conn()

        def test_which_one_raised(expect):
            with pytest.raises(psycopg.errors.UndefinedObject) as exc:
                conn.execute("SET pgcolumnar.no_such_guc = 1")
                conn.execute("ALTER TABLE t SET ACCESS METHOD no_such_am")
            expect.sqlstate(exc.value, "42704", "the ALTER was refused")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(result, "two statements in the block must not be collectable")
    result.stderr.fnmatch_lines(["*holds 2 statements, so which one raised*"])


def test_a_raises_block_with_one_statement_is_accepted(pytester, expect):
    """Control for the arm above, differing in exactly one property: the setup
    moved above the block, leaving the statement under test alone inside it."""
    result = _inner(pytester, '''
        import psycopg
        import pytest

        def test_one_statement(expect):
            with pytest.raises(psycopg.errors.UndefinedFunction) as exc:
                raise psycopg.errors.UndefinedFunction("no such function")
            expect.sqlstate(exc.value, "42883", "the statement under test failed")
        ''')
    expect.outcomes(result, "one statement in the block is the honest form",
                    passed=1, failed=0)


def test_the_raises_scan_reads_code_not_a_string_literal(pytester, expect):
    """The false positive this scan is written to avoid, pinned so it cannot return.

    The inner file contains the refused shape inside a `makepyfile` string, exactly
    as every arm in this file does. A line regex refuses it; `ast` does not see a
    handler or a call inside a string.
    """
    result = _inner(pytester, '''
        def test_quotes_the_shape(expect):
            forbidden = """
                import psycopg, pytest
                def test_inner(expect):
                    with pytest.raises(psycopg.Error):
                        conn = psycopg.connect("host=/nope")
                        conn.execute("SELECT 1")
            """
            expect.at_least(len(forbidden), 1,
                            "the shape above is a string, not code")
        ''')
    expect.outcomes(result, "the forbidden shape inside a string is not refused",
                    passed=1, failed=0)


# ---------------------------------------------------------------------------
# expect.sqlstate, the honest form the scan points at.
# ---------------------------------------------------------------------------

def test_sqlstate_refuses_a_sqlstate_class_prefix(pytester, expect):
    """"42" is a SQLSTATE CLASS. Accepting it would make the pin a prefix claim
    wearing the spelling of an exact one -- the substring defect, one layer up."""
    expect.refusal(_inner(pytester, '''
        import psycopg

        def test_prefix(expect):
            expect.sqlstate(psycopg.errors.UndefinedFunction("x"), "42", "a class")
        '''), "sqlstate refuses a two-character class", "is not a SQLSTATE")


def test_sqlstate_refuses_an_empty_expectation(pytester, expect):
    """An empty want names no error, so nothing could have failed it."""
    expect.refusal(_inner(pytester, '''
        import psycopg

        def test_empty_want(expect):
            expect.sqlstate(psycopg.errors.UndefinedFunction("x"), "", "nothing")
        '''), "sqlstate refuses an empty expectation", "is not a SQLSTATE")


def test_sqlstate_refuses_an_object_carrying_no_sqlstate(pytester, expect):
    """Passing pytest's ExceptionInfo instead of `exc.value` is the mistake that
    produces it, and it would otherwise compare None against a real code forever."""
    expect.refusal(_inner(pytester, '''
        def test_wrong_object(expect):
            expect.sqlstate(RuntimeError("not a database error"), "42883", "wrong")
        '''), "sqlstate refuses an object with no sqlstate", "carries no sqlstate")


def test_sqlstate_fails_when_the_failure_never_reached_the_server(pytester, expect):
    """The measured case. A connect to a socket that does not exist raises
    OperationalError with sqlstate None: a psycopg.Error that is no server error."""
    result = _inner(pytester, '''
        import psycopg

        def test_no_sqlstate_at_all(expect):
            exc = psycopg.OperationalError("connection failed")
            expect.sqlstate(exc, "42883", "an unknown function")
        ''')
    expect.outcomes(result, "a failure with no SQLSTATE is not the named error",
                    failed=1, passed=0)
    result.stdout.fnmatch_lines(["E*carrying no SQLSTATE*"])


def test_sqlstate_fails_on_a_different_sqlstate(pytester, expect):
    """The whole point: the error measured from the setup line was 42602 and the
    statement under test raises 42704. One `raises` accepts both; this does not."""
    result = _inner(pytester, '''
        import psycopg

        def test_the_other_error(expect):
            expect.sqlstate(psycopg.errors.InvalidName("bad name"), "42704",
                            "the ALTER was refused")
        ''')
    expect.outcomes(result, "a different SQLSTATE fails", failed=1, passed=0)
    result.stdout.fnmatch_lines(["E*got SQLSTATE '42602' want '42704'*"])


def test_sqlstate_accepts_the_exact_sqlstate(pytester, expect):
    """Positive control for all five arms above."""
    result = _inner(pytester, '''
        import psycopg

        def test_exact(expect):
            expect.sqlstate(psycopg.errors.UndefinedFunction("x"), "42883",
                            "an unknown function is 42883")
        ''')
    expect.outcomes(result, "the exact SQLSTATE passes", passed=1, failed=0)


def test_sqlstate_accepts_one_of_several_named_codes(pytester, expect):
    """This tree supports majors 15 through 19, so an error code can legitimately
    differ between them. A tuple widens the claim by exactly the codes it names."""
    result = _inner(pytester, '''
        import psycopg

        def test_either_code(expect):
            expect.sqlstate(psycopg.errors.UndefinedObject("x"), ("42883", "42704"),
                            "one of the two codes this major uses")
        ''')
    expect.outcomes(result, "a named pair of codes passes", passed=1, failed=0)


def test_sqlstate_refuses_an_empty_set_of_codes(pytester, expect):
    """The escape hatch must not become the hole. An empty tuple is satisfied by
    nothing, so it could not have passed and says nothing about which error came."""
    expect.refusal(_inner(pytester, '''
        import psycopg

        def test_no_codes(expect):
            expect.sqlstate(psycopg.errors.UndefinedFunction("x"), (), "nothing")
        '''), "sqlstate refuses an empty set of codes",
        "an empty set of SQLSTATEs is satisfied by nothing")


# ---------------------------------------------------------------------------
# What this scan must NOT do. Both of these were proven failures on a sibling
# branch in this layer, so they are arms here rather than a sentence.
# ---------------------------------------------------------------------------

def test_the_raises_scan_leaves_the_unrunnable_state_alone(pytester, expect):
    """A documented hatch the corpus does not exercise, exercised.

    `VACUITY_MODES.md` section 3.3 promises `cannot_run` is not a skip: the run
    prints `UNRUN`, counts it, and exits `EXIT_INCOMPLETE`. A sibling guard in this
    layer measured zero false positives over all 148 tests and still broke that,
    because nothing in the corpus declares itself unrunnable. The file here also
    holds a legitimate pinned `raises`, so the scan has run over it.
    """
    result = _inner(pytester, '''
        import psycopg
        import pytest

        def test_pins_its_error(expect):
            with pytest.raises(psycopg.Error) as exc:
                raise psycopg.errors.UndefinedFunction("no such function")
            expect.sqlstate(exc.value, "42883", "an unknown function is 42883")

        def test_cannot_run_here(expect):
            expect.cannot_run("MISSING_DEPENDENCY", "duckdb is not installed here")
        ''')
    expect.num(result.ret, 67, "the run still exits EXIT_INCOMPLETE")
    result.stdout.fnmatch_lines(["*checks unrunnable: 1*"])


def test_the_raises_scan_does_not_touch_a_recorder_made_in_the_body(pytester, expect):
    """A recorder fetched during the CALL phase must still satisfy the layer.

    A sibling guard read the recorder before pytest's call hook yielded, so a test
    that asks for `expect` itself was reddened with a neighbouring guard's message.
    This scan runs at collection time and cannot do that; the arm is here so a later
    edit that moves it cannot do it either.
    """
    result = _inner(pytester, '''
        import psycopg
        import pytest

        def test_asserts_in_its_own_body(request):
            expect = request.getfixturevalue("expect")
            expect.num(2 + 2, 4, "arithmetic, concluded by the test body itself")

        def test_pins_its_error(expect):
            with pytest.raises(psycopg.Error) as exc:
                raise psycopg.errors.UndefinedFunction("no such function")
            expect.sqlstate(exc.value, "42883", "an unknown function is 42883")
        ''')
    expect.outcomes(result, "a recorder made in the body still satisfies the layer",
                    passed=2, failed=0)


# ---------------------------------------------------------------------------
# THE RESIDUAL, PINNED. `raises-catches-setup` is MITIGATED by the one-statement
# rule, NOT closed, and the two shapes that walk past it get an arm each. They
# assert the scan reports NOTHING, which is what makes the residual a measurement
# rather than a sentence -- and what stops the next reader of the scan from
# assuming the sibling mode is handled.
#
# The one-statement rule counts TOP-LEVEL statements in the block. Both shapes
# below are one top-level statement that performs the setup inside the block.
# ---------------------------------------------------------------------------

def test_a_helper_hiding_the_setup_is_not_refused(pytester, expect):
    """Residual shape 1 of 2: a CALL TO A HELPER that performs the setup.

    One statement, a narrow class, a pinned SQLSTATE, and the setup still raised.
    The block holds one top-level statement, so the statement rule is satisfied;
    the class names a single SQLSTATE and the test pins it, so the SQLSTATE rule is
    satisfied; and the error came from inside the helper rather than from the
    statement the test is about. Against this guard: `1 passed`, exit 0, and the
    scan reported no offence.

    What would close it is a claim about WHICH statement raised -- a position, or a
    helper that runs exactly one statement and owns the assertion -- and this scan
    makes no such claim. So `raises-catches-setup` stays in `VACUITY_MODES.md`
    section 3.4.
    """
    result = _inner(pytester, '''
        import psycopg
        import pytest

        def _do_the_thing(flag):
            if flag:
                raise psycopg.errors.UndefinedObject("SET pgcolumnar.no_such_guc")
            raise psycopg.errors.UndefinedFunction("the statement under test")

        def test_the_alter_is_refused(expect):
            with pytest.raises(psycopg.errors.UndefinedObject) as exc:
                _do_the_thing(True)
            expect.sqlstate(exc.value, "42704", "the statement under test")
        ''')
    expect.outcomes(result, "the setup hidden in a helper is NOT refused -- the "
                            "first residual this guard leaves open",
                    passed=1, failed=0)
    # `passed=1` IS THE ZERO-OFFENCE ASSERTION, and it is the whole of it. An
    # offence makes the layer raise pytest.UsageError, which collects nothing and
    # exits 4, so `passed=1` is reachable only when the scan reported nothing at
    # all. A `result.stderr.no_fnmatch_line("*names no SQLSTATE*")` after this line
    # was tried and removed: `expect.outcomes` fails first in the only case where an
    # offence could appear, so the extra line can never execute and reads as a check
    # while being none. Measured -- under a mutation that flags every block, both
    # residual arms redden on `outcomes` and the stderr lines are never reached.


def test_a_compound_statement_hiding_the_setup_is_not_refused(pytester, expect):
    """Residual shape 2 of 2: a COMPOUND STATEMENT holding the setup and the
    statement under test.

    A `for` over two statements is ONE top-level statement, so `len(node.body) == 1`
    and the rule is satisfied. The loop raises on its FIRST iteration -- the setup --
    and the statement the test names never runs. Measured here as `1 passed`, exit 0,
    with the scan reporting no offence, which is the same failure
    `test_setup_inside_a_raises_block_is_refused` catches when the two statements sit
    side by side instead.

    An `if`, a `with`, or a `try` nests the same way. Counting statements RECURSIVELY
    would catch this and would also refuse a legitimate single-statement loop, so the
    fix is not a deeper count; it is a claim about which statement raised.
    """
    result = _inner(pytester, '''
        import psycopg
        import pytest

        def _run(stmt):
            if stmt.startswith("SET"):
                raise psycopg.errors.UndefinedObject("no such GUC")
            raise psycopg.errors.UndefinedFunction("the statement under test")

        def test_the_alter_is_refused(expect):
            with pytest.raises(psycopg.errors.UndefinedObject) as exc:
                for stmt in ("SET pgcolumnar.no_such_guc = 1",
                             "ALTER TABLE t SET ACCESS METHOD no_such_am"):
                    _run(stmt)
            expect.sqlstate(exc.value, "42704", "the statement under test")
        ''')
    expect.outcomes(result, "a compound statement hiding the setup is NOT refused "
                            "-- the second residual this guard leaves open",
                    passed=1, failed=0)
    # Zero offences, by the argument given in the arm above.


# ---------------------------------------------------------------------------
# The rule's own parameters must not be reachable from the tree it polices.
# ---------------------------------------------------------------------------

def test_a_conftest_cannot_switch_the_broad_family_list_off(pytester, expect):
    """A conftest that rewrites the scan's family list must change nothing.

    Every `conftest.py` under `test/pytest/` is imported before collection, so a
    module-level tuple is writable from the corpus the rule polices: four lines in a
    conftest empty the list, the scan then reports zero offences, and the suite is
    green with the guard switched off and nothing saying so.

    The list is therefore bound inside `_raises_sites` rather than at module level.
    The conftest below writes BOTH plausible spellings of the name onto the module
    and then presents the refused shape. The run must still be refused.
    """
    pytester.makeconftest('''
        import pgc_vacuity

        pgc_vacuity._BROAD_RAISES = ()
        pgc_vacuity.broad_families = ()
        pgc_vacuity.BROAD_RAISES = ()
        ''')
    pytester.makepyfile(
        """
        import psycopg
        import pytest

        def test_an_unknown_function_is_rejected(expect):
            with pytest.raises(psycopg.Error):
                raise psycopg.errors.UndefinedFunction("no such function")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(result, "a conftest writing the family list does not disable "
                              "the rule")
    result.stderr.fnmatch_lines(["*pytest.raises(Error) names no SQLSTATE*"])
