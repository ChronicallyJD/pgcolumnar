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

import fcntl
import hashlib
import os
import re
import pathlib
import shutil
import socket
import subprocess
import tempfile

# THE OLD CONSTANT HERE WAS 54600, AND BOTH HALVES OF ITS COMMENT WERE FALSE
# (@jdatcmd, #897 review). It claimed to sit below the ephemeral floor and to
# match the bash harness. Measured: /proc/sys/net/ipv4/ip_local_port_range is
# `32768 60999`, so 54600 is INSIDE the ephemeral range, and test/portlib.sh's
# bands are MAIN [10000, 29568) and AUX [29768, 31768) -- nowhere near. The
# kernel handed out 54600, 54602, 54604 and 54606 during a 6000-connection
# probe, 54600 being the master worker's port, while the bash MAIN band took 0
# of 6000. It cost me cluster start failures in this very session before the
# review arrived.
#
# The floor is READ, not assumed, and the band arithmetic is portlib.sh's own so
# the two harnesses cannot drift apart again.
DEFAULT_EPHEMERAL_FLOOR = 32768
MIN_FLOOR = 20000


def ephemeral_floor(range_text):
    """The kernel's lowest ephemeral port, from ip_local_port_range's contents.

    Falls back to the documented default rather than guessing when the file is
    unreadable or malformed, and never returns something so low that the bands
    below it collapse.
    """
    try:
        low = int(str(range_text).split()[0])
    except (ValueError, IndexError, AttributeError):
        return DEFAULT_EPHEMERAL_FLOOR
    return low if low >= MIN_FLOOR else DEFAULT_EPHEMERAL_FLOOR


def read_ephemeral_floor(path="/proc/sys/net/ipv4/ip_local_port_range"):
    try:
        return ephemeral_floor(pathlib.Path(path).read_text())
    except OSError:
        return DEFAULT_EPHEMERAL_FLOOR


def aux_band(floor):
    """test/portlib.sh's AUX band, by its own arithmetic.

        PGC_AUX_PORT_HI = floor - 1000
        PGC_AUX_PORT_LO = AUX_HI - 2000

    AUX rather than MAIN because AUX is for "extra clusters a single suite
    stands up beyond its own", which is what an xdist worker is, and because the
    matrix walks MAIN.
    """
    hi = floor - 1000
    return hi - 2000, hi


