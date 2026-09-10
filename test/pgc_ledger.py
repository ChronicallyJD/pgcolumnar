#!/usr/bin/env python3
"""The mutation ledger: which checks have ever been seen red, and under what.

Nothing recorded whether a check had ever been red. That is the gap that let 39
checks across 35 suites ship unable to fail, three of them inside the suite whose
whole purpose is to stop exactly that. The gate answered "did anything print FAIL"
and had never answered "could anything print FAIL".

WHAT THIS RECORDS, AND WHAT IT DOES NOT
---------------------------------------
It records that a named check WAS OBSERVED RED in a recorded run. It does NOT
claim the check is proven able to fail: that needs a named mutation applied
deliberately, and conflating the two would put a claim in the ledger that nothing
measured -- the `defeated: 0` shape from VACUITY_MODES section 1.

THE TWO NUMBERS ARE DIFFERENT KINDS OF THING, and the first design got this wrong
in a way that deadlocked.
-------------------------------------------------------------------------------
`checks_never_observed_red` is a CENSUS. It cannot be a ceiling: every new check
enters the ledger as `never`, so bounding it means every added check breaks the
gate, and the only way to land one is to raise a number the design says may only
fall. That is a deadlock, not a budget. It is reported, and it falls as checks are
attacked.

`suites_not_covered` IS a ceiling, and a monotone one, because adding a check to a
covered suite does not move it. It falls as suites are seeded, and it may only
fall: the gate compares the working value against the previously committed one and
refuses an increase, so widening the debt is an edit a reviewer sees AND a gate
refuses, rather than either alone.

WHAT THE GATE REFUSES
---------------------
A check the committed ledger has never seen. That is the allowlist the issue asks
for -- existing checks are grandfathered, a new one is named and refused until the
ledger is regenerated, which is a reviewable one-line diff and the INTENDED action
rather than a forbidden one.

WHAT FEEDS IT
-------------
`run_all_versions.sh` merges every suite's log before it removes the build
directory, so every matrix run feeds a ledger -- locally and in CI. The committed
ledger is updated deliberately, by running `merge` against a real run and
committing the diff. CI verifies; humans commit. A ledger that CI rewrote by
itself would be a file nobody reads changing under everybody.

It is not only mutation runs. Every real CI red fills it, every flake, every
bisect. A mutation run is the deliberate accelerator.

FAIL CLOSED
-----------
An unreadable file, an empty one, or a record with too few fields is an ERROR.
Silently skipping them made every integrity failure indistinguishable from a clean
run: a gate over a nonexistent log returned success.

FORMAT
------
Tab separated, five columns, keyed on the first three:

    suite <TAB> part <TAB> check name <TAB> last observed red <TAB> mutations

`last observed red` is a date or `never`. `mutations` is `-`, or a `;`-separated
SET of the mutations that have reddened this check -- accumulated, not overwritten,
because a column that keeps only the last one records the most recent attack
rather than the catalogue it exists to become.
"""

import argparse
import os
import pathlib
import subprocess
import sys

NEVER = "never"
NONE = "-"
FIELDS = 5


class LedgerError(Exception):
    """An integrity failure. Never silently skipped."""


def read_records(paths, *, require_nonempty=True):
    """[(suite, part, name, verdict)] for every RESULT line in the given logs.

    Fails closed. A path that cannot be read, a log with no records, or a record
    with too few fields is an error -- silently skipping them is how a gate over a
    nonexistent log returned success.
    """
    out = []
    for p in paths:
        path = pathlib.Path(p)
        try:
            text = path.read_text(errors="replace")
        except OSError as e:
            raise LedgerError(f"cannot read {p}: {e}") from e
        found = 0
        for n, line in enumerate(text.splitlines(), 1):
            if not line.startswith("RESULT\t"):
                continue
            f = line.split("\t")
            if len(f) < 5:
                raise LedgerError(
                    f"{p}:{n}: a record needs suite, part, name and verdict; got {len(f) - 1} field(s)")
            out.append((f[1], f[2], f[3], f[4]))
            found += 1
        if require_nonempty and found == 0:
            raise LedgerError(f"{p}: no RESULT records, so there is nothing to reconcile")
    return out


def read_ledger(path):
    """{(suite, part, name): [last_red, {mutations}]}.

    Keyed on the part as well as the name: harness_selftest sources 40-odd parts
    into one shell and phrases its premises to be COPIED, so a name-only key is a
    key of check NAMES rather than of checks.
    """
    rows = {}
    p = pathlib.Path(path)
    if not p.exists():
        return rows
    for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) != FIELDS:
            raise LedgerError(f"{path}:{n}: a ledger row needs {FIELDS} fields, got {len(f)}")
        muts = set() if f[4] == NONE else {m for m in f[4].split(";") if m}
        rows[(f[0], f[1], f[2])] = [f[3] or NEVER, muts]
    return rows


