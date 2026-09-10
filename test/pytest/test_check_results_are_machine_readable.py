"""A check result must be machine-readable, and counted in ONE place.

Check results were prose. `check`, `check_num` and `check_text` printed PASS or FAIL
and nothing else, so proving a mutation reddened one NAMED check meant grepping text.
That is how a reverted guard once reported plain green while the check count fell from
190 to 186: the suite passed, and the only evidence anything had changed was a number
nobody was comparing.

The fix is not a second emitter beside the counters. A second source of truth for how
many checks ran is the defect this issue family exists to close, and `lib.sh` had
ELEVEN places that bumped `PGC_CHECKS` -- eleven chances to add a twelfth and forget
the line beside it, which is exactly what `projections.sh`'s `expect_fail` did with ten
call sites for as long as it existed.

So counting a check and recording it are ONE operation, `pgc_record`. `checks run: N`
and the N record lines are the same increment seen twice.

These tests drive the shell out of `lib.sh` rather than reimplementing it, for the same
reason `test_suite_accounting.py` does: a Python twin would agree with itself.
"""

import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
LIB = REPO / "test" / "lib.sh"
RUNNER = REPO / "test" / "run_all_versions.sh"


def _sh(body):
    """Run a snippet with lib.sh sourced, under the shell options the suites use."""
    script = f'set -uo pipefail\ncd "{LIB.parent}"\n. ./lib.sh >/dev/null 2>&1\n{body}\n'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout


def _records(call):
    return [l for l in _sh(call).splitlines() if l.startswith("RESULT\t")]


def _human(call):
    return [l for l in _sh(call).splitlines() if not l.startswith("RESULT\t")]


def _extract(path, name):
    out, keep = [], False
    for line in path.read_text().splitlines():
        if line.startswith(f"{name}() "):
            keep = True
        if keep:
            out.append(line)
            if line == "}":
                break
    return "\n".join(out)


# ---- the structural arm -----------------------------------------------------


def test_lib_sh_counts_a_check_in_exactly_one_place(expect):
    """Eleven bump sites were eleven chances to add a twelfth and forget the outcome.

    This is the arm that stops the next `expect_fail` from being written, rather than
    catching it after it has been silently miscounting for a year.
    """
    text = LIB.read_text()
    expect.num(text.count("PGC_CHECKS=$((PGC_CHECKS"), 1,
               "lib.sh bumps PGC_CHECKS in exactly one place")
    expect.num(_extract(LIB, "pgc_record").count("PGC_CHECKS=$((PGC_CHECKS"), 1,
               "and that place is pgc_record")


# ---- the record line --------------------------------------------------------


def test_each_verdict_emits_one_record_carrying_its_fields(tmp_path, expect):
    """Tab separated -- suite, name, verdict, reason -- so a name with spaces survives.

    The reason carries the REASON_CODE, which is what makes this more than a reformat:
    an unrunnable check is distinguishable from a passing one without parsing prose.
    """
    for call, verdict in ((' check "a name" x x', "PASS"),
                          (' check "a name" x y', "FAIL")):
        recs = _records(call)
        expect.num(len(recs), 1, f"a {verdict} check emits exactly one record")
        expect.text(recs[0].split("\t")[4], verdict, f"and its verdict field says {verdict}")
    expect.text(_records(' check "a name" x x')[0].split("\t")[3], "a name",
                "and the name field keeps its spaces")

    # WHICH PART asked it. The suite is not enough: harness_selftest sources
    # 40-odd parts into one shell and its premises are phrased to be COPIED --
    # "premise: the pytest layer is where THIS PART thinks it is" says "this part"
    # so the same sentence works in any of them. So (suite, name) is a key of
    # check NAMES, not of checks, and one sharer going red would mark them all.
    # Derived from BASH_SOURCE rather than from a convention. Found by
    # OffgridwithJD, whose own six branches were each adding more.
    # THESE TWO ARMS COULD NOT FAIL, and OffgridwithJD said so. The field is
    # `${_part:-${PGC_SUITE:-unknown}}`, so deleting the derivation still yields a
    # non-blank single value and both arms stayed green. "Exactly one, and not
    # blank" is satisfied by the fallback.
    #
    # The property needs a case where the part and the suite DIFFER, which is the
    # case the field exists for: harness_selftest sources 40-odd parts into one
    # shell. So a fixture does the same -- an outer script that sources an inner
    # one which calls the check -- and the record must name the INNER file.
    outer = tmp_path / "outer_suite.sh"
    inner = tmp_path / "inner_part.sh"
    inner.write_text('check "a name" x x\n')
    outer.write_text(f'. "{LIB}"\n. "{inner}"\n')
    r = subprocess.run(["bash", "-c", f'set -uo pipefail\nbash "{outer}"'],
                       capture_output=True, text=True)
    recs = [l for l in r.stdout.splitlines() if l.startswith("RESULT\t")]
    expect.num(len(recs), 1, "premise: the sourced part emitted exactly one record")
    suite, part = recs[0].split("\t")[1], recs[0].split("\t")[2]
    expect.text(suite, "outer_suite", "the suite is the script that ran")
    expect.text(part, "inner_part", "and the part is the file the check was asked from")
    expect.text("different" if suite != part else "same", "different",
                "which are not the same thing, and the fallback would make them so")

    recs = _records(' check_unrunnable "a name" MISSING_DEPENDENCY "no jq"')
    expect.num(len(recs), 1, "an unrunnable check emits exactly one record")
    expect.text(recs[0].split("\t")[4], "UNRUN",
                "and its verdict is UNRUN, which is neither of the other two")
    expect.text(recs[0].split("\t")[5], "MISSING_DEPENDENCY",
                "and the REASON_CODE travels in the reason field, not in prose")

    # A reason the enum does not hold is already a FAIL. It must record the verdict it
    # produced, not the one it was asked for.
    expect.text(_records(' check_unrunnable "n" NOT_A_REASON "x"')[0].split("\t")[4],
                "FAIL", "a bogus reason code records FAIL, not UNRUN")


