"""The matrix must reconcile the suites it registered against the ones that accounted.

`run_all_versions.sh` prints "suites that ran: N of M" and never checks it, and ten
registered suites exit 0 having never counted a check. Counted among the suites that
"ran", they are the overcount #447 added that line to stop, one level further down.

A count cannot close this. Two errors of opposite sign cancel, and an exempt list
maintained by hand makes the count agree by construction. So membership is derived
from a property each suite carries -- its own text calls `pgc_summary`, and its log
carries the `accounting:` line `pgc_summary` prints before every exit path -- and the
two readings are reconciled as SETS, in both directions.

These tests drive the SHELL functions out of `run_all_versions.sh` rather than
reimplementing them in Python. A Python twin would be a second implementation and
would agree with itself; the house rule asks for two observers of one implementation.
"""

import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "test" / "run_all_versions.sh"


def _extract(name):
    """The text of one shell function, taken from the runner itself."""
    out, keep = [], False
    for line in RUNNER.read_text().splitlines():
        if line.startswith(f"{name}() "):
            keep = True
        if keep:
            out.append(line)
            if line == "}":
                break
    return "\n".join(out)


def _call(name, *args, mutate=None):
    """Run one of the runner's functions and return (stdout, returncode)."""
    body = _extract(name)
    if mutate:
        body = mutate(body)
    # `set -o pipefail` is not decoration: harness_selftest.sh runs under it, and a
    # pipeline inside one of these functions behaves differently with it on. Driving
    # them without it would test a shell the harness never uses.
    script = ("set -uo pipefail\n" + body + "\n"
              + " ".join([name] + [f'"{a}"' for a in args]) + "\n")
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r.stdout, r.returncode


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


# ---- the declaration reader -------------------------------------------------


def test_a_suite_that_calls_pgc_summary_declares_accounting(tmp_path, expect):
    """The property is the CALL. A mention is not one, and neither is a longer name.

    The easy wrong implementation is a bare grep, and it reads a suite that only
    explains why it cannot account as though it does -- a claim satisfied by prose,
    which is the failure this whole approach exists to refuse.
    """
    calls = _write(tmp_path, "calls.sh", '. lib.sh\ncheck "x" a a\npgc_summary\n')
    silent = _write(tmp_path, "silent.sh", ". lib.sh\necho hi\nexit 0\n")
    noted = _write(tmp_path, "noted.sh", ". lib.sh\n# cannot call pgc_summary here\nexit 0\n")
    longer = _write(tmp_path, "longer.sh", ". lib.sh\npgc_summary_of_something\n")

    expect.text(_call("pgc_suite_declares_accounting", calls)[0].strip(), "yes",
                "a suite that calls pgc_summary declares accounting")
    expect.text(_call("pgc_suite_declares_accounting", silent)[0].strip(), "no",
                "one that never calls it does not")
    expect.text(_call("pgc_suite_declares_accounting", noted)[0].strip(), "no",
                "a comment mentioning it is not a declaration")
    expect.text(_call("pgc_suite_declares_accounting", longer)[0].strip(), "no",
                "a longer name containing it is not a declaration")
    expect.text(_call("pgc_suite_declares_accounting", str(tmp_path / "gone.sh"))[0].strip(),
                "no", "an absent file declares nothing rather than erroring")


# ---- the observation reader -------------------------------------------------


def test_the_accounting_line_is_read_on_every_exit_path(tmp_path, expect):
    """`pgc_summary` prints it before pass, failure, skip and incomplete alike.

    That is what makes it the runtime twin of the declaration rather than a synonym
    for PASSED: a suite that failed still reached its summary and still accounted.
    """
    shapes = {
        "pass": "accounting: 3 passed + 0 failed + 0 unrunnable = 3\nx.sh: PASSED\n",
        "fail": "accounting: 1 passed + 2 failed + 0 unrunnable = 3\nx.sh: FAILED\n",
        "skip": "accounting: 0 passed + 0 failed + 0 unrunnable = 0\nx.sh: SKIPPED (ran no checks)\n",
        "inc": "accounting: 2 passed + 0 failed + 1 unrunnable = 3\nx.sh: INCOMPLETE\n",
    }
    for shape, text in shapes.items():
        log = _write(tmp_path, f"{shape}.log", text)
        expect.text(_call("pgc_log_shows_accounting", log)[0].strip(), "yes",
                    f"a {shape} log shows accounting")

    bare = _write(tmp_path, "bare.log", "x.sh: PASSED\n")
    prose = _write(tmp_path, "prose.log", "this suite prints accounting: in prose\n")
    expect.text(_call("pgc_log_shows_accounting", bare)[0].strip(), "no",
                "a PASSED claim without the line shows none")
    expect.text(_call("pgc_log_shows_accounting", prose)[0].strip(), "no",
                "and prose containing the word is not the line")
    expect.text(_call("pgc_log_shows_accounting", str(tmp_path / "gone.log"))[0].strip(),
                "no", "an absent log shows none rather than erroring")


