"""Port of test/hilbert_locality.sh: does the Hilbert curve buy range locality?

BLOCKED ON #897. THIS FILE CANNOT RUN ON main.

The harness it is written against -- `conftest.py`, `pgc_vacuity.py`,
`pgc_cluster.py`, `pytest.ini` -- lives only on the branch of pull request #897,
which is NOT MERGED and currently has changes requested. `test/pytest/` does not
exist on main, so on main this file has no `expect` fixture, no `pgc_cluster`
fixture and no vacuity plugin, and pytest will fail at collection. It is
committed here so that the port exists and can be reviewed beside the bash
suite; it becomes runnable when #897 lands, and not before.

It was RUN, before being committed, against #897's harness assembled beside it
in a scratch tree (PostgreSQL 18.4, prefix /usr/local/pg18_loc889): 16 passed,
18.20s including the extension build and 5.13s on a warm one. The numbers below
are that run's, and they are the bash suite's numbers.

    pytest --pg-config .../bin/pg_config --pgc-expect-tests 16 \
           test_hilbert_locality.py

AND THE BLOCKING DEPENDENCY IS WIDER THAN test/pytest/. #897 also adds
`pgc_build_and_install` to test/lib.sh, which `pgc_cluster.build_and_install`
drives. With this file dropped beside #897's test/pytest/ but main's lib.sh, the
session ends before any test runs:

    RuntimeError: pgcolumnar failed to build or install from ...
    bash: line 1: pgc_build_and_install: command not found

So "blocked on #897" means the whole of #897, not only the directory.

ONE THING THIS FILE CANNOT DO THAT ITS BASH TWIN DOES, AND IT IS MEASURED

The bash suite REFUSES to report a ratio when the two partitions are not
different: the twelve measurement arms print UNRUN, pgc_summary prints
"12 unrunnable" and the suite exits 67, INCOMPLETE. Here the same refusal goes
through `expect.cannot_run("UNMET_PRECONDITION", ...)`, and the layer records
the third state but nothing reports it. Measured, with the fixture mutated to
lay BOTH arms out with cluster(): "1 failed, 15 passed" -- the four
test_groups_read_over_sixty_placements cases PASSED while asserting nothing
about groups read. Only test_the_two_partitions_differ reddened, and it reddened
for its own reason. The suite is still red overall, so nothing ships silently;
but a reader counting greens counts four that never asked their question. See
the report accompanying this file.

WHAT THIS IS A PORT OF, AND WHAT IT IS FOR

test/hilbert_locality.sh builds one fixture, lays it out twice -- once with
pgcolumnar.cluster() (Z-order) and once with pgcolumnar.cluster_hilbert() --
and counts the engine's own "Columnar Chunk Groups Read" over 60 deterministic
window placements at each of four window sizes. Read that file first: its
header carries the reasoning, the three defects the shape exists to avoid, and
the list of things the measurement does NOT claim. Every property asserted here
is asserted there, under a name that matches, so the two can be compared
mechanically.

WHAT THIS PORT DOES NOT CLAIM

It does not claim the two harnesses agree by construction. They agree because
both were run and both produced 241/118, 351/209, 588/402 and 1624/1313 -- and
if one day they disagree, that disagreement is the finding, not a merge
conflict to resolve by editing one of them.

THREE MECHANISMS DIFFER FROM THE BASH ARM, ON PURPOSE

  1. THE COUNTERS ARE READ AS TYPED JSON, NOT GREPPED. The bash suite runs
     EXPLAIN in text and pulls integers out with sed. Here it is
     `EXPLAIN (..., FORMAT JSON)`, which psycopg hands back as parsed Python, so
     "Columnar Chunk Groups Read" is a key holding an int. A regex that matched
     the wrong line, or that matched nothing and yielded the empty string, is
     not a failure mode this arm has.

  2. THE COLUMNAR-SCAN PREMISE GOES THROUGH expect.plan_marker, not a grep for
     a node name. `Custom Plan Provider == "PgColumnarScan"` is NOT the same
     question: the vectorized aggregate node reuses the scan's registered
     methods and reports the same provider, so that predicate says yes for a
     plan with no columnar scan in it. `plan_marker` asks for the
     "Columnar Projected Columns" key, which only the scan's explain callback
     emits -- the faithful port of `pgc_is_columnar_scan`.

  3. THE FIXTURE IS BUILT ONCE PER MODULE, not once per test. It is 200,000
     rows and six clustering operations. See the note on `locality` below for
     what that costs in isolation and why it is still the right trade.
"""

