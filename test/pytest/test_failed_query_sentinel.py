"""A failed query must not be comparable with another failed query (#432).

`error-swallowed-to-empty`: two queries raise, a helper turns each into the same
value, and they compare equal. The test is green and has asserted nothing about
either query.

`lib.sh` closed this by PRODUCING a sentinel with a sequence number per failure --
`res="QUERY_ERROR.$seq"` -- so two failures can never compare equal. The pytest port
had the constant `QUERY_ERROR = "QUERY_ERROR"` and a comment claiming it was "unique
per occurrence", which was false of a constant, and a refusal in exactly one
assertion. Measured before this file existed, with the sentinel on both sides:

    expect.hash          REFUSED
    expect.text          PASSED
    expect.rows          PASSED
    expect.row_set       PASSED
    expect.ordered_rows  PASSED

So four of the five comparisons accepted two failed queries as agreement.

THE MECHANISM IS THE REFUSAL, and `query_error()` is the second line rather than the
first. A non-unique sentinel is safe against the layer, because no comparison
accepts one at all; it is NOT safe against a helper that compares by hand, which is
why the producer exists and why new code should use it.
"""
import inspect

import pgc_vacuity
from pgc_vacuity import QUERY_ERROR, VacuityError, query_error


# Every public assertion that compares two caller-supplied values. DERIVED from the
# signature rather than listed, so an assertion added later is covered by the arm
# below instead of being the next hole -- which is how this mode survived: `hash`
# had a refusal and the four written after it did not.
def _comparisons():
    cls = pgc_vacuity.Expect
    out = []
    for name, fn in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith("_"):
            continue
        params = list(inspect.signature(fn).parameters)[1:]
        if len(params) >= 2 and params[0] == "got" and params[1] in ("want", "floor"):
            out.append((name, params[1]))
    return sorted(out)


def test_the_comparison_surface_is_what_this_file_thinks_it_is(expect):
    """premise: the derivation finds the assertions, so the arm below is not vacuous."""
    names = [n for n, _ in _comparisons()]
    expect.at_least(len(names), 5, "the layer offers at least five (got, want) comparisons")
    for required in ("hash", "text", "rows", "row_set", "ordered_rows"):
        expect.num(names.count(required), 1, f"{required} is one of them")


# What a VALID pair looks like for each comparison, so the sentinel can be put in
# one side and the other side stays something the assertion would otherwise accept.
#
# DECLARED, and the premise below requires it to cover every comparison the
# derivation finds. That is the anti-drift part: an assertion added to the layer
# without an entry here fails the premise, rather than being quietly skipped by an
# arm that looked like it covered everything. The first version of this arm fudged
# the shapes in a loop and never placed a sentinel in `at_least`'s floor at all --
# it reported `at_least ACCEPTED a failed query`, which was my fixture's fault and
# not the layer's.
VALID = {
    "hash":          ("abc", "abc"),
    "text":          ("abc", "abc"),
    "num":           (7, 7),
    "rowcount":      (7, 7),
    "at_least":      (7, 1),
    "rows":          ([(1,), (2,)], [(1,), (2,)]),
    "row_set":       ([(1,), (2,)], [(2,), (1,)]),
    "ordered_rows":  ([(1,), (2,)], [(1,), (2,)]),
}

# How a sentinel arrives for each: bare for a scalar comparison, and as a CELL for a
# row comparison, because that is what a one-column query that failed looks like
# after a helper swallowed the error.
def _as_side(name, sentinel):
    if name in ("rows", "row_set", "ordered_rows"):
        return [(sentinel,), (2,)]
    return sentinel


def test_the_shape_table_covers_every_comparison_the_layer_offers(expect):
    """premise: no comparison is silently outside the arm below."""
    missing = sorted(n for n, _ in _comparisons() if n not in VALID)
    expect.num(len(missing), 0, f"every comparison has a declared valid pair; missing: {missing}")


def test_every_comparison_refuses_a_failed_query_on_either_side(expect):
    """The arm that would have caught this mode, phrased over the whole surface.

    Two DISTINCT sentinel values, because the interned constant makes `got is want`
    true and `hash` would then refuse for THAT reason -- a refusal that says nothing
    about sentinels. This is the control the original `hash` arm did not have.
    """
    e = pgc_vacuity.Expect("sentinel::derivation")
    checked = 0
    for name, _second in _comparisons():
        fn = getattr(e, name)
        good_got, good_want = VALID[name]
        for side in ("left", "right"):
            s = query_error(side)
            got = _as_side(name, s) if side == "left" else good_got
            want = _as_side(name, s) if side == "right" else good_want
            try:
                fn(got, want, "an arm over a failed query")
            except VacuityError:
                checked += 1
            except AssertionError as exc:
                raise AssertionError(
                    f"{name} COMPARED a failed query on the {side} instead of refusing "
                    f"it, so a pair of failures would have compared equal: {exc}"
                )
            else:
                raise AssertionError(
                    f"{name} ACCEPTED a failed query on the {side} and passed"
                )
    expect.num(checked, 2 * len(_comparisons()),
               "every comparison refused the sentinel on both sides")


