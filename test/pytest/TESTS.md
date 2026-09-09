# The pytest corpus: what each test asserts, and why it exists

Reference for anyone reading, running, or adding to `test/pytest/`. The design and
the decisions behind the harness are in `design/ISSUE_432_PYTEST_HARNESS.md`. This
file covers the tests themselves.

Twenty-five tests in three files. Ten of them test the harness rather than the
product, and they come first, because a harness that can report a false green makes
every other result in this directory worthless.

Every measured fact quoted below was run. Where a test encodes a number or a
behaviour, the source of that number is named.

## Contents

- [1. How to read a test in here](#1-how-to-read-a-test-in-here)
- [2. The assertion vocabulary](#2-the-assertion-vocabulary)
- [3. test_layer.py: the guards, testing themselves](#3-test_layerpy-the-guards-testing-themselves)
- [4. test_connection.py: the cluster and the direct connection](#4-test_connectionpy-the-cluster-and-the-direct-connection)
- [5. test_native_projection.py: the ported suite](#5-test_native_projectionpy-the-ported-suite)
- [6. Adding a test](#6-adding-a-test)
- [7. Traps this corpus records](#7-traps-this-corpus-records)

## 1. How to read a test in here

Three rules apply to every test, and they are enforced rather than requested.

**A test must make a counted assertion.** Counted means it went through the
`expect` fixture. A bare Python `assert` is allowed but does not satisfy the
requirement, so a body that computes and concludes nothing fails. This applies to
the tests that test the guards, too. An exemption there would be the first step to
exempting everything.

**Every assertion carries a name.** The name is the first thing a reader sees in a
failure, and for a ported test it is the same string the bash check uses, which is
what lets `compare_to_bash.py` diff the two suites by property.

**A premise gets its own assertion.** If a test deletes rows and then compares two
things, it asserts that the delete removed something first. Otherwise both
comparisons are satisfied by a table that never changed.

## 2. The assertion vocabulary

All of these live on the `expect` fixture, in `pgc_vacuity.py`. Each refuses its own
degenerate cases, and refusing raises `VacuityError` rather than failing an
assertion, so the two read differently in output.

| helper | asserts | refuses |
| --- | --- | --- |
| `num(got, want, name)` | two numbers are equal | anything that is not a number, including `bool`, and including the string `"100"` that `psql -At` would have given |
| `at_least(got, floor, name)` | `got >= floor` | non-numbers, and a floor of zero or less, which any count satisfies |
| `rows(got, want, name, allow_empty=None)` | two result sets are equal | both sides empty, unless `allow_empty` gives a reason |
| `hash(got, want, name)` | two oracle hashes are equal | comparing an object against itself, either side being a `QUERY_ERROR` sentinel, both sides empty |
| `text(got, want, name)` | two strings are equal | an empty expectation, which anything empty satisfies |
| `plan_marker(plan, key, name, absent=False)` | some plan node carries a `Columnar` property key | nothing; `absent=True` inverts it |
| `plan_node(plan, node_type=, provider=)` | some node matches those fields exactly | being called with neither field, which would assert nothing |
| `outcomes(result, name, **want)` | an inner pytest run's outcomes | being called with no expectation |
| `run_failed(result, name)` | an inner run exited non-zero | nothing |
| `cannot_run(reason, detail)` | declares the test unrunnable | a reason outside the closed list |

`rows` compares row sets rather than `md5(string_agg(...))`. That asserts the same
property as the bash oracle by a stronger means: a hash mismatch says two hashes
differ, a row-set mismatch says which row. It also avoids recomputing the hash in
Python, where encoding or collation could make identical rows hash differently.

`UNRUNNABLE_REASONS` is the closed list `lib.sh` already uses:
`MISSING_DEPENDENCY`, `UNSUPPORTED_MAJOR`, `ABSENT_FIXTURE`,
`UNAVAILABLE_ENDPOINT`, `UNMET_PRECONDITION`.

## 3. test_layer.py: the guards, testing themselves

These ten run pytest inside pytest through the `pytester` fixture. Each writes a
small test file, runs it with the plugin loaded, and asserts on the INNER run's
outcome. That is what proves a guard REFUSES, rather than assuming it.

Each row names the measured bare-pytest behaviour the guard exists to stop. Every
one of those eight measurements exited 0.

| test | the guard | bare pytest, measured |
| --- | --- | --- |
| `test_layer_rejects_a_test_with_no_assertion` | a test that concludes nothing fails | `1 passed`, exit 0 |
| `test_a_counted_assertion_passes` | **positive control**: a real assertion still passes | — |
| `test_layer_rejects_two_empty_results` | empty compared with empty is refused | `2 passed`, exit 0 |
| `test_layer_allows_an_empty_result_when_declared` | **escape hatch**: an empty result with a reason passes | — |
| `test_layer_rejects_a_self_comparison` | a value compared against itself is refused | it cannot fail, so it passes |
| `test_layer_rejects_a_substring_plan_match` | a plan field is matched exactly, not by substring | `"ColumnarScan" in "…PgColumnarScan…"` passes |
| `test_layer_matches_the_exact_provider` | **positive control**: the real name matches | — |
| `test_layer_rejects_a_bare_skip` | a bare `@pytest.mark.skip` fails the run | `2 skipped`, exit 0 |
| `test_layer_fails_on_a_collected_count_mismatch` | a run that collects fewer tests than expected fails | a filtered run exits 5, widely treated as fine |
| `test_layer_refuses_a_zero_expectation` | `--pgc-expect-tests 0` is refused | it would be satisfied by collecting nothing |

Four of the ten are controls rather than guards. They are not decoration. A guard
with a bad false-positive rate gets switched off, and then the guard it replaced is
gone too. `test_a_counted_assertion_passes` and
`test_layer_matches_the_exact_provider` exist so that a guard which starts
rejecting good tests reddens here first.

The escape hatches are deliberately more expensive to type than the honest form.
`allow_empty` takes a reason, not `True`. `--pgc-expect-tests` takes the real
number. `cannot_run` takes a reason from a closed list. None of them can become the
default by being shorter.

## 4. test_connection.py: the cluster and the direct connection

| test | asserts |
| --- | --- |
| `test_cluster_fixture_gives_a_typed_connection` | `count(*)` arrives as a Python `int`, and its type is `int` |
| `test_the_extension_is_installed_and_columnar` | the fixture's cluster has `pgcolumnar` at the expected version |
| `test_a_columnar_table_round_trips_with_real_types` | `numeric` is `Decimal`, `float8` is `float`, `bytea` is `bytes`, an array is a `list` |
| `test_the_plan_shows_a_columnar_scan` | the plan arrives as parsed Python, and the scan ran |
| `test_the_provider_name_does_not_identify_a_scan` | **pins a trap**; see below |
| `test_each_test_gets_its_own_schema` | the schema is test-private and first on `search_path` |
| `test_the_worker_owns_its_own_cluster` | the port is the one derived from THIS worker's id |
| `test_the_cluster_refuses_a_foreign_server` | the identity check can return False |

Two of these deserve their reasoning stated.

**`test_the_worker_owns_its_own_cluster`** asserts `port == PORT_BASE + slot` for its
own worker, not merely that the port is an integer. The mapping from worker id to
port is injective, so if every worker's port matches its own id then no two workers
share one. Asserting "the port is an int" would have passed with every worker
sitting on 54600.

**`test_the_cluster_refuses_a_foreign_server`** points the identity check at a
datadir that is not ours and requires `False`. `pg_ctl -w` proves only that
SOMETHING answers on the port, and `lib.sh` added this check because a foreign
cluster answering would let every later assertion run against the wrong server. A
guard that has never returned False is not known to work.

### The trap that `test_the_provider_name_does_not_identify_a_scan` pins

Measured on 18.4. `Custom Plan Provider == "PgColumnarScan"` does **not** mean "a
columnar scan ran":

```
plain scan            'Custom Scan' provider='PgColumnarScan'  Columnar Projected Columns present
ungrouped vector agg  'Custom Scan' provider='PgColumnarScan'  Columnar Projected Columns ABSENT
grouped vector agg    'Custom Scan' provider='PgColumnarScan'  Columnar Projected Columns ABSENT
```

`columnar_vector.c:806` assigns the aggregate node `&pgcolumnar_scan_methods`, whose
`CustomName` is `PgColumnarScan` (`columnar_customscan.c:167`). So every pgcolumnar
node reports that provider. With the vectorized aggregate engaged the plan is a
single node and the aggregate has absorbed the scan, yet the provider still matches.

`pgc_is_columnar_scan` in `lib.sh` greps for `Columnar Projected Columns`, which is
emitted only by the scan's callback (`columnar_customscan.c:3631`) and never by
either aggregate callback. So the faithful port is `plan_marker`, and the provider
predicate answers a weaker question.

`PgColumnarAgg` never appears in a plan at all. It is the `CustomName` of a
`CustomPathMethods`, and EXPLAIN prints the scan methods' name.

This test asserts all three facts, so reverting to the provider predicate reddens
here rather than passing quietly. The first version of this harness used the
provider predicate and was wrong in exactly this way.

## 5. test_native_projection.py: the ported suite

A complete port of `test/native_projection.sh`, chosen because it is 55 lines, has 8
assertions, does no process work, and depends on nothing timing-related.

| bash check | pytest test |
| --- | --- |
| `fp fan-out matches base (a,c)` | `test_fp_fanout_matches_base` |
| `fq fan-out matches base (b)` | `test_fq_fanout_matches_base` |
| `fp row count matches base` | `test_fp_row_count_matches_base` |
| `fp storage is native` | `test_fp_storage_is_native` |
| `fp has zone maps (native skip metadata)` | `test_fp_has_zone_maps` |
| `fp reflects deletes (a,c)` | `test_fp_reflects_deletes` |
| `fp count after delete matches base` | `test_fp_reflects_deletes` |
| `fp spans multiple projection row groups` | `test_fp_spans_multiple_row_groups` |

Eight checks map to seven tests, because one test carries two of them. That is why
`compare_to_bash.py` compares names and not counts.

The port adds one assertion the original lacks: `premise: the DELETE removed rows`.
Without it, both delete arms are satisfied by a projection that never changed.

Two mechanical differences from the original, both deliberate:

- The fan-out comparisons compare row sets, not `md5(string_agg(...))`.
- `fp has zone maps` and `fp spans multiple row groups` stay numeric through
  `at_least`. The original turns each into the string `yes` or `no` via
  `[ "$(...)" -ge 1 ]`, which converts a number to text and then compares text. A
  non-number becomes `no` there and is refused here.

### How this port is proved

Running it green proves little on its own. It is proved by the differential:

```
ARM A unmutated          .so 8370e9b1beba   bash 8 passed 0 failed   pytest 7 passed 0 failed
ARM B fan-out neutered   .so 9e9510593777   bash 0 passed 8 failed   pytest 0 passed 7 failed
```

The mutation makes `PgColumnarProjectionFanoutRow` return without writing. Each arm
builds and installs once, and both harnesses print the `.so` md5 they measured, so
an arm where the two differ is void rather than reported.

## 6. Adding a test

1. Write the failing test first and run it. Confirm it fails for the reason you
   intend, not because a helper or module is missing. A red on `ImportError` proves
   only that a file is absent.
2. Give every assertion a name. Porting a bash check means reusing its exact name
   string.
3. Assert the premise. If a fixture is supposed to write rows, assert that it did.
4. If the test needs an escape hatch, give it a reason rather than a flag.
5. Run `compare_to_bash.py` if you are porting, and expect it to report every bash
   property as covered.
6. Run serially and with `-n 4`. A test that passes only in one of those is
   order-dependent or shares state.
7. If you add a guard, add the red test that proves it fires, and a control that
   proves it does not fire on a legitimate test.
8. Run `test/harness_selftest.sh`. **The harness's own selftests police this
   directory too.** `test/selftest/300-a-test-script-must-be-runnable.sh` requires
   that any file declaring an interpreter be executable, and the first version of
   `compare_to_bash.py` was mode 644 with a `#!/usr/bin/env python3` line. That
   failed the selftest on both majors of the matrix, which is how it was found. A
   new directory under `test/` inherits every rule the old ones follow.

## 7. Traps this corpus records

Recorded because each one produced a confident wrong result before it was caught,
and all are the same family as the defect the layer exists to prevent.

**A `UsageError` is written to stderr.** Two of the layer's tests assert on a
message and both were checking stdout at first. They still exited non-zero, so
`assert result.ret != 0` passed and the tests looked correct. Every message
assertion here now names its stream.

**A red test can fail for the wrong reason.** The first guard's red state was
`ImportError: No module named 'pgc_vacuity'`. The module had to exist and simply
not guard yet before the red meant anything.

**`git checkout` restores source, not the installed library.** After the mutation
arm, the source was clean and `/usr/local/pg18a` still held the mutated `.so`, so
the next run tested a mutated binary against clean sources. The harness prints its
`.so` fingerprint on every run, which is the only reason this was visible.

**Counting is a fragile instrument.** A `grep -c " PASSED"` reported 6 of 7 tests,
because the first test's outcome shares a line with a fixture's print. A `head` in
the differential truncated its own summary line. Both produced a report that looked
complete. This is why the property comparison reads names.

**`ps | grep "[p]attern"` can match its own shell.** The bracket protects the
enclosing command line only while the plain word appears nowhere else in it. A probe
whose body also contained `/tmp/pgc-pytest-*` counted its own invocation as a leaked
process. Walking `/proc/<pid>/cmdline` is the reliable instrument.