import pytest

# THE PRIVATE IMPORT IS DELIBERATE AND IT IS A GAP, NOT A PREFERENCE.
#
# The vacuity layer walks an EXPLAIN JSON tree in `_plan_nodes`, and exposes no
# public way to READ a counter out of one -- `plan_marker` asserts a key is
# present and `plan_node` returns a node matched by type or provider, but this
# suite's whole subject is the VALUE under "Columnar Chunk Groups Read". The
# alternatives were to reimplement the traversal (a second copy of the tree
# shape, free to drift from the layer's) or to import the layer's own. Importing
# it keeps one traversal in the tree. See the report accompanying this file:
# `expect.counter(plan, key)` belongs in the layer.
from pgc_vacuity import _plan_nodes

# ---- the fixture's constants, identical to the bash suite --------------------

ROWS = 200_000
SPAN = 100_000

# NOT DYADIC, ON PURPOSE. 200000/1500 is 133.33, so no group boundary lines up
# with a power of two. The dyadic case is where the two curves cut the same
# blocks, and it is kept as a control (test_dense_dyadic_grid_is_one_partition)
# rather than allowed to become the fixture by accident.
STRIPE_ROWS = 1500
GROUPS = 134

PLACEMENTS = 60
STRIDE_X = 997
STRIDE_Y = 7919

# The pins: box -> (Z-order total, Hilbert total) over the 60 placements.
# Measured on main f2af080, PG 18.4, and reproduced bit-for-bit by the bash
# suite and by this one.
#
# EXACT INTEGERS AND NOT A THRESHOLD. A threshold is the thing someone lowers
# when it reddens; it survives a regression that costs half the benefit, and it
# survives it quietly. Any change to the layout, the curve, the group sizing or
# the skip logic moves one of these eight numbers and names itself.
PINS = {
    2000: (241, 118),
    5000: (351, 209),
    12000: (588, 402),
    30000: (1624, 1313),
}

# The partition digests the pins were measured over.
DIGEST_ZORDER = "2169ae4551d8"
DIGEST_HILBERT = "1706e49ef5a2"

DENSE_SIDE = 256
DENSE_STRIPE_ROWS = 1024

# The deterministic generator. hashint8 rather than random(): the pilot ran a
# random() INSERT once per table, so the two arms held DIFFERENT DATA and the
# ratio was a fact about the data rather than about the curve.
SRC_INSERT = f"""
INSERT INTO src (a, b, pad)
SELECT (hashint8(g) % {SPAN} + {SPAN}) % {SPAN},
       (hashint8(g * 2654435761) % {SPAN} + {SPAN}) % {SPAN},
       repeat('x', 40)
FROM generate_series(1, {ROWS}) g
"""

# THE PARTITION DIGEST, ORDER-INDEPENDENT BY CONSTRUCTION.
#
# One string per row group from BOTH columns' min and max, and then those
# strings SORTED before hashing. What is hashed is the SET of group boxes, so
# two layouts that cut the same boxes hash equal however the curve numbered
# them. Ordering the groups by group_number instead -- the obvious first
# version -- makes the digest report the NUMBERING too, so it says "different"
# for two identical partitions and the dense control below passes its premise
# and goes on to report a ratio. That is the defect this form exists to avoid.
#
# vector_index = -1 is the row-group-level zone map: the box of the whole group,
# which is what decides whether the group can be skipped.
DIGEST_SQL = """
SELECT substr(md5(string_agg(g, ',' ORDER BY g)), 1, 12) FROM (
    SELECT string_agg(column_index::text || ':' ||
                      encode(minimum, 'hex') || ':' ||
                      encode(maximum, 'hex'), '/' ORDER BY column_index) AS g
    FROM pgcolumnar.zone_map
    WHERE storage_id = pgcolumnar.get_storage_id(%s)
      AND vector_index = -1 AND column_index IN (0, 1)
    GROUP BY group_number) t
"""

