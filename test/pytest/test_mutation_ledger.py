"""The mutation ledger: which checks have ever been seen red, and under what.

Nothing recorded whether a check had ever been red. That is the gap that let 39
checks across 35 suites ship unable to fail, three of them inside the suite whose
whole purpose is to stop exactly that. The gate answered *did anything print FAIL*
and had never answered *could anything print FAIL*.

**What this ledger claims, and what it does not.** It records that a named check was
OBSERVED RED in a recorded run. It does not claim the check is proven able to fail:
that is a stronger statement, it needs a named mutation applied deliberately, and
conflating the two would put a claim in the ledger that nothing measured -- the
`defeated: 0` shape from `VACUITY_MODES` section 1, a number that reads as evidence
and is not.

So v1 fills the observed column honestly and leaves the rest as debt, counted. A
ledger whose entries all read `never` is a measurement of how much of the corpus has
never been attacked, and that measurement is worth having on day one.

**What fills it.** Not only deliberate mutation runs. Every real CI red fills it,
every flake, every bisect -- and those arrive whether anyone remembers or not. A
mutation run is the deliberate accelerator, not the only source.

These tests drive the real tool, for the same reason the other two files drive the
real shell: a Python twin of a Python tool would agree with itself.
"""

import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
LEDGER_TOOL = REPO / "test" / "pgc_ledger.py"
RUNNER = REPO / "test" / "run_all_versions.sh"


def _run(*args):
    r = subprocess.run(["python3", str(LEDGER_TOOL), *args],
                       capture_output=True, text=True)
    return r.stdout + r.stderr, r.returncode


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def _rows(path):
    return [l.split("\t") for l in pathlib.Path(path).read_text().splitlines() if l]


GREEN = ("RESULT\tdemo\tpart1\tfirst check\tPASS\t\n"
         "RESULT\tdemo\tpart1\tsecond check\tPASS\t\n"
         "checks run: 2\n")
RED = ("RESULT\tdemo\tpart1\tfirst check\tFAIL\t\n"
       "RESULT\tdemo\tpart1\tsecond check\tPASS\t\n"
       "checks run: 2\n")


def test_a_green_run_records_debt_and_never_a_red_observation(tmp_path, expect):
    """The arm that matters most.

    A green run has seen nothing go red, so merging one must never record a red
    observation -- otherwise an ordinary CI run retires the debt the ledger exists
    to count.
    """
    ledger = _write(tmp_path, "l.tsv", "")
    log = _write(tmp_path, "green.log", GREEN)
    _run("merge", "--ledger", ledger, log)
    rows = _rows(ledger)
    expect.num(len(rows), 2, "merging a green run records both checks")
    expect.text(",".join(sorted({r[3] for r in rows})), "never",
                "and records neither as ever having been red")


def test_a_red_observation_is_dated_and_survives_a_later_green_run(tmp_path, expect):
    """The ledger records that a check WAS seen red, which stays true."""
    ledger = _write(tmp_path, "l.tsv", "")
    _run("merge", "--ledger", ledger, _write(tmp_path, "g.log", GREEN))
    _run("merge", "--ledger", ledger, "--date", "2026-09-10",
         _write(tmp_path, "r.log", RED))
    by = {r[2]: r[3] for r in _rows(ledger)}
    expect.text(by["first check"], "2026-09-10",
                "a check observed red gains the date it was seen")
    expect.text(by["second check"], "never",
                "and one that stayed green keeps its debt")

    _run("merge", "--ledger", ledger, "--date", "2026-09-11",
         _write(tmp_path, "g2.log", GREEN))
    expect.text({r[2]: r[3] for r in _rows(ledger)}["first check"], "2026-09-10",
                "a later green run does not erase an observation")


def test_the_mutation_column_exists_from_v1(tmp_path, expect):
    """Present with nothing filling it automatically, because adding a column later
    means rewriting every entry.

    If an entry can record WHICH mutation reddened a check, the catalogue a mutation
    gate would need builds itself out of work people already do by hand.
    """
    ledger = _write(tmp_path, "l.tsv", "")
    _run("merge", "--ledger", ledger, "--date", "2026-09-10",
         _write(tmp_path, "r.log", RED))
    expect.num(len([r for r in _rows(ledger) if len(r) != 5]), 0,
               "every row carries four fields, the fourth being the mutation")
    expect.text("[" + {r[2]: r[4] for r in _rows(ledger)}["first check"] + "]", "[]",
                "and it is empty when nothing named a mutation")

    _run("merge", "--ledger", ledger, "--date", "2026-09-10",
         "--mutation", "SAOP limit 128 -> 0", _write(tmp_path, "r2.log", RED))
    by = {r[2]: r[4] for r in _rows(ledger)}
    expect.text(by["first check"], "SAOP limit 128 -> 0",
                "a named mutation is recorded against the check that reddened")
    expect.text("[" + by["second check"] + "]", "[]",
                "and not against one that stayed green")


