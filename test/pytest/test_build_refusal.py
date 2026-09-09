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

import os
import pathlib
import subprocess

import pytest

from pgc_cluster import (build_and_install, build_once, make_cluster,
                         source_fingerprint)


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


# ---------------------------------------------------------------------------
# The ORDER of build and server start, which is not a detail.
#
# shared_preload_libraries maps the library at postmaster start, so a cluster
# started before the install keeps the OLD .so mapped for its whole life. The
# build reports success and every test still measures the previous branch's
# code -- the guard defeated by the order of two lines. This is how it showed
# up: the first run after a source change failed to start a cluster, and the
# next run passed because the install had already landed.


class _C:
    """Just enough Cluster to drive the verdict."""
    from pgc_cluster import Cluster
    server_binary_verdict = Cluster.server_binary_verdict


def test_a_server_older_than_the_library_is_refused(expect):
    expect.text(_C().server_binary_verdict(so_mtime=200, postmaster_epoch=100),
                "predates", "the .so was written after the server started")


def test_a_server_started_after_the_library_is_fresh(expect):
    expect.text(_C().server_binary_verdict(so_mtime=100, postmaster_epoch=200),
                "fresh", "the server started after the .so was installed")


def test_equal_timestamps_are_fresh_not_predates(expect):
    """The exact boundary. A one-second-resolution mtime and a start time in the
    same second must not read as stale, or every fast run refuses itself."""
    expect.text(_C().server_binary_verdict(so_mtime=100, postmaster_epoch=100),
                "fresh", "same second is not stale")


def test_an_unreadable_side_is_unknown_not_fresh(expect):
    """`unknown` never reads as `fresh` anywhere in this harness."""
    expect.text(_C().server_binary_verdict(so_mtime=None, postmaster_epoch=100),
                "unknown", "no .so mtime")
    expect.text(_C().server_binary_verdict(so_mtime=100, postmaster_epoch=None),
                "unknown", "no postmaster start time")
    expect.text(_C().server_binary_verdict(so_mtime="x", postmaster_epoch="y"),
                "unknown", "non-numeric epochs")


# ---------------------------------------------------------------------------
# TWO FINDINGS FROM @linuxhikerpm, both reproduced against the branch before
# these arms were written. They are infrastructure guarantees rather than
# corpus coverage: the first runs stale code under a FRESH verdict, and the
# second leaves state behind precisely on failed setup, where repeated runs
# need isolation most.


def _tree_with_objstore(tmp_path, name):
    """A tree shaped like this repository's: src/ plus a SEPARATELY built
    module the top-level Makefile reaches by recursion."""
    tree = tmp_path / name
    (tree / "src").mkdir(parents=True, exist_ok=True)
    (tree / "src" / "columnar.c").write_text("int a = 1;\n")
    (tree / "objstore").mkdir(parents=True, exist_ok=True)
    (tree / "objstore" / "module.c").write_text("int b = 1;\n")
    (tree / "objstore" / "Makefile").write_text("all:\n\ttrue\n")
    (tree / "Makefile").write_text("all:\n\t$(MAKE) -C objstore\n")
    (tree / "test").mkdir(parents=True, exist_ok=True)
    (tree / "test" / "lib.sh").write_text(
        "pgc_build_and_install() { return 0; }\n")
    return tree


def test_the_fingerprint_covers_a_separately_built_module(tmp_path, expect):
    """An objstore/ edit must move the fingerprint.

    Reproduced by @linuxhikerpm on `5f3dedb`: `source_fingerprint` read
    `src/*` and the top-level Makefile only, so editing the recursed module
    left the hash unchanged --

        objstore_before=2799803eaeac objstore_after=2799803eaeac
        builds=1 second=already-built

    -- and the second run certified a stale module as current. This is the
    Python form of the gap #898 closes in `test/lib.sh`, and #897 carries an
    INDEPENDENT implementation, so rebasing #898 would not have fixed it.
    """
    tree = _tree_with_objstore(tmp_path, "fp")
    before = source_fingerprint(tree)
    expect.text(repr(before is None), "False",
                "premise: the tree fingerprints at all")

    (tree / "objstore" / "module.c").write_text("int b = 2;\n")
    after = source_fingerprint(tree)
    expect.num(int(after != before), 1,
               "editing a separately built module moves the fingerprint")

    (tree / "objstore" / "module.c").write_text("int b = 1;\n")
    expect.text(source_fingerprint(tree), before,
                "and restoring it restores the fingerprint")