# Order-blind, exactly like pgc_set_hash in test/lib.sh, and that is right here:
# the arms are supposed to differ in ORDER and in nothing else, so an
# order-sensitive oracle would report a difference for the property under test.
SET_HASH_SQL = """
SELECT coalesce(md5(string_agg(t, chr(10) ORDER BY t)), 'EMPTY')
FROM (SELECT r::text AS t FROM {table} r) s
"""


# ---- helpers ----------------------------------------------------------------


def _scalar(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row[0] if row else None


def _digest(conn, table):
    """The partition digest, or a sentinel that no comparison can accept.

    A helper that returned None here would let two FAILED reads compare equal
    and pass an equality arm, and would satisfy an INEQUALITY arm outright --
    which matters, because the arm that licenses the whole measurement is an
    inequality. `expect.hash` refuses a QUERY_ERROR sentinel outright, so the
    sentinel is the layer's own.
    """
    value = _scalar(conn, DIGEST_SQL, (table,))
    return value if value else f"QUERY_ERROR.no-partition-for-{table}"


def _verdict(a, b):
    """different | IDENTICAL | UNMEASURED[...] -- the bash suite's differs().

    THE LAYER HAS NO INEQUALITY RECORDER. `expect` compares for equality
    (num, text, hash, rows), asserts a floor (at_least), and asserts a plan key.
    "these two differ" has to become "the verdict about these two equals the
    string 'different'", which is what this function is for. Computing the
    verdict here rather than writing `assert a != b` is not decoration: a bare
    Python assert is not COUNTED by the vacuity layer, so a test that concluded
    only that way would be failed for asserting nothing.
    """
    for label, value in (("a", a), ("b", b)):
        if not value or str(value).startswith("QUERY_ERROR") or value == "EMPTY":
            return f"UNMEASURED[{label}={value}]"
    return "different" if a != b else "IDENTICAL"


def _plan(conn, sql):
    """The ANALYZEd plan as parsed JSON."""
    return _scalar(
        conn, f"EXPLAIN (ANALYZE, TIMING OFF, COSTS OFF, FORMAT JSON) {sql}")


def _counter(plan, key):
    """One Columnar counter out of a plan, or None when no node carries it.

    None rather than 0: `expect.num` refuses a non-number, so a counter that was
    never reported fails the arm instead of being summed as nothing.
    """
    for node in _plan_nodes(plan):
        if key in node:
            return node[key]
    return None


def _window(table, ox, oy, box):
    """The query under measurement. One shape, one place, so the arms and the
    premises cannot drift into asking about two different queries."""
    return (f"SELECT count(*) FROM {table} "
            f"WHERE a BETWEEN {ox} AND {ox + box} "
            f"AND b BETWEEN {oy} AND {oy + box}")


def _origins(box):
    """The 60 placements. Two coprime strides over the span, so the origins
    neither repeat nor march in step with the group boundaries, and the same 60
    are used for both arms and every box."""
    span = SPAN - box
    return [((i * STRIDE_X) % span, (i * STRIDE_Y) % span)
            for i in range(1, PLACEMENTS + 1)]


def _groups_read(conn, table, box):
    """(placements measured, groups read) over the 60 windows.

    BOTH numbers are returned. The sum alone cannot distinguish a genuinely
    small number of groups from a run that measured fewer windows than it was
    asked to -- and a truncated run reads as a BETTER result, which is the
    direction in which a defect here would go unnoticed.
    """
    measured, total = 0, 0
    for ox, oy in _origins(box):
        value = _counter(_plan(conn, _window(table, ox, oy, box)),
                         "Columnar Chunk Groups Read")
        if isinstance(value, int):
            measured += 1
            total += value
    return measured, total


# ---- the fixture ------------------------------------------------------------


@pytest.fixture(scope="module")
def locality(pgc_cluster):
    """The whole fixture, built once for the module.

    MODULE SCOPE, NOT THE `pgc_conn` FIXTURE, AND THAT IS A COMPROMISE. This
    fixture is 200,000 rows and six clustering operations; per test it would be
    paid fifteen times over. `pgc_conn` is function-scoped -- it gives every
    test a private schema, which is the isolation this harness is built on --
    and a module-scoped fixture cannot depend on a function-scoped one, so this
    opens its own connection and makes its own schema by hand, duplicating what
    `pgc_conn` does. See the report accompanying this file: a module- or
    session-scoped sibling of `pgc_conn` is the missing piece.

    SET max_parallel_workers_per_gather = 0, ON THIS CONNECTION, IS NOT TUNING.
    Every digest below is a claim about physical group boundaries and every
    count is read out of a plan; a parallel plan divides that work across
    workers, so parallelism off is what makes the counters a fact about the
    layout rather than about scheduling. The bash suite says this once, in the
    server's config file, through PGC_EXTRA_CONF. `pgc_cluster.py` hard-codes
    its postgresql.conf and has no equivalent hook, so it is a SET on the one
    connection every query in this module runs through -- which is why the
    module hands out a single connection rather than one per test.
    """
    import psycopg

    conn = psycopg.connect(pgc_cluster.dsn(), autocommit=True)
    schema = "pgc_hilbert_locality"
    try:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}", public')
        conn.execute("SET max_parallel_workers_per_gather = 0")

        # The data is materialised ONCE, into a heap table, and both arms load
        # from it. Two independent evaluations of the generator is how the arms
        # come to hold different rows.
        conn.execute("CREATE TABLE src (a int, b int, pad text)")
        conn.execute(SRC_INSERT)

        for table in ("hz", "hh", "cz1", "cz2"):
            conn.execute(
                f"CREATE TABLE {table} (a int, b int, pad text) USING pgcolumnar")
            conn.execute("SELECT pgcolumnar.set_options(%s, stripe_row_limit => %s)",
                         (table, STRIPE_ROWS))
            conn.execute(f"INSERT INTO {table} SELECT * FROM src")

        # hz is Z-order, hh is Hilbert. cz1 and cz2 are the control: the same
        # verb twice, so an "the partitions differ" arm cannot be satisfied by
        # an instrument that reports any two tables as different.
        conn.execute("SELECT pgcolumnar.cluster('hz', 'a', 'b')")
        conn.execute("SELECT pgcolumnar.cluster_hilbert('hh', 'a', 'b')")
        conn.execute("SELECT pgcolumnar.cluster('cz1', 'a', 'b')")
        conn.execute("SELECT pgcolumnar.cluster('cz2', 'a', 'b')")

        # The dense dyadic grid the design predicted the two curves would agree
        # on: 256 x 256 cells, 1024 rows to a group, 64 full groups.
        conn.execute("CREATE TABLE dsrc (a int, b int)")
        conn.execute(
            f"INSERT INTO dsrc SELECT (g - 1) / {DENSE_SIDE}, (g - 1) % {DENSE_SIDE} "
            f"FROM generate_series(1, {DENSE_SIDE * DENSE_SIDE}) g")
        for table in ("dz", "dh"):
            conn.execute(f"CREATE TABLE {table} (a int, b int) USING pgcolumnar")
            conn.execute("SELECT pgcolumnar.set_options(%s, stripe_row_limit => %s)",
                         (table, DENSE_STRIPE_ROWS))
            conn.execute(f"INSERT INTO {table} SELECT * FROM dsrc")
        conn.execute("SELECT pgcolumnar.cluster('dz', 'a', 'b')")
        conn.execute("SELECT pgcolumnar.cluster_hilbert('dh', 'a', 'b')")

        yield conn
    finally:
        try:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            conn.close()


