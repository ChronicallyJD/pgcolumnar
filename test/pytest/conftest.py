"""pgColumnar pytest harness: fixtures.

The vacuity layer in pgc_vacuity.py is loaded for every run through the `-p`
argument in pytest.ini, not imported here, so that a test file cannot opt out of it.

`pytester` is enabled because the layer's own tests run pytest inside pytest: a
guard is proven to REFUSE rather than assumed to.
"""

import os
import re
import pathlib
import shutil

import psycopg
import pytest

from pgc_cluster import _pg_config, build_once, make_cluster

pytest_plugins = ["pytester"]

DEFAULT_PG_CONFIG = "/usr/local/pg18a/bin/pg_config"


def pytest_addoption(parser):
    parser.addoption(
        "--pg-config",
        action="store",
        default=os.environ.get("PGC_PG_CONFIG", DEFAULT_PG_CONFIG),
        help="pg_config of the server build under test (assert-enabled, per lib.sh)",
    )


SRCDIR = pathlib.Path(__file__).resolve().parents[2]


def major_of(version_text):
    """"PostgreSQL 18.4" -> "18". The build stamp is per major, because objects
    from another major link and then fail to load (#536)."""
    m = re.search(r"(\d+)", version_text or "")
    return m.group(1) if m else ""


@pytest.fixture(scope="session")
def pgc_cluster(request, worker_id):
    """One cluster per xdist worker, built once and torn down at session end."""
    pg_config = request.config.getoption("--pg-config")

    # BUILD BEFORE THE SERVER STARTS. This ran the other way round first, and the
    # ordering was not a detail: shared_preload_libraries maps the library at
    # postmaster start, so a cluster started before the install keeps the OLD
    # .so mapped for its whole life. The build would report success and every
    # test would still measure the previous branch's code -- the same defect the
    # build guard exists to close, reintroduced by the order of two lines.
    #
    # It showed up as a flake: the first run after a source change failed to
    # start a cluster, and the next run passed because the install had already
    # landed.
    major = major_of(_pg_config(pg_config, "--version"))
    verdict = build_once(str(SRCDIR), pg_config, major)

    cluster, root = make_cluster(pg_config, worker_id)
    print(f"\n-- build: {verdict} from {SRCDIR}")
    # Printed for the same reason lib.sh prints it: so a reader can tell which
    # binary produced the results below.
    print(f"-- cluster: worker={worker_id} port={cluster.port} "
          f"{cluster.version} .so={cluster.so_md5()}")
    # And the running server is the one that loaded THAT library. @jdatcmd noted
    # a start-time check would be near-vacuous because the cluster is initdb'd
    # fresh each session, so the postmaster always starts after the .so. That is
    # true once the order above is right, and it is exactly what pins the order:
    # with the build after the start, the .so is NEWER than the postmaster and
    # this refuses.
    cluster.require_server_loaded_this_binary()
    try:
        with psycopg.connect(cluster.dsn(), autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pgcolumnar")
        yield cluster
    finally:
        cluster.stop()
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def pgc_conn(pgc_cluster, request):
    """A direct connection, in a schema private to this one test.

    A private schema rather than a private database: isolation without paying an
    initdb per test. It is first on the search_path, so an unqualified CREATE TABLE
    lands in it and cannot collide with another test's fixture.

    autocommit is ON deliberately. With it off, a fixture that forgets to commit
    leaves the next connection looking at an absent table, which is measured in the
    design document as a way to make a test assert nothing.
    """
    schema = "pgc_test_" + "".join(
        ch if ch.isalnum() else "_" for ch in request.node.name
    )[:48]
    conn = psycopg.connect(pgc_cluster.dsn(), autocommit=True)
    try:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}", public')
        yield conn
    finally:
        try:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            conn.close()