def write_ledger(path, rows):
    lines = []
    for (suite, part, name), (red, muts) in sorted(rows.items()):
        # No trailing tab. An empty last field is trailing whitespace on every
        # row, which `git diff --check` reports and which made 614 of them.
        lines.append("\t".join((suite, part, name, red,
                                ";".join(sorted(muts)) if muts else NONE)))
    pathlib.Path(path).write_text("\n".join(lines) + ("\n" if lines else ""))


def _by_run(paths):
    """[(path, {(suite, part, name): [verdicts]})] -- one entry per LOG.

    Per log, because the same check appearing in two logs is two RUNS of it, while
    twice in one log is a duplicate name sharing a ledger row. Merging the logs
    first cannot tell those apart, and reported the first as the second.
    """
    runs = []
    for p in paths:
        seen = {}
        for suite, part, name, verdict in read_records([p]):
            seen.setdefault((suite, part, name), []).append(verdict)
        runs.append((p, seen))
    return runs


def cmd_census(args):
    for suite, part, name, verdict in read_records(args.logs):
        print(f"{suite}\t{part}\t{name}\t{verdict}")
    return 0


def cmd_merge(args):
    rows = read_ledger(args.ledger)
    runs = _by_run(args.logs)

    if args.mutation and len(runs) > 1:
        raise LedgerError(
            "--mutation names one deliberate change, so it cannot be attributed across "
            f"{len(runs)} logs at once: merge them one run at a time")

    for path, seen in runs:
        for key, verdicts in sorted(seen.items()):
            if key not in rows:
                # A check this ledger has never seen enters as DEBT. A green run
                # has observed nothing go red, so merging one must never record a
                # red observation.
                rows[key] = [NEVER, set()]
            if "FAIL" in verdicts:
                rows[key][0] = args.date
                if args.mutation:
                    # A SET. Keeping only the last one records the most recent
                    # attack rather than the catalogue this column exists to
                    # become.
                    rows[key][1].add(args.mutation)
        for key, verdicts in sorted(seen.items()):
            if len(verdicts) > 1:
                print(f"    duplicate check name in one run, so one ledger row covers "
                      f"{len(verdicts)}: {key[0]}\t{key[1]}\t{key[2]}")

    write_ledger(args.ledger, rows)
    seen_all = {k for _, s in runs for k in s}
    red = sum(1 for v in rows.values() if v[0] != NEVER)
    print(f"  ledger: rows={len(rows)} | runs={len(runs)}, distinct checks this merge={len(seen_all)}, "
          f"observed red ever={red}, never={len(rows) - red}")
    return 0


def cmd_rename_scan(args):
    """A name that appeared while another disappeared, WITHIN ONE PART, is a rename.

    Keyed by the display string, a rename loses history and reads exactly like a
    brand-new check that has never been red -- the one state this ledger exists to
    distinguish. Detected and named rather than silently reset.

    Grouped by (suite, part) before pairing. A global positional zip misses a real
    rename whenever unrelated movement in another part shifts the ordering.

    Scanned against ONE run. Given a before-log and an after-log together, the
    vanished name is present in the union and nothing appears to have gone.
    """
    runs = _by_run(args.logs)
    if len(runs) > 1:
        raise LedgerError(
            f"rename-scan compares ONE run against the ledger, but got {len(runs)} logs: "
            "the union of a before-log and an after-log hides the disappearance")
    rows = read_ledger(args.ledger)
    now = set(runs[0][1])

    parts = {(s, p) for s, p, _ in now}
    known = {k for k in rows if (k[0], k[1]) in parts}

    rc = 0
    n_app = n_van = 0
    for part in sorted(parts):
        app = sorted(k[2] for k in now - known if (k[0], k[1]) == part)
        van = sorted(k[2] for k in known - now if (k[0], k[1]) == part)
        n_app += len(app)
        n_van += len(van)
        for new, old in zip(app, van):
            was = rows.get((part[0], part[1], old), [NEVER, set()])[0]
            print(f"    possible rename: {old} -> {new} "
                  f"(in {part[0]}/{part[1]}, history: last red {was})")
            rc = 1
    print(f"  rename scan: appeared={n_app}, vanished={n_van}")
    return rc


def read_budget(path):
    out = {}
    text = pathlib.Path(path).read_text()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            out[parts[0]] = int(parts[1])
    return out