def test_row_set_refuses_before_it_maps_rather_than_after(expect):
    """The delegation case, which the first version of the fix got wrong.

    `row_set` hands `rows` a list of repr STRINGS, and `repr(("QUERY_ERROR.1",))` is
    `"('QUERY_ERROR.1',)"` -- it does not start with the prefix. So a refusal living
    only in `rows` cannot see a sentinel that arrived as a cell. Delegating an
    assertion does not delegate its refusals when the delegation transforms the data.
    """
    e = pgc_vacuity.Expect("sentinel::rowset")
    try:
        e.row_set([(query_error(),)], [(query_error(),)], "two failed one-column queries")
    except VacuityError:
        expect.num(1, 1, "row_set refuses a sentinel that arrived as a cell")
    else:
        raise AssertionError("row_set accepted a sentinel cell")


def test_the_producer_is_unique_per_occurrence(expect):
    """The property the old comment claimed and the constant did not have."""
    values = [query_error() for _ in range(50)]
    expect.num(len(set(values)), 50, "fifty occurrences are fifty distinct values")
    expect.num(sum(1 for v in values if v.startswith(QUERY_ERROR)), 50,
               "and every one of them still carries the prefix the refusals match")
    expect.text(query_error("no-partition").split(".")[-1], "no-partition",
                "a detail survives into the value, so a log line says which query failed")


def test_the_constant_alone_is_not_unique_which_is_why_the_producer_exists(expect):
    """The control for the arm above: the thing that was wrong, still measurable.

    Compared in plain Python rather than through `expect`, because the layer now
    REFUSES to compare two sentinels -- which is the whole point, and which means an
    arm about sentinel equality cannot use the assertion it is describing. The first
    version of this arm did, and was refused by the guard it exists to document.
    """
    expect.num(1 if QUERY_ERROR == QUERY_ERROR else 0, 1,
               "the bare constant equals itself, in plain Python")
    expect.num(len({QUERY_ERROR, QUERY_ERROR}), 1,
               "so two failures that both assigned it would have compared equal")
    expect.num(len({query_error(), query_error()}), 2,
               "where two calls to the producer are two values")


def test_the_refusal_cannot_be_switched_off_from_the_corpus_it_polices(expect):
    """Every conftest under test/pytest/ is imported before collection, so a test
    file can reach into this module. A refusal that reads a module-level name is
    therefore writable by the thing it polices -- the hatch an earlier guard in this
    layer had to close for its family list. Here the prefix is a module global, so
    the arm is whether rewriting it disarms the refusal."""
    e = pgc_vacuity.Expect("sentinel::hatch")
    original = pgc_vacuity.QUERY_ERROR
    try:
        for spelling in ("", "NOTHING_MATCHES_THIS", "Q"):
            pgc_vacuity.QUERY_ERROR = spelling
            try:
                e.text(query_error("a"), query_error("b"), "a rewritten prefix")
            except VacuityError:
                expect.num(1, 1, f"the refusal still arrives with the prefix set to {spelling!r}")
            except AssertionError:
                raise AssertionError(
                    f"rewriting QUERY_ERROR to {spelling!r} disarmed the refusal: the "
                    f"values were COMPARED instead of refused"
                )
            else:
                raise AssertionError(f"rewriting QUERY_ERROR to {spelling!r} disarmed the refusal")
    finally:
        pgc_vacuity.QUERY_ERROR = original
    expect.num(1 if pgc_vacuity.QUERY_ERROR == original else 0, 1,
               "and the module is left as it was found")


def test_a_legitimate_comparison_is_untouched(expect):
    """The cost side. A refusal that also refuses real data is not a refusal."""
    e = pgc_vacuity.Expect("sentinel::cost")
    e.text("abc", "abc", "equal text still passes")
    e.rows([(1, "a")], [(1, "a")], "equal rows still pass")
    e.row_set([(1,), (2,)], [(2,), (1,)], "a set comparison still ignores order")
    e.num(7, 7, "equal numbers still pass")
    expect.num(1, 1, "four honest comparisons passed through the new refusal")