def test_a_rename_is_reported_rather_than_silently_resetting_history(tmp_path, expect):
    """Keyed by the display string, a rename loses history and reads exactly like a
    brand-new check that has never been red -- the one state this ledger exists to
    distinguish. It is detected and named instead.

    Both directions are required: a check merely added, or merely removed, is not a
    rename, and reporting one on every new check is noise that gets it ignored.
    """
    ledger = _write(tmp_path, "l.tsv", "")
    before = ("RESULT\tdemo\tpart1\tthe old name\tFAIL\t\n"
              "RESULT\tdemo\tpart1\ta stable check\tPASS\t\nchecks run: 2\n")
    _run("merge", "--ledger", ledger, "--date", "2026-09-01",
         _write(tmp_path, "b.log", before))

    after = ("RESULT\tdemo\tpart1\tthe new name\tPASS\t\n"
             "RESULT\tdemo\tpart1\ta stable check\tPASS\t\nchecks run: 2\n")
    out, _ = _run("rename-scan", "--ledger", ledger, _write(tmp_path, "a.log", after))
    expect.num(out.count("possible rename: the old name -> the new name"), 1,
               "a name that appeared while another disappeared is reported")
    expect.num(out.count("a stable check"), 0, "and the stable check is not")

    added = after.replace("the new name", "the old name") + ""
    added = ("RESULT\tdemo\tpart1\tthe old name\tPASS\t\n"
             "RESULT\tdemo\tpart1\ta stable check\tPASS\t\n"
             "RESULT\tdemo\tpart1\ta genuinely new check\tPASS\t\nchecks run: 3\n")
    out, _ = _run("rename-scan", "--ledger", ledger, _write(tmp_path, "add.log", added))
    expect.num(out.count("possible rename"), 0,
               "a check merely added is not reported as a rename")

    removed = "RESULT\tdemo\tpart1\ta stable check\tPASS\t\nchecks run: 1\n"
    out, _ = _run("rename-scan", "--ledger", ledger, _write(tmp_path, "rm.log", removed))
    expect.num(out.count("possible rename"), 0,
               "nor is one merely removed")


def test_a_duplicated_check_name_shares_one_row_and_is_reported(tmp_path, expect):
    """Two checks with the same name in one suite share a ledger row, so one going
    red marks BOTH as observed red -- a claim about a check nothing attacked, which
    is exactly what this ledger must not make.

    It cannot be fixed by keying harder without a synthetic id someone would
    maintain, so it is reported. The real corpus carries four today, which is how
    this was noticed: 609 records reduced to 605 rows.
    """
    ledger = _write(tmp_path, "l.tsv", "")
    dupe = ("RESULT\tdemo\tpart1\tthe same name\tPASS\t\n"
            "RESULT\tdemo\tpart1\tthe same name\tFAIL\t\n"
            "RESULT\tdemo\tpart1\ta unique name\tPASS\t\nchecks run: 3\n")
    out, _ = _run("merge", "--ledger", ledger, "--date", "2026-09-10",
                  _write(tmp_path, "d.log", dupe))
    expect.num(out.count("duplicate check name, so one ledger row covers 2: "
                         "demo\tpart1\tthe same name"), 1,
               "a duplicated check name is reported by name")
    expect.num(out.count("a unique name"), 0, "and a unique one is not")
    expect.num(len(_rows(ledger)), 2,
               "the two collapse to one row, which is the loss being reported")


def test_the_gate_refuses_a_check_the_ledger_has_never_seen(tmp_path, expect):
    """A gate that fails on 3,762 unledgered sites is one somebody disables under
    deadline, and then we are back at PGC_SKIP_TIMING with extra steps. So the
    budget grandfathers what exists -- but a NEW check must not enter as silent
    debt either."""
    ledger = _write(tmp_path, "l.tsv", "")
    _run("merge", "--ledger", ledger, _write(tmp_path, "g.log", GREEN))
    budget = _write(tmp_path, "b.txt", "checks_never_observed_red 2\n")
    log = _write(tmp_path, "g2.log", GREEN)
    expect.num(_run("gate", "--ledger", ledger, "--budget", budget, log)[1], 0,
               "a run whose debt is within budget passes")

    over = _write(tmp_path, "b2.txt", "checks_never_observed_red 1\n")
    out, rc = _run("gate", "--ledger", ledger, "--budget", over, log)
    expect.num(rc, 1, "and one over budget does not")
    expect.num(out.count("checks_never_observed_red: 2 exceeds the budget of 1"), 1,
               "and the gate says which number was exceeded, by how much")

    newer = _write(tmp_path, "n.log", GREEN + "RESULT\tdemo\tpart1\tbrand new\tPASS\t\n")
    out, rc = _run("gate", "--ledger", ledger, "--budget", budget, newer)
    expect.num(rc, 1, "a check the ledger has never seen is refused")
    expect.num(out.count("not in the ledger: demo\tpart1\tbrand new"), 1,
               "and it is named, so the author knows which one")


def test_the_committed_ledger_and_budget_agree(expect):
    """Both are tracked files, so a change to either is a diff a reviewer sees. If
    they disagree, one of them was edited by hand -- the failure this whole design
    refuses."""
    ledger = REPO / "test" / "check_ledger.tsv"
    budget = REPO / "test" / "check_ledger_budget.txt"
    expect.text("yes" if ledger.exists() else "no", "yes", "the ledger is in the tree")
    expect.text("yes" if budget.exists() else "no", "yes", "the budget is in the tree")

    rows = [l.split("\t") for l in ledger.read_text().splitlines() if l]
    never = [r for r in rows if r[3] == "never"]
    red = [r for r in rows if r[3] != "never"]
    print(f"  ledger: inputs={len(rows)} | observed red={len(red)}, "
          f"never={len(never)} | sum={len(red) + len(never)}")
    expect.num(len(red) + len(never), len(rows), "the ledger partitions")
    expect.at_least(len(rows), 1, "premise: it is not empty")

    nums = {}
    for line in budget.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit() and not line.startswith("#"):
            nums[parts[0]] = int(parts[1])
    expect.num(nums.get("checks_never_observed_red", -1), len(never),
               "the committed budget matches the committed ledger's debt")

    listed = subprocess.run(["bash", str(RUNNER), "--list-suites"],
                            capture_output=True, text=True).stdout.split()
    covered = {r[0] for r in rows}
    expect.num(nums.get("suites_not_covered", -1), len(set(listed) - covered),
               "and the coverage debt matches the suites with no rows")
