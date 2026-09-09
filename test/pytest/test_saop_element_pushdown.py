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


def _plan(conn, values):
    with conn.cursor() as cur:
        cur.execute(
            "EXPLAIN (ANALYZE, FORMAT JSON, COSTS OFF, TIMING OFF, SUMMARY OFF) "
            f"SELECT count(*) FROM t WHERE ts IN ({values})"
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
            "CREATE TABLE t (ts int) USING pgcolumnar; "
            "INSERT INTO t SELECT g FROM generate_series(1,40000) g"
        )
        cur.execute("SELECT count(*) FROM t")
        expect.num(cur.fetchone()[0], 40000, "premise: fixture has every row")

    scattered = _plan(pgc_conn, "100, 20100, 38100")
    contiguous = _plan(pgc_conn, "100, 101, 102")

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
    large_values = ", ".join(str(i) for i in range(1, 130))
    large = _plan(pgc_conn, large_values)
    expect.num(
        _pushed(large), 2,
        "a large IN-list falls back to two bounded hull filters",
    )

    with pgc_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM t WHERE ts IN (100, 20100, 38100)")
        expect.num(cur.fetchone()[0], 3, "scattered pruning keeps the exact answer")
        cur.execute("SELECT count(*) FROM t WHERE ts IN (100, 101, 102)")
        expect.num(cur.fetchone()[0], 3, "contiguous pruning keeps the exact answer")
        cur.execute(f"SELECT count(*) FROM t WHERE ts IN ({large_values})")
        expect.num(cur.fetchone()[0], 129, "the large-list fallback keeps the exact answer")
