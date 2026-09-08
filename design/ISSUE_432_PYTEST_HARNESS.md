# Issue 432: a pytest harness, and the vacuity guard it must carry

## Who this is for

A developer adding or porting a pgColumnar test. It assumes you can read Python and
SQL, that you have used pytest, and that you have run `test/run_all_versions.sh`
at least once. It does not assume you know the bash harness internals.

## What this document decides

Issue #432 asks whether to move the test suite from bash to pytest. This is the
plan for doing it, and the answer to the question the discussion on that issue
left open: what a port must carry across so it does not lose coverage it cannot
see it has lost.

**The port is not the hard part. The vacuity guard is.**

A vacuity defect is a test that reports PASS while asserting nothing. The bash
harness has been bitten by this and now defends against it in several places. Bare
pytest defends against it nowhere. Section 4 measures that, and section 5 is the
layer that fixes it.

## 1. Scope

In scope for the first landing:

- A pytest harness that talks to the server over a direct connection.
- Tests that run in parallel.
- The vacuity-refusal layer, with its own tests.
- Two ported suites, running beside their bash originals, not replacing them.
- A differential check that the port asserts the same thing as the original.

Out of scope, deliberately:

- Porting the other 254 suites. Nothing is deleted in this landing.
- Replacing `test/run_all_versions.sh`. It stays the gate.
- Porting any suite that starts, kills or crashes a server.
- FreeBSD support. It is a reason to prefer Python, not a deliverable here.

## 2. Prerequisites, measured

The container had none of the tooling. This is what it took.

`pytest`, `pytest-xdist`, `psycopg` and `psycopg2` were all absent. Python is
3.14.4 and is marked `EXTERNALLY-MANAGED`, so `pip install` into the system
interpreter is refused. `python3 -m venv` failed too, because `ensurepip` is not
in the base image.

The working sequence:

```sh
apt-get install -y python3.14-venv
python3 -m venv /root/pyenv
/root/pyenv/bin/pip install pytest pytest-xdist 'psycopg[binary]'
```

That produced pytest 9.1.1, pytest-xdist 3.8.0 and psycopg 3.3.5 against libpq
18.0.6, using the binary build so nothing compiles.

Distribution packages are an alternative: `python3-psycopg` 3.3.2,
`python3-pytest` 9.0.2, `python3-pytest-xdist` 3.8.0. The venv is preferred
because it pins versions, and CI must install from a checked-in requirements file
rather than from whatever the runner happens to carry.

`test/` already holds 13 Python files. **None of them connect to PostgreSQL.**
They generate corpora and check documents. So there is no direct-connection
precedent in this tree, and this work sets it.

## 3. Direct connections, and the short list of exceptions

The requirement is a direct connection and typed results. Shelling out to `psql`
and reading its text is allowed only where nothing else works.

Measured against a live cluster, psycopg returns real Python types:

| SQL | Python value | type |
|---|---|---|
| `count(*)` | `100` | `int` |
| `1.5::numeric` | `Decimal('1.5')` | `Decimal` |
| `1.5::float8` | `1.5` | `float` |
| `NULL::int` | `None` | `NoneType` |
| `'\x00ff'::bytea` | `b'\x00\xff'` | `bytes` |
| `ARRAY[1,2]` | `[1, 2]` | `list` |

`psql -At` returns the string `100` for the first row and leaves every conversion
to the reader. That difference is the point of the change.

Operations that must still run a binary, with the reason:

| operation | why a connection cannot do it |
|---|---|
| `initdb` | creates the cluster a connection would connect to |
| `pg_ctl start` / `stop` | starts and stops the server itself |
| `pg_dump`, `pg_restore`, `pg_dumpall` | client programs; no libpq call performs a dump |
| `pg_upgrade`, `pg_basebackup` | same, and both operate on files not sessions |
| `make`, `make install` | builds the extension under test |

Things that look like exceptions and are not:

