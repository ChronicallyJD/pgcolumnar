#!/usr/bin/env python3
"""What a build reads, as a manifest, and the fingerprint that is its hash.

THE ONE IMPLEMENTATION. `test/lib.sh` and `test/pytest/pgc_cluster.py` each used
to carry their own, and on 2026-09-09 the pair produced four defects in a day --
two in each copy, and not one found by whoever wrote that copy (#907):

    objstore/*.c never walked            python   found by @linuxhikerpm
    the bare NAME instead of the path    python   found while fixing the above
    `xargs -0 cat | md5sum`, no bounds   shell    found by @linuxhikerpm
    each build dir's Makefile omitted    python   found while writing the twin

The Python docstring asserted "the same input set as pgc_source_fingerprint in
test/lib.sh" throughout all four. It was false when written and stayed false
through two rounds of fixing. A prose claim of agreement is not a mechanism, and
it is worse than saying nothing because it is what stops the next person checking.

WHY PYTHON RATHER THAN SHELL, which is the opposite of what was first proposed.
The single implementation goes in the more portable language, not the less: bash
is largely a GNU thing, while Python is present on FreeBSD and Windows where bash
is not (jd). `test/lib.sh` already requires bash, so calling a more portable
interpreter from it cannot cost portability -- and it is not a cost at all:

    shell, forking md5sum once per file   239 ms/call
    this module, one interpreter start     26 ms/call

STDLIB ONLY, AND IT MUST RUN ON THE SYSTEM INTERPRETER. test/pytest/README.md
records that the interpreter is EXTERNALLY-MANAGED and that pytest runs from a
venv. lib.sh must never need that venv: a freshness gate that depended on the
pytest test dependencies would make every bash suite unrunnable until somebody
had installed pytest. Nothing here imports outside the standard library, and
nothing here imports from test/pytest/.
"""

import hashlib
import os
import pathlib
import sys

__all__ = ["norm_path", "build_dirs", "manifest", "fingerprint"]

SOURCE_SUFFIXES = (".c", ".h")
ROOT_SUFFIXES = (".control", ".sql")


def norm_path(d):
    """The tree's physical path, or the argument unchanged if it cannot be entered.

    One tree hashes one way however the path is spelled. The relative path below
    is produced by stripping a prefix, so `$dir` with a trailing slash, with a
    `/./` segment, or reached through a symlink used to put the full ABSOLUTE
    path into the manifest and the same tree hashed four different ways. The
    fallback matches the shell's `pgc_norm_path`: hand back the raw path, find
    nothing under it, and let the caller return no fingerprint.
    """
    try:
        return pathlib.Path(os.path.realpath(str(d)))
    except OSError:
        return pathlib.Path(str(d))


def _is_plain_file(p):
    """A regular file, NOT a symlink to one.

    `find -type f` tests the link itself, so a symlinked source is not in the
    shell's manifest. `pathlib.is_file()` FOLLOWS the link and would have added
    one, which is a silent divergence of exactly the kind this module exists to
    end -- and it would have appeared only on trees that use symlinks, which is
    to say in somebody else's checkout rather than in CI.
    """
    try:
        return p.is_file() and not p.is_symlink()
    except OSError:
        return False


def build_dirs(root):
    """Every directory the build compiles in: src, plus each recursed module.

    src unconditionally, whether or not it exists -- the shell prints it before
    looking, and a missing src must not change the RESULT, only what is found in
    it. Then any depth-2 Makefile's directory, which is how the top-level
    Makefile reaches a separately built module such as objstore/.
    """
    root = pathlib.Path(root)
    out = [root / "src"]
    try:
        entries = sorted(root.iterdir(), key=lambda p: os.fsencode(str(p)))
    except OSError:
        return out
    for d in entries:
        try:
            if not d.is_dir() or d.is_symlink():
                continue        # find does not descend a symlinked directory
        except OSError:
            continue
        if d == root / "src":
            continue
        if _is_plain_file(d / "Makefile"):
            out.append(d)
    return out


def _manifest_files(root):
    paths = []
    for d in build_dirs(root):
        try:
            entries = list(d.iterdir())
        except OSError:
            continue            # find prints nothing for an unreadable directory
        for f in entries:
            if _is_plain_file(f) and (f.suffix in SOURCE_SUFFIXES or f.name == "Makefile"):
                paths.append(f)
    try:
        entries = list(root.iterdir())
    except OSError:
        entries = []
    for f in entries:
        if _is_plain_file(f) and (f.name == "Makefile" or f.suffix in ROOT_SUFFIXES):
            paths.append(f)
    # Sorted as BYTES over the absolute path, which is what `sort -z` does under
    # LC_ALL=C and what every stamp on disk was written with. It is NOT what
    # `sort -z` does under a locale: no locale is pinned anywhere in the harness,
    # and en_US.UTF-8 collation reorders `columnar_arrow.c` against
    # `columnar-arrow.c`, so the same tree fingerprinted two ways depending on
    # the developer's environment --
    #
    #     LC_ALL=C            6d122a7158d5
    #     LC_ALL=en_US.UTF-8  0b59bd75fa4f
    #
    # A desktop default of en_US.UTF-8 stamping a tree that CI then reads under
    # C.UTF-8 is a FATAL naming a stale binary against a clean tree. Sorting
    # bytes here removes the environment from the answer.
    return sorted(paths, key=lambda p: os.fsencode(str(p)))


def manifest(root):
    """-> "relpath digest" per file, newline-joined, or None if one could not be read.

    None rather than a short manifest. A digest that FAILED must not look like
    one that succeeded: the shell version contributed an empty digest for a failed
    md5sum and returned a confident wrong hash at status 0, which cost a matrix.
    """
    root = norm_path(root)
    lines = []
    for f in _manifest_files(root):
        try:
            digest = hashlib.md5(f.read_bytes()).hexdigest()
        except OSError:
            return None
        try:
            rel = f.relative_to(root)
        except ValueError:
            return None
        lines.append(f"{rel} {digest}")
    return "\n".join(lines)


def fingerprint(root):
    """-> 12 hex characters, or "" if it could not be computed.

    Empty rather than a hash, which pgc_freshness_verdict turns into `unknown`
    and the controller prints as "freshness UNVERIFIED" -- deliberately not a
    failure. A false UNVERIFIED costs a line of output; a false FATAL costs a
    matrix and teaches people to re-run past a freshness check.
    """
    out = manifest(root)
    if out is None or out == "":
        return ""
    # THE TRAILING NEWLINE IS LOAD-BEARING. The shell piped its loop straight
    # into md5sum, so the stream md5sum saw ended with one. Drop it and the same
    # unchanged tree hashes differently, every stamp already on disk reads
    # `stale`, and a portability fix becomes a false FATAL for everyone holding a
    # built worktree.
    return hashlib.md5((out + "\n").encode()).hexdigest()[:12]


def main(argv):
    if len(argv) != 3 or argv[1] not in ("manifest", "fingerprint"):
        print("usage: pgc_fingerprint.py {manifest|fingerprint} DIR", file=sys.stderr)
        return 2
    if argv[1] == "manifest":
        out = manifest(argv[2])
        # An unreadable digest prints nothing and exits 1, so a caller cannot
        # mistake "could not be computed" for "the tree holds nothing".
        if out is None:
            return 1
        if out:
            print(out)
        return 0
    print(fingerprint(argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
