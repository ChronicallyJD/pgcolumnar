#!/usr/bin/env python3
"""Compare every skip loop's names against the arms its sibling branch emits.

#994. A `for VAR in <names>; do check_skip "$VAR" ...; done` exists so that a
skipped arm records under the name it would have used. The loop DUPLICATES those
names, so a rename in the sibling branch desynchronises them silently and the
skip starts recording under a name nothing emits.

WHY A SCRIPT AND NOT awk IN THE PART. The first version used two awk extractors
that each `exit` on first match, so a file with three loops over one variable
compared only the first -- and the one it compared was the one whose both sides
had just been written together, so it agreed by construction.

WHAT IS AND IS NOT COMPARED, reported rather than assumed:

    loops         every `for VAR in ... check_skip "$VAR"` found
    armless       the sibling branch names no arms; the skip IS the record
    interpolated  either side contains a shell expansion, so a literal set
                  comparison would be wrong in both directions
    compared      the rest, where a mismatch is a real finding

`interpolated` is printed because a comparison nobody makes and a comparison that
passes are indistinguishable in a total of mismatches.
"""

import pathlib
import re
import sys

# Derived, not listed: any function defined in the corpus whose body reaches
# check/pgc_record emits a record under its first argument.
_HELPER_DEF = re.compile(r"^([a-z_][a-z0-9_]*)\(\)\s*\{", re.M)
_LOOP = re.compile(r"^\s*for\s+([a-z_][a-z0-9_]*)\s+in\b")


_HEREDOC = re.compile(r"<<-?\s*'?\"?([A-Za-z_][A-Za-z0-9_]*)'?\"?\s*$")


def blank_heredocs(lines):
    """Return lines with heredoc BODIES blanked out.

    Shell-shaped tokens inside a heredoc are not shell. `native_parquet_flba.sh`
    embeds python whose `if phys != {...}:` a naive depth count reads as a shell
    `if`, which unbalanced the walk and made a ten-arm branch report six. The
    tool that finds silently-lost arms was silently losing arms.
    """
    out, term = [], None
    for l in lines:
        if term is None:
            m = _HEREDOC.search(l)
            out.append(l)
            if m:
                term = m.group(1)
        else:
            out.append("")
            if l.strip() == term:
                term = None
    return out


def emitters(text):
    out = {"check", "check_num", "check_skip", "check_text", "check_timing"}
    for m in _HELPER_DEF.finditer(text):
        name, start = m.group(1), m.end()
        end = text.find("\n}", start)
        body = text[start:end if end > 0 else len(text)]
        if re.search(r"\bcheck\w*\b|\bpgc_record\b", body):
            out.add(name)
    return out


def names_in(lines, emit):
    pat = re.compile(r"^\s*(?:%s)\s+\"([^\"]*)\"" % "|".join(sorted(emit, key=len, reverse=True)))
    out = set()
    for l in lines:
        m = pat.match(l)
        if not m:
            continue
        n = m.group(1)
        # A BARE VARIABLE REFERENCE IS THE SKIP MECHANISM, NOT AN ARM. A sibling
        # branch often contains its own `check_skip "$VAR"` loop; counting that as
        # an arm name made four comparable sites read as INTERPOLATED and therefore
        # uncompared -- a silent loss of coverage in the tool that reports coverage.
        if re.fullmatch(r"\$\{?[a-z_][a-z0-9_]*\}?", n):
            continue
        out.add(n)
    return out


def loop_blocks(lines, var):
    """Every `for <var> in` header block and the line index it ends on."""
    out = []
    for i, l in enumerate(lines):
        m = _LOOP.match(l)
        if not m or m.group(1) != var:
            continue
        j = i
        while j < len(lines) and not lines[j].rstrip().endswith("; do"):
            j += 1
        out.append((i, j))
    return out


