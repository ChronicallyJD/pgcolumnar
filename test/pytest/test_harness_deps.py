"""The harness must be able to test ITSELF without a database.

WHY THIS EXISTS. `conftest.py` imported psycopg at module scope, and conftest is
imported before every run, so a DATABASE DRIVER was a hard requirement of the
whole corpus -- including the 61 tests that never open a connection. With psycopg
absent the run did not fail a test, it failed to COLLECT:

    ImportError while loading conftest '.../conftest.py'
    conftest.py:15: in <module>
        import psycopg
    E   ModuleNotFoundError: No module named 'psycopg'

That coupling is why the guard-testing half of this corpus cannot run where the
gate runs. README.md records the decision not to register the corpus in `SUITES`
and names the price; this removes one of the two things making that price real.

These arms keep it removed. A module-scope import reads like an ordinary tidy-up
when someone adds a fixture, and nothing else here would notice.
"""

import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent

# The files that never open a connection. Derived rather than listed would be
# better, but "imports psycopg" is not the property -- the property is "uses a
# cluster fixture", and a file can name one in a docstring. Listed, with an arm
# below that fails if one of them starts needing a database.
NO_CLUSTER = [
    "test_docs_cover_the_corpus.py",
    "test_guards_pinned.py",
    "test_ordered.py",
    "test_runshape.py",
]


def _run_without_psycopg(args, expect):
    """Run pytest with `import psycopg` forced to fail, and return the result.

    A SHIM RATHER THAN AN UNINSTALL. Uninstalling psycopg would test the machine
    rather than the harness, cannot run concurrently with anything else, and
    leaves the environment broken if the test dies. A module that raises on
    import, placed FIRST on the path, is the same observation and is reversible
    by construction.
    """
    shim = tempfile.mkdtemp(prefix="pgc-nopsy-")
    pathlib.Path(shim, "psycopg.py").write_text(
        'raise ImportError("psycopg is shimmed out by '
        'test_harness_deps: the harness must self-test without a database")\n'
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = shim + os.pathsep + str(HERE)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=str(HERE), env=env, capture_output=True, text=True,
    )
    # PREMISE: the shim must actually bite, or this arm proves nothing at all.
    probe = subprocess.run(
        [sys.executable, "-c", "import psycopg"],
        cwd=str(HERE), env=env, capture_output=True, text=True,
    )
    expect.at_least(int("ImportError" in probe.stderr), 1,
                    "premise: the shim really does make `import psycopg` fail")
    return proc


def test_the_guard_half_of_the_corpus_runs_without_a_database_driver(expect):
    """61 of 142 tests need no database. They must not need its driver either."""
    proc = _run_without_psycopg(NO_CLUSTER, expect)
    out = proc.stdout + proc.stderr
    # Collection surviving is the first thing to establish: without it, a green
    # exit code would only mean pytest never got as far as running anything.
    defeated = "ImportError while loading conftest" in out or "ModuleNotFoundError" in out
    expect.text(repr(defeated), "False",
                "collection is not defeated by the absent driver")
    expect.num(proc.returncode, 0,
               f"the no-cluster files pass with psycopg absent: {out[-400:]}")


def test_a_cluster_test_still_needs_the_driver(expect):
    """THE CONTROL, and without it the arm above is satisfied by a corpus that
    connects to nothing at all.

    Deferring the import must not have made the database optional -- only its
    IMPORT lazy. A test that actually wants a connection must still fail when the
    driver is gone, and it must fail for that reason rather than by being skipped.
    """
    proc = _run_without_psycopg(["test_connection.py"], expect)
    expect.at_least(proc.returncode, 1,
                    "a cluster test cannot pass without the driver")
    expect.at_least(
        int("psycopg is shimmed out" in (proc.stdout + proc.stderr)), 1,
        "and it fails BECAUSE the driver is gone, naming the shim")


def test_conftest_imports_no_database_driver_at_module_scope(expect):
    """The regression named directly, because the behavioural arm above is slow
    and a reader changing conftest deserves to be told in one line."""
    src = (HERE / "conftest.py").read_text()
    module_scope = [
        ln for ln in src.splitlines()
        if ln.startswith("import psycopg") or ln.startswith("from psycopg")
    ]
    expect.text(", ".join(module_scope) or "none", "none",
                "conftest.py imports no database driver at module scope")
    # PREMISE: the check can see an import at all -- otherwise "none" is what a
    # broken reader says too.
    fake = "import os\nimport psycopg\n"
    seen = [ln for ln in fake.splitlines() if ln.startswith("import psycopg")]
    expect.num(len(seen), 1, "premise: the reader recognises a module-scope import")


def test_the_no_cluster_list_still_names_files_that_exist(expect):
    """A list is a hazard. This one is small and pinned, so it fails loudly rather
    than silently covering fewer files after a rename."""
    missing = [n for n in NO_CLUSTER if not (HERE / n).is_file()]
    expect.text(", ".join(missing) or "none", "none",
                "every file in NO_CLUSTER exists")
    expect.at_least(len(NO_CLUSTER), 4, "premise: the list is not empty")


def test_ci_derives_the_file_list_rather_than_repeating_it(expect):
    """CI must ask this module for NO_CLUSTER, not carry its own copy.

    A second copy of a list is the defect this repository spent a day removing
    from TESTS.md: a hand-maintained value whose correct content is a function of
    the tree, going stale silently because nothing compares the two. The job runs
    `from test_harness_deps import NO_CLUSTER`, so adding a file here changes what
    CI runs with no second edit.

    The pins are single-sourced the same way, out of requirements-test.txt, so the
    version CI installs cannot drift from the version the corpus was tested with.
    """
    ci = (HERE.parent.parent / ".github" / "workflows" / "ci.yml")
    expect.text(repr(ci.is_file()), "True", "premise: ci.yml is where this expects")
    text = ci.read_text()

    expect.at_least(text.count("from test_harness_deps import NO_CLUSTER"), 1,
                    "the job derives the file list from this module")
    expect.at_least(text.count("requirements-test.txt"), 1,
                    "and the pins from requirements-test.txt")

    # AND IT MUST NOT ALSO HARDCODE THEM. Deriving plus a stale literal copy is
    # worse than either alone, because the copy looks authoritative.
    job = text[text.index("pytest-guards:"):]
    job = job[:job.index("\n  build:")] if "\n  build:" in job else job
    hardcoded = [n for n in NO_CLUSTER if n in job]
    expect.text(", ".join(hardcoded) or "none", "none",
                "the job names no corpus file literally")


def test_the_job_installs_no_database_driver(expect):
    """The job's value is that it runs where there is no database.

    If it installed psycopg the tests would pass for the ordinary reason and prove
    nothing about the coupling this file exists to keep removed.
    """
    ci = (HERE.parent.parent / ".github" / "workflows" / "ci.yml")
    job = ci.read_text()
    job = job[job.index("pytest-guards:"):]
    job = job[:job.index("\n  build:")] if "\n  build:" in job else job
    installs_driver = "psycopg" in job and "pip install" in job and "pip show psycopg" not in job
    expect.text(repr(installs_driver), "False",
                "the job installs no database driver")
    expect.at_least(job.count("pip show psycopg"), 1,
                    "and it asserts the driver is absent rather than assuming it")