def test_every_helper_records_exactly_once(expect):
    """Not a sample. Each of these had its own counter bump and its own outcome line,
    and each was one place the pair could come apart."""
    cases = {
        'check_text "n" "" "x"': "FAIL",
        'check_num "n" abc 1': "FAIL",
        'check_ratio "n" abc 1 2': "FAIL",
        'check_ratio "n" 0 1 2': "FAIL",
        'check_ratio "n" 1 1 2': "PASS",
        'pgc_pass "n"': "PASS",
        'pgc_fail "n" "d"': "FAIL",
    }
    for call, verdict in cases.items():
        recs = _records(" " + call)
        expect.num(len(recs), 1, f"{call.split()[0]} emits exactly one record")
        expect.text(recs[0].split("\t")[4], verdict, f"and records {verdict}")


def test_the_human_lines_are_byte_identical(expect):
    """3,762 call sites, and suites, selftests and CI all grep `^PASS` and `^FAIL`.

    Adding a record beside them is only safe if the prose did not move, so the exact
    strings are pinned rather than the refactor trusted.
    """
    cases = {
        ' check "a name" x x': "PASS  a name",
        ' check "a name" x y': "FAIL  a name: got [x] want [y]",
        ' check_unrunnable "a name" MISSING_DEPENDENCY "no jq"':
            "UNRUN  a name: MISSING_DEPENDENCY: no jq",
        ' check_text "n" "" "x"':
            "FAIL  n: a side is empty, so nothing was compared: got [] want [x]",
        ' check_num "n" abc 1':
            "FAIL  n: not a measurement, so nothing was compared: got [abc] want [1]",
    }
    for call, want in cases.items():
        expect.text("\n".join(_human(call)), want, f"{call.strip().split()[0]} prints its old line")


def test_the_record_count_equals_the_counter_the_summary_reports(expect):
    """One operation, so it cannot fail by drifting -- but it CAN fail if a helper is
    added that prints an outcome without recording it, which is the expect_fail shape."""
    out = _sh(' check a x x; check b x y; check_text c "" x; check_num d abc 1\n'
              ' check_ratio e 1 1 2; pgc_pass f; check_unrunnable g MISSING_DEPENDENCY h\n'
              ' echo "COUNTED $PGC_CHECKS"')
    records = len([l for l in out.splitlines() if l.startswith("RESULT\t")])
    counted = int(next(l.split()[1] for l in out.splitlines() if l.startswith("COUNTED ")))
    expect.num(records, 7, "premise: the probe ran every helper shape once")
    expect.num(records, counted, "the record count equals the counter the summary reports")


# ---- the runner reconciles the two --------------------------------------------


def test_the_runner_reconciles_records_against_the_stated_count(tmp_path, expect):
    """A log states `checks run: N` and carries N records. Those are two artifacts of
    the same run, and they can genuinely disagree: a suite killed mid-way, a truncated
    log, a helper that prints an outcome without recording it."""
    body = _extract(RUNNER, "pgc_reconcile_records")
    expect.at_least(len(body), 1, "premise: the runner defines the reconciliation")

    def run(text):
        log = tmp_path / "s.log"
        log.write_text(text)
        script = f'set -uo pipefail\n{body}\npgc_reconcile_records "{log}"\n'
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        return r.stdout, r.returncode

    ok = "RESULT\ts\tp\ta\tPASS\t\nRESULT\ts\tp\tb\tPASS\t\nchecks run: 2\n"
    expect.num(run(ok)[1], 0, "a log whose records match its stated count reconciles")

    out, rc = run("RESULT\ts\tp\ta\tPASS\t\nchecks run: 2\n")
    expect.num(rc, 1, "a log with fewer records than it claims is caught")
    expect.num(out.count("records=1"), 1, "and both numbers are named, not just the verdict")

    expect.num(run("RESULT\ts\tp\ta\tPASS\t\nRESULT\ts\tp\tb\tPASS\t\n"
                   "RESULT\ts\tp\tc\tPASS\t\nchecks run: 2\n")[1], 1,
               "a log with more records than it claims is caught too")

    # A log with no count at all never reached its summary. That is a different fault
    # from a miscount and must not read as a clean reconciliation.
    expect.num(run("RESULT\ts\tp\ta\tPASS\t\n")[1], 1,
               "a log that never stated a count is not silently accepted")