def port_is_free(port, host="127.0.0.1"):
    """Bind-test. A band is an argument about probability; a bind is a fact."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(slot, floor=None, is_free=port_is_free):
    """A free port in the AUX band for this worker slot.

    Walks on collision instead of trusting the band, because the band only makes
    a collision unlikely and this harness has already been broken once by a port
    that something else was holding.
    """
    lo, hi = aux_band(floor if floor is not None else read_ephemeral_floor())
    span = hi - lo
    start = slot * 2
    for step in range(span):
        port = lo + ((start + step) % span)
        if is_free(port):
            return port
    raise RuntimeError(
        f"no free port in the AUX band [{lo}, {hi}) for worker slot {slot}")


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
        self.sharedir = _pg_config(pg_config, "--sharedir")
        self._started = False

    # -- is the installed extension the one this checkout describes? -------
    @property
    def extension_dir(self):
        return os.path.join(self.sharedir, "extension")

    def _read(self, path):
        try:
            return pathlib.Path(path).read_text()
        except OSError:
            return None

    def install_freshness(self):
        """(verdict, source version, installed version) for the prefix in use.

        The harness does not build. It runs against whatever is already in the
        prefix, which is what makes not-rebuilding-per-test possible and is also
        how a corpus ends up measuring another branch's extension.
        """
        srcdir = pathlib.Path(__file__).resolve().parents[2]
        src_ctl = self._read(srcdir / "pgcolumnar.control")
        inst_ctl = self._read(os.path.join(self.extension_dir, "pgcolumnar.control"))
        src_v = control_default_version(src_ctl)
        inst_v = control_default_version(inst_ctl)

        src_sql = self._read(srcdir / f"pgcolumnar--{src_v}.sql") if src_v else None
        inst_sql = (self._read(os.path.join(self.extension_dir,
                                            f"pgcolumnar--{inst_v}.sql"))
                    if inst_v else None)
        return install_verdict(src_v, inst_v, src_sql, inst_sql), src_v, inst_v

    def require_fresh_install(self):
        """Refuse to run against an extension this checkout did not produce.

        Raises rather than skips. A skip here would green the whole corpus, and
        "the extension was from another branch" is the one thing a skip must
        never be allowed to say quietly.

        `unknown` does NOT raise: someone who installed by hand has no readable
        pair to compare, and refusing would break a documented workflow. It says
        which question went unanswered instead of printing nothing.
        """
        verdict, src_v, inst_v = self.install_freshness()
        if verdict == "stale":
            raise RuntimeError(
                "the installed pgcolumnar was not built from this source: "
                f"this checkout declares {src_v!r}, {self.extension_dir} holds "
                f"{inst_v!r}"
                + (" (same version, different base script)"
                   if src_v == inst_v else "")
                + ". Rebuild and reinstall before running the corpus; every "
                  "test below would otherwise report on code this tree does "
                  "not contain."
            )
        if verdict == "unknown":
            print(f"-- install freshness UNVERIFIED (source {src_v!r}, "
                  f"installed {inst_v!r})")
        return verdict

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


_DEFAULT_VERSION_RE = re.compile(
    r"""^\s*default_version\s*=\s*['"]([^'"]+)['"]""", re.MULTILINE)


def control_default_version(text):
    """The default_version a .control file declares, or None.

    None rather than "" for absent, so a caller cannot confuse "no version
    here" with "a version that is the empty string".
    """
    if not text:
        return None
    m = _DEFAULT_VERSION_RE.search(text)
    return m.group(1) if m else None


def install_verdict(src_version, installed_version, src_sql, installed_sql):
    """Did the installed extension come from this source tree?

    A pure function of four strings, so it is driven directly by
    test_install_freshness.py without a cluster -- the same shape test/lib.sh
    uses for its own freshness verdicts.

    Exactly three values, and a caller's `if verdict == "stale"` depends on
    that: "fresh", "stale", "unknown".

    UNKNOWN IS NOT FRESH. If either side is unreadable the honest answer is
    that the question was not answered. Returning "fresh" there would certify
    every run the harness failed to check, which is the failure this guard
    exists to stop.

    The version alone is not enough. A release cycle is long and the base
    install script changes inside it, so two builds can share a version and
    differ. The script is compared as well, which is why the second arm of
    test_same_version_but_a_different_script_is_stale exists.
    """
    if not src_version or not installed_version:
        return "unknown"
    if src_version != installed_version:
        return "stale"
    if not src_sql or not installed_sql:
        return "unknown"
    return "fresh" if src_sql == installed_sql else "stale"


def build_and_install(srcdir, pg_config, major, runner=None):
    """Build and install the extension, or raise.

    Drives `pgc_build_and_install` out of test/lib.sh rather than carrying a
    second implementation. The bash harness has refused to report checks against
    a previously installed library since #536; this harness did not, and reported
    25 passed against source carrying `#error THIS SOURCE IS BROKEN AND CANNOT
    BUILD` (@jdatcmd, #897 review). Two implementations of "is the thing under
    test the thing in this tree" would drift, and that drift would be invisible
    in exactly the way that defect was.

    RAISES rather than skips. A skip greens the corpus, and "the source does not
    compile" is the last thing that may be said quietly.
    """
    srcdir = str(srcdir)
    script = (
        f'. "{srcdir}/test/lib.sh" || exit 1; '
        f'pgc_build_and_install "{srcdir}" "{pg_config}" "{major}"'
    )
    run = runner or (lambda argv: subprocess.run(
        argv, capture_output=True, text=True))
    proc = run(["bash", "-c", script])
    if proc.returncode != 0:
        raise RuntimeError(
            f"pgcolumnar failed to build or install from {srcdir}; refusing to "
            f"report checks against whatever was installed before.\n"
            f"{(proc.stderr or '').strip()}\n{(proc.stdout or '').strip()}".strip()
        )


def source_fingerprint(srcdir):
    """A hash of everything a build reads, or None if the tree is unreadable.

    Same input set as pgc_source_fingerprint in test/lib.sh: the C sources and
    headers, the Makefile, the control file and the SQL scripts. Content, not
    mtime, because a checkout or a branch switch rewrites mtimes without
    changing what compiles, and `git stash` does the reverse.
    """
    srcdir = pathlib.Path(srcdir)
    paths = sorted(
        list((srcdir / "src").glob("*.c")) + list((srcdir / "src").glob("*.h"))
        + [p for p in (srcdir / "Makefile",) if p.exists()]
        + sorted(srcdir.glob("*.control")) + sorted(srcdir.glob("*.sql"))
    )
    if not paths:
        return None
    h = hashlib.md5()
    for path in paths:
        try:
            h.update(path.name.encode())
            h.update(path.read_bytes())
        except OSError:
            return None
    return h.hexdigest()[:12]


def build_once(srcdir, pg_config, major, lock_path=None, runner=None):
    """build_and_install, but at most once across xdist workers.

    pgc_cluster.py:6 gives the pkglibdir race as the reason this harness does not
    install. That is a reason to serialise the install, not to skip it: the
    workers share one prefix, so one of them builds under a lock and the rest
    wait and then find the marker.

    The marker records the pg_config and major, so a second run against a
    DIFFERENT prefix still builds -- keying it on "did anyone build" alone would
    reintroduce the defect for anyone who runs the corpus twice against two
    majors.
    """
    lock_path = lock_path or os.path.join(
        tempfile.gettempdir(), "pgc-pytest-build.lock")
    marker = lock_path + ".done"
    # THE FINGERPRINT IS PART OF THE KEY. Keying on pg_config and major alone
    # would skip the build after a source edit, which is the staleness this
    # whole guard exists to stop -- reintroduced by the optimisation meant to
    # make the guard cheap. A tree we cannot fingerprint gets a key that never
    # matches, so it always rebuilds.
    fp = source_fingerprint(srcdir)
    want = f"{pg_config}\n{major}\n{fp}\n" if fp else None
    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            try:
                if want is not None and pathlib.Path(marker).read_text() == want:
                    return "already-built"
            except OSError:
                pass
            build_and_install(srcdir, pg_config, major, runner=runner)
            if want is not None:
                pathlib.Path(marker).write_text(want)
            return "built"
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


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
    port = pick_port(slot)
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