# ---- the reconciliation -----------------------------------------------------


def test_the_reconciliation_names_both_directions(tmp_path, expect):
    """Declared-but-not-accounted and accounted-but-not-declared are opposite faults.

    The first is a suite that died before reaching its summary -- today that reads
    PASS whenever the shell happened to exit 0. The second is a stale reading of the
    source, which is the failure a hand-maintained exempt list can never report.
    """
    d = _write(tmp_path, "d", "alpha\nbeta\ngamma\n")
    o = _write(tmp_path, "o", "alpha\nbeta\ngamma\n")
    expect.num(_call("pgc_reconcile_accounting", d, o)[1], 0, "equal sets reconcile")

    o = _write(tmp_path, "o", "alpha\nbeta\n")
    out, rc = _call("pgc_reconcile_accounting", d, o)
    expect.num(rc, 1, "a declared suite that never accounted is caught")
    expect.num(out.count("declared but never accounted: gamma"), 1, "and is named")

    d = _write(tmp_path, "d", "alpha\nbeta\n")
    o = _write(tmp_path, "o", "alpha\nbeta\ngamma\n")
    out, rc = _call("pgc_reconcile_accounting", d, o)
    expect.num(rc, 1, "an undeclared suite that DID account is caught")
    expect.num(out.count("accounted but never declared: gamma"), 1,
               "and is named as the opposite fault")


def test_opposite_errors_do_not_cancel(tmp_path, expect):
    """One error masking the other is exactly what a count cannot distinguish."""
    d = _write(tmp_path, "d", "alpha\ndelta\n")
    o = _write(tmp_path, "o", "alpha\ngamma\n")
    out, rc = _call("pgc_reconcile_accounting", d, o)
    expect.num(rc, 1, "a run wrong in both directions fails")
    expect.num(out.count("declared but never accounted: delta")
               + out.count("accounted but never declared: gamma"), 2,
               "and both directions are reported, not one")


def test_the_driver_s_own_non_dispatch_record_excuses_only_what_it_names(tmp_path, expect):
    """PGC_SKIP_TIMING drops four suites on every CI run.

    They declare accounting and correctly produce none, because nothing ran them.
    Without a term for that the check goes red for the one reason that is not a
    defect. The term is recorded by the branch that makes the decision rather than
    inferred from the log that branch forges.
    """
    d = _write(tmp_path, "d", "alpha\nbeta\ngamma\n")
    o = _write(tmp_path, "o", "alpha\nbeta\n")
    nd = _write(tmp_path, "nd", "gamma\n")
    expect.num(_call("pgc_reconcile_accounting", d, o, nd)[1], 0,
               "a suite the driver never dispatched reconciles")
    expect.num(_call("pgc_reconcile_accounting", d, o)[1], 1,
               "and without that record the same run is still caught")

    # A suite cannot both have reached its summary and not have been dispatched.
    d = _write(tmp_path, "d", "alpha\nbeta\n")
    o = _write(tmp_path, "o", "alpha\nbeta\n")
    nd = _write(tmp_path, "nd", "beta\n")
    out, rc = _call("pgc_reconcile_accounting", d, o, nd)
    expect.num(rc, 1, "a suite both accounted and recorded as never dispatched fails")
    expect.num(out.count("both accounted and recorded as never dispatched: beta"), 1,
               "and is named as that fault rather than one of the other two")

    d = _write(tmp_path, "d", "alpha\n")
    o = _write(tmp_path, "o", "alpha\n")
    nd = _write(tmp_path, "nd", "zeta\n")
    out, _ = _call("pgc_reconcile_accounting", d, o, nd)
    expect.num(out.count("accounted but never declared: zeta"), 1,
               "the record cannot introduce a suite the source never declared")