# ---- the timing helpers reported an outcome that nothing counted ------------


def _timing(skip, call):
    """Run one timing helper with PGC_SKIP_TIMING set or clear."""
    body = (f'PGC_SKIP_TIMING={skip}\n'
            'PGC_FAIL=0; PGC_CHECKS=0; PGC_PASSED=0; PGC_FAILED=0; PGC_UNRUN=0; PGC_SKIPPED=0\n'
            f'{call}\n'
            'echo "COUNTS $PGC_CHECKS/$PGC_PASSED/$PGC_SKIPPED"')
    out = _sh(body)
    recs = [l for l in out.splitlines() if l.startswith("RESULT\t")]
    human = [l for l in out.splitlines()
             if not l.startswith("RESULT\t") and not l.startswith("COUNTS ")]
    counts = next((l.split()[1] for l in out.splitlines() if l.startswith("COUNTS ")), "")
    return recs, human, counts


def test_a_skipped_timing_check_is_counted_and_recorded(expect):
    """`check_timing` and `check_ratio_needs_quiet_machine` under PGC_SKIP_TIMING=1
    printed a human SKIP line and returned -- no count, no record.

    Two outcomes a reader sees, invisible to both the count and the records, in the
    part whose whole argument is that those are one operation. Nothing reached those
    branches either: removing both emitters left every other arm green. Found by
    @linuxhikerpm.

    SKIP is a fourth outcome, counted like the other three, so `checks run:` reports
    the checks a suite ENCOUNTERED rather than the ones it managed to evaluate. It is
    deliberately not `check_unrunnable`: that state exits the suite INCOMPLETE, and CI
    sets PGC_SKIP_TIMING on every run, so every run would go red. A wall-clock check
    not asked on a shared runner is a different thing from one that could not be
    answered.
    """
    for call, tail in ((' check_timing "a timing check" 1 1',
                        "wall-clock measurement"),
                       (' check_ratio_needs_quiet_machine "a ratio check" 1 1 2',
                        "wall-clock ratio")):
        name = call.split('"')[1]
        recs, human, counts = _timing(1, call)
        expect.num(len(recs), 1, f"{name}: skipped, emits exactly one record")
        expect.text(recs[0].split("\t")[4], "SKIP", f"{name}: and its verdict is SKIP")
        expect.text(counts, "1/0/1", f"{name}: and it is counted as a skip")
        expect.text("\n".join(human), f"SKIP  {name} (PGC_SKIP_TIMING: {tail})",
                    f"{name}: and its human line is unchanged")

        recs, _, counts = _timing(0, call)
        expect.num(len(recs), 1, f"{name}: enabled, emits exactly one record")
        expect.text(recs[0].split("\t")[4], "PASS", f"{name}: and passes")
        expect.text(counts, "1/1/0", f"{name}: counted as a pass, not a skip")


def test_the_accounting_line_reconciles_four_outcomes(expect):
    """Four counters against the count, which is the same shape as three against it.

    The skipped term is printed even when zero: a term that disappears when empty is
    a term a reader cannot tell from a term that was never there.
    """
    def acct(skip):
        out = _sh(f'PGC_SKIP_TIMING={skip}\n'
                  ' check "an ordinary check" x x\n'
                  ' check_timing "a timing check" 1 1\n'
                  ' pgc_summary')
        return next((l for l in out.splitlines() if l.startswith("accounting: ")), "")

    expect.text(acct(1), "accounting: 1 passed + 0 failed + 0 unrunnable + 1 skipped = 2",
                "a skipped check appears in the accounting identity")
    expect.text(acct(0), "accounting: 2 passed + 0 failed + 0 unrunnable + 0 skipped = 2",
                "and the term is printed when zero, not omitted")


def test_a_suite_that_evaluated_nothing_did_not_pass(expect):
    """Before the fourth counter a skipped check left PGC_CHECKS at zero, so the
    all-skipped suite hit the "ran no checks" branch by accident. Counting it would
    have made the suite report PASSED with nothing behind it, so the condition now
    says what it always meant: PASSED + FAILED + UNRUN, not CHECKS.
    """
    out = _sh('PGC_SKIP_TIMING=1\n'
              ' check_timing "a timing check" 1 1\n'
              ' pgc_summary')
    verdicts = [l for l in out.splitlines()
                if l.endswith(("PASSED", "FAILED", "INCOMPLETE"))
                or l.endswith("SKIPPED (ran no checks)")]
    expect.text("\n".join(v.split(": ", 1)[1] for v in verdicts),
                "SKIPPED (ran no checks)",
                "a suite whose every check was skipped did not pass")
