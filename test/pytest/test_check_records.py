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