def test_an_objstore_edit_forces_a_second_build(tmp_path, expect):
    """The consequence, end to end, which is what the finding was about."""
    tree = _tree_with_objstore(tmp_path, "fp2")
    lock = str(tmp_path / "lock_obj")
    calls = []

    def counting(argv):
        calls.append(argv)
        return _Proc(0)

    build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    expect.num(len(calls), 1, "premise: an unchanged tree builds once")

    (tree / "objstore" / "module.c").write_text("int b = 2;\n")
    build_once(tree, "/bin/pg_config", "18", lock_path=lock, runner=counting)
    expect.num(len(calls), 2, "an edited objstore module builds again")


def test_make_cluster_leaves_nothing_behind_when_setup_fails(tmp_path, expect):
    """make_cluster owns its temporary tree until it successfully returns.

    Reproduced by @linuxhikerpm: `root` is created by `mkdtemp` and then
    `Cluster()`, `initdb()`, `start()` and `is_ours()` run with no cleanup
    guard --

        make_cluster_error=RuntimeError
        new_roots=1 leaked=['/tmp/pgc-pytest-777-h3phhtxc']

    -- and `conftest.py` cannot clean it, because the tuple assignment
    `cluster, root = make_cluster(...)` never completes when it raises. The
    handled `is_ours()` path leaked too: it stopped the cluster and left the
    directory.
    """
    import glob
    before = set(glob.glob("/tmp/pgc-pytest-*"))

    raised = "no"
    try:
        make_cluster("/nonexistent/bin/pg_config", "gw77")
    except Exception:
        raised = "yes"

    expect.text(raised, "yes", "premise: setup really failed, so the arm is not vacuous")
    leaked = sorted(set(glob.glob("/tmp/pgc-pytest-*")) - before)
    expect.text(", ".join(leaked) or "none", "none",
                "a failed make_cluster leaves no directory behind")


# ---------------------------------------------------------------------------
# THE PYTEST TWIN of test/selftest/340's stamp arms, owed under jd's rule of
# 2026-09-23... 2026-09-09: every test written twice. The .sh half could not
# have one until test/pytest/ existed on main, which it now does (#897).
#
# These drive the SHELL functions through bash rather than reimplementing them,
# for the reason that keeps being proved this week: a second implementation of
# one idea drifts, and the drift is invisible until someone diffs the two.


# The tree this corpus belongs to, derived the same way conftest.py derives it.
SRCDIR = pathlib.Path(__file__).resolve().parents[2]


def _sh(srcdir, expr):
    """Evaluate one lib.sh expression against a tree, and return its stdout."""
    script = f'. "{SRCDIR}/test/lib.sh" || exit 1; {expr}'
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return p.stdout.strip(), p.returncode


def _tree_with_module(tmp_path, name):
    t = tmp_path / name
    (t / "src").mkdir(parents=True, exist_ok=True)
    (t / "objstore").mkdir(parents=True, exist_ok=True)
    (t / "src" / "a.c").write_text("int a;\n")
    (t / "objstore" / "b.c").write_text("int b;\n")
    (t / "objstore" / "Makefile").write_text("all:\n\ttrue\n")
    (t / "Makefile").write_text("all:\n\t$(MAKE) -C objstore\n")
    (t / "pgcolumnar.control").write_text("x\n")
    return t


def test_the_stamp_writer_reports_failure(tmp_path, expect):
    """`|| true` made both controllers' warning branches unreachable."""
    out, rc = _sh(tmp_path, 'pgc_write_source_stamp "/proc/pgc-twin" "deadbeef"')
    expect.num(rc, 1, "the writer reports failure on an unwritable target")
    ok, rc2 = _sh(tmp_path, f'pgc_write_source_stamp "{tmp_path}/s" "cafebabe"')
    expect.num(rc2, 0, "control: and succeeds on a writable one")