- **Terminating a backend.** Use `pg_terminate_backend`, which is SQL. Killing a
  `psql` process leaves the backend running its statement, which has already
  produced one false removal proof in this project.
- **COPY.** psycopg supports `COPY` directly, both directions.
- **A torn connection.** Close the socket from Python.
- **Reading a plan.** `EXPLAIN (FORMAT JSON)` comes back as parsed Python.

## 4. What bare pytest does with a test that asserts nothing

Every row below was run. The exit code is the one pytest returned.

| what the test does | pytest reports | exit |
|---|---|---|
| no `assert` anywhere in the body | 1 passed | **0** |
| `assert got == want`, both empty strings | 2 passed | **0** |
| `parametrize` over an empty list | 1 skipped | **0** |
| every test skipped | 2 skipped | **0** |
| `xfail` that unexpectedly passes, non-strict | 1 xfailed, 1 xpassed | **0** |
| `return got == want` instead of asserting | 1 passed, 1 warning | **0** |
| `pytest.raises(Exception)` satisfied by an unrelated error | 1 passed | **0** |
| `assert "ColumnarScan" in plan` where the plan says `PgColumnarScan` | 1 passed | **0** |

Four behaviours are already safe: a fixture raising in teardown exits 1, `-k`
filtering everything out exits 5, collecting no tests exits 5, and an xdist worker
crash exits 1.

**Eight ways to report success while asserting nothing, all exiting 0.** That is
the gap this design exists to close. Exit 5 also matters: it means "no tests ran",
and a CI step written as `pytest || exit 1` treats it as failure only by accident
of the shell, while many wrappers treat any non-1 code as fine.

## 5. The vacuity-refusal layer

Each refusal is structural. A convention a reviewer is asked to remember is not a
refusal.

### 5.1 A test must make at least one counted assertion

A conftest plugin counts assertions per test and fails a test that made none. The
count comes from the assertion helpers in 5.2, not from Python's `assert`, so a
test that computes and concludes nothing cannot pass.

This one mechanism also kills the `return`-instead-of-assert mode, because a
returning test makes no counted assertion either.

### 5.2 Comparisons refuse degenerate inputs

The helpers mirror the bash harness, which added them for issue #418 after
"empty compared with empty" printed PASS.

- `expect_num(got, want, name)` requires both sides to be numbers.
- `expect_rows(got, want, name)` refuses two empty results unless the test says
  `allow_empty=True` and gives a reason.
- `expect_hash(got, want, name)` refuses two equal hashes that are the error
  sentinel, and refuses comparing a value against itself.
- `expect_text(got, want, name)` requires a non-empty expectation.

The bash `check_num` already refuses two identical md5 hashes. That rule ports
directly.

### 5.3 A failed query can never compare equal to another failed query

`pgc_set_hash` returns `QUERY_ERROR.<seq>`, a different value each time, so two
broken queries never match. The Python layer keeps that idea but does better:
psycopg raises. Measured, a query against a missing table raises `UndefinedTable`
rather than returning an empty result.

The risk moves rather than disappearing. After any failed statement, every later
statement on that connection raises `InFailedSqlTransaction` until rollback. So
one broad `except` around a test body swallows the real error and every error
after it. **The layer therefore forbids bare `except Exception` in test code**, and
a lint rule enforces it. Where a test must catch, it catches the specific class.

### 5.4 Plan assertions read a typed field, never a substring

Measured on a columnar scan:

```
Node Type='Aggregate'      Custom Plan Provider=None
  Node Type='Custom Scan'  Custom Plan Provider='PgColumnarScan'
```

`EXPLAIN (FORMAT JSON)` arrives as a parsed Python list. The assertion is exact
equality on `Custom Plan Provider`. A superstring cannot satisfy it. Note that the
provider name really is `PgColumnarScan`, which is the string that made
`grep ColumnarScan` unfalsifiable in the first place.

The helper `expect_plan_node(plan, node_type=..., provider=...)` walks the tree and
refuses a substring argument.

### 5.5 A skip must be declared, and a silent skip fails the run

