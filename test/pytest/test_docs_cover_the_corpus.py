"""TESTS.md must document every test in this directory.

THE TWIN RULE. Every test in this tree is written twice, once as a `.sh` suite and
once here, in the same change. This file is the pytest half of
`test/selftest/350-the-pytest-corpus-must-be.sh`, and the two are not
interchangeable:

  * The `.sh` half is the one with TEETH. `harness_selftest` is registered in
    `SUITES`, so it runs in the matrix and in CI. Nothing runs pytest -- not
    `run_all_versions.sh`, not any workflow under `.github/` -- so a guard written
    only here would never fire in the gate.
  * This half is the one a person running the corpus by hand gets, and it is
    where a failure arrives with the offenders as a Python list rather than as a
    string assembled by shell.

WHY THE GUARD EXISTS AT ALL. TESTS.md says its job is "what each test asserts, and
why it exists". It went stale inside a single rework: the corpus grew from 25 tests
in three files to 54 in five, and the two new files -- 29 tests, every one added by
the rework that answered a review -- were named nowhere in it, while the header
still read "Twenty-five tests in three files".

A partial index of something claiming completeness reads as a total one. A reader
who opens a file whose stated purpose is completeness does not then go and count
the tests. That is the same defect class the vacuity layer refuses one level down:
a report that looks like coverage and is not.
"""

import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
DOC = HERE / "TESTS.md"

# The bold, fixed-form totals line. Written in a form that can be read back
# precisely so it can be checked: prose that says "twenty-five" cannot be compared
# with anything, which is how the stale header survived being read many times.
TOTALS = re.compile(r"^\*\*(\d+) tests in (\d+) files\.\*\*", re.M)


def corpus_tests(directory):
    """-> {filename: [test name, ...]} for every test_*.py in `directory`."""
    found = {}
    for f in sorted(pathlib.Path(directory).glob("test_*.py")):
        found[f.name] = re.findall(r"^def (test_\w+)", f.read_text(), re.M)
    return found


def undocumented(directory, doc_path):
    """-> sorted list of file and test names the document does not name."""
    text = pathlib.Path(doc_path).read_text()
    missing = []
    for name, tests in corpus_tests(directory).items():
        if name not in text:
            missing.append(name)
        missing.extend(t for t in tests if t not in text)
    return sorted(missing)


def stated_totals(doc_path):
    """-> (tests, files) the document claims, or None if it states none."""
    m = TOTALS.search(pathlib.Path(doc_path).read_text())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _fixture(tmp_path, doc_body):
    """A two-test corpus and a document, so the arms can drive a KNOWN answer."""
    d = tmp_path / "corpus"
    d.mkdir(exist_ok=True)
    (d / "test_one.py").write_text(
        "def test_alpha(expect):\n    pass\ndef test_beta(expect):\n    pass\n")
    doc = d / "DOC.md"
    doc.write_text(doc_body)
    return d, doc


# ---------------------------------------------------------------------------
# The real corpus. Three properties, each mechanical.
# ---------------------------------------------------------------------------

def test_the_sweep_finds_the_corpus_rather_than_an_empty_glob(expect):
    """A sweep that found nothing reports "nothing missing" and is
    indistinguishable from a sweep that works. This is the premise the other two
    arms rest on, and it is asserted rather than assumed."""
    found = corpus_tests(HERE)
    expect.at_least(len(found), 3, "premise: the sweep found the corpus files")
    expect.at_least(sum(len(v) for v in found.values()), 20,
                    "premise: and the tests inside them")


def test_every_file_and_test_is_named_in_the_document(expect):
    """The property that went wrong. Named rather than counted, so a failure says
    WHICH test is undocumented instead of only how many."""
    missing = undocumented(HERE, DOC)
    expect.text(", ".join(missing) or "none", "none",
                "every test file and every test in the corpus is named in TESTS.md")


def test_the_stated_totals_are_the_totals_on_disk(expect):
    """Neither arm above would catch a wrong count: a document can name every test
    and still miscount them, which is exactly what the stale header did."""
    stated = stated_totals(DOC)
    expect.text(repr(stated is not None), "True",
                "TESTS.md states its totals in a form that can be read back")
    found = corpus_tests(HERE)
    expect.text(repr(stated), repr((sum(len(v) for v in found.values()), len(found))),
                "and the totals it states are the totals on disk")


# ---------------------------------------------------------------------------
# And the guard must be able to FAIL. Everything above passes on a healthy tree,
# which is exactly what a guard that does nothing also does.
# ---------------------------------------------------------------------------

def test_a_fully_documented_corpus_reports_nothing_missing(tmp_path, expect):
    """Control. A guard with a bad false-positive rate gets switched off, and then
    the guard it replaced is gone too."""
    d, doc = _fixture(tmp_path, "**2 tests in 1 files.**\ntest_one.py: test_alpha and test_beta\n")
    expect.text(", ".join(undocumented(d, doc)) or "none", "none",
                "control: a fully documented corpus reports nothing missing")


def test_an_undocumented_test_is_named_rather_than_passed_over(tmp_path, expect):
    """The exact shape that shipped: the file is named, one test inside it is not."""
    d, doc = _fixture(tmp_path, "**2 tests in 1 files.**\ntest_one.py: test_alpha\n")
    expect.text(", ".join(undocumented(d, doc)), "test_beta",
                "an undocumented test is named rather than passed over")


def test_an_undocumented_file_is_caught_with_the_tests_inside_it(tmp_path, expect):
    """How 29 tests went missing at once: two whole files were never named."""
    d, doc = _fixture(tmp_path, "**2 tests in 1 files.**\nnothing about the corpus at all\n")
    expect.text(", ".join(undocumented(d, doc)), "test_alpha, test_beta, test_one.py",
                "an undocumented file is caught along with the tests inside it")


def test_a_document_with_no_totals_line_states_none(tmp_path, expect):
    """`None` must not read as "the totals happen to match". Absent is its own
    answer, the same way `unknown` never reads as `fresh` elsewhere here."""
    d, doc = _fixture(tmp_path, "test_one.py: test_alpha and test_beta\n")
    expect.text(repr(stated_totals(doc)), "None",
                "a document stating no totals reports None, not a match")


def test_a_stated_total_that_disagrees_with_disk_is_visible(tmp_path, expect):
    """The count arm's own red. A document can name every test and still lie about
    how many there are."""
    d, doc = _fixture(tmp_path, "**9 tests in 4 files.**\ntest_one.py: test_alpha and test_beta\n")
    found = corpus_tests(d)
    expect.text(repr(stated_totals(doc)), "(9, 4)", "the document states 9 in 4")
    expect.text(repr((sum(len(v) for v in found.values()), len(found))), "(2, 1)",
                "while the fixture on disk holds 2 in 1")
    expect.num(int(stated_totals(doc) == (sum(len(v) for v in found.values()), len(found))), 0,
               "a stated total that disagrees with disk does not compare equal")
