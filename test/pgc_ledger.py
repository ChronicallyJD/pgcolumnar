#!/usr/bin/env python3
"""The mutation ledger: which checks have ever been seen red, and under what.

Nothing recorded whether a check had ever been red. That is the gap that let 39
checks across 35 suites ship unable to fail, three of them inside the suite whose
whole purpose is to stop exactly that. The gate answered "did anything print FAIL"
and had never answered "could anything print FAIL".

WHAT THIS LEDGER CLAIMS, AND WHAT IT DOES NOT
---------------------------------------------
It records that a named check WAS OBSERVED RED in a recorded run. It does NOT
claim the check is proven able to fail: that is a stronger statement, it needs a
named mutation applied deliberately, and conflating the two would put a claim in
the ledger that nothing measured -- the `defeated: 0` shape from VACUITY_MODES
section 1, a number that reads as evidence and is not.

So v1 fills the observed column honestly and leaves the rest as debt, counted. A
ledger whose entries all read `never` is a measurement of how much of the suite
has never been attacked, and that measurement is worth having on day one.

WHAT FILLS IT
-------------
Not only deliberate mutation runs. Every real CI red fills it, every flake, every
bisect -- and those arrive whether anyone remembers or not. A mutation run is the
deliberate accelerator, not the only source.

THE MUTATION COLUMN
-------------------
Present from v1 with nothing filling it automatically, because adding a column
later means rewriting every entry. If an entry can record WHICH mutation reddened
a check, the catalogue a mutation gate would need builds itself out of work people
already do by hand.

FORMAT
------
Tab separated, one row per check, sorted:

    suite <TAB> part <TAB> check name <TAB> last observed red <TAB> mutation

`last observed red` is a date, or the literal `never`. `mutation` is free text or
empty. Both are written by this tool, never by hand.

The row is keyed on (suite, part, name). The part matters because harness_selftest
sources 40-odd parts into one shell and phrases its premises to be COPIED, so a
name-only key is a key of check NAMES rather than of checks.
"""

import argparse
import pathlib
import sys

NEVER = "never"


def read_records(paths):
    """(suite, name, verdict) for every RESULT line in the given logs."""
    out = []
    for p in paths:
        try:
            text = pathlib.Path(p).read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if not line.startswith("RESULT\t"):
                continue
            f = line.split("\t")
            if len(f) < 5:
                continue
            # suite, part, name, verdict
            out.append((f[1], f[2], f[3], f[4]))
    return out


def read_ledger(path):
    """{(suite, part, name): [last_red, mutation]} from a ledger file.

    KEYED ON THE PART AS WELL AS THE NAME. harness_selftest sources 40-odd parts
    into one shell and phrases its premises to be copied -- "premise: the pytest
    layer is where THIS PART thinks it is" works verbatim in any of them -- so
    (suite, name) is a key of check NAMES rather than of checks, and one sharer
    going red would mark them all. Measured over a real run: 583 records give 579
    distinct (suite, name) and 582 distinct (suite, part, name).
    """
    rows = {}
    p = pathlib.Path(path)
    if not p.exists():
        return rows
    for line in p.read_text(errors="replace").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        while len(f) < 5:
            f.append("")
        rows[(f[0], f[1], f[2])] = [f[3] or NEVER, f[4]]
    return rows


def write_ledger(path, rows):
    lines = [
        "\t".join((suite, part, name, v[0], v[1]))
        for (suite, part, name), v in sorted(rows.items())
    ]
    pathlib.Path(path).write_text("\n".join(lines) + ("\n" if lines else ""))


def cmd_census(args):
    for suite, part, name, verdict in read_records(args.logs):
        print(f"{suite}\t{part}\t{name}\t{verdict}")
    return 0


def cmd_merge(args):
    rows = read_ledger(args.ledger)
    for suite, part, name, verdict in read_records(args.logs):
        key = (suite, part, name)
        if key not in rows:
            # A check this ledger has never seen enters as DEBT. A green run has
            # observed nothing go red, so merging one must never record a red
            # observation -- otherwise an ordinary CI run retires the debt it
            # exists to count.
            rows[key] = [NEVER, ""]
        if verdict == "FAIL":
            rows[key][0] = args.date
            if args.mutation:
                rows[key][1] = args.mutation
    write_ledger(args.ledger, rows)

    # A DUPLICATED NAME SHARES ONE LEDGER ROW, so one of the two going red marks
    # BOTH as observed red -- a claim about a check nothing attacked, which is
    # precisely what this ledger must not make. It cannot be fixed by keying
    # harder without a synthetic id someone would maintain, so it is reported.
    # A duplicate WITHIN one part still shares a row -- the part fixed the
    # convention collisions, not genuine repeats. One survives in the real
    # corpus, and naming it precisely is the point of keying on the part.
    records = read_records(args.logs)
    counts = {}
    for suite, part, name, _ in records:
        counts[(suite, part, name)] = counts.get((suite, part, name), 0) + 1
    for suite, part, name in sorted(k for k, c in counts.items() if c > 1):
        print(f"    duplicate check name, so one ledger row covers "
              f"{counts[(suite, part, name)]}: {suite}\t{part}\t{name}")

    seen = len({(s, p_, n) for s, p_, n, _ in records})
    red = sum(1 for v in rows.values() if v[0] != NEVER)
    print(f"  ledger: rows={len(rows)} | seen this run={seen}, "
          f"observed red ever={red}, never={len(rows) - red}")
    return 0


