"""A write that wrote nothing must not pass as a fixture that built something.

`INSERT ... SELECT ... WHERE false` writes no rows and raises nothing. psycopg
reports `INSERT 0 0` with `rowcount == 0`, and until this guard existed nobody in
the corpus read either: the fixture built the wrong situation, and every assertion
downstream of it compared two empty things. That is `insert-wrote-no-rows` in
VACUITY_MODES.md section 3.5.

THE TAG IS THE SIGNAL, NOT THE SQL TEXT. A zero `rowcount` alone cannot tell a
write that wrote nothing from a SELECT that matched nothing -- both are 0. The
server's own command tag separates them, so this guard never parses SQL. Measured
on PG 18 against a pgcolumnar table, which is where these values come from:

    statusmessage       rowcount   statement
    CREATE TABLE              -1   CREATE TABLE t (i int) USING pgcolumnar
    INSERT 0 5                 5   INSERT INTO t SELECT g FROM generate_series(1,5) g
    INSERT 0 0                 0   INSERT ... WHERE false
    UPDATE 0                   0   UPDATE t SET i = i WHERE i > 100
    DELETE 0                   0   DELETE FROM t WHERE i > 100
    SELECT 0                   0   SELECT * FROM t WHERE false
    SET                       -1   SET search_path TO public
    TRUNCATE TABLE            -1   TRUNCATE t

THE ARMS HERE NEED NO DATABASE, and that is deliberate rather than convenient: the
thing under test is the classifier and the refusal, which a stub cursor carrying
those two measured fields exercises exactly. The separate question -- whether the
connection the tests actually use is watched at all -- is a different property and
cannot be proven here. It has its own arm in `test_connection.py`, for the reason
#917 had to learn twice: proving a function and proving its call site are two
proofs, and the second one is the one that goes missing.
"""

import pgc_vacuity


class _Cur:
    """The two fields of a psycopg cursor this guard reads, and nothing else."""

    def __init__(self, statusmessage, rowcount):
        self.statusmessage = statusmessage
        self.rowcount = rowcount


def _writes(nodeid):
    return pgc_vacuity._WRITES.get(nodeid, [])


def test_a_write_that_wrote_nothing_is_recorded(expect, request):
    nodeid = request.node.nodeid + "::probe-1"
    pgc_vacuity.note_write(nodeid, _Cur("INSERT 0 0", 0))
    recorded = _writes(nodeid)
    expect.num(len(recorded), 1, "an INSERT reporting 0 rows is recorded")
    expect.num(recorded[0].count, 0, "and the count it carries is the zero")
    expect.text(recorded[0].tag, "INSERT", "and the tag is the command, not the SQL")
    pgc_vacuity._WRITES.pop(nodeid, None)


def test_update_and_delete_are_writes_too(expect, request):
    for tag, message in (("UPDATE", "UPDATE 0"), ("DELETE", "DELETE 0")):
        nodeid = request.node.nodeid + "::" + tag
        pgc_vacuity.note_write(nodeid, _Cur(message, 0))
        expect.num(len(_writes(nodeid)), 1, f"a {tag} reporting 0 rows is recorded")
        pgc_vacuity._WRITES.pop(nodeid, None)


def test_a_select_matching_nothing_is_not_a_write(expect, request):
    """The arm the rowcount-only version of this guard would fail.

    `SELECT 0` and `INSERT 0 0` both carry rowcount 0. A guard keyed on the count
    alone would refuse every test whose last statement was a SELECT over an empty
    result, which is a legitimate and common thing to assert.
    """
    nodeid = request.node.nodeid + "::select"
    pgc_vacuity.note_write(nodeid, _Cur("SELECT 0", 0))
    expect.num(len(_writes(nodeid)), 0, "a SELECT returning no rows is not a write")
    pgc_vacuity._WRITES.pop(nodeid, None)


def test_ddl_is_not_a_write(expect, request):
    for message in ("CREATE TABLE", "SET", "TRUNCATE TABLE", "DROP SCHEMA"):
        nodeid = request.node.nodeid + "::" + message.replace(" ", "_")
        pgc_vacuity.note_write(nodeid, _Cur(message, -1))
        expect.num(len(_writes(nodeid)), 0, f"{message} is not a write that wrote rows")
        pgc_vacuity._WRITES.pop(nodeid, None)


def test_a_write_that_wrote_rows_needs_no_acknowledgement(expect, request):
    nodeid = request.node.nodeid + "::ok"
    pgc_vacuity.note_write(nodeid, _Cur("INSERT 0 5", 5))
    recorded = _writes(nodeid)
    expect.num(len(recorded), 1, "a write that wrote rows is still recorded")
    expect.num(recorded[0].count, 5, "with the count it reported")
    expect.num(sum(1 for w in recorded if w.count == 0), 0,
               "and nothing about it is a zero-row write")
    pgc_vacuity._WRITES.pop(nodeid, None)


