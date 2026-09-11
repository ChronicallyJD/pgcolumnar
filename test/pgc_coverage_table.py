#!/usr/bin/env python3
"""Print an lcov tracefile's per-file coverage, least covered first.

WHY NOT `lcov --list`. Because it gave wrong answers on the nightly runner and
right ones here, from the same tracefile, on two builds of the same lcov 2.0 --
`2.0-4ubuntu2` against `2.0-1`. The nightly's table printed
`columnar_parquet_codec.c | 2.0% 100|3200% 2| - 0` for a file whose records say
`LF:100 LH:100 FNF:2 FNH:2 BRF:64 BRH:47`: a file at 100% presented as 2.0% and
sorted to the top of a list headed "least covered first". Four of the files it
named as least covered were between 94% and 100%.

A rate is a division of two integers the tracefile states outright, so computing it
here removes the one moving part -- whichever distro patch changes `--list` cannot
change `LF:`. `lcov --summary` stays where it is: it was correct on both builds.

THE FORMAT SHOWS hit/total, not just the total. `93.7% 22765` cannot be checked by
a reader; `93.7% 21320/22765` can, and a reader who can check the number is the
only one who will notice when it is wrong again.

An absent counter prints `-`, which is what a file with no branches has: not 0.0%,
which would sort it to the top as if it were the worst covered thing in the tree.
"""

import argparse
import pathlib
import sys

# The six counters this reads, and nothing else. `DA`/`BRDA`/`FN`/`FNDA` are the
# per-line detail the totals are computed from; re-deriving the totals from them
# would be a second implementation that can disagree with the first.
_PAIRS = (("lines", "LF", "LH"), ("functions", "FNF", "FNH"), ("branches", "BRF", "BRH"))


def read_tracefile(path):
    """-> [{name, lines:(hit,found), functions:(...), branches:(...)}], in file order."""
    records, cur = [], None
    for raw in pathlib.Path(path).read_text(errors="replace").splitlines():
        if raw.startswith("SF:"):
            cur = {"name": raw[3:], "counters": {}}
        elif cur is None:
            continue
        elif raw == "end_of_record":
            records.append(cur)
            cur = None
        else:
            key, _, value = raw.partition(":")
            if key in ("LF", "LH", "FNF", "FNH", "BRF", "BRH"):
                try:
                    cur["counters"][key] = int(value)
                except ValueError:
                    pass            # a malformed counter is absent, not zero
    return records


def rate(hit, found):
    """A rate, or None when there is nothing to rate.

    None is NOT zero. A header with no branches would sort first under 0.0% and be
    read as the least covered file in the tree, which is how a table misleads while
    every individual number in it is defensible.
    """
    if not found:
        return None
    return 100.0 * hit / found


def rows(records):
    out = []
    for rec in records:
        c = rec["counters"]
        row = {"name": rec["name"].rsplit("/", 1)[-1]}
        for label, found_key, hit_key in _PAIRS:
            found, hit = c.get(found_key), c.get(hit_key)
            if found is None or hit is None:
                row[label] = (None, None, None)
            else:
                row[label] = (rate(hit, found), hit, found)
        out.append(row)
    return out


def cell(value):
    pct, hit, found = value
    if pct is None:
        return f"{'-':>7} {'':>13}"
    return f"{pct:6.1f}% {f'{hit}/{found}':>13}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tracefile")
    ap.add_argument("--limit", type=int, default=20,
                    help="rows to print (0 for all); the count printed names what was dropped")
    args = ap.parse_args(argv)

    table = rows(read_tracefile(args.tracefile))
    if not table:
        print("  no SF records in the tracefile, so there is nothing to rank")
        return 1

    # Sort by line rate. A file with no line counter at all has no place in a
    # ranking by line rate, so it goes last rather than first.
    table.sort(key=lambda r: (r["lines"][0] is None, r["lines"][0] if r["lines"][0] is not None else 0))

    shown = table if args.limit <= 0 else table[:args.limit]
    print(f"  {'file':<34}{'lines':<22}{'functions':<22}{'branches'}")
    for r in shown:
        print(f"  {r['name']:<34}{cell(r['lines'])} {cell(r['functions'])} {cell(r['branches'])}")
    if len(shown) < len(table):
        print(f"  ({len(table) - len(shown)} further file(s) not shown, all covered at least as"
              f" well as the last row)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