@pytest.fixture(scope="module")
def digests(locality):
    """The two partitions under measurement, read once."""
    return _digest(locality, "hz"), _digest(locality, "hh")


# =============================================================================
# ARM 1  PREMISE: THE TWO ARMS HOLD THE IDENTICAL ROW MULTISET
# =============================================================================


def test_both_arms_hold_the_identical_row_multiset(locality, expect):
    """bash: 'premise: the two arms hold the identical row multiset' and the
    two arms that follow it.

    Without this every number below is a fact about two different tables.
    """
    hz = _scalar(locality, SET_HASH_SQL.format(table="hz"))
    hh = _scalar(locality, SET_HASH_SQL.format(table="hh"))
    src = _scalar(locality, SET_HASH_SQL.format(table="src"))
    expect.hash(hh, hz, "the two arms hold the identical row multiset")
    # And that multiset is the source's. Comparing the arms only to each other
    # passes if both loads went equally wrong.
    expect.hash(hz, src, "and it is the source's multiset, so neither load dropped rows")
    # A hash of nothing equals a hash of nothing. 'EMPTY' is what the oracle
    # returns for a genuinely empty relation, and it is not what these are.
    expect.at_least(_scalar(locality, "SELECT count(*) FROM hz"), ROWS,
                    "and it is a hash of rows: the Z-order arm holds them")
    expect.at_least(_scalar(locality, "SELECT count(*) FROM hh"), ROWS,
                    "and it is a hash of rows: the Hilbert arm holds them")


