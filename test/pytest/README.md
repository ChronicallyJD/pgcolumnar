# Running the pytest harness

This is the issue #432 pilot. It runs beside `test/*.sh`, and replaces nothing.

- `TESTS.md` in this directory documents every test and every assertion helper.
- `VACUITY_MODES.md` is the inventory of ways a pytest harness can report a false
  pass: 79 modes, 73 demonstrated by a run, 23 refused by this layer today.
- `design/ISSUE_432_PYTEST_HARNESS.md` holds the design and the measurements
  behind each guard.

## Prerequisites

The interpreter is marked `EXTERNALLY-MANAGED`, so install into a virtual
environment rather than into system Python:

```sh
apt-get install -y python3.14-venv        # ensurepip is not in the base image
python3 -m venv /root/pyenv
/root/pyenv/bin/pip install -r test/pytest/requirements-test.txt
```

## Running it

```sh
cd test/pytest
PYTHONPATH=. /root/pyenv/bin/pytest                      # serial
PYTHONPATH=. /root/pyenv/bin/pytest -n 4                 # four workers
PYTHONPATH=. /root/pyenv/bin/pytest --pgc-expect-tests 24 # assert the run's shape
PGC_PG_CONFIG=/usr/local/pg19a/bin/pg_config PYTHONPATH=. /root/pyenv/bin/pytest
```

Each worker builds its own throwaway cluster on a port derived from its worker id,
and drops it at session end. Nothing survives a run.

## Checking a port against its bash original

```sh
/root/pyenv/bin/python test/pytest/compare_to_bash.py \
    test/native_projection.sh test/pytest/test_native_projection.py
```

It compares the two by assertion NAME and exits non-zero if the bash suite asserts
a property the port does not. A port keeps this working by passing each assertion
the same name string the bash check uses.

## This is not in the gate yet

`test/run_all_versions.sh` does not run these tests, and neither does CI. That is a
decision with a price, recorded in section 1a of the design document: `pgc_skip`
treats a missing dependency as a failure rather than a skip, so registering this run
in `SUITES` would redden every CI job until `ci.yml` installs from
`requirements-test.txt`. Until someone takes that decision, run it by hand.

## Warnings

The vacuity layer is loaded through `pytest.ini` and cannot be turned off by a test
file. A test that concludes nothing fails, a bare skip fails the run, and a
comparison that could not have failed is refused. If a guard blocks something
legitimate, the escape hatches take a reason rather than a flag, and every one of
them is listed in the design document. Adding a new escape hatch needs a red test
that proves the guard still fires without it.
