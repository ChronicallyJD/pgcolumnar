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
        # (forward, reverse) AS WELL AS (got, want). `ordering_observable` compares two
        # caller-supplied readings under different parameter names, so a derivation
        # keyed on "got" missed it -- and it was the one assertion the unique producer
        # made WEAKER, turning a loud red into a silent pass. Reported by @jdatcmd.
        if len(params) >= 2 and (
                (params[0] == "got" and params[1] in ("want", "floor"))
                or (params[0], params[1]) == ("forward", "reverse")):
            out.append((name, params[1]))
    return sorted(out)


def test_the_comparison_surface_is_what_this_file_thinks_it_is(expect):
    """premise: the derivation finds the assertions, so the arm below is not vacuous."""
    names = [n for n, _ in _comparisons()]
    expect.at_least(len(names), 5, "the layer offers at least five (got, want) comparisons")
    for required in ("hash", "text", "rows", "row_set", "ordered_rows",
                     "ordering_observable"):
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
    # Forward and reverse must DIFFER, or the assertion refuses the fixture for a
    # different reason and the arm would pass without testing the sentinel.
    "ordering_observable": ([(1,), (2,)], [(2,), (1,)]),
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
    """Every conftest under test/pytest/ is imported before collection, so a corpus file
    can rewrite this module's globals. The refusal must survive that.

    THE FIRST VERSION OF THIS ARM WAS TAUTOLOGICAL and @jdatcmd measured it. It rewrote
    `pgc_vacuity.QUERY_ERROR` and THEN minted its sentinels with `query_error()`, which
    read that same global -- so producer and matcher moved together and the refusal
    matched whatever the prefix had just been set to. It could not fail for the property
    it names.

    The faithful hatch is this one: mint while the layer is armed, rewrite afterwards,
    which is what a corpus file actually does. Against the old code that COMPARED two
    sentinels instead of refusing them, and an end-to-end corpus file reported
    `1 passed` over two failed queries.

    `ZZZ_NOT_A_PREFIX` is in the list deliberately. `'Q'` alone cannot disarm a
    prefix-reading matcher, because `'QUERY_ERROR.1'.startswith('Q')` is true -- so a
    spelling that is not a prefix of the real one is the case that would have found the
    hole, and it is the case the old arm never tried.
    """
    e = pgc_vacuity.Expect("sentinel::hatch")
    original = pgc_vacuity.QUERY_ERROR
    for spelling in ("", "NOTHING_MATCHES_THIS", "Q", "ZZZ_NOT_A_PREFIX"):
        a, b = query_error("a"), query_error("b")      # minted WHILE ARMED
        # Compared in plain Python: `expect.text` now refuses a value carrying the
        # prefix, which is the point, and an arm ABOUT sentinels therefore cannot use
        # the assertion it is describing on one.
        expect.num(1 if a.split(".")[0] == original else 0, 1,
                   f"premise: minted under the real prefix ({spelling!r} case)")
        pgc_vacuity.QUERY_ERROR = spelling             # the corpus rewrites it after
        try:
            e.text(a, b, "a rewritten prefix")
        except VacuityError:
            expect.num(1, 1, f"the refusal survives the prefix being set to {spelling!r}")
        except AssertionError:
            raise AssertionError(
                f"rewriting QUERY_ERROR to {spelling!r} disarmed the refusal: the two "
                f"sentinels were COMPARED instead of refused"
            )
        else:
            raise AssertionError(f"rewriting QUERY_ERROR to {spelling!r} disarmed the refusal")
        finally:
            pgc_vacuity.QUERY_ERROR = original
    expect.num(1 if pgc_vacuity.QUERY_ERROR == original else 0, 1,
               "and the module is left as it was found")


def test_a_hardcoded_sentinel_survives_the_same_rewrite(expect):
    """The corpus hardcodes sentinel text that no producer minted --
    `'QUERY_ERROR.empty-relation'` and `f"QUERY_ERROR.no-partition-for-{table}"` in
    `test_hilbert_locality.py`, and `"QUERY_ERROR.1"` in `test_guards_pinned.py`. One of
    those is built inside SQL by `coalesce(...)`, so it can never come from
    `query_error()`. A matcher that read a rewritable global would stop seeing them.
    """
    e = pgc_vacuity.Expect("sentinel::hardcoded")
    original = pgc_vacuity.QUERY_ERROR
    left = "QUERY_ERROR.empty-relation"
    right = "".join(["QUERY_ERROR", ".empty-relation"])   # equal, distinct objects
    expect.num(1 if left is not right else 0, 1,
               "premise: the two are distinct objects, so identity guards cannot fire")
    pgc_vacuity.QUERY_ERROR = "NOTHING_MATCHES_THIS"
    try:
        e.text(left, right, "two hardcoded sentinels after a rewrite")
    except VacuityError:
        expect.num(1, 1, "a hardcoded sentinel is still refused")
    except AssertionError:
        raise AssertionError("the hardcoded sentinel was COMPARED after the rewrite")
    else:
        raise AssertionError("the hardcoded sentinel was accepted after the rewrite")
    finally:
        pgc_vacuity.QUERY_ERROR = original


def test_the_ordering_premise_refuses_a_failed_reading(expect):
    """The one assertion the unique producer made WEAKER before this arm existed.

    `ordering_observable` requires forward and reverse to differ. With the old shared
    constant two failed readings were IDENTICAL, so it went red -- loudly, for the wrong
    reason but in the right direction. With unique sentinels they differ, so it passed
    and greenlit every ordered assertion resting on the premise. Measured by @jdatcmd,
    and it is why the refusal is now the first thing that assertion does.
    """
    e = pgc_vacuity.Expect("sentinel::ordering")
    for label, fwd, rev in (
            ("both readings failed", [(query_error("f"),)], [(query_error("r"),)]),
            ("one reading failed", [(query_error("f"),), (1,)], [(1,), (2,)])):
        try:
            e.ordering_observable(fwd, rev, "the ordering premise")
        except VacuityError:
            expect.num(1, 1, f"the ordering premise refuses when {label}")
        except AssertionError:
            raise AssertionError(f"{label}: compared instead of refused")
        else:
            raise AssertionError(f"{label}: the ordering premise PASSED on a failed query")


def test_a_legitimate_comparison_is_untouched(expect):
    """The cost side. A refusal that also refuses real data is not a refusal."""
    e = pgc_vacuity.Expect("sentinel::cost")
    e.text("abc", "abc", "equal text still passes")
    e.rows([(1, "a")], [(1, "a")], "equal rows still pass")
    e.row_set([(1,), (2,)], [(2,), (1,)], "a set comparison still ignores order")
    e.num(7, 7, "equal numbers still pass")
    expect.num(1, 1, "four honest comparisons passed through the new refusal")
