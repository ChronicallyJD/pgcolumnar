"""The cluster fixture and the direct connection, tested before they exist.

The requirement is a direct typed connection. These tests assert on Python types
coming back from the server, which is the thing `psql -At` cannot give: it returns
the string "100" and leaves every conversion to the reader.
"""

import decimal


def test_cluster_fixture_gives_a_typed_connection(pgc_conn, expect):
    """count(*) must arrive as an int, not as text."""
    with pgc_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM (SELECT generate_series(1,7)) s")
        value = cur.fetchone()[0]
    expect.num(value, 7, "count arrives as a number")
    expect.text(type(value).__name__, "int", "and its Python type is int")


def test_the_extension_is_installed_and_columnar(pgc_conn, expect):
    """The fixture must give a cluster with pgcolumnar loaded and usable."""
    with pgc_conn.cursor() as cur:
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'pgcolumnar'")
        row = cur.fetchone()
    expect.rows([row[0]] if row else [], ["1.0-alpha3"], "the extension version")


def test_a_columnar_table_round_trips_with_real_types(pgc_conn, expect):
    """Typed results end to end, including the types psql flattens to text."""
    with pgc_conn.cursor() as cur:
        cur.execute("CREATE TABLE t (id int, n numeric, f float8, b bytea, a int[]) USING pgcolumnar")
        cur.execute("INSERT INTO t VALUES (1, 1.5, 2.5, '\\x00ff', ARRAY[1,2])")
        cur.execute("SELECT id, n, f, b, a FROM t")
        row = cur.fetchone()
    expect.num(row[0], 1, "int column")
    expect.text(type(row[1]).__name__, "Decimal", "numeric arrives as Decimal")
    expect.num(row[1], decimal.Decimal("1.5"), "and holds its exact value")
    expect.text(type(row[2]).__name__, "float", "float8 arrives as float")
    expect.text(row[3].hex(), "00ff", "bytea arrives as bytes")
    expect.rows(row[4], [1, 2], "array arrives as a list")


def test_the_plan_names_the_columnar_provider(pgc_conn, expect):
    """EXPLAIN FORMAT JSON arrives parsed, and the provider matches exactly."""
    with pgc_conn.cursor() as cur:
        cur.execute("CREATE TABLE p (id int, a int) USING pgcolumnar")
        cur.execute("INSERT INTO p SELECT g, g%10 FROM generate_series(1,500) g")
        cur.execute("SET enable_seqscan = on")
        cur.execute("EXPLAIN (FORMAT JSON, COSTS OFF) SELECT count(*) FROM p WHERE a > 5")
        plan = cur.fetchone()[0]
    expect.text(type(plan).__name__, "list", "the plan arrives as parsed Python")
    expect.plan_node(plan, provider="PgColumnarScan", name="the columnar provider")


def test_each_test_gets_its_own_schema(pgc_conn, expect):
    """Isolation without a cluster per test: a private schema, first on the path."""
    with pgc_conn.cursor() as cur:
        cur.execute("SHOW search_path")
        path = cur.fetchone()[0]
        cur.execute("SELECT current_schema()")
        schema = cur.fetchone()[0]
    expect.text(schema.startswith("pgc_test_"), True, "the schema is test-private")
    expect.text(path.split(",")[0].strip().startswith("pgc_test_"), True,
                "and it is first on the search path")


def test_the_worker_owns_its_own_cluster(pgc_cluster, expect):
    """Under xdist each worker must own a cluster, not share one.

    Two workers installing into one pkglibdir race, and a shared cluster lets one
    test see another's tables.

    This asserts the port is the one DERIVED FROM THIS WORKER'S ID, which is what
    makes distinctness a property rather than a hope: the mapping from worker id to
    port is injective, so if every worker's port matches its own id, no two workers
    share a port. Asserting only "the port is an int" would have passed while every
    worker sat on 54600.
    """
    from pgc_cluster import PORT_BASE

    wid = pgc_cluster.worker_id
    slot = 0 if wid in (None, "master") else int(str(wid).lstrip("gw") or 0)
    expect.num(pgc_cluster.port, PORT_BASE + slot,
               f"worker {wid} owns the port derived from its id")
    expect.text(pgc_cluster.is_ours(), True,
                "and the server answering there runs from our datadir")


def test_the_cluster_refuses_a_foreign_server(pgc_cluster, expect):
    """The identity guard must be able to say NO, not just say yes.

    pg_ctl -w proves only that SOMETHING answers on the port. lib.sh added this
    check because a foreign cluster answering would let every later assertion run
    against the wrong server. A guard that has never returned False is not known to
    work, so this points it at a datadir that is not ours and requires a False.
    """
    import pathlib

    from pgc_cluster import Cluster

    impostor = Cluster(pgc_cluster.pg_config, pgc_cluster.worker_id,
                       pathlib.Path("/tmp/definitely-not-our-datadir"),
                       pgc_cluster.port)
    expect.text(impostor.is_ours(), False,
                "a server whose datadir differs is refused")
