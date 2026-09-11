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


def stated_totals_in(text):
    """-> (tests, files) the TEXT claims, or None if it states none."""
    m = TOTALS.search(text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def stated_totals(doc_path):
    """-> (tests, files) the document claims, or None if it states none."""
    return stated_totals_in(pathlib.Path(doc_path).read_text())


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


def documented_but_absent(directory, doc):
    """Names the DOCUMENT claims that the corpus does not have.

    THE SWEEP ABOVE GOES ONE WAY ONLY. `undocumented()` computes tests on disk
    that the document fails to name, and nothing computed the reverse. So a test
    DELETED or RENAMED while its entry survived was caught by the totals line and
    by nothing else -- and the totals line is a merge target whose correct value
    is a function of the merge, so it is the half most likely to be removed
    (#908). Removing it while this direction was uncovered would have retired a
    check silently, which is the move this file exists to prevent.

    Driven against the real functions, on the corpus that shipped:

        on disk           (1, 1)      # test_one.py holds test_alpha
        document states   (2, 1)      # "test_one.py: test_alpha and test_beta"

        the NAMING arm  : []          <- says nothing is wrong
        the TOTALS arm  : DISAGREE    <- the only arm that reddens

    A BACKTICKED NAME, not any occurrence. The document discusses fixtures and
    hypothetical tests in prose, and a bare-word sweep would report those as
    missing. Backticks are how this document already marks a real identifier, and
    the false-positive budget over the corpus was measured before this was
    written rather than after: 127 backticked names, 2 of which were genuinely
    absent, and both were real defects rather than noise.
    """
    found = corpus_tests(directory)
    on_disk_fns = {n for names in found.values() for n in names}
    on_disk_files = set(found)
    named = set(re.findall(r"`(test_[A-Za-z0-9_]*(?:\.py)?)`", doc.read_text()))
    # A SORTED LIST, like undocumented() beside it. It returned a preformatted
    # "[n: a b c]" string first, copying the bash twin's shape rather than its
    # Python neighbour's, and the two-return-types-one-concept split immediately
    # cost something real: a check written against it read `x in ("[]", "")`,
    # which is False for an empty LIST, and reported a defect as unreproducible.
    return sorted({n for n in named if n.endswith(".py")} - on_disk_files) \
         + sorted({n for n in named if not n.endswith(".py")} - on_disk_fns)


def test_a_documented_test_that_does_not_exist_is_named(expect):
    """The document must not claim a test the corpus does not have.

    It did. `test_layer_rejects_an_absence_assertion_over_an_empty_plan` and its
    control `..._allows_an_absence_assertion_over_a_real_plan` were named in the
    test_layer.py section and existed nowhere: the work is real but lives in
    test_guards_pinned.py as `test_plan_marker_refuses_an_absence_claim_over_an_empty_plan`,
    and is documented correctly there. Two rows claimed coverage under names that
    had never been written, and every other arm in this file passed over them --
    which is the point.
    """
    expect.text(", ".join(documented_but_absent(HERE, DOC)) or "none", "none",
                "every test the document names exists in the corpus")


def test_a_document_naming_a_test_that_was_deleted_is_caught(tmp_path, expect):
    """The removal proof, on a fixture: the shape the real defect had.

    Without this the arm above passes on a healthy tree, which is exactly what an
    arm that computes nothing also does.
    """
    (tmp_path / "test_one.py").write_text("def test_alpha(expect):\n    pass\n")
    doc = tmp_path / "DOC.md"
    doc.write_text("**1 tests in 1 files.**\n`test_one.py`: `test_alpha` and `test_beta`\n")
    expect.text(", ".join(documented_but_absent(tmp_path, doc)), "test_beta",
                "a documented test that does not exist is named, not passed over")
    doc.write_text("**1 tests in 1 files.**\n`test_one.py`: `test_alpha`\n")
    expect.text(", ".join(documented_but_absent(tmp_path, doc)) or "none", "none",
                "control: a document naming only what exists is clean")


def test_a_documented_file_that_does_not_exist_is_caught(tmp_path, expect):
    """A whole file can go the same way, and it is how a rename usually shows up."""
    (tmp_path / "test_one.py").write_text("def test_alpha(expect):\n    pass\n")
    doc = tmp_path / "DOC.md"
    doc.write_text("`test_one.py` and `test_gone.py`: `test_alpha`\n")
    expect.text(", ".join(documented_but_absent(tmp_path, doc)), "test_gone.py",
                "a documented file that does not exist is named")


def test_no_test_name_is_defined_twice_in_the_corpus(expect):
    """The premise the set-equality argument needs, and it was missing (@jdatcmd).

    #919 argues that removing the totals line costs nothing because the two
    sweeps give set EQUALITY between the document and the corpus. That is true of
    NAMES and it is not true of DEFINITION COUNTS, which is what a total counts:

        two files defining test_shared_shape
            definitions on disk           2
            distinct names                1
            undocumented()                clean
            documented_but_absent()       clean
            -> BOTH ARMS GREEN, and the counts differ

    Measured, not argued. It cannot happen today -- 139 definitions against 139
    distinct names, zero duplicates -- so the conclusion was true in fact but not
    by construction, which is the difference between an argument and a guard.

    IT CLOSES SOMETHING REAL BEYOND THE ARGUMENT. `undocumented()` asks whether a
    name appears in the document at all, so a test defined TWICE and documented
    ONCE reads as fully covered. The second definition is invisible to every arm
    here, and pytest runs both.
    """
    found = corpus_tests(HERE)
    names = [n for tests in found.values() for n in tests]
    expect.at_least(len(names), 20, "premise: the corpus was found")
    dupes = sorted({n for n in names if names.count(n) > 1})
    expect.text(", ".join(dupes) or "none", "none",
                "no test name is defined twice in the corpus")
    expect.num(len(names), len(set(names)),
               "so definitions and distinct names are the same count")


def test_a_name_defined_in_two_files_is_caught(tmp_path, expect):
    """The removal proof, and the exact shape that defeats the equality argument."""
    (tmp_path / "test_a.py").write_text("def test_shared_shape(expect):\n    pass\n")
    (tmp_path / "test_b.py").write_text("def test_shared_shape(expect):\n    pass\n")
    found = corpus_tests(tmp_path)
    names = [n for tests in found.values() for n in tests]
    expect.num(len(names), 2, "premise: both definitions were seen")
    expect.num(len(set(names)), 1, "and they share one name")
    expect.text(", ".join(sorted({n for n in names if names.count(n) > 1})),
                "test_shared_shape",
                "a name defined in two files is named, not passed over")


def test_the_document_states_no_totals_for_a_merge_to_get_wrong(expect):
    """TESTS.md must NOT carry a totals line (#908, step 2).

    It used to, and `selftest/350` compared it against the corpus, which is what
    made it a claim rather than decoration. The problem was never the check: it
    was that the number was WRITTEN rather than DERIVED, and its correct value is
    a function of the MERGE rather than of either branch. It collided on
    essentially every rebase touching the corpus -- ten times in one day, both
    sides wrong every time, so there was no side to pick.

    REMOVING IT COSTS NOTHING, and that is provable rather than hopeful. The two
    sweeps together are strictly stronger than any count:

        test_every_file_and_test_is_named_in_the_document
            every test on disk is named here          (disk  subset of  document)
        test_a_documented_test_that_does_not_exist_is_named
            every name here exists on disk            (document  subset of  disk)

    Two subsets in opposite directions is set EQUALITY, so the documented set and
    the corpus are the same set, and any count over one equals the count over the
    other. A stated total was a derived value written by hand.

    WHY THIS IS AN ARM AND NOT JUST A DELETION. Nothing stops the next person
    adding the sentence back -- it reads like an improvement. This arm is what
    makes its absence a decision rather than an accident, and `stated_totals`
    stays for it: the reader still has to work, or "no totals line" would be
    indistinguishable from "cannot find one".
    """
    expect.text(repr(stated_totals(DOC)), "None",
                "TESTS.md states no totals line for a merge to get wrong")

    # And the reader that reports it must still be able to FIND one, or the arm
    # above passes because the parser is broken rather than because the line is
    # gone -- the exact shape this corpus exists to refuse.
    expect.text(repr(stated_totals_in("**7 tests in 3 files.** and prose")),
                "(7, 3)",
                "premise: the reader still finds a totals line when one is there")


def test_the_corpus_counts_are_reported_rather_than_written(expect):
    """The counts do not vanish; they move to where they cannot go stale.

    A number nobody maintains is better than a wrong one, but a number nobody can
    SEE is worse than both. The harness prints them every run, computed from the
    corpus, so a reader gets the same information without the document asserting
    anything.
    """
    found = corpus_tests(HERE)
    total = sum(len(v) for v in found.values())
    expect.at_least(total, 20, "premise: the corpus was found, so a count means something")
    expect.num(len(found), len({f for f in found}), "each file counted once")
    print(f"\nCORPUS: {total} test functions in {len(found)} files")


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
    expect.differ(stated_totals(doc),
                  (sum(len(v) for v in found.values()), len(found)),
                  "a stated total that disagrees with disk does not compare equal")


# ---------------------------------------------------------------------------
# VACUITY_MODES.md counts itself, and the count is checked.
#
# @jdatcmd found README.md and VACUITY_MODES.md disagreeing about how many modes
# the layer refuses, and could not check either because the document offered NO
# COUNTING RULE. A document whose subject is claims that cannot be checked should
# not make one. Section 1a now defines a mode as a backticked kebab id of three
# or more words; this asserts the numbers 1a states are the numbers on disk.

MODE_ID = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+){2,})`")
MODES_DOC = HERE / "VACUITY_MODES.md"


def _named_modes():
    """-> (refused, not_refused, all) per section 1a's rule."""
    text = MODES_DOC.read_text()
    chunks = {}
    for chunk in re.split(r"^## ", text, flags=re.M):
        head = chunk.splitlines()[0] if chunk.strip() else ""
        chunks[head] = set(MODE_ID.findall(chunk))
    refused = next((v for k, v in chunks.items() if k.startswith("2.")), set())
    not_refused = next((v for k, v in chunks.items() if k.startswith("3.")), set())
    # Section 3 keeps a back-reference to every mode that moved into section 2
    # ("`X` is now closed"), so a mode can be named in both. Section 2 wins: a
    # refused mode is refused. Without this the same id is counted in two states
    # and the totals stop adding up -- measured at 25 + 50 against 72 named.
    not_refused = not_refused - refused
    return refused, not_refused, set().union(*chunks.values()) if chunks else set()


def test_the_mode_inventory_states_its_own_totals_correctly(expect):
    """The numbers in section 1a must be the numbers on disk.

    Not a tidiness check: these totals are how a reader decides whether a gap is
    covered, and they were wrong in two files at once with no way to tell.
    """
    refused, not_refused, allm = _named_modes()
    expect.at_least(len(allm), 20, "premise: the counting rule finds modes at all")

    doc = MODES_DOC.read_text()
    for label, got in (("refused today", len(refused)),
                       ("not refused", len(not_refused)),
                       ("named in this document", len(allm))):
        row = re.search(rf"\|[^|\n]*{re.escape(label)}[^|\n]*\|\s*\**(\d+)", doc)
        expect.text(repr(row is not None), "True",
                    f"section 1a states a total for {label!r}")
        expect.num(int(row.group(1)), got,
                   f"the stated total for {label!r} is the number on disk")


def test_the_readme_and_the_inventory_agree_on_what_is_refused(expect):
    """They did not, and neither could be checked against anything.

    README.md said 23 refused while the inventory named 21 — the run's number
    against the document's, with nothing to distinguish them.
    """
    refused, _, _ = _named_modes()
    readme = (HERE / "README.md").read_text()
    expect.at_least(readme.count(f"{len(refused)} refused"), 1,
                    "README.md quotes the number of modes actually named as refused")


def test_the_inventory_accounts_for_every_mode_the_run_found(expect):
    """The 'named nowhere here' row is the gap this document admits to.

    It is arithmetic between numbers the document states, so it can go stale on
    its own: an editor who transcribes a missing mode updates the named total and
    leaves the gap row claiming a gap that has closed. The enumeration's own 79 is
    history -- it is not on disk, and this does not pretend to check it.
    """
    doc = MODES_DOC.read_text()

    def row(label):
        m = re.search(rf"\|[^|\n]*{re.escape(label)}[^|\n]*\|\s*\**(\d+)", doc)
        expect.text(repr(m is not None), "True", f"section 1a states {label!r}")
        return int(m.group(1))

    refused, not_refused, _ = _named_modes()
    expect.num(len(refused) + len(not_refused), row("named in this document"),
               "the two section totals sum to the document total")
    expect.num(row("produced by the enumeration run") - row("named in this document"),
               row("named nowhere here"),
               "the admitted gap is the run's total minus what is written down")


def test_the_prose_totals_match_the_counted_modes(expect):
    """Section 1a's table was not the only place a total lived.

    Three sentences outside it still asserted the run's 23 after the table said 21 --
    section 2's opening, the closing paragraph, and TESTS.md. A table that is checked
    and prose that is not means the drift simply moves into the prose, which is where
    it was in the first place.

    The run's own 23 appears once on purpose, as history, and is not touched here:
    what is gated is every sentence that states what the layer refuses TODAY.
    """
    refused, _, _ = _named_modes()
    n = len(refused)
    for path, pattern in (
        (MODES_DOC, r"(\d+) of the 79"),
        (MODES_DOC, r"known to refuse (\d+) demonstrated modes"),
        (HERE / "TESTS.md", r"This layer refuses (\d+)"),
    ):
        m = re.search(pattern, path.read_text())
        expect.text(repr(m is not None), "True",
                    f"{path.name} states a refused total matching {pattern!r}")
        expect.num(int(m.group(1)), n,
                   f"{path.name}: the prose total is the number of ids named")

def test_the_two_halves_of_the_refused_sentence_sum_to_the_named_total(expect):
    """TESTS.md states the split twice in one sentence: how many modes the layer
    refuses, and how many it does not. Only the first half was gated.

    `selftest/350`'s TESTS.md total arm matches `This layer refuses [0-9]+`, which is the
    half a change to the layer naturally updates. Closing a mode and updating that number
    left "The other 47" behind, and 26 + 47 = 73 against the 72 the inventory names --
    a contradiction introduced by the very change that fixed the other half, and caught
    by nothing. Reported by @jdatcmd.

    So both halves are read here, and checked against the inventory's own count of the
    ids it names rather than against a number typed twice.
    """
    doc = (HERE / "TESTS.md").read_text()
    m = re.search(r"This layer refuses (\d+)\s*\n?of them\.\*\*\s*The other (\d+)", doc)
    expect.text("found" if m else "missing", "found",
                "premise: the sentence states both halves in a form this arm can read")
    refused, other = int(m.group(1)), int(m.group(2))
    named = len(_named_modes()[0]) + len(_named_modes()[1])
    expect.num(refused + other, named,
               "the two halves sum to the number of modes the inventory names")
    expect.num(refused, len(_named_modes()[0]),
               "and the refused half is the count of ids section 2 claims")