def _sibling_before(lines, start):
    """If the loop sits in an `else` branch, return the `then` branch above it."""
    depth = 0
    j = start - 1
    while j >= 0:
        t = lines[j].strip()
        if t == "fi" or t.startswith("fi "):
            depth += 1
        elif t.startswith("if ") or t.startswith("if["):
            if depth == 0:
                return []          # reached our own `if` without meeting an `else`
            depth -= 1
        elif (t == "else" or t.startswith("elif ")) and depth == 0:
            # collect from here back to the matching `if`
            k, d2, idx = j - 1, 0, []
            while k >= 0:
                u = lines[k].strip()
                if u == "fi" or u.startswith("fi "):
                    d2 += 1
                elif u.startswith("if ") or u.startswith("if["):
                    if d2 == 0:
                        return idx
                    d2 -= 1
                idx.append(k)
                k -= 1
            return []          # ran off the top without a balanced `if`: unparsed
        j -= 1
    return []


def sibling_lines(real, struct, start):
    """Walk the heredoc-free view, return the corresponding real lines."""
    idx = sibling(struct, start, want_index=True)
    return [real[i] for i in idx]


def sibling(lines, start, want_index=False):
    """The branch the loop is the alternative to, looking BOTH ways.

    A loop in the `then` branch has its arms after the `else`. A loop in the
    `else` branch has them BEFORE it, after the `if`. The first version looked
    only forward, so the two outer pyarrow gates -- whose thirteen arms sit in
    the `then` branch -- read as ARMLESS: a false negative of exactly the kind
    this tool exists to find, in the tool. @OffgridwithJD made the same mistake
    classifying the sites in #994, which is why there were six rather than four.
    """
    back = _sibling_before(lines, start)
    if back:
        return back
    depth, j = 0, start
    while j < len(lines):
        s = lines[j].strip()
        if s.startswith("if ") or s.startswith("if["):
            depth += 1
        elif s == "fi" or s.startswith("fi "):
            if depth == 0:
                return []
            depth -= 1
        elif (s == "else" or s.startswith("elif ")) and depth == 0:
            k, d2, idx = j + 1, 0, []
            while k < len(lines):
                t = lines[k].strip()
                if t.startswith("if "):
                    d2 += 1
                elif t == "fi":
                    if d2 == 0:
                        return idx
                    d2 -= 1
                idx.append(k)
                k += 1
            return idx
        j += 1
    return []


def main(testdir):
    root = pathlib.Path(testdir)
    files = sorted(list(root.glob("*.sh")) + list((root / "selftest").glob("*.sh")))
    lib = (root / "lib.sh").read_text(errors="replace") if (root / "lib.sh").exists() else ""

    loops = compared = interpolated = armless = 0
    bad = []
    for f in files:
        text = f.read_text(errors="replace")
        if "check_skip \"$" not in text:
            continue
        lines = text.splitlines()
        # STRUCTURE IS READ FROM A HEREDOC-FREE VIEW; names still come from the
        # real lines, because a heredoc never contains a check.
        struct = blank_heredocs(lines)
        emit = emitters(text) | emitters(lib)
        for var in sorted(set(re.findall(r'check_skip\s+"\$([a-z_][a-z0-9_]*)"', text))):
            for start, hdr_end in loop_blocks(struct, var):
                loops += 1
                loop_names = {s for s in re.findall(r'"([^"]*)"', "\n".join(lines[start:hdr_end + 1]))
                              if s and not s.startswith("$")}
                arms = names_in(sibling_lines(lines, struct, hdr_end), emit)
                if not arms:
                    armless += 1
                    continue
                if any("$" in n for n in loop_names | arms):
                    interpolated += 1
                    continue
                compared += 1
                if loop_names != arms:
                    bad.append(f"{f.name}:{start + 1}")
    print(f"loops {loops}")
    print(f"compared {compared}")
    print(f"interpolated {interpolated}")
    print(f"armless {armless}")
    for b in bad:
        print(f"MISMATCH {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "test"))