def test_two_installations_of_one_major_do_not_share_a_stamp(tmp_path, expect):
    """The stamp key must name the installation, not only the major."""
    cfgs = []
    for n in ("a", "b"):
        c = tmp_path / f"pg_config.{n}"
        c.write_text('#!/bin/sh\ncase "$1" in\n'
                     '  --version) echo "PostgreSQL 18.4" ;;\n'
                     f'  --pkglibdir) echo "/usr/local/pg18{n}/lib" ;;\nesac\n')
        c.chmod(0o755)
        cfgs.append(c)
    a, _ = _sh(tmp_path, f'pgc_source_stamp_path /tree "{cfgs[0]}"')
    b, _ = _sh(tmp_path, f'pgc_source_stamp_path /tree "{cfgs[1]}"')
    expect.text(str(a != b), "True", "two prefixes of one major get different stamps")
    a2, _ = _sh(tmp_path, f'pgc_source_stamp_path /tree "{cfgs[0]}"')
    expect.text(a2, a, "control: the same pg_config twice gives the same path")


def test_moving_bytes_between_files_moves_the_shell_fingerprint(tmp_path, expect):
    """`xargs -0 cat | md5sum` could not see a repartition."""
    t = _tree_with_module(tmp_path, "rp")
    before, _ = _sh(t, f'pgc_source_fingerprint "{t}"')
    expect.at_least(len(before), 12, "premise: the tree fingerprints at all")
    (t / "src" / "a.c").write_text("int a;\nint b;\n")
    (t / "objstore" / "b.c").write_text("")
    after, _ = _sh(t, f'pgc_source_fingerprint "{t}"')
    expect.text(str(after != before), "True",
                "moving bytes between files moves the fingerprint")


def test_the_two_fingerprint_implementations_cover_the_same_inputs(tmp_path, expect):
    """THE PROPERTY THE TWO IMPLEMENTATIONS MUST SHARE, and the one they did not.

    `source_fingerprint` in pgc_cluster.py says in its own docstring that it uses
    "the same input set as pgc_source_fingerprint in test/lib.sh". It did not:
    the shell hashes each build directory's `*.c`, `*.h` AND `Makefile`, while
    the Python read only `*.c` and `*.h` there. Editing `objstore/Makefile` --
    which changes how that module builds -- moved the shell hash and not the
    Python one, so `build_once` certified a stale module as current:

        baseline                    shell=45be41a5c47b  python=bea88c7d79ca
        objstore/Makefile edited    shell=cfb8f4553041  python=bea88c7d79ca

    That is @linuxhikerpm's finding one layer over: they found the .c files
    missing from the Python side, and the Makefiles were still missing after it
    was fixed.

    The two hashes are NOT required to be equal -- they are different digests
    over the same files, used independently. What is required is that the same
    edit moves both, which is what "the same input set" means and all the
    docstring ever claimed.
    """
    t = _tree_with_module(tmp_path, "cover")
    for edit, path, body in (
        ("a source file", t / "src" / "a.c", "int a = 2;\n"),
        ("a module source", t / "objstore" / "b.c", "int b = 2;\n"),
        ("a module Makefile", t / "objstore" / "Makefile", "all:\n\ttrue # x\n"),
        ("the top-level Makefile", t / "Makefile", "all:\n\t$(MAKE) -C objstore # x\n"),
        ("the control file", t / "pgcolumnar.control", "y\n"),
    ):
        sh_before, _ = _sh(t, f'pgc_source_fingerprint "{t}"')
        py_before = source_fingerprint(t)
        old = path.read_text()
        path.write_text(body)
        sh_after, _ = _sh(t, f'pgc_source_fingerprint "{t}"')
        py_after = source_fingerprint(t)
        path.write_text(old)
        expect.text(f"{sh_after != sh_before} {py_after != py_before}", "True True",
                    f"editing {edit} moves both fingerprints")


# ---------------------------------------------------------------------------
# THE TWIN of test/selftest/340's fingerprint-integrity arms. Two observers, one
# implementation: these drive the real shell functions through bash rather than
# reimplementing them, for the reason four fingerprint defects in one day proved
# — a second implementation of one idea drifts, and the drift is invisible until
# someone diffs the two.