def _resolve_against(path, spec):
    """Which ref carries the prior ceiling. Fails closed rather than guessing.

    NOT a hardcoded remote name. `origin` is per-clone: in a contributor's setup it
    is their fork, and OffgridwithJD measured theirs 446 commits behind upstream.
    Comparing against a stale main makes this check WEAKER, never falsely red --
    the ceiling may only fall, so an older main carries a higher one, and a raise
    passes whenever the stale prior is high enough. It fails open while printing a
    line that reads like the enforcement happened, which is the same shape as the
    absolute-path bug one level down: compared against the wrong thing, rather than
    could not compare.

    So:

      GITHUB_BASE_REF   in CI this names the PR's target branch, which IS the prior
                        by definition. Its remote-tracking ref must exist -- if the
                        checkout did not fetch it, that is an error, not a fallback.
      main@{upstream}   outside CI, ask git rather than a convention. The configured
                        upstream of the local main is the answer to "which main is
                        mine", per clone.

    Anything else is an error. A gate that quietly enforces less than it claims is
    the thing this whole change exists to refuse, and a fallback that says so is
    still a gate enforcing less.
    """
    if spec != "auto":
        return spec
    repo = pathlib.Path(path).resolve().parent

    def _rev(ref):
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", ref],
                           capture_output=True, text=True)
        return ref if r.returncode == 0 else None

    base = os.environ.get("GITHUB_BASE_REF", "").strip()
    if base:
        for cand in (f"refs/remotes/origin/{base}", base):
            if _rev(cand):
                return cand
        raise LedgerError(
            f"GITHUB_BASE_REF is {base!r} but no ref for it resolves here, so the prior "
            "ceiling cannot be read. The checkout needs to fetch the base branch")

    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "main@{upstream}"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    raise LedgerError(
        "no trustworthy prior ceiling: GITHUB_BASE_REF is unset and the local main has no "
        "configured upstream. Naming a remote would compare against whatever `origin` "
        "happens to be in this clone, which is how a fork 446 commits stale gets treated "
        "as the prior")


