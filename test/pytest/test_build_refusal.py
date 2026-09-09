"""The corpus must not report on source it never built.

@jdatcmd demonstrated the defect this closes: with
`#error THIS SOURCE IS BROKEN AND CANNOT BUILD` appended to
src/columnar_projection.c and nothing rebuilt,

    pytest                          -> 25 passed, exit 0
    bash test/native_projection.sh  -> FATAL: the build failed ..., exit 1

The bash harness has refused that since #536. This one did not, because it never
built, never installed and never compared anything -- `Cluster.so_md5` printed a
fingerprint that nothing read.

The refusal now comes from `pgc_build_and_install` in test/lib.sh, driven from
Python, so there is one implementation rather than two that can drift.

Two levels of arm here, deliberately. The injected-runner arms pin what the
Python side does with a verdict. The `bash` arms pin the SHELL PLUMBING -- the
sourcing, the quoting and the exit-status path -- which an injected runner
cannot reach and which is where a wrong quote would hide.
"""

import pathlib
import subprocess

import pytest

from pgc_cluster import build_and_install, build_once, source_fingerprint


class _Proc:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_a_failed_build_raises_rather_than_returning(expect):
    with pytest.raises(RuntimeError) as exc:
        build_and_install("/nowhere", "/bin/false", "18",
                          runner=lambda argv: _Proc(1, err="compiler said no"))
    expect.at_least(str(exc.value).count("refusing"), 1,
                    "the refusal says it is refusing")
    expect.at_least(str(exc.value).count("compiler said no"), 1,
                    "and carries the build's own output, not a summary")


def test_the_refusal_names_the_tree_it_refused(expect):
    """A reader with several worktrees needs to know WHICH source failed."""
    with pytest.raises(RuntimeError) as exc:
        build_and_install("/root/some-worktree", "/bin/false", "18",
                          runner=lambda argv: _Proc(1))
    expect.at_least(str(exc.value).count("/root/some-worktree"), 1,
                    "the message names the source directory")


def test_a_successful_build_is_silent(expect):
    """Positive control: the guard must not fire on a build that worked."""
    build_and_install("/nowhere", "/bin/false", "18",
                      runner=lambda argv: _Proc(0))
    expect.num(1, 1, "a returncode of 0 raises nothing")


def _fake_tree(tmp_path, verdict_rc):
    """A tree whose test/lib.sh defines the function with a fixed verdict."""
    (tmp_path / "test").mkdir(parents=True, exist_ok=True)
    (tmp_path / "test" / "lib.sh").write_text(
        "pgc_build_and_install() {\n"
        "  echo '-- building'\n"
        f"  [ {verdict_rc} -eq 0 ] || {{ echo 'FATAL: the build failed' >&2; return 1; }}\n"
        "  return 0\n"
        "}\n"
    )
    return tmp_path


def test_the_shell_path_really_refuses(tmp_path, expect):
    """The real bash invocation, not an injected runner: sourcing, quoting and
    the exit status all have to work for the refusal to arrive."""
    tree = _fake_tree(tmp_path / "broken", 1)
    with pytest.raises(RuntimeError) as exc:
        build_and_install(tree, "/bin/false", "18")
    expect.at_least(str(exc.value).count("FATAL: the build failed"), 1,
                    "the shell's own FATAL reaches the Python caller")


def test_the_shell_path_accepts_a_good_build(tmp_path, expect):
    """Control for the arm above, through the same plumbing."""
    tree = _fake_tree(tmp_path / "ok", 0)
    build_and_install(tree, "/bin/false", "18")
    expect.num(1, 1, "a zero verdict through real bash raises nothing")


def test_a_missing_lib_sh_is_a_refusal_not_a_pass(tmp_path, expect):
    """If lib.sh cannot be sourced there is no guard at all, so the harness must
    fail rather than proceed ungated."""
    with pytest.raises(RuntimeError) as exc:
        build_and_install(tmp_path / "empty", "/bin/false", "18")
    expect.at_least(str(exc.value).count("refusing"), 1,
                    "an unsourceable lib.sh refuses")