def test_the_fixture_is_two_dimensional(locality, expect):
    """bash: 'premise: column a spans the square' and its sibling.

    A generator that collapsed one column to a handful of values would make
    both curves the identity in that dimension and the comparison meaningless,
    and it would do so silently.
    """
    for column in ("a", "b"):
        expect.num(
            _scalar(locality,
                    f"SELECT (min({column}) < {SPAN // 100} "
                    f"AND max({column}) > {SPAN - SPAN // 100})::int FROM src"),
            1, f"column {column} spans the square")


def test_both_arms_have_the_group_count_measured(locality, expect):
    """bash: 'premise: hz has the group count this measurement was taken at'.

    The fixture is only the fixture that was measured if the groups are the
    size they were measured at: 200,000 rows at 1,500 to a group is 134, the
    last one short.
    """
    counts = {}
    for table in ("hz", "hh"):
        counts[table] = _scalar(
            locality,
            "SELECT count(*) FROM pgcolumnar.row_group "
            "WHERE storage_id = pgcolumnar.get_storage_id(%s)",
            (table,))
    expect.num(counts["hz"], GROUPS, "hz has the group count measured")
    expect.num(counts["hh"], counts["hz"],
               "hh has the same group count, so a group is the same unit on both arms")


# =============================================================================
# ARM 2  PREMISE: THE TWO PARTITIONS ARE TWO DIFFERENT PARTITIONS
# =============================================================================


def test_the_two_partitions_differ(digests, expect):
    """bash: 'premise: the Z-order and Hilbert partitions differ', and the two
    pins under it.

    This is what licenses the measurement to attribute its difference to the
    curve. Pinned as well as merely different: "different" is satisfied by any
    change to either layout, while these two values say the layouts are the
    ones the pinned integers were measured over. A moved digest beside moved
    integers is a layout change; moved integers beside these digests would be a
    change in the reader.
    """
    dz, dh = digests
    expect.text(_verdict(dz, dh), "different",
                "the Z-order and Hilbert partitions differ")
    expect.text(dz, DIGEST_ZORDER,
                "the Z-order partition is the one these numbers were measured over")
    expect.text(dh, DIGEST_HILBERT,
                "the Hilbert partition is the one these numbers were measured over")