Skips are allowed only through `pgc_unrunnable(reason)`, which takes a reason from
a closed list, the same list the bash harness uses. The run then exits non-zero
unless the caller passed an explicit allowance. A bare `pytest.mark.skip` is
rejected by the plugin.

`xfail` is configured strict by default, so an unexpected pass fails.

### 5.6 The run asserts its own shape

The harness records the number of tests it expects to collect. The CI step
compares collected against expected and fails on any difference, so a filtered,
truncated or empty run cannot be green. Exit code 5 is mapped to failure
explicitly. This mirrors `pgc_summary`, which reconciles passed plus failed plus
unrunnable against the total and fails when the arithmetic does not close.

### 5.7 The binary under test is fingerprinted

A session fixture records the `.so` md5 and the server's
`pg_postmaster_start_time()`, and fails if the library is older than the running
server. This is the bash `pgc_so_line` guard, which exists because a suite once
reported a full pass against a previously installed library.

## 6. Fixtures and parallelism

One cluster per xdist worker, created once per session and owned exclusively by
that worker. Each test gets its own schema inside that cluster, so tests are
isolated without paying for a cluster each.

Why not one shared cluster: two workers installing the extension into one
`pkglibdir` race, and the bash harness has already been bitten by a port collision
that read like a real failure.

Worker count is capped. The machine has 8 cores shared with a desktop, and the
bash matrix already runs 6 suites at once. The default is 4, overridable, and
never `-n auto`.

Ports come from the same band the bash harness uses, below the ephemeral floor,
derived from the worker id rather than picked at random.

## 7. Proving the port against the bash harness

A port that agrees with the original on green proves little. It has to agree on
red as well.

For each ported suite:

1. Run the bash suite. Record every check name and outcome.
2. Run the pytest port. Record every test name and outcome.
3. Compare property by property. A property in one and not the other is a defect
   in the port, not a difference of style.
4. Apply a mutation to the extension that the property is meant to catch.
5. **Both harnesses must go red.** If the bash suite reddens and the port does
   not, the port is not asserting the property. If neither reddens, the property
   was never covered and the mutation is the wrong one.

Step 5 is the check that matters. It is the only one that can tell a real
assertion from a vacuous one.

## 8. The order of work

Each step names the test that must fail first, and why it fails before the code
exists.

| # | test | fails before, because |
|---|---|---|
| 1 | `test_layer_rejects_a_test_with_no_assertion` | no plugin exists, so the empty test passes |
| 2 | `test_layer_rejects_two_empty_results` | `expect_rows` does not exist |
| 3 | `test_layer_rejects_a_self_comparison` | `expect_hash` does not exist |
| 4 | `test_layer_rejects_a_substring_plan_match` | `expect_plan_node` does not exist |
| 5 | `test_layer_rejects_a_bare_skip` | bare skip currently exits 0 |
| 6 | `test_layer_fails_on_a_collected_count_mismatch` | nothing records an expected count |
| 7 | `test_layer_fails_on_a_stale_library` | no fingerprint fixture exists |
| 8 | `test_cluster_fixture_gives_a_typed_connection` | no fixture exists |
| 9 | `test_two_workers_get_different_clusters` | no per-worker cluster exists |
| 10 | the first ported suite, property by property | the port does not exist |
| 11 | the differential, including the mutation arm | nothing compares the two harnesses |

Tests 1 to 7 are the layer testing itself. They come first because a harness that
can report a false green makes every later result worthless.

## 8a. What is built, and what it measured

All of section 8 is implemented and green. The numbers below are runs, not estimates.

```
test/pytest/  24 tests   serial: 24 passed    xdist -n 4: 24 passed
```

Seventeen of those tests are the layer testing itself. They run pytest inside
pytest through the `pytester` fixture, so each guard is proven to REFUSE rather
than assumed to. The layer's own tests obey the layer: they use the same recorder
every other test uses, because an exemption for the tests that prove the guard is
the first step to exempting everything else.