# ---- the guard, through a real inner run -------------------------------------
#
# An inner run rather than a direct call on the hook, because the property is "the
# test FAILS", and only a run can report that. Same shape as test_layer.py's arms.

_PROLOGUE = """
    import pgc_vacuity

    class _Cur:
        def __init__(self, statusmessage, rowcount):
            self.statusmessage = statusmessage
            self.rowcount = rowcount
"""


def _inner(pytester, body):
    pytester.makeconftest("pytest_plugins = ['pgc_vacuity']")
    pytester.makepyfile(_PROLOGUE + body)
    return pytester.runpytest("-p", "pgc_vacuity")


def test_an_unacknowledged_zero_row_write_fails_the_test(expect, pytester):
    result = _inner(pytester, """
    def test_fixture_built_nothing(expect, request):
        pgc_vacuity.note_write(request.node.nodeid, _Cur("INSERT 0 0", 0))
        expect.num(1, 1, "an assertion, so the no-assertion guard is not what fires")
    """)
    expect.outcomes(result, "a test whose write wrote nothing does not pass",
                    passed=0, failed=1)
    # ONE PATTERN PER CALL. `expect.refusal` anchors each pattern to a single `E`
    # line, and pytest WORD-WRAPS a long traceback line -- so two patterns need two
    # lines and a multi-word phrase can straddle the wrap. Measured: matching
    # "wrote no rows" failed against a message that contained it, which reads as
    # "the guard did not fire". Single unbreakable tokens, one per call.
    expect.refusal(result, "and the refusal names the mode", r"insert-wrote-no-rows")
    expect.refusal(result, "and it names the command that moved nothing", r"INSERT")


def test_expect_wrote_acknowledges_the_zero(expect, pytester):
    """A zero-row write is legitimate when it is the thing being asserted.

    A negative control -- a DELETE that must delete nothing -- is a real test, and
    the guard must not make it unwritable. Naming the zero is the acknowledgement.
    """
    result = _inner(pytester, """
    def test_deliberately_wrote_nothing(expect, request):
        cur = _Cur("DELETE 0", 0)
        pgc_vacuity.note_write(request.node.nodeid, cur)
        expect.wrote(cur, 0, "the delete matched nothing, which is the point")
    """)
    expect.outcomes(result, "naming the zero lets the test pass", passed=1, failed=0)


def test_expect_wrote_refuses_a_count_that_is_not_a_count(expect, pytester):
    """rowcount is -1 when the statement produced no count.

    Comparing -1 with an expected number would read as a mismatch, which is the
    right verdict for the wrong reason. The same trap `expect.rowcount` records.
    """
    result = _inner(pytester, """
    def test_no_count_available(expect, request):
        expect.wrote(_Cur("CREATE TABLE", -1), 0, "a DDL statement has no row count")
    """)
    expect.outcomes(result, "a -1 is refused rather than compared", passed=0, failed=1)
    expect.refusal(result, "and the refusal says the count is not one",
                   r"no-count-available")


def test_expect_wrote_still_compares(expect, pytester):
    """The acknowledgement is not a waiver: a wrong count is still a failure."""
    result = _inner(pytester, """
    def test_wrote_the_wrong_number(expect, request):
        cur = _Cur("INSERT 0 3", 3)
        pgc_vacuity.note_write(request.node.nodeid, cur)
        expect.wrote(cur, 5, "the fixture claims five rows")
    """)
    expect.outcomes(result, "acknowledging a count does not excuse a wrong one",
                    passed=0, failed=1)
    # THE PATTERN IS NOT DECORATION. With only `failed=1` this arm passed before
    # `expect.wrote` existed at all, satisfied by the AttributeError from the
    # missing function -- a green for a reason that had nothing to do with the
    # comparison. Naming the numbers is what makes the red the right red.
    expect.refusal(result, "and the refusal names both counts", r"got 3 want 5")


def test_several_writes_and_only_the_empty_one_is_named(expect, pytester):
    """The refusal must name WHICH write wrote nothing, not that one did.

    A fixture that runs four INSERTs and gets nothing from the third is the real
    shape. A message saying only "a write wrote no rows" sends the reader to the
    wrong statement.
    """
    result = _inner(pytester, """
    def test_three_writes_one_empty(expect, request):
        n = request.node.nodeid
        pgc_vacuity.note_write(n, _Cur("INSERT 0 5", 5))
        pgc_vacuity.note_write(n, _Cur("UPDATE 0", 0))
        pgc_vacuity.note_write(n, _Cur("INSERT 0 7", 7))
        expect.num(1, 1, "an assertion")
    """)
    expect.outcomes(result, "the empty write fails the test", passed=0, failed=1)
    expect.refusal(result, "and the UPDATE is the one named, not the INSERTs",
                   r"UPDATE")
    expect.refusal(result, "and the mode is named", r"insert-wrote-no-rows")