# =============================================================================
# ARM 3  CONTROL: SAME CURVE TWICE -> THE DIGESTS ARE IDENTICAL
# =============================================================================


def test_two_tables_on_the_same_curve_are_one_partition(locality, digests, expect):
    """bash: 'control: two tables on the same curve have the identical partition'.

    The removal proof for the arm above. An inequality passes for any
    instrument that reports "different" too readily -- including one that is
    really reporting "these are two different tables". Two tables built the
    same way from the same source and laid out by the SAME verb must hash
    EQUAL, and that hash must be the measured Z-order arm's, so the control is
    a control on THIS fixture rather than on an unrelated one.
    """
    dz, _ = digests
    cz1 = _digest(locality, "cz1")
    cz2 = _digest(locality, "cz2")
    expect.hash(cz1, cz2, "two tables on the same curve have the identical partition")
    expect.hash(cz1, dz, "and that partition is the measured Z-order arm's")


# =============================================================================
# ARM 4  CONTROL: A DENSE DYADIC GRID -> THE TWO CURVES AGREE
# =============================================================================


def test_dense_dyadic_grid_is_one_partition(locality, expect):
    """bash: 'control: on a dense dyadic grid the two curves cut the identical
    partition'.

    The degenerate case the design predicted: over a dense grid whose side is a
    power of two, cut into groups whose size is a power of two, the two curves
    visit the same blocks in a different ORDER and produce the same set of
    group boxes. It is here so the suite carries its own counterexample to
    "Hilbert always changes the layout", and so a reader can see that arm 2's
    "different" is a measurement rather than a foregone conclusion.
    """
    expect.num(
        _scalar(locality,
                "SELECT count(*) FROM (SELECT a, b FROM dsrc "
                "GROUP BY a, b HAVING count(*) <> 1) x"),
        0, "the dense grid is dense -- every cell present exactly once")
    expect.num(
        _scalar(locality,
                "SELECT count(*) FROM pgcolumnar.row_group "
                "WHERE storage_id = pgcolumnar.get_storage_id('dz')"),
        DENSE_SIDE * DENSE_SIDE // DENSE_STRIPE_ROWS,
        "the dense grid has the dyadic group count")
    expect.hash(_digest(locality, "dz"), _digest(locality, "dh"),
                "on a dense dyadic grid the two curves cut the identical partition")


# =============================================================================
# ARM 5  PREMISE: BOTH ARMS PLAN AS A COLUMNAR SCAN
# =============================================================================


def test_both_arms_plan_as_a_columnar_scan(locality, expect):
    """bash: 'premise: the Z-order arm plans as a columnar scan'.

    plan_marker, not a provider name. The vectorized aggregate node reuses the
    scan's registered methods and reports the same Custom Plan Provider, so
    that predicate says yes for a plan with no columnar scan in it.
    "Columnar Projected Columns" is emitted only by the scan's explain
    callback.
    """
    box = 2000
    ox, oy = _origins(box)[0]
    for table in ("hz", "hh"):
        expect.plan_marker(_plan(locality, _window(table, ox, oy, box)),
                           "Columnar Projected Columns",
                           name=f"the {table} arm plans as a columnar scan")


def test_parallelism_is_off_so_a_counter_is_a_fact_about_the_layout(locality, expect):
    """No bash twin by name: the bash suite sets this in the server's config
    through PGC_EXTRA_CONF, where it cannot be undone by a session.

    Here it is a SET on one connection, so it is asserted rather than assumed.
    A parallel plan divides the scan across workers and the counters below
    would be a fact about scheduling.
    """
    expect.text(_scalar(locality, "SHOW max_parallel_workers_per_gather"), "0",
                "parallelism is off on the connection every arm runs through")


# =============================================================================
# ARMS 6-7  PREMISES ABOUT THE COUNTERS' OWN PLAN
# =============================================================================