### The differential, both arms

`test/native_projection.sh` and its port `test/pytest/test_native_projection.py`,
each arm building and installing once so both harnesses measure the SAME library:

```
ARM A unmutated          .so 8370e9b1beba   bash 8 passed 0 failed   pytest 7 passed 0 failed
ARM B fan-out neutered   .so 9e9510593777   bash 0 passed 8 failed   pytest 7 passed... 0, 7 failed
```

The mutation makes `PgColumnarProjectionFanoutRow` return without writing. Both
harnesses go red together, and the arm records the `.so` md5 each harness measured
so an arm where they differ is marked void rather than reported.

### Property by property, by name

`test/pytest/compare_to_bash.py` extracts the check names from the bash suite and
the assertion names from the port, and diffs the two sets:

```
bash checks: 8 (8 distinct)
pytest named assertions: 9 (9 distinct)
PROPERTIES IN THE BASH SUITE AND NOT IN THE PORT: none
ASSERTIONS IN THE PORT AND NOT IN THE BASH SUITE: premise: the DELETE removed rows
```

Names, not counts. The bash suite has 8 checks and the port has 7 tests, because
one test carries two of the bash assertions. A count comparison calls that a
defect. A name comparison does not, and it still catches a property asserted in one
harness and nowhere in the other.

The extra assertion is an improvement the port makes: the bash suite deletes rows
and then compares the projection against the base, without first checking that the
DELETE removed anything. If it removed nothing, both arms are satisfied by a
projection that never changed.

### The leak, measured

After two gate matrix runs this container held **four** orphaned postmasters from
`/tmp/pgcolumnar-test.*` datadirs, aged 18 to 35 minutes, still running after their
runs had finished. The pytest harness left **zero**: no listeners on its port band,
no cluster directories, no postmasters.

That was measured by walking `/proc/<pid>/cmdline` for every postgres process. A
first attempt used `ps | grep`, which reported a leak that was the grep's own
enclosing command line. The bracket trick protects the pattern, not the command
line that contains it.

### Three instrument defects found while building this

Recorded because they are the same class the layer exists to prevent, and all three
produced a confident wrong number before they were caught.

1. A red test failed on `ImportError` rather than on the guard's absence. The
   module had to exist and simply not guard yet, or the test proved only that a
   file was missing.
2. The differential piped its output through `head`, which truncated the summary
   line. The result was unknown while the report looked complete.
3. A `grep -c " PASSED"` counted 6 of 7 tests, because the first test's outcome
   shares a line with a fixture's print. This is why the property comparison reads
   names.

A fourth, in the same family: after the mutation arm, `git checkout` restored the
source but nothing rebuilt, so the next run tested the MUTATED library against
clean sources. The harness prints its `.so` fingerprint on every run, which is the
only reason it was visible.

## 9. Verification

| phase | proven done by |
|---|---|
| prerequisites | a requirements file, and CI installing from it |
| the layer | tests 1 to 7 red, then green, with the red output recorded |
| fixtures | tests 8 and 9, plus two workers running concurrently |
| the first port | property-by-property agreement with the bash suite |
| the differential | one mutation reddening both harnesses |
| the landing | the bash matrix still green, and the pytest run green, both in CI |

## 10. What this layer still cannot catch

Stated plainly, because a guard that claims to catch everything is the defect it
is meant to prevent.

- A test that asserts a true and irrelevant property. Counting assertions cannot
  tell whether the assertion is about the thing under test.
- A fixture that builds the wrong situation. If the fixture writes 100 rows to the
  wrong table, every assertion about that table is sound and meaningless.
- A mutation that changes nothing observable. The differential in section 7 needs
  a mutation the property can see, and choosing it is human work.
- A GUC set but a code path never engaged. The bash harness has been bitten here
  and the fix was a positive marker, not a language change.
- Agreement between two harnesses that share a wrong assumption.

The layer removes a class of accident. It does not remove the need to ask what a
test would have to see in order to fail.