def _sh_fp(expr, path_env=None, env=None):
    """Evaluate a lib.sh expression, optionally with a stubbed PATH."""
    script = f'. "{SRCDIR}/test/lib.sh" || exit 1; {expr}'
    e = dict(os.environ)
    if env:
        e.update(env)
    if path_env:
        e["PATH"] = path_env + ":" + e.get("PATH", "")
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=e)
    return p.stdout.strip(), p.returncode


def _fp_tree(tmp_path, name="t"):
    t = tmp_path / name
    (t / "src").mkdir(parents=True, exist_ok=True)
    (t / "objstore").mkdir(parents=True, exist_ok=True)
    (t / "src" / "a.c").write_text("int a;\n")
    (t / "src" / "b.c").write_text("int b;\n")
    (t / "src" / "c.c").write_text("int c;\n")
    (t / "objstore" / "m.c").write_text("int m;\n")
    (t / "objstore" / "Makefile").write_text("all:\n\ttrue\n")
    (t / "Makefile").write_text("all:\n\ttrue\n")
    (t / "pgcolumnar.control").write_text("x\n")
    return t


def _md5_stub(tmp_path, fail_on):
    """A stub md5sum: real, except that its Nth call fails with no output.

    Models one transient failure -- a fork that hits EAGAIN, an OOM kill, a
    loaded runner -- rather than a permanently broken md5sum, because the
    permanent case is not the one that produced a wrong answer in CI.
    """
    b = tmp_path / f"bin{fail_on}"
    b.mkdir(exist_ok=True)
    counter = tmp_path / f"count{fail_on}"
    counter.write_text("0")
    (b / "md5sum").write_text(
        "#!/bin/bash\n"
        f'_n=$(( $(cat "{counter}" 2>/dev/null || echo 0) + 1 ))\n'
        f'echo "$_n" > "{counter}"\n'
        f'[ "$_n" = "{fail_on}" ] && exit 1\n'
        'exec /usr/bin/md5sum "$@"\n'
    )
    (b / "md5sum").chmod(0o755)
    return str(b)


def test_a_failed_digest_yields_no_fingerprint_rather_than_a_wrong_one(tmp_path, expect):
    """`$(md5sum ... 2>/dev/null)` substituted an EMPTY digest and returned rc=0.

    One failed invocation among many silently changed the whole hash, so the
    function gave three different confident answers for one unchanged tree.
    """
    t = _fp_tree(tmp_path)
    base, rc = _sh_fp(f'pgc_source_fingerprint "{t}"')
    expect.at_least(len(base), 12, "premise: the tree fingerprints at all")

    # Premise for the stub: with nothing configured to fail it must agree with
    # the real md5sum, or the arms below measure the stub and not the fix.
    quiet = _md5_stub(tmp_path, 0)
    got, _ = _sh_fp(f'pgc_source_fingerprint "{t}"', path_env=quiet)
    expect.text(got, base, "premise: the stub agrees with md5sum when nothing fails")

    for n in (2, 3):
        stub = _md5_stub(tmp_path, n)
        got, _ = _sh_fp(f'pgc_source_fingerprint "{t}"', path_env=stub)
        expect.text(got or "empty", "empty",
                    f"a failed digest on file {n} yields no fingerprint")


def test_a_failed_digest_gives_unverified_and_never_a_false_stale(tmp_path, expect):
    """The property that matters. `stale` is the FATAL; `unknown` is UNVERIFIED.

    A false UNVERIFIED costs a line of output. A false FATAL costs a matrix and
    teaches people to re-run past a freshness check.
    """
    t = _fp_tree(tmp_path, "v")
    base, _ = _sh_fp(f'pgc_source_fingerprint "{t}"')
    stub = _md5_stub(tmp_path, 2)
    verdict, _ = _sh_fp(
        f'pgc_freshness_verdict "{base}" "$(pgc_source_fingerprint "{t}")"',
        path_env=stub)
    expect.text(verdict, "unknown", "a failed digest reads as unknown, not stale")
    healthy, _ = _sh_fp(f'pgc_freshness_verdict "{base}" "$(pgc_source_fingerprint "{t}")"')
    expect.text(healthy, "fresh", "control: an unstubbed run still reads fresh")


