"""Per-element pruning for scattered ``= ANY`` sets (#752).

The hull of ``{100,20100,38100}`` intersects every row group, so the old
``[min,max]`` reduction removes none.  A set-aware predicate can keep only the
three groups containing an element.  The contiguous set is the negative control:
its element test and its hull must agree.
"""


def _nodes(plan):
    for root in plan:
        stack = [root["Plan"]]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.get("Plans", ()))


def _plan(conn, qual):
    with conn.cursor() as cur:
        cur.execute(
            "EXPLAIN (ANALYZE, FORMAT JSON, COSTS OFF, TIMING OFF, SUMMARY OFF) "
            f"SELECT count(*) FROM t WHERE {qual}"
        )
        return cur.fetchone()[0]


def _removed(plan):
    return next(
        node.get("Columnar Chunk Groups Removed by Filter", 0)
        for node in _nodes(plan)
        if "Columnar Chunk Groups Total" in node
    )


def _pushed(plan):
    return next(
        node.get("Columnar Pushed-Down Filters", 0)
        for node in _nodes(plan)
        if "Columnar Projected Columns" in node
    )


def test_scattered_saop_prunes_each_element(pgc_conn, expect):
    with pgc_conn.cursor() as cur:
        cur.execute(
            "SET pgcolumnar.stripe_row_limit=2000; "
            'CREATE TABLE t (ts int, txt text COLLATE "C", ov int) USING pgcolumnar; '
            "INSERT INTO t SELECT g, lpad(g::text,8,'0'), (g%40)*2+10 "
            "FROM generate_series(1,40000) g"
        )
        cur.execute("SELECT count(*) FROM t")
        expect.num(cur.fetchone()[0], 40000, "premise: fixture has every row")

    scattered = _plan(pgc_conn, "ts IN (100, 20100, 38100)")
    contiguous = _plan(pgc_conn, "ts IN (100, 101, 102)")

    expect.plan_marker(
        scattered, "Columnar Projected Columns",
        name="premise: scattered arm uses the columnar scan",
    )
    expect.num(
        _removed(scattered), 17,
        "a scattered IN-list prunes by element, not only by its hull",
    )
    expect.num(
        _removed(contiguous), 19,
        "a contiguous IN-list agrees with its hull",
    )
    limit_values = ", ".join(str(i) for i in range(1, 129))
    limit = _plan(pgc_conn, f"ts IN ({limit_values})")
    expect.num(
        _pushed(limit), 1,
        "exactly 128 elements still use one set filter",
    )
    large_values = ", ".join(str(i) for i in range(1, 130))
    large = _plan(pgc_conn, f"ts IN ({large_values})")
    expect.num(
        _pushed(large), 2,
        "a large IN-list falls back to two bounded hull filters",
    )
    int_null = _plan(
        pgc_conn, "ts = ANY (ARRAY[100,20100,38100,NULL]::int[])"
    )
    expect.num(
        _removed(int_null), 17,
        "a multi-value integer set strips NULL and still prunes",
    )
    text_null = _plan(
        pgc_conn,
        "txt = ANY (ARRAY['00000100','00020100','00038100',NULL]::text[])",
    )
    expect.num(
        _removed(text_null), 17,
        "a by-reference text set strips NULL without crashing",
    )
    bloom_only = _plan(pgc_conn, "ov = ANY ('{25,27,29}'::int[])")
    expect.num(
        _removed(bloom_only), 20,
        "a multi-value set bloom-prunes all overlapping groups",
    )

    with pgc_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM t WHERE ts IN (100, 20100, 38100)")
        expect.num(cur.fetchone()[0], 3, "scattered pruning keeps the exact answer")
        cur.execute("SELECT count(*) FROM t WHERE ts IN (100, 101, 102)")
        expect.num(cur.fetchone()[0], 3, "contiguous pruning keeps the exact answer")
        cur.execute(f"SELECT count(*) FROM t WHERE ts IN ({large_values})")
        expect.num(cur.fetchone()[0], 129, "the large-list fallback keeps the exact answer")
        cur.execute(
            "SELECT count(*) FROM t "
            "WHERE ts = ANY (ARRAY[100,20100,38100,NULL]::int[])"
        )
        expect.num(cur.fetchone()[0], 3, "the integer NULL set stays exact")
        cur.execute(
            "SELECT count(*) FROM t WHERE txt = ANY "
            "(ARRAY['00000100','00020100','00038100',NULL]::text[])"
        )
        expect.num(cur.fetchone()[0], 3, "the text NULL set stays exact")
        cur.execute("SELECT count(*) FROM t WHERE ov = ANY ('{25,27,29}'::int[])")
        expect.num(cur.fetchone()[0], 0, "the bloom-only set stays exact")