def test_the_printed_identity_can_actually_fail(tmp_path, expect):
    """inputs == sum(buckets) is printed beside every reconciliation. Can it be false?

    Measured rather than argued. Computing inputs FROM the buckets makes the line
    P + D + O == P + D + O and nothing reddens -- which is why inputs is counted from
    the two files by a separate route. Dropping the sort before comm makes the buckets
    garbage and the totals diverge, and that is the fault this identity guards:
    selftest 070's subject arriving in a second place.
    """
    unsorted = lambda b: (b
                          .replace('LC_ALL=C sort -u "$_decl" 2>/dev/null',
                                   'cat "$_decl" 2>/dev/null')
                          .replace('LC_ALL=C sort -u "$_obs"  2>/dev/null',
                                   'cat "$_obs" 2>/dev/null'))

    body = _extract("pgc_reconcile_accounting")
    expect.num(body.count('LC_ALL=C sort -u "$_decl"'), 1,
               "premise: the real function sorts its declared side")
    expect.num(unsorted(body).count('LC_ALL=C sort -u "$_decl"'), 0,
               "premise: the mutation applied -- the twin no longer does")

    d = _write(tmp_path, "d", "gamma\nbeta\nalpha\n")
    o = _write(tmp_path, "o", "delta\ngamma\nbeta\n")
    out_twin, _ = _call("pgc_reconcile_accounting", d, o, mutate=unsorted)
    out_real, _ = _call("pgc_reconcile_accounting", d, o)
    expect.num(out_twin.count("does not add up"), 1,
               "the identity catches comm reading unsorted input")
    expect.num(out_real.count("does not add up"), 0,
               "and does not fire on the same input unmutated, so the arm is not noise")


# ---- the readers, over the real population ----------------------------------


def test_the_partition_over_the_registered_suites_adds_up(expect):
    """A reader that works on fixtures and not on the 251 registered suites has been
    tested against the world it was written for.

    No count is asserted. How many suites are exempt is not a fact about correctness,
    and pinning it here would be a second copy of the hand-maintained list this design
    exists to remove. What is asserted is that the partition covers the population and
    that both buckets are occupied -- a reader answering the same way for everything
    would satisfy every fixture above.
    """
    listed = subprocess.run(["bash", str(RUNNER), "--list-suites"],
                            capture_output=True, text=True).stdout.split()
    expect.at_least(len(listed), 1, "premise: the runner listed its suites")

    body = _extract("pgc_suite_declares_accounting")
    script = body + '\nfor f in "$@"; do pgc_suite_declares_accounting "$f"; done\n'
    paths = [str(REPO / "test" / f"{s}.sh") for s in listed]
    verdicts = subprocess.run(["bash", "-c", script, "_"] + paths,
                              capture_output=True, text=True).stdout.split()

    yes, no = verdicts.count("yes"), verdicts.count("no")
    print(f"  registered={len(listed)} | declares={yes}, does not={no} | sum={yes + no}")
    expect.num(yes + no, len(listed), "the partition covers every registered suite")
    expect.at_least(no, 1, "the reader does not answer yes for every suite")
    expect.at_least(yes, 1, "nor no for every one of them")


def test_the_declaration_reader_survives_pipefail_on_a_long_suite(tmp_path, expect):
    """A regression arm for a bug this file's first implementation shipped.

    It piped `sed` into `grep -q`. grep -q exits the moment it matches, closing the
    pipe while sed is still writing; sed takes EPIPE, and under `set -o pipefail` the
    pipeline reports that failure even though grep matched. The reader then answered
    "no" for a suite that plainly calls pgc_summary.

    It is a race, so it reproduces on long files and not short ones -- which is why it
    passed every fixture above and failed only on the real population, naming the two
    longest suites. Selftest 040 carries the same story from #473 and #476.
    """
    big = tmp_path / "big.sh"
    big.write_text(". lib.sh\npgc_summary\n" + "".join(f"echo padding {i}\n" for i in range(40000)))
    expect.at_least(len(big.read_text().splitlines()), 10000,
                    "premise: the fixture is long enough to lose the race")

    expect.text(_call("pgc_suite_declares_accounting", str(big))[0].strip(), "yes",
                "a long suite that calls pgc_summary still declares accounting")

    # The arm can fail: the grep -q shape is the one that gets this wrong. Restated
    # here rather than extracted, because the wrong version is no longer in the tree.
    twin = ("set -uo pipefail\n"
            "sed 's/#.*$//' \"$1\" | grep -qE '(^|[^_[:alnum:]])pgc_summary([^_[:alnum:]]|$)'"
            " && echo yes || echo no\n")
    got = subprocess.run(["bash", "-c", twin, "_", str(big)],
                         capture_output=True, text=True).stdout.strip()
    expect.text(got, "no", "the grep -q shape is the one that gets this wrong under pipefail")

    short = tmp_path / "short.sh"
    short.write_text(". lib.sh\npgc_summary\n")
    got_short = subprocess.run(["bash", "-c", twin, "_", str(short)],
                               capture_output=True, text=True).stdout.strip()
    expect.text(got_short, "yes",
                "and it agrees on a SHORT file, which is why it survived review")