def test_one_tree_hashes_one_way_however_the_path_is_spelled(tmp_path, expect):
    """`${f#"$dir"/}` strips a prefix that must match character for character."""
    t = _fp_tree(tmp_path, "s")
    link = tmp_path / "s_link"
    link.symlink_to(t)
    plain, _ = _sh_fp(f'pgc_source_fingerprint "{t}"')
    expect.at_least(len(plain), 12, "premise: the fixture fingerprints at all")
    for label, spelling in (
        ("a trailing slash", f"{t}/"),
        ("a /./ segment", f"{t}/./"),
        ("a /src/.. segment", f"{t}/src/.."),
        ("a symlink", str(link)),
    ):
        got, _ = _sh_fp(f'pgc_source_fingerprint "{spelling}"')
        expect.text(got, plain, f"{label} hashes the same tree the same way")
    rel, _ = _sh_fp(f'cd "{t}" && pgc_source_fingerprint .')
    expect.text(rel, plain, "a relative path hashes the same tree the same way")


def test_the_fix_does_not_rebaseline_stamps_already_on_disk(tmp_path, expect):
    """A COMPATIBILITY assertion, not a tidiness one.

    Capturing the per-file lines to inspect them strips the trailing newline the
    old straight-pipe into md5sum included. Without restoring it the same
    unchanged tree hashes differently before and after the fix, every stamp on
    disk reads `stale`, and a fix for false FATALs becomes a false FATAL for
    everyone holding a built worktree. The matrix cannot catch this: it copies a
    fresh tree and re-stamps every run.
    """
    t = _fp_tree(tmp_path, "c")
    previous = r'''
_prev() { local dir="$1" d
  { while IFS= read -r d; do [ -n "$d" ] || continue
      find "$d" -maxdepth 1 -type f \( -name '*.c' -o -name '*.h' -o -name 'Makefile' \) -print0 2>/dev/null
    done < <(pgc_source_build_dirs "$dir")
    find "$dir" -maxdepth 1 -type f \( -name 'Makefile' -o -name '*.control' -o -name '*.sql' \) -print0 2>/dev/null
  } | sort -z | while IFS= read -r -d '' _f; do
      printf '%s %s\n' "${_f#"$dir"/}" "$(md5sum < "$_f" 2>/dev/null | cut -d' ' -f1)"
    done | md5sum | cut -c1-12; }
'''
    now, _ = _sh_fp(f'pgc_source_fingerprint "{t}"')
    before, _ = _sh_fp(previous + f'_prev "{t}"')
    expect.text(now, before,
                "the fixed fingerprint equals what the previous implementation produced")


def test_the_fingerprint_still_moves_on_a_real_change(tmp_path, expect):
    """Without this the spelling arms are vacuous.

    "Every spelling agrees" is satisfied perfectly by a fingerprint that ignores
    its input, so the set needs one arm proving the hash still moves.
    """
    t = _fp_tree(tmp_path, "m")
    before, _ = _sh_fp(f'pgc_source_fingerprint "{t}"')
    (t / "src" / "a.c").write_text("int a = 2;\n")
    after, _ = _sh_fp(f'pgc_source_fingerprint "{t}"')
    expect.text(str(after != before), "True", "a real content change moves the fingerprint")
    (t / "src" / "a.c").write_text("int a;\n")
    restored, _ = _sh_fp(f'pgc_source_fingerprint "{t}"')
    expect.text(restored, before, "and restoring the content restores it")


def test_a_tree_with_nothing_hashable_reports_no_fingerprint(tmp_path, expect):
    """The hash of an empty stream is a stable, comparable value: two empty
    trees would have "matched"."""
    empty = tmp_path / "hollow"
    empty.mkdir()
    got, _ = _sh_fp(f'pgc_source_fingerprint "{empty}"')
    expect.text(got or "empty", "empty", "an unhashable tree yields no fingerprint")
