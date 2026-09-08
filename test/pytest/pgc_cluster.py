"""pgColumnar pytest harness: the cluster a worker owns, and the connection to it.

Design notes that are load-bearing, from design/ISSUE_432_PYTEST_HARNESS.md:

- ONE CLUSTER PER XDIST WORKER, not one shared and not one per test. Two workers
  installing the extension into a single pkglibdir race with each other, and a
  shared cluster lets one test see another's tables. A cluster per test would cost
  an initdb each.
- THE PORT IS DERIVED FROM THE WORKER ID, not picked at random, and sits below the
  ephemeral floor. The bash harness took a random port and then needed a retry,
  because two suites on one box start on the same port and the loser reports a wall
  of errors with no named check failing.
- initdb AND pg_ctl ARE BINARIES, so they are subprocesses. That is the whole
  psql-exception list for this file. Everything after the server is up goes over a
  libpq connection: no psql, no text parsing.
- THE SERVER RUNS AS postgres WHEN WE ARE ROOT. initdb and postgres refuse to run
  as root, so the harness uses runuser, exactly as lib.sh does.
"""

import os
import pathlib
import shutil
import subprocess
import tempfile

# Below the ephemeral floor so a test cluster cannot collide with a kernel-assigned
# port. The bash harness keeps to the same band.
PORT_BASE = 54600


class Cluster:
    """A throwaway cluster owned by one xdist worker."""

    def __init__(self, pg_config, worker_id, datadir, port):
        self.pg_config = pg_config
        self.worker_id = worker_id
        self.datadir = datadir
        self.port = port
        self.bindir = _pg_config(pg_config, "--bindir")
        self.version = _pg_config(pg_config, "--version")
        self.libdir = _pg_config(pg_config, "--pkglibdir")
        self._started = False

    # -- the dsn every test connects through -------------------------------
    def dsn(self, dbname="postgres"):
        return f"host=127.0.0.1 port={self.port} user=postgres dbname={dbname}"

    @property
    def so_path(self):
        return os.path.join(self.libdir, "pgcolumnar.so")

    def so_md5(self):
        """Fingerprint the library under test.

        lib.sh prints this on every run because a suite once reported a full pass
        against a previously installed library. The Python harness keeps it for the
        same reason.
        """
        out = _run(["md5sum", self.so_path])
        return out.split()[0][:12]

    # -- lifecycle, the only place a binary is invoked ---------------------
    def initdb(self):
        _asroot(["initdb", "-D", str(self.datadir), "-A", "trust", "-U", "postgres"],
                self.bindir, self.datadir)
        conf = self.datadir / "postgresql.conf"
        with open(conf, "a") as fh:
            fh.write(
                "\n".join(
                    [
                        "",
                        f"port={self.port}",
                        "listen_addresses='127.0.0.1'",
                        "shared_preload_libraries='pgcolumnar'",
                        # Deterministic output so a hash oracle means the same thing
                        # on every machine. lib.sh sets the same three.
                        "extra_float_digits=3",
                        "timezone='UTC'",
                        "lc_messages='C'",
                        # A test that hangs should fail, not wedge the run.
                        "statement_timeout='120s'",
                        "log_min_messages=warning",
                        "",
                    ]
                )
            )

    def start(self):
        _asroot(["pg_ctl", "-D", str(self.datadir), "-l",
                 str(self.datadir / "server.log"), "-w", "start"],
                self.bindir, self.datadir)
        self._started = True

    def stop(self):
        if not self._started:
            return
        _asroot(["pg_ctl", "-D", str(self.datadir), "-m", "immediate", "-w", "stop"],
                self.bindir, self.datadir, check=False)
        self._started = False

    def is_ours(self):
        """Does the server on our port run from OUR datadir?

        lib.sh asks this because `pg_ctl -w` proves only that SOMETHING answers on
        the port. A foreign cluster answering would let every later check run
        against the wrong server.
        """
        import psycopg

        with psycopg.connect(self.dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute("SHOW data_directory")
                live = pathlib.Path(cur.fetchone()[0]).resolve()
        return live == self.datadir.resolve()


def _pg_config(pg_config, flag):
    return _run([pg_config, flag]).strip()


def _run(argv, check=True):
    proc = subprocess.run(argv, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{argv!r} failed rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout


def _asroot(argv, bindir, datadir, check=True):
    """Run a server binary, dropping to postgres when we are root.

    initdb, pg_ctl and postgres all refuse to run as root. lib.sh uses runuser for
    the same reason, and the datadir has to be owned by postgres before they run.
    """
    exe = os.path.join(bindir, argv[0])
    cmd = [exe] + argv[1:]
    if os.geteuid() == 0:
        shutil.chown(datadir, user="postgres")
        for path in datadir.rglob("*"):
            shutil.chown(path, user="postgres")
        cmd = ["runuser", "-u", "postgres", "--"] + cmd
    return _run(cmd, check=check)


def make_cluster(pg_config, worker_id):
    """Create and start a cluster for one worker. The caller stops it."""
    slot = 0 if worker_id in (None, "master") else int(str(worker_id).lstrip("gw") or 0)
    port = PORT_BASE + slot
    root = pathlib.Path(tempfile.mkdtemp(prefix=f"pgc-pytest-{slot}-"))
    os.chmod(root, 0o777)
    datadir = root / "data"
    datadir.mkdir()
    cluster = Cluster(pg_config, worker_id, datadir, port)
    cluster.initdb()
    cluster.start()
    if not cluster.is_ours():
        cluster.stop()
        raise RuntimeError(
            f"the server on port {port} is not ours: its data_directory differs "
            f"from {datadir}. Refusing to test against a foreign cluster."
        )
    return cluster, root
