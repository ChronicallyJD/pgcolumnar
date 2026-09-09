"""Port of test/native_projection.sh, property for property.

The original is 55 lines of bash with 8 assertions, no process work and nothing
timing-dependent, which is what makes it a fair first pilot. Every check in the
original appears here with the same name, so the two can be compared mechanically.

ONE DELIBERATE DIFFERENCE IN MECHANISM. The bash suite compares
`md5(string_agg(t ORDER BY t))`, which is order-blind by construction. This port
compares the result sets themselves through `expect.row_set`, which is order-blind
by declaration. That asserts the same property by a stronger means: an md5 mismatch
tells you two hashes differ, a row-set mismatch tells you which row. It also avoids
recomputing the hash in Python, where encoding and collation could make the same
rows hash differently.

The fetch helper returns rows in query order and the assertion chooses the
comparison, because sorting inside the helper is how an ordering claim silently
becomes a set one.
"""

import pytest

STRIPE_ROWS = 1000
ROWS = 5000


@pytest.fixture
def fo(pgc_conn):
    """The original's fixture, verbatim in effect: 5000 rows, two projections."""
    with pgc_conn.cursor() as cur:
        cur.execute("CREATE TABLE fo (a int, b text, c int) USING pgcolumnar")
        cur.execute("SELECT pgcolumnar.set_options('fo', stripe_row_limit => %s)",
                    (STRIPE_ROWS,))
        cur.execute("SELECT pgcolumnar.add_projection('fo','fp',ARRAY['a','c'],ARRAY['c'])")
        cur.execute("SELECT pgcolumnar.add_projection('fo','fq',ARRAY['b'])")
        cur.execute(
            "INSERT INTO fo SELECT g, 'r'||g, (g*7)%%100 FROM generate_series(1,%s) g",
            (ROWS,),
        )
    return pgc_conn


def _rows(conn, sql, params=None):
    """Rows in the order the query returned them.

    NOT sorted here. Which comparison is wanted is the assertion's business, and
    sorting in the fetch helper is how an ordered claim silently becomes a set one:
    the caller says expect.row_set for an order-blind comparison and
    expect.ordered_rows for an ordering claim, and the collection scan refuses
    sorted() feeding the latter.
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [r[0] for r in cur.fetchall()]


def _scalar(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def _proj_storage(conn, table, name):
    return _scalar(
        conn,
        "SELECT proj_storage_id FROM pgcolumnar.projection "
        "WHERE storage_id = pgcolumnar.get_storage_id(%s) AND name = %s",
        (table, name),
    )


def test_fp_fanout_matches_base(fo, expect):
    """bash: 'fp fan-out matches base (a,c)'"""
    got = _rows(fo, "SELECT pgcolumnar.read_projection('fo','fp')")
    want = _rows(fo, "SELECT a::text || '|' || c::text FROM fo")
    expect.row_set(got, want, "fp fan-out matches base (a,c)")


def test_fq_fanout_matches_base(fo, expect):
    """bash: 'fq fan-out matches base (b)'"""
    got = _rows(fo, "SELECT pgcolumnar.read_projection('fo','fq')")
    want = _rows(fo, "SELECT b FROM fo")
    expect.row_set(got, want, "fq fan-out matches base (b)")


def test_fp_row_count_matches_base(fo, expect):
    """bash: 'fp row count matches base'. Both sides are ints here, not text."""
    got = _scalar(fo, "SELECT count(*) FROM pgcolumnar.read_projection('fo','fp')")
    want = _scalar(fo, "SELECT count(*) FROM fo")
    expect.num(got, want, "fp row count matches base")


def test_fp_storage_is_native(fo, expect):
    """bash: 'fp storage is native'"""
    n = _scalar(fo, "SELECT count(*) FROM pgcolumnar.storage WHERE storage_id = %s",
                (_proj_storage(fo, "fo", "fp"),))
    expect.num(n, 1, "fp storage is native")


def test_fp_has_zone_maps(fo, expect):
    """bash: 'fp has zone maps (native skip metadata)'

    The original turns this into the string 'yes' via `[ ... -ge 1 ]`. Here it
    stays a number, so a non-number is refused rather than becoming 'no'.
    """
    n = _scalar(fo, "SELECT count(*) FROM pgcolumnar.zone_map WHERE storage_id = %s",
                (_proj_storage(fo, "fo", "fp"),))
    expect.at_least(n, 1, "fp has zone maps (native skip metadata)")


def test_fp_reflects_deletes(fo, expect):
    """bash: 'fp reflects deletes (a,c)' and 'fp count after delete matches base'."""
    with fo.cursor() as cur:
        cur.execute("DELETE FROM fo WHERE a BETWEEN 1000 AND 2000")
        deleted = cur.rowcount
    # The premise: the DELETE must actually have removed rows, or both arms below
    # are satisfied by a projection that never changed.
    expect.at_least(deleted, 1, "premise: the DELETE removed rows")

    got = _rows(fo, "SELECT pgcolumnar.read_projection('fo','fp')")
    want = _rows(fo, "SELECT a::text || '|' || c::text FROM fo")
    expect.row_set(got, want, "fp reflects deletes (a,c)")

    pcount = _scalar(fo, "SELECT count(*) FROM pgcolumnar.read_projection('fo','fp')")
    bcount = _scalar(fo, "SELECT count(*) FROM fo")
    expect.num(pcount, bcount, "fp count after delete matches base")


def test_fp_spans_multiple_row_groups(fo, expect):
    """bash: 'fp spans multiple projection row groups'"""
    n = _scalar(fo, "SELECT count(*) FROM pgcolumnar.row_group WHERE storage_id = %s",
                (_proj_storage(fo, "fo", "fp"),))
    expect.at_least(n, 2, "fp spans multiple projection row groups")
