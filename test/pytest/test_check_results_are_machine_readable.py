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


def test_each_verdict_emits_one_record_carrying_its_fields(expect):
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
    parts = {r.split("\t")[2] for r in _records(' check "a name" x x')}
    expect.num(len(parts), 1, "the record names exactly one part")
    expect.text("nonempty" if parts and next(iter(parts)) else "empty", "nonempty",
                "and the part field is not blank")

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

    ok = "RESULT\ts\ta\tPASS\t\nRESULT\ts\tb\tPASS\t\nchecks run: 2\n"
    expect.num(run(ok)[1], 0, "a log whose records match its stated count reconciles")

    out, rc = run("RESULT\ts\ta\tPASS\t\nchecks run: 2\n")
    expect.num(rc, 1, "a log with fewer records than it claims is caught")
    expect.num(out.count("records=1"), 1, "and both numbers are named, not just the verdict")

    expect.num(run("RESULT\ts\ta\tPASS\t\nRESULT\ts\tb\tPASS\t\n"
                   "RESULT\ts\tc\tPASS\t\nchecks run: 2\n")[1], 1,
               "a log with more records than it claims is caught too")

    # A log with no count at all never reached its summary. That is a different fault
    # from a miscount and must not read as a clean reconciliation.
    expect.num(run("RESULT\ts\ta\tPASS\t\n")[1], 1,
               "a log that never stated a count is not silently accepted")