def _behind(path, ref):
    """" (N commits behind HEAD)" when the prior lags, "" when it does not.

    A reader can see WHICH ref was compared against. Without this they cannot see
    that it is 446 commits stale, which is the difference between knowing the
    comparison happened and knowing what it was worth.
    """
    repo = pathlib.Path(path).resolve().parent
    r = subprocess.run(["git", "-C", str(repo), "rev-list", "--count", f"{ref}..HEAD"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip().isdigit():
        return " (distance from HEAD unknown)"
    n = int(r.stdout.strip())
    return "" if n == 0 else f" ({n} commit{'s' if n != 1 else ''} behind HEAD)"


def _committed_budget(path, ref):
    """The budget as of `ref`. Raises rather than returning None.

    `git show REF:PATH` needs a REPO-RELATIVE path. The production caller passes an
    absolute one inside a copied build directory, so the first version returned
    None and printed "no prior ceiling to compare" -- a message that reads like a
    pass while the ceiling it was asked to enforce went unchecked. That is the
    fail-open shape this whole change is about, in the code that closes it.
    Reported by OffgridwithJD.

    So the path is resolved here rather than demanded of the caller, and every
    failure to resolve it is an ERROR. Asked to compare, unable to compare, is not
    the same as nothing to compare.
    """
    abspath = pathlib.Path(path).resolve()
    try:
        top = subprocess.run(["git", "-C", str(abspath.parent), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError) as e:
        raise LedgerError(
            f"--against {ref} was given, but {path} is not inside a git repository, "
            "so the prior ceiling cannot be read") from e
    try:
        rel = abspath.relative_to(pathlib.Path(top).resolve())
    except ValueError as e:
        raise LedgerError(f"{path} resolves outside its own repository at {top}") from e
    try:
        blob = subprocess.run(["git", "-C", top, "show", f"{ref}:{rel.as_posix()}"],
                              capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError) as e:
        raise LedgerError(
            f"--against {ref} was given, but {rel.as_posix()} does not exist at {ref}, "
            "so there is no prior ceiling to compare against") from e
    out = {}
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if len(f) == 2 and f[1].isdigit():
            out[f[0]] = int(f[1])
    if "suites_not_covered" not in out:
        raise LedgerError(f"the budget at {ref} names no suites_not_covered")
    return out


def cmd_gate(args):
    rows = read_ledger(args.ledger)
    budget = read_budget(args.budget)
    seen = {k for k, _, _ in ((k, None, None) for k in
                              {(s, p, n) for s, p, n, _ in read_records(args.logs)})}

    rc = 0

    # THE REFUSAL: a check the committed ledger has never seen, IN A SUITE THE
    # LEDGER COVERS.
    #
    # The suite restriction is not a softening, it is the meaning of
    # suites_not_covered: the gate cannot refuse a new check in a suite it has
    # never seen, because it has no idea which of that suite's checks are new.
    # Without it the gate refuses every check of all 250 uncovered suites and
    # reddens the whole matrix on the first run -- which is a gate somebody turns
    # off, the failure mode this issue family exists to prevent.
    #
    # It tightens on its own as suites are seeded, and the ceiling is what forces
    # that direction.
    covered_suites = {k[0] for k in rows}
    unknown = sorted(k for k in seen - set(rows) if k[0] in covered_suites)
    for suite, part, name in unknown:
        print(f"    not in the ledger: {suite}\t{part}\t{name}")
    if unknown:
        print(f"    {len(unknown)} check(s) the ledger has never seen. Regenerate it with:")
        print(f"      python3 test/pgc_ledger.py merge --ledger {args.ledger} --date <today> <log>")
        rc = 1

    # A CENSUS, not a ceiling. Bounding it deadlocks: every new check enters as
    # `never`, so the only way to land one would be to raise a number the design
    # says may only fall.
    never = sum(1 for v in rows.values() if v[0] == NEVER)
    print(f"  ledger census: rows={len(rows)} | never observed red={never}, "
          f"ever red={len(rows) - never}, new this run={len(unknown)}")

    if not args.registered:
        raise LedgerError(
            "--registered is required: without the registered suite list the coverage "
            "claim cannot be made, and skipping it silently is how a gate reports success "
            "for a question it never asked")
    registered = {w for w in pathlib.Path(args.registered).read_text().split() if w}
    if not registered:
        raise LedgerError(f"{args.registered}: no registered suites listed")
    uncovered = sorted(registered - {k[0] for k in rows})
    want = budget.get("suites_not_covered")
    print(f"  ledger coverage: registered={len(registered)} | covered={len(registered) - len(uncovered)}, "
          f"not covered={len(uncovered)}, ceiling={want if want is not None else 'unset'}")
    if want is None:
        print("    the budget names no suites_not_covered, so nothing bounds the coverage debt")
        return 1
    if len(uncovered) > want:
        print(f"    suites_not_covered: {len(uncovered)} exceeds the ceiling of {want}")
        rc = 1

    # MONOTONE, mechanically. The tracked file says the ceiling may only fall;
    # without this that sentence is prose and raising the number passes.
    if args.against:
        ref = _resolve_against(args.budget, args.against)
        # HOW FAR BEHIND THE PRIOR IS, printed beside it.
        #
        # `main@{upstream}` is the per-clone answer to "which main is mine", and
        # in a contributor's setup it resolves to their FORK -- OffgridwithJD's is
        # 446 commits behind upstream. Naming the ref told a reader WHICH prior
        # was used; it did not tell them what the comparison was worth. The
        # direction still fails open: an older main carries a higher ceiling, so a
        # raise passes whenever the stale prior is high enough.
        #
        # There is no better ref to pick that does not guess, so the weakness is
        # made visible instead. It costs nothing when the number is 0.
        shown = f"{ref}{_behind(args.budget, ref)}"
        p_want = _committed_budget(args.budget, ref)["suites_not_covered"]
        if want > p_want:
            print(f"    suites_not_covered was raised from {p_want} to {want} "
                  f"(against {shown}): the ceiling may only fall")
            rc = 1
        else:
            print(f"    ceiling against {shown}: {p_want} -> {want}, which does not rise")
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("census", help="print suite/part/name/verdict for each record")
    c.add_argument("logs", nargs="+")
    c.set_defaults(fn=cmd_census)

    m = sub.add_parser("merge", help="merge a run's records into the ledger")
    m.add_argument("--ledger", required=True)
    m.add_argument("--date", default="unknown")
    m.add_argument("--mutation", default="")
    m.add_argument("logs", nargs="+")
    m.set_defaults(fn=cmd_merge)

    r = sub.add_parser("rename-scan", help="report names that look renamed")
    r.add_argument("--ledger", required=True)
    r.add_argument("logs", nargs="+")
    r.set_defaults(fn=cmd_rename_scan)

    g = sub.add_parser("gate", help="refuse a check the ledger has never seen")
    g.add_argument("--ledger", required=True)
    g.add_argument("--budget", required=True)
    g.add_argument("--registered", default="",
                   help="file listing every registered suite (required)")
    g.add_argument("--against", default="",
                   help="'auto' to resolve the prior from GITHUB_BASE_REF or main@{upstream}, "
                        "or an explicit git ref. Fails closed when no trustworthy prior exists")
    g.add_argument("logs", nargs="+")
    g.set_defaults(fn=cmd_gate)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except LedgerError as e:
        print(f"    ledger integrity failure: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