@pytest.mark.parametrize("box", sorted(PINS))
def test_the_predicates_are_usable_and_the_denominators_match(locality, expect, box):
    """bash: 'premise: box N, the Z-order arm can skip on all four predicates'
    and the two arms after it.

    FOUR, NOT TWO. A BETWEEN is two scan keys, >= and <=, and the reader builds
    a skip predicate from each; two BETWEENs over two columns are four usable
    predicates. A "> 0" bound would accept an arm that had lost one whole
    dimension -- which is the dimension the curve is about.

    "Pushed-Down Filters" is deliberately not the number checked: it counts what
    the reader was HANDED, and a key it could not build a skip predicate from
    excludes no group at all while still being reported as pushed down (#477).

    And the denominators are compared to EACH OTHER, not to a literal: a
    literal would still be satisfied if both arms drifted together, and the
    property is that a ratio is taken between two equal denominators.
    """
    ox, oy = _origins(box)[0]
    pz = _plan(locality, _window("hz", ox, oy, box))
    ph = _plan(locality, _window("hh", ox, oy, box))

    expect.num(_counter(pz, "Columnar Usable Skip Predicates"), 4,
               f"box {box}, the Z-order arm can skip on all four predicates")
    expect.num(_counter(ph, "Columnar Usable Skip Predicates"), 4,
               f"box {box}, the Hilbert arm can skip on all four predicates")
    expect.num(_counter(ph, "Columnar Chunk Groups Total"),
               _counter(pz, "Columnar Chunk Groups Total"),
               f"box {box}, both arms have the same number of groups to read")
    expect.num(_counter(pz, "Columnar Chunk Groups Total"), GROUPS,
               f"box {box}, that denominator is the whole relation")


# =============================================================================
# ARM 8  THE MEASUREMENT
# =============================================================================


@pytest.mark.parametrize("box", sorted(PINS))
def test_groups_read_over_sixty_placements(locality, digests, expect, box):
    """bash: 'box N: groups read over 60 placements, Z-order' and the three
    arms beside it.

    Reported only if the partitions differ. With no difference in layout there
    is nothing for a ratio to be about, and printing one anyway is how the
    pilot produced numbers for the dense grid.
    """
    dz, dh = digests
    verdict = _verdict(dz, dh)
    if verdict != "different":
        expect.cannot_run(
            "UNMET_PRECONDITION",
            f"the two partitions are not different ({verdict}), so a ratio "
            f"between them is not about the curve")
        return

    want_z, want_h = PINS[box]
    measured_z, total_z = _groups_read(locality, "hz", box)
    measured_h, total_h = _groups_read(locality, "hh", box)

    # EVERY PLACEMENT WAS MEASURED. A run that lost windows would sum fewer
    # groups and read as a better result on whichever arm lost them.
    expect.num(measured_z, PLACEMENTS,
               f"box {box}: all {PLACEMENTS} placements reported a Z-order group count")
    expect.num(measured_h, PLACEMENTS,
               f"box {box}: all {PLACEMENTS} placements reported a Hilbert group count")

    expect.num(total_z, want_z,
               f"box {box}: groups read over {PLACEMENTS} placements, Z-order")
    expect.num(total_h, want_h,
               f"box {box}: groups read over {PLACEMENTS} placements, Hilbert")

    # And, separately from the pins: the curve still wins here. This arm stays
    # meaningful when the pins are re-taken, and it is what tells a reader
    # "the layout moved" apart from "Hilbert stopped winning".
    #
    # A DIFFERENCE, BECAUSE THE LAYER HAS NO STRICT INEQUALITY. `at_least` is
    # the only bound it offers and it refuses a floor of zero, so "h < z" is
    # written as "z - h is at least 1", which asserts exactly that and nothing
    # weaker.
    expect.at_least(total_z - total_h, 1,
                    f"box {box}: Hilbert reads fewer groups than Z-order")

    # The ratio is PRINTED, from the two numbers just measured, and asserted
    # nowhere: a ratio can be held constant by both arms getting worse together.
    print(f"-- box {box}: z={total_z} h={total_h} "
          f"z/h={total_z / total_h:.4f}")
