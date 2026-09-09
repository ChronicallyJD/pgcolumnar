# The pytest corpus: what each test asserts, and why it exists

Reference for anyone reading, running, or adding to `test/pytest/`. The design and
the decisions behind the harness are in `design/ISSUE_432_PYTEST_HARNESS.md`. This
file covers the tests themselves.

**62 tests in 6 files.** Forty-seven of them test the harness rather than the
product, and they come first, because a harness that can report a false green makes
every other result in this directory worthless.

That ratio is not an accident of taste. Two of those files exist because a reviewer
neutered the guards one at a time and found most of them deletable with the suite
still green, and because the corpus once reported 25 passed against source carrying
`#error`. Both are recorded below in the sections for the files that close them.

The totals in bold above are checked. `test/selftest/350-the-pytest-corpus-must-be.sh`
reads them back and compares them with the corpus on disk, and also requires every
file and every test here to be named in this document -- because this file went stale
inside a single rework, and a partial index of something claiming completeness reads
as a total one.

Every measured fact quoted below was run. Where a test encodes a number or a
behaviour, the source of that number is named.

## Contents

- [1. How to read a test in here](#1-how-to-read-a-test-in-here)
- [2. The assertion vocabulary](#2-the-assertion-vocabulary)
- [3. test_layer.py: the guards, testing themselves](#3-test_layerpy-the-guards-testing-themselves)
- [4. test_guards_pinned.py: every refusal, pinned to its own message](#4-test_guards_pinnedpy-every-refusal-pinned-to-its-own-message)
- [5. test_build_refusal.py: never report on source you did not build](#5-test_build_refusalpy-never-report-on-source-you-did-not-build)
- [6. test_docs_cover_the_corpus.py: this document, checked](#6-test_docs_cover_the_corpuspy-this-document-checked)
- [7. test_connection.py: the cluster and the direct connection](#7-test_connectionpy-the-cluster-and-the-direct-connection)
- [8. test_native_projection.py: the ported suite](#8-test_native_projectionpy-the-ported-suite)
- [9. Adding a test](#9-adding-a-test)
- [10. Traps this corpus records](#10-traps-this-corpus-records)

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
| `refusal(result, name, *patterns)` | an inner run failed **and** its output carries each pattern | being called with no pattern, which is an outcome-only assertion wearing a better name |
| `cannot_run(reason, detail)` | declares the test unrunnable | a reason outside the closed list |

`refusal` is the helper the whole of section 4 turns on. Asserting that an inner run
failed is not the same as asserting that a named guard fired: several guards are
subsumed by a neighbouring one, so the inner run fails either way and an
outcome-only assertion cannot tell which. Requiring the message is the same move as
asserting on a SQLSTATE rather than on prose -- name the contract, not the symptom.

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

## 4. test_guards_pinned.py: every refusal, pinned to its own message

**Why this file exists.** @jdatcmd neutered each guard in the layer in turn and
found **11 of 17 deletable with `test_layer.py` still green**. Repeating the census
over the whole corpus after the ordered oracle landed gave 12 of 17; the two extra
were guards added later, so this is not a defect of the original layer that
subsequent work happened to avoid. It is the shape the layer was in.

Two causes, and they need the same remedy.

**Never driven.** `test_layer.py` never called `text()`, `at_least()`,
`plan_marker()` or `cannot_run()` at all. A guard nothing calls cannot be observed
to work.

**Driven, but pinned by nothing.** This is the interesting half. Neuter the
both-empty guard in `ordered_rows` and the UNOBSERVABLE guard fires on the same
input. The inner run still fails, so an assertion on outcomes alone still passes.
The guard is unreachable **by subsumption** rather than untested, and an arm that
asserts only "something failed" cannot tell the two apart.

So every arm here goes through `expect.refusal`, which requires the message as well
as the failure.

| test | the refusal it pins |
| --- | --- |
| `test_num_refuses_a_string_that_looks_like_a_number` | `num("100", "100", …)` — the psql-text defect this harness exists to remove |
| `test_num_accepts_real_numbers` | **control**: a genuine numeric comparison still passes |
| `test_text_refuses_an_empty_expectation` | an empty expected string, which anything empty satisfies |
| `test_at_least_refuses_a_non_number` | a bound taken from text |
| `test_at_least_refuses_a_floor_of_zero` | a floor every possible value clears |
| `test_at_least_accepts_a_real_bound` | **control**: `at_least(7, 3, …)` passes |
| `test_plan_node_refuses_no_criteria` | called with neither `node_type` nor `provider` |
| `test_outcomes_refuses_no_expectation` | called with no expectation at all |
| `test_cannot_run_refuses_a_reason_outside_the_closed_list` | the escape hatch cannot be widened by inventing a reason |
| `test_hash_refuses_self_comparison` | a value compared against itself |
| `test_hash_refuses_a_LEFT_error_sentinel` | a `QUERY_ERROR` on the left |
| `test_hash_refuses_a_RIGHT_error_sentinel` | the mirror, which one arm never covered |
| `test_hash_refuses_two_empties` | two distinct empty values |
| `test_refusal_itself_refuses_an_empty_pattern_list` | the new helper must not become the defect it removes |

Three of these carry reasoning that is easy to lose.

**The sentinel arms name the SIDE.** A single arm asserting "is a failed query"
left both sentinel guards unheld. Neuter the left guard and the comparison itself
still fails the inner run — subsumption by the ordinary assertion, not by another
guard. With the side named, a left guard that stops working can no longer be
covered by the right one or by the comparison.

**`test_hash_refuses_two_empties` is reachable only with two DISTINCT empties.**
The self-comparison guard above it is `got is want`, an identity test, and CPython
interns `""` — so `expect.hash("", "", …)` trips *that* guard and never reaches
this one. Written the obvious way, the arm would have passed while asserting
nothing about the guard it names. Prove an input can reach a guard before asserting
the guard fires.

**`test_refusal_itself_refuses_an_empty_pattern_list` closes the loop.**
`refusal(result, name)` with no pattern is exactly the outcome-only assertion that
caused most of the unheld guards. The helper introduced to fix the problem refuses
to be used that way.

### What the census says now

Run the way the reviewer ran it — each guard neutered alone, the mutation asserted
to have applied, the file restored and compared byte-for-byte afterwards, and
`inputs == sum(buckets)` asserted:

```
base branch  before   13 guards    3 HELD   10 UNHELD
base branch  after    13 guards   13 HELD    0 UNHELD
full stack   after    18 guards   18 HELD    0 UNHELD
```

## 5. test_build_refusal.py: never report on source you did not build

**Why this file exists.** @jdatcmd appended
`#error THIS SOURCE IS BROKEN AND CANNOT BUILD` to `src/columnar_projection.c`,
rebuilt nothing, and ran both harnesses:

```
pytest                          ->  25 passed, exit 0
bash test/native_projection.sh  ->  FATAL: the build failed …, exit 1
```

The bash harness has refused that since #536. This corpus did not, because it never
built, never installed and never compared anything. `Cluster.so_md5` printed a
fingerprint that nothing read — a number on the screen is not a guard.

**The first fix was insufficient and was deleted rather than kept.** Comparing the
installed `.control` and `.sql` against source cannot catch `#error` in a `.c` file:
both artifacts stay byte-identical. The refusal now comes from
`pgc_build_and_install` in `test/lib.sh`, driven from Python, so there is one
implementation rather than two that can drift.

**Two levels of arm, deliberately.** The injected-runner arms pin what the Python
side does with a verdict. The `bash` arms pin the shell plumbing — the sourcing, the
quoting and the exit-status path — which an injected runner cannot reach and which
is where a wrong quote would hide.

| test | asserts |
| --- | --- |
| `test_a_failed_build_raises_rather_than_returning` | the refusal raises, says it is refusing, and carries the build's own output rather than a summary |
| `test_the_refusal_names_the_tree_it_refused` | the message names the source directory; a reader with several worktrees needs to know which |
| `test_a_successful_build_is_silent` | **control**: the guard does not fire on a build that worked |
| `test_the_shell_path_really_refuses` | the shell's own `FATAL` reaches the Python caller, through real bash |
| `test_the_shell_path_accepts_a_good_build` | **control** for the arm above, through the same plumbing |
| `test_a_missing_lib_sh_is_a_refusal_not_a_pass` | an unsourceable `lib.sh` means no guard at all, so it must refuse rather than proceed ungated |
| `test_build_once_builds_once_and_then_skips` | the workers share one prefix, so the install is serialised rather than skipped |
| `test_build_once_rebuilds_for_a_different_prefix` | running against two majors in turn rebuilds for each |
| `test_editing_the_source_rebuilds` | the marker is keyed on the source fingerprint, not just the prefix |
| `test_the_fingerprint_reads_content_not_mtime` | `touch` does not move the fingerprint; an edit does |
| `test_an_unfingerprintable_tree_always_rebuilds` | no fingerprint means no key, and no key must mean rebuild |
| `test_a_server_older_than_the_library_is_refused` | `predates` |
| `test_a_server_started_after_the_library_is_fresh` | `fresh` |
| `test_equal_timestamps_are_fresh_not_predates` | the exact boundary: the same second is not stale |
| `test_an_unreadable_side_is_unknown_not_fresh` | three unreadable shapes all give `unknown` |

### The build/start ORDER, which is not a detail

`shared_preload_libraries` maps the library at postmaster start, so **a cluster
started before the install keeps the OLD `.so` mapped for its whole life.** The
build reports success and every test still measures the previous branch's code —
the guard defeated by the order of two lines.

The first fix here had exactly that defect: the build ran *after* `make_cluster`,
which does `initdb` and starts the server. It surfaced as a flake — the first run
after the alpha4 rebase gave 15 cluster-start errors and the second run passed.
**A flake that clears on a second run is what a stale-binary defect looks like from
outside.**

### `unknown` never reads as `fresh`

Three of the verdict arms exist to keep that true. `server_binary_verdict` returns
one of `fresh`, `predates` or `unknown`, and `unknown` is what an unreadable mtime,
an unreadable postmaster start time, or a non-numeric epoch all produce. The
boundary arm is separate on purpose: mtime resolution is one second, so a run fast
enough to install and start within the same second must not refuse itself.

## 6. test_docs_cover_the_corpus.py: this document, checked

The file you are reading is checked mechanically, because it went stale inside a
single rework and nothing noticed. The corpus grew from 25 tests in three files to
54 in five; the two new files, 29 tests, were named nowhere here, and the header
still said "Twenty-five tests in three files".

**A partial index of something claiming completeness reads as a total one.** A
reader who opens a file whose stated purpose is completeness does not then go and
count the tests. That is the same defect the vacuity layer refuses one level down:
a report that looks like coverage and is not.

Three properties, each mechanical:

- every `test_*.py` file in this directory is named in TESTS.md
- every `def test_` in those files is named in TESTS.md
- the totals TESTS.md states are the totals on disk

The third is what the stale header got wrong, and neither of the first two would
have caught it: a document can name every test and still miscount them. That is why
the totals are written in a fixed, parseable form -- prose that says "twenty-five"
cannot be compared with anything, which is how the wrong header survived being read
many times.

| test | asserts |
| --- | --- |
| `test_the_sweep_finds_the_corpus_rather_than_an_empty_glob` | **premise**: the sweep saw files and tests, so "nothing missing" means something |
| `test_every_file_and_test_is_named_in_the_document` | every file and test is named here, and a failure says WHICH |
| `test_the_stated_totals_are_the_totals_on_disk` | the bold totals line matches the corpus |
| `test_a_fully_documented_corpus_reports_nothing_missing` | **control**: no false positive on a complete document |
| `test_an_undocumented_test_is_named_rather_than_passed_over` | the exact shape that shipped: file named, one test inside it not |
| `test_an_undocumented_file_is_caught_with_the_tests_inside_it` | how 29 tests went missing at once |
| `test_a_document_with_no_totals_line_states_none` | absent totals report `None`, which must not read as "they match" |
| `test_a_stated_total_that_disagrees_with_disk_is_visible` | the count arm's own red |

The five fixture arms exist because everything above them passes on a healthy tree,
which is exactly what a guard that does nothing also does. They run the identical
functions over a corpus built to be wrong.

### The twin, and which half has teeth

This is the pytest half. The other half is
`test/selftest/350-the-pytest-corpus-must-be.sh`, and the two are **not**
interchangeable:

- **The `.sh` half is the one that gates.** `harness_selftest` is registered in
  `SUITES`, so it runs in the matrix and in CI.
- **Nothing runs pytest.** Not `run_all_versions.sh`, not any workflow under
  `.github/`. A guard written only here would never fire in the gate, and a guard
  that does not run is a comment.

So the `.sh` copy is the enforcement and this one is what a person running the
corpus by hand gets, with the offenders arriving as a Python list rather than as a
string assembled by shell. Both are written in the same change, per the rule in
section 9.

This guard reddened on its own arrival, which is the only reason it is known to
work here: adding this file moved the corpus from `(54, 5)` to `(62, 6)` and the
totals arm failed with `got '(54, 5)' want '(62, 6)'` until this section was
written.

## 7. test_connection.py: the cluster and the direct connection

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

## 8. test_native_projection.py: the ported suite

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

## 9. Adding a test

0. **Write it twice.** Every test in this tree ships as a `.sh` suite and a pytest
   test **in the same change** (jd, 2026-09-09). Not ported later, not one or the
   other. Only the `.sh` half runs in the gate today, and only the pytest half gets
   typed results and a real connection, so a test that exists in one harness is not
   finished. Where the two differ in force, say which is which in both headers.
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

## 10. Traps this corpus records

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