def test_build_once_builds_once_and_then_skips(tmp_path, expect):
    """The xdist workers share one prefix, so the install is serialised rather
    than skipped."""
    # A fingerprintable tree: the marker is keyed on source content, so a tree
    # with nothing to compile deliberately never certifies and always rebuilds.
    tree = _tree_with_source(tmp_path, "ok2", "int a = 1;\n")
    lock = str(tmp_path / "lock")
    calls = []

    def counting(argv):
        calls.append(argv)
        return _Proc(0)

    first = build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    second = build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    expect.text(first, "built", "the first caller builds")
    expect.text(second, "already-built", "the second finds the marker")
    expect.num(len(calls), 1, "and the build ran exactly once")


def test_build_once_rebuilds_for_a_different_prefix(tmp_path, expect):
    """Keying the marker on 'did anyone build' would reintroduce the defect for
    anyone who runs the corpus against two majors in turn."""
    tree = _tree_with_source(tmp_path, "ok3", "int a = 1;\n")
    lock = str(tmp_path / "lock2")
    calls = []

    def counting(argv):
        calls.append(argv)
        return _Proc(0)

    build_once(tree, "/usr/local/pg18a/bin/pg_config", "18", lock_path=lock, runner=counting)
    build_once(tree, "/usr/local/pg19a/bin/pg_config", "19", lock_path=lock, runner=counting)
    expect.num(len(calls), 2, "a different prefix builds again")


def _tree_with_source(tmp_path, name, body):
    """A fake tree that is fingerprintable: it has src/*.c and a Makefile."""
    tree = _fake_tree(tmp_path / name, 0)
    (tree / "src").mkdir(parents=True, exist_ok=True)
    (tree / "src" / "columnar.c").write_text(body)
    (tree / "Makefile").write_text("all:\n\ttrue\n")
    return tree


def test_editing_the_source_rebuilds(tmp_path, expect):
    """The marker is keyed on the source fingerprint, not just the prefix.

    Keying on pg_config and major alone would skip the build after a source
    edit -- the staleness this whole guard exists to stop, reintroduced by the
    optimisation meant to make the guard cheap.
    """
    tree = _tree_with_source(tmp_path, "edited", "int a = 1;\n")
    lock = str(tmp_path / "lock3")
    calls = []

    def counting(argv):
        calls.append(argv)
        return _Proc(0)

    build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    expect.num(len(calls), 1, "unchanged source builds once")

    (tree / "src" / "columnar.c").write_text("int a = 2;\n")
    build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    expect.num(len(calls), 2, "an edited source builds again")


def test_the_fingerprint_reads_content_not_mtime(tmp_path, expect):
    """A checkout or a branch switch rewrites mtimes without changing what
    compiles, and `git stash` does the reverse. Content is the honest input."""
    tree = _tree_with_source(tmp_path, "mtime", "int a = 1;\n")
    before = source_fingerprint(tree)
    (tree / "src" / "columnar.c").touch()
    expect.text(source_fingerprint(tree), before,
                "touching a file does not change the fingerprint")
    (tree / "src" / "columnar.c").write_text("int a = 2;\n")
    expect.at_least(int(source_fingerprint(tree) != before), 1,
                    "changing its content does")


def test_an_unfingerprintable_tree_always_rebuilds(tmp_path, expect):
    """No fingerprint means no key, and no key must mean rebuild rather than
    skip. `unknown` is never allowed to read as `fresh` anywhere in this
    harness."""
    tree = _fake_tree(tmp_path / "nosrc", 0)   # no src/, no Makefile
    expect.text(repr(source_fingerprint(tree)), "None",
                "a tree with nothing to compile has no fingerprint")
    lock = str(tmp_path / "lock4")
    calls = []

    def counting(argv):
        calls.append(argv)
        return _Proc(0)

    build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    expect.num(len(calls), 2, "both calls build, because neither could be certified")