def cmd_rename_scan(args):
    """A name that appeared while another disappeared is probably a rename.

    Keyed by the display string, a rename loses the check's history and reads
    exactly like a brand-new check that has never been red -- the one state this
    ledger exists to distinguish. It cannot be prevented without a synthetic id
    that someone would have to maintain, so it is DETECTED and named instead of
    silently resetting a count to `never`.

    Both directions are required. A check merely added, or merely removed, is not
    a rename, and reporting one on every new check is noise that gets the whole
    thing ignored.
    """
    rows = read_ledger(args.ledger)
    now = {(s, p_, n) for s, p_, n, _ in read_records(args.logs)}
    parts = {(s, p_) for s, p_, _ in now}
    known = {k for k in rows if (k[0], k[1]) in parts}

    appeared = sorted(now - known)
    vanished = sorted(known - now)
    rc = 0
    if appeared and vanished:
        # Only pair within a PART. Keying on the part also fixes a blind spot the
        # name-only key had: a premise moving between parts was indistinguishable
        # from a rename, and now it is a disappearance and an appearance in two
        # different parts, which this does not pair.
        for (s_a, p_a, n_a), (s_v, p_v, n_v) in zip(appeared, vanished):
            if (s_a, p_a) != (s_v, p_v):
                continue
            was = rows.get((s_v, p_v, n_v), [NEVER, ""])[0]
            print(f"    possible rename: {n_v} -> {n_a} "
                  f"(in {s_a}/{p_a}, history: last red {was})")
            rc = 1
    print(f"  rename scan: appeared={len(appeared)}, vanished={len(vanished)}")
    return rc


def _read_budget(path):
    out = {}
    p = pathlib.Path(path)
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            out[parts[0]] = int(parts[1])
    return out


def cmd_gate(args):
    rows = read_ledger(args.ledger)
    budget = _read_budget(args.budget)
    seen = {(s, p_, n) for s, p_, n, _ in read_records(args.logs)}

    # A check the ledger has never heard of is NEW. The allowlist exists so a
    # gate that fails on 3,762 unledgered sites is not what lands -- but a new
    # one must not enter as silent debt either.
    unknown = sorted(seen - set(rows))
    rc = 0
    for suite, part, name in unknown:
        print(f"    not in the ledger: {suite}\t{part}\t{name}")
        rc = 1

    never = sum(1 for v in rows.values() if v[0] == NEVER)
    want = budget.get("checks_never_observed_red")
    print(f"  ledger gate: rows={len(rows)} | never observed red={never}, "
          f"budget={want if want is not None else 'unset'}, new={len(unknown)}")
    if want is None:
        print("    the budget file names no checks_never_observed_red, so nothing bounds the debt")
        return 1
    if never > want:
        print(f"    checks_never_observed_red: {never} exceeds the budget of {want}")
        rc = 1

    # The SECOND debt, and the one that is easy to forget: a suite with no rows
    # in the ledger is not covered at all, and its checks are invisible to
    # everything above -- the gate cannot refuse a new check in a suite it has
    # never seen. Counting it separately keeps "we ledger 605 checks" from
    # reading as "we ledger the corpus".
    if args.registered:
        registered = {l.strip() for l in pathlib.Path(args.registered).read_text().split()
                      if l.strip()}
        covered = {k[0] for k in rows}
        uncovered = sorted(registered - covered)
        want_s = budget.get("suites_not_covered")
        print(f"  ledger coverage: registered={len(registered)} | "
              f"covered={len(registered) - len(uncovered)}, not covered={len(uncovered)}, "
              f"budget={want_s if want_s is not None else 'unset'}")
        if want_s is None:
            print("    the budget file names no suites_not_covered, so nothing bounds the coverage")
            return 1
        if len(uncovered) > want_s:
            print(f"    suites_not_covered: {len(uncovered)} exceeds the budget of {want_s}")
            rc = 1
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("census", help="print suite/name/verdict for each RESULT line")
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

    g = sub.add_parser("gate", help="refuse new checks and debt over budget")
    g.add_argument("--ledger", required=True)
    g.add_argument("--budget", required=True)
    g.add_argument("--registered", default="",
                   help="file listing every registered suite, for the coverage debt")
    g.add_argument("logs", nargs="+")
    g.set_defaults(fn=cmd_gate)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
