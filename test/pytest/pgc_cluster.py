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
import importlib.util
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

    def server_binary_verdict(self, so_mtime, postmaster_epoch):
        """fresh | predates | unknown, from two epochs.

        Pure, so it is driven without a server. `predates` means the postmaster
        started BEFORE the library on disk was written, so the backends are
        executing older code than the file -- shared_preload_libraries maps the
        library at start and a reinstall does not reload it.
        """
        try:
            so, pm = float(so_mtime), float(postmaster_epoch)
        except (TypeError, ValueError):
            return "unknown"
        return "predates" if so > pm else "fresh"

    def require_server_loaded_this_binary(self):
        """Refuse if the running server predates the installed library."""
        try:
            so_mtime = os.stat(self.so_path).st_mtime
        except OSError:
            so_mtime = None
        pm = None
        try:
            import psycopg
            with psycopg.connect(self.dsn(), autocommit=True) as conn:
                row = conn.execute(
                    "SELECT extract(epoch from pg_postmaster_start_time())"
                ).fetchone()
                pm = row[0] if row else None
        except Exception:
            pm = None
        verdict = self.server_binary_verdict(so_mtime, pm)
        if verdict == "predates":
            raise RuntimeError(
                f"this server started before {self.so_path} was installed, so its "
                f"backends are running older code than the file on disk. "
                f"shared_preload_libraries maps the library at start; a reinstall "
                f"does not reload it."
            )
        return verdict

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


# BOTH OF THESE NOW DELEGATE TO test/pgc_fingerprint.py.
#
# They used to be an independent implementation of what test/lib.sh does, and the
# pair produced four defects in one day -- two here, two there, and not one found
# by whoever wrote that copy (#907):
#
#     objstore/*.c never walked            here     found by @linuxhikerpm
#     the bare NAME instead of the path    here     found while fixing the above
#     `xargs -0 cat | md5sum`, no bounds   lib.sh   found by @linuxhikerpm
#     each build dir's Makefile omitted    here     found while writing the twin
#
# The docstring here asserted "the same input set as pgc_source_fingerprint in
# test/lib.sh" through all four. It was false when written and stayed false
# through two rounds of fixing, which is the case against a prose claim of
# agreement: it is not a mechanism, and it is worse than silence because it is
# exactly what stops the next person checking.
#
# Loaded BY PATH rather than by package import: test/ is not a package, and this
# module is imported by pytest from test/pytest/ while lib.sh runs it as a script
# from test/. Neither should have to know about the other's layout.
_FP_PATH = pathlib.Path(__file__).resolve().parent.parent / "pgc_fingerprint.py"
_fp_spec = importlib.util.spec_from_file_location("pgc_fingerprint", _FP_PATH)
_fp = importlib.util.module_from_spec(_fp_spec)
_fp_spec.loader.exec_module(_fp)


def source_build_dirs(srcdir):
    """Every directory the build compiles in: src/, plus any with its own Makefile.

    DERIVED, NOT LISTED. Naming objstore/ would fix today and fail the next time a
    module is added; a directory carrying its own Makefile is what the top-level
    Makefile recurses into, so that is the property to read.
    """
    return _fp.build_dirs(srcdir)


def source_fingerprint(srcdir):
    """A hash of everything a build reads, or None if it could not be computed.

    None rather than "" because that is the contract this harness already had, and
    build_once distinguishes "no fingerprint" from a real one. The module returns
    "" for the same condition; the mapping happens here rather than there so the
    shell and Python callers each get the shape they already expect.
    """
    return _fp.fingerprint(srcdir) or None


def source_manifest(srcdir):
    """Every file the fingerprint hashes, one "relpath digest" per line.

    THE SAME TEXT test/lib.sh's `pgc_source_manifest` prints, because both are the
    same call into test/pgc_fingerprint.py. A caller comparing the two is therefore
    comparing one implementation with itself rather than two that can drift.

    None, not "", when a file could not be read -- the module's contract, and
    deliberate: a digest that FAILED must not look like one that succeeded. lib.sh's
    wrapper substitutes a sentinel line there instead, which is the WRAPPER's
    behaviour and not the module's, so a test of that belongs to the shell harness.

    I wrote this as a join over (relpath, digest) pairs first. `manifest()` returns the
    joined TEXT, and my probe had an `isinstance` fallback that quietly stringified it
    and then reported the two "identical" -- so the wrong assumption read as verified
    until the real call raised.
    """
    return _fp.manifest(srcdir)


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
    """Create and start a cluster for one worker. The caller stops it.

    THIS FUNCTION OWNS THE TREE UNTIL IT SUCCESSFULLY RETURNS. It did not, and
    the failure mode is the one that matters least when things work and most
    when they do not (@linuxhikerpm, #897 review): `root` came from `mkdtemp`
    and then `Cluster()`, `initdb()`, `start()` and `is_ours()` ran with no
    cleanup guard --

        make_cluster_error=RuntimeError
        new_roots=1 leaked=['/tmp/pgc-pytest-777-h3phhtxc']

    -- and conftest.py cannot clean up after it, because the tuple assignment
    `cluster, root = make_cluster(...)` never completes when the call raises.
    The handled is_ours() path leaked too: it stopped the cluster and left the
    directory.

    So every exit that is not a successful return stops whatever was started and
    removes the tree. A partially started cluster is stopped with `-m immediate`
    inside `stop()`; failing to stop it must not mask the original error, so the
    cleanup is itself guarded.
    """
    slot = 0 if worker_id in (None, "master") else int(str(worker_id).lstrip("gw") or 0)
    port = pick_port(slot)
    root = pathlib.Path(tempfile.mkdtemp(prefix=f"pgc-pytest-{slot}-"))
    cluster = None
    try:
        os.chmod(root, 0o777)
        datadir = root / "data"
        datadir.mkdir()
        cluster = Cluster(pg_config, worker_id, datadir, port)
        cluster.initdb()
        cluster.start()
        if not cluster.is_ours():
            raise RuntimeError(
                f"the server on port {port} is not ours: its data_directory "
                f"differs from {datadir}. Refusing to test against a foreign "
                f"cluster."
            )
        return cluster, root
    except BaseException:
        # BaseException, not Exception: a KeyboardInterrupt during initdb leaks
        # a datadir and a possibly-running postmaster exactly like an error does.
        if cluster is not None:
            try:
                cluster.stop()
            except Exception:
                pass
        shutil.rmtree(root, ignore_errors=True)
        raise
