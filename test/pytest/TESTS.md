# The pytest corpus: what each test asserts, and why it exists

Reference for anyone reading, running, or adding to `test/pytest/`. The design and
the decisions behind the harness are in `design/ISSUE_432_PYTEST_HARNESS.md`. This
file covers the tests themselves.

**134 tests in 11 files.** One hundred and nineteen of them test the harness rather than the
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
- [9. test_ordered.py: the ordered oracle](#9-test_orderedpy-the-ordered-oracle)
- [10. test_runshape.py: the shape of the run itself](#10-test_runshapepy-the-shape-of-the-run-itself)
- [11. test_zonemap_boundaries.py: exact boundaries](#11-test_zonemap_boundariespy-exact-boundaries)
- [12. test_saop_element_pushdown.py: scattered set pruning](#12-test_saop_element_pushdownpy-scattered-set-pruning)
- [13. test_hilbert_locality.py: what the Hilbert curve buys](#13-test_hilbert_localitypy-what-the-hilbert-curve-buys)
- [14. Adding a test](#14-adding-a-test)
- [15. What this corpus does NOT yet refuse](#15-what-this-corpus-does-not-yet-refuse)
- [16. Traps this corpus records](#16-traps-this-corpus-records)

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
| `row_set(got, want, name, allow_empty=None)` | two result sets are equal **ignoring order** | what `rows` refuses |
| `ordered_rows(got, want, name)` | two sequences are equal **in order** | two empty sequences, and a sequence whose elements are all identical, where order cannot be observed |
| `ordering_observable(forward, reverse, name)` | this fixture can distinguish order at all | a fixture that reads identically both ways |
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

**Which oracle you pick is an assertion, not a formatting choice.** `row_set`
ignores order by declaration; `ordered_rows` asserts it. The collection scan refuses
`sorted()` or `set()` feeding `ordered_rows`, because that reads as an ordering claim
and is not one. This is `pgc_seq_hash`, `diff_query_ordered` and
`pgc_check_ordered_oracle` ported, including that third one's control: the set oracle
must be order-blind BY DESIGN, or an ordered oracle could quietly be implemented as a
set one and every ordering test would go silent while staying green.

`rows` compares row sets rather than `md5(string_agg(...))`. That asserts the same
property as the bash oracle by a stronger means: a hash mismatch says two hashes
differ, a row-set mismatch says which row. It also avoids recomputing the hash in
Python, where encoding or collation could make identical rows hash differently.

`UNRUNNABLE_REASONS` is the closed list `lib.sh` already uses:
`MISSING_DEPENDENCY`, `UNSUPPORTED_MAJOR`, `ABSENT_FIXTURE`,
`UNAVAILABLE_ENDPOINT`, `UNMET_PRECONDITION`.

## 3. test_layer.py: the guards, testing themselves

These eighteen run pytest inside pytest through the `pytester` fixture. Each
writes a small test file, runs it with the plugin loaded, and asserts on the INNER
run's outcome. That is what proves a guard REFUSES, rather than assuming it.

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
| `test_an_unrunnable_test_does_not_leave_the_run_green` | a test declaring itself unrunnable exits 67 | **`1 passed`, exit 0** |
| `test_an_unrunnable_test_names_its_reason_and_its_detail` | the `UNRUN` line carries reason and detail | nothing was printed at all |
| `test_a_real_failure_outranks_an_unrunnable_test` | a run with both exits 1, not 67 | — |
| `test_a_run_with_nothing_unrunnable_still_exits_zero` | **control**: a green run is untouched | — |
| `test_layer_rejects_an_absence_assertion_over_an_empty_plan` | an absence claim over `[]` is refused | it passes: nothing is there to find |
| `test_layer_allows_an_absence_assertion_over_a_real_plan` | **control**: `absent=True` still works on a plan that arrived | — |
| `test_layer_rejects_psycopgs_no_count_sentinel` | `rowcount` of `-1` is refused | `-1` and `1` are both numbers, so `num` compares them happily |
| `test_layer_rejects_a_broad_except_in_a_test_file` | a broad `except` is uncollectable | it was forbidden in a COMMENT, which enforces nothing |

Six of the eighteen are controls rather than guards. They are not decoration. A guard
with a bad false-positive rate gets switched off, and then the guard it replaced is
gone too. `test_a_counted_assertion_passes` and
`test_layer_matches_the_exact_provider` exist so that a guard which starts
rejecting good tests reddens here first.

The last four came from checking the layer against the 79-mode inventory in
`VACUITY_MODES.md` rather than from reasoning about it, and **all three guards they
added had been passing silently**. Two are worth stating in full because the shape
recurs.

**`plan_marker(absent=True)` returned a pass against `[]`.** An absence assertion is
satisfied by nothing being there at all, which is the case most worth catching: a
plan that failed to arrive looks exactly like a plan that legitimately lacks the
node. Absence claims need a premise that the thing which could carry the marker
exists — the same reason `at_least` refuses a floor of zero.

**A broad `except` was forbidden in a comment, which enforces nothing.** After any
failed statement psycopg raises `InFailedSqlTransaction` for every later one, so a
single `except Exception` hides the real error and all its successors. Written first
as a line regex, the guard immediately rejected this layer's own tests, because the
forbidden shape appears inside a `pytester.makepyfile` string. It now parses with
`ast`, where a handler inside a string literal is not an `ExceptHandler` node. **A
line regex over source cannot tell code from a string** — the same mistake as
matching a plan by substring, and a guard that rejects legitimate tests is a guard
somebody switches off.

The escape hatches are deliberately more expensive to type than the honest form.
`allow_empty` takes a reason, not `True`. `--pgc-expect-tests` takes the real
number. `cannot_run` takes a reason from a closed list. None of them can become the
default by being shorter.

### The third state, and the hole it left

**`cannot_run` reported a pass.** It wrote `self.unrunnable` and nothing read it,
so a test that declared itself unrunnable printed `1 passed` and exited 0 —
measured, not inferred. A write-only field, the same shape
`test/selftest/320-a-check-that-could-not-run.sh` polices in the runner, where an
INCOMPLETE branch set a variable the verdict never read.

**It made the layer's own escape hatch its largest hole.** A bare
`@pytest.mark.skip` FAILS the run. The honest-looking alternative greened
silently, so the layer refused the cheap dishonest escape and permitted the
expensive-looking one. An escape hatch that costs nothing is the default.

The run now ends `EXIT_INCOMPLETE`, which is 67 — deliberately the same number as
`PGC_EXIT_INCOMPLETE` in `lib.sh:58`, because a runner that learns the code should
learn it once. pytest itself uses 0–6, so 67 collides with nothing. The reason and
detail print in lib.sh's shape:

```
UNRUN  test_probe.py::test_cannot: ABSENT_FIXTURE: the parquet corpus was not built
checks unrunnable: 1
```

**Failure still dominates**, exactly as in lib.sh: a run with both a failure and an
unrunnable test is a failure, because the failure is the more urgent fact. The
override only ever moves a run off zero. Measured in all four combinations, serial
and under `-n 2`:

```
unrunnable only          exit 67    exit 67  (-n 2)
unrunnable + a failure   exit  1    exit  1  (-n 2)
```

The xdist column is not decoration. The declaration travels to the controller as a
`user_property` on the test report, because a worker's own exit status is discarded
by xdist and a variable held in the worker process would never be seen. The
collector is held on the **config**, not in a module global, because `pytester`
runs the layer's own tests in-process: a module-level list would leak an inner
run's declarations into the outer session and exit the whole corpus INCOMPLETE.

The structural half of this is pinned in the gate by
`test/selftest/360-an-unrunnable-pytest-test-must.sh`, which is greppable from a
checkout with nothing installed — it asserts the field is read, that the read
reaches the exit status, that the override is conditional, and that the two
harnesses agree on 67. Against the pre-fix layer it reddens six arms.

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
| `test_plan_marker_present_arm_fails_when_the_key_is_absent` | the arm that makes "did the columnar scan run" answerable |
| `test_plan_marker_present_arm_passes_when_the_key_is_there` | **control** |
| `test_plan_marker_absent_arm_fails_when_the_key_is_present` | the arm that pins the vector-aggregate trap |
| `test_plan_marker_absent_arm_passes_on_a_plan_that_lacks_the_key` | **control** |
| `test_plan_marker_refuses_an_absence_claim_over_an_empty_plan` | the hole under both arms |
| `test_refusal_itself_refuses_an_empty_pattern_list` | the new helper must not become the defect it removes |

### plan_marker, and the three ways it could not fail

@jdatcmd named this one first: *"both of its arms can be deleted independently
with the suite green. Under one of those mutations the premise can never fail, so
the provider-trap test would silently be about an ordinary plan."*

It is the worst place in the layer for that to be true. `plan_marker` is the
faithful port of `pgc_is_columnar_scan`, and `test_connection.py` calls it three
times — once as the **premise** that the vectorized aggregate engaged. A premise
that cannot fail turns its test into a test about an ordinary plan, and nothing
goes red while it happens.

**A third hole sat underneath both arms.** An absence claim is satisfied by
nothing being there at all: `plan_marker([], key, absent=True)` gave `1 passed`,
exit 0, because a plan that never arrived looks exactly like a plan that
legitimately lacks the node. That is now a `VacuityError`, and it is refused for
the present arm too — an empty plan means the `EXPLAIN` did not arrive, so
neither question can be answered.

The four arm tests are behavioural rather than refusals, because `plan_marker`'s
two arms raise `AssertionError`: `expect.refusal` does not apply and
`expect.outcomes` is the right instrument. Their value is not their own green,
which they had before the guards were pinned. It is the census:

```
unmutated                      38c951eb7dda   5 passed
present arm neutered           dc066341dba2   1 failed  <- its own arm, and only it
absent arm neutered            7ce63404d821   1 failed  <- its own arm, and only it
empty-plan guard neutered      a4e9d763e77c   1 failed  <- its own arm, and only it
restored                       38c951eb7dda   byte-exact
```

**Each mutation reddens exactly one test, and it is that test's own.** That is
the property worth having: it proves the three are distinguishable rather than
subsumed, which "something went red" cannot.
| `test_ordered_rows_both_empty_names_its_own_refusal` | the sequence oracle's both-empty refusal, pinned to ITS message |
| `test_ordering_observable_both_empty_names_its_own_refusal` | the premise check's both-empty refusal, pinned to ITS message |
| `test_refusal_itself_refuses_an_empty_pattern_list` | the new helper must not become the defect it removes |

The two ordered-oracle rows are the subsumption case in its purest form. Both
guards refuse a both-empty comparison, and so does `rows()` underneath them, so an
arm asserting only "the inner run failed" passes with any one of the three deleted.
Each is pinned to its own message, which is the only way the three stay
distinguishable.

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
| `test_the_fingerprint_covers_a_separately_built_module` | an `objstore/` edit moves the hash |
| `test_an_objstore_edit_forces_a_second_build` | and forces a rebuild, end to end |
| `test_make_cluster_leaves_nothing_behind_when_setup_fails` | a failed setup leaks no directory |
| `test_the_stamp_writer_reports_failure` | `\|\| true` made both controllers' warnings unreachable |
| `test_two_installations_of_one_major_do_not_share_a_stamp` | the key names the installation, not just the major |
| `test_moving_bytes_between_files_moves_the_shell_fingerprint` | the digest sees a repartition |
| `test_the_two_fingerprint_implementations_cover_the_same_inputs` | **the two implementations move on the same edits** |

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

### The twin of `selftest/340`, and the fourth instance of one defect

These four drive the **shell** functions through `bash` rather than
reimplementing them, and they are the pytest half of `test/selftest/340`'s stamp
arms, owed under the twin rule and payable only once `test/pytest/` reached
`main` with #897.

The last one is the interesting one. `source_fingerprint` in `pgc_cluster.py`
says in its own docstring that it uses *"the same input set as
`pgc_source_fingerprint` in `test/lib.sh`"*. It did not. The shell hashes each
build directory's `*.c`, `*.h` **and `Makefile`**; this side read only the
sources, so editing `objstore/Makefile` — which changes how that module builds —
moved one hash and not the other:

```
baseline                    shell=45be41a5c47b  python=bea88c7d79ca
objstore/Makefile edited    shell=cfb8f4553041  python=bea88c7d79ca
```

`build_once` then certified a stale module as current. **That is
@linuxhikerpm's finding one layer over**: they found the module's *sources*
missing from this implementation, and the module's *Makefile* was still missing
after that was fixed.

The arm asserts the property the docstring always claimed, and not more: the two
hashes are **not** required to be equal — they are different digests over the
same files, used independently — but **the same edit must move both**. It walks
five edits: a source, a module source, a module Makefile, the top-level
Makefile, and the control file.

Two implementations of one idea have now been separately wrong, separately
fixed, and a third party had to find each. That is the argument for making them
one.

### Two findings from @linuxhikerpm, both about infrastructure rather than coverage

**The fingerprint read `src/` only.** `objstore/` is a separately built shared
library the top-level Makefile reaches by recursion, so editing
`objstore/module.c` left the hash unchanged and `build_once` certified a stale
module as current:

```
objstore_before=2799803eaeac objstore_after=2799803eaeac
builds=1 second=already-built
```

That is the same gap #898 closes in `test/lib.sh` — but this is an **independent
implementation**, so rebasing #898 would not have fixed it. `source_build_dirs`
now derives the set by the same rule the build follows: `src/`, plus any
directory carrying its own Makefile. The hash also mixes in each file's path
relative to the tree rather than its bare name, because with two build
directories `src/module.c` and `objstore/module.c` would otherwise be
interchangeable.

**`make_cluster` leaked its tree when setup failed.** It created `root` with
`mkdtemp` and then ran `initdb`, `start` and `is_ours` with no cleanup guard:

```
make_cluster_error=RuntimeError
new_roots=1 leaked=['/tmp/pgc-pytest-777-h3phhtxc']
```

`conftest.py` cannot clean up after it, because `cluster, root = make_cluster(…)`
never completes when the call raises. The handled `is_ours()` path leaked too —
it stopped the cluster and left the directory. Every exit that is not a
successful return now stops whatever was started and removes the tree, catching
`BaseException` so an interrupt during `initdb` cleans up like an error does.

Both are pinned structurally in the gate by
`test/selftest/380-the-pytest-cluster-helpers.sh`, which requires the *glob*
rather than the name — the only way to tell a derivation from a list that
happens to be complete today.

### `unknown` never reads as `fresh`

Three of the verdict arms exist to keep that true. `server_binary_verdict` returns
one of `fresh`, `predates` or `unknown`, and `unknown` is what an unreadable mtime,
an unreadable postmaster start time, or a non-numeric epoch all produce. The
boundary arm is separate on purpose: mtime resolution is one second, so a run fast
enough to install and start within the same second must not refuse itself.

### The fingerprint's own integrity, and why it needed six more arms

Six tests, added with the fix that closed three defects in `pgc_source_fingerprint`
itself. The subject is the instrument every other arm in this section depends on:
if the fingerprint can be wrong, `never report on source you did not build` reports
on nothing.

`test_a_failed_digest_yields_no_fingerprint_rather_than_a_wrong_one` drives the
real shell function with a **stub `md5sum` that is the real one except on its Nth
call**, where it fails with no output — a fork that hits `EAGAIN`, an OOM kill, a
loaded runner. The old code substituted that empty digest into the hash and
returned status 0, so one unchanged tree produced three different confident
answers. The premise arm requires the stub to agree with the real `md5sum` when
nothing is configured to fail, or the test would be measuring the stub.

`test_a_failed_digest_gives_unverified_and_never_a_false_stale` is the property
that matters. `stale` is the FATAL; `unknown` prints `freshness UNVERIFIED` and
runs the suites. The asymmetry is the whole argument for the change: a false
UNVERIFIED costs a line of output, a false FATAL costs a matrix **and** teaches
people to re-run past a freshness check, which is the failure this controller
exists to prevent.

`test_one_tree_hashes_one_way_however_the_path_is_spelled` pins five spellings —
trailing slash, `/./`, `/src/..`, a symlink, and a relative `.` — against the plain
path. Three of them disagreed before the fix, because `${f#"$dir"/}` strips a
prefix that has to match character for character.

`test_the_fix_does_not_rebaseline_stamps_already_on_disk` is a **compatibility**
assertion rather than a tidiness one, and it is the arm that would have caught the
worst version of this change. Detecting a failed digest means capturing the
per-file lines to inspect them, and `$(...)` strips the trailing newline that the
old straight pipe into `md5sum` included. Without restoring it, the same unchanged
tree hashes differently before and after the fix, every stamp already on disk reads
`stale`, and a fix for false FATALs becomes a false FATAL for everyone holding a
built worktree. The matrix cannot catch that: it copies a fresh tree and re-stamps
every run, so it lands on developers and on nobody's CI. The arm transcribes the
previous implementation and requires the same answer.

`test_the_fingerprint_still_moves_on_a_real_change` is the control without which
the spelling arms are vacuous — "every spelling agrees" is satisfied perfectly by a
fingerprint that ignores its input.

`test_a_tree_with_nothing_hashable_reports_no_fingerprint` closes the last one: the
hash of an empty stream is a stable, comparable value, so two trees with no source
would have *matched*.

**That last arm is the only one in this set with a real observation behind it
rather than a model, and it was not the case it was written for.** It shipped as
"a legitimate empty tree". @OffgridwithJD then observed the WHOLE manifest coming
back empty under process pressure, on a read-only bind mount where content was
excluded by construction: two distinct fingerprints over a tree incapable of
changing, and the deviant value was `d41d8cd98f00`, which is md5 of the empty
string — not a corrupted manifest but *no* manifest, hashed confidently. Measured
here as an A/B with the real `md5sum` and no stub, 20 samples per cell:

    true fingerprint = eebe35d6eaed ; md5("") = d41d8cd98f00

    OLD ulimit -u 45   correct=19  md5("")=1   refused=0  other=0  | sum=20 of 20
    OLD ulimit -u 40   correct=8   md5("")=11  refused=0  other=1  | sum=20 of 20
    NEW ulimit -u 45   correct=20  md5("")=0   refused=0  other=0  | sum=20 of 20
    NEW ulimit -u 40   correct=20  md5("")=0   refused=0  other=0  | sum=20 of 20

At `ulimit -u 40` the old function returns a confident answer about nothing in 11
runs of 20. The guard covers it structurally rather than statistically: a
non-empty `out` has at least one line, so `md5("")` is not a reachable return
value.

### When it refuses, it says what it hashed

Six more tests, added after two CI failures reported *the same pair of hashes and
nothing else* — `source now a735c673b129, binary built from 6d122a7158d5`,
identically, across two branches, two majors and two build directories, with the
fingerprint fix present in one of them. **A bare hash made the second occurrence
another sample rather than an answer.**

So the manifest is a function in its own right, `pgc_source_fingerprint` is
defined as its hash — the two cannot drift apart, and one test asserts exactly
that — and the FATAL path prints it through `pgc_freshness_report`.

`test_an_added_file_is_named_rather_than_merely_changing_the_hash` is the arm
aimed at the open question. An addition is the only class that explains one
deviant value from two different build directories, because the manifest carries
the path RELATIVE to the tree: the same file appearing under `matrix-17` and
`matrix-18` contributes the same line and therefore the same hash. The test
requires the diff to name the file rather than report that something changed.

`test_the_manifest_names_what_the_fingerprint_hashed` pins the shape of each line
— a tree-relative path and a 32-character digest, never an absolute path, because
an absolute path in the digest is the spelling defect returning by another route.
`test_the_fingerprint_is_the_hash_of_the_manifest` is the arm that keeps the two
from drifting, and `test_an_empty_manifest_is_reported_as_empty_not_as_silence`
covers the case the report exists for.

`test_the_fatal_report_can_be_run_rather_than_grepped_for` exists because the
alternative was asserting that the source calls the function, which is the shape
this suite refuses everywhere else. The report is a function so an arm can drive
it, and the empty case says `(empty -- nothing under ...)` rather than printing
nothing, because a silent empty dump reads as *the manifest was fine*.

### The suite that wrote into the tree the other suites were reading

`test_no_selftest_part_writes_into_the_live_source_tree` scans the parts for a
redirection aimed at the live tree.

`test/selftest/340` used to write `objstore/.pgc_fingerprint_probe.c` into
`$PGC_SRCDIR`, to prove that a new file under a recursed directory moves the
fingerprint. `harness_selftest` runs IN the matrix, so at `PGC_JOBS=4` it created
that file in the shared build directory while sibling suites fingerprinted
concurrently, and whichever sampled inside that window reported `FATAL: the binary
under test was not built from this source` against a tree that was correct. The
path is tree-relative and the content fixed, so the deviant value was *identical*
across majors, build directories and branches — which is what made it look like a
real staleness. It cost four pull requests and two wrong diagnoses before
@linuxhikerpm found it by reading the suite.

The arm now probes a hardlinked COPY of the tree. The intent survives, because the
defect it was written for was that the *real* tree's `objstore/` was not being
read, and a hand-built fixture could not have caught that — so a premise requires
the copy to discover the same build directories as the real tree. **That premise
immediately earned itself**: the first fix hardlinked across a filesystem
boundary, `cp -al` failed after creating the destination, `cp -a` then copied the
tree *inside* it, and the copy's build directories came out as `bfix src` rather
than `objstore src`.

**A BEFORE/AFTER RUN CANNOT CATCH THIS, and that is worth recording because it
was my first attempt.** Fingerprint the tree, run the suite, fingerprint again:
the probe was created and `rm -f`'d inside the same suite, so the tree is
byte-identical by the time the run ends and the comparison passes. The damage is
done to whoever samples DURING the window, and an after-the-fact observer is blind
to it by construction. Sampling concurrently instead would make the arm racy — it
would pass whenever the timing missed. So the observable property is the one in
the source: no part directs a write at the live tree.

Its limit is stated in the test: it recognises a redirection whose target mentions
the tree-root variables the parts actually use, and a write reaching the tree by
another route would evade it. It carries three premises of its own — that the scan
recognises a write at `$PGC_SRCDIR`, that it recognises one through `$_bd_root`,
and that a write into a COPY is *not* flagged — because a pattern that matches
nothing would otherwise pass this arm silently.

**What is still not guarded**, named here rather than left for someone to find: a
TRUNCATED manifest — `find` returning fewer files rather than none — would produce
a plausible wrong hash that neither the per-file sentinel nor the empty-manifest
guard can see. It has not been observed. The boundary of this change is "the three
observed variants are closed", not "the function is now infallible".

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
| `test_the_mode_inventory_states_its_own_totals_correctly` | the totals in VACUITY_MODES.md section 1a are the modes on disk |
| `test_the_readme_and_the_inventory_agree_on_what_is_refused` | README.md quotes the inventory's number, so the two cannot drift apart again |
| `test_the_inventory_accounts_for_every_mode_the_run_found` | the admitted gap row is the run's total minus what is written down |
| `test_the_prose_totals_match_the_counted_modes` | every sentence stating what the layer refuses today carries the counted number, not just the table |
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

## 9. test_ordered.py: the ordered oracle

`lib.sh` has two oracles and this port had one. `pgc_set_hash` sorts before hashing,
so a bash test naming `ORDER BY` and comparing with `diff_query` cannot fail on
order; `pgc_seq_hash` and `diff_query_ordered` are the ones that can. These nine
tests port that pair and its premise check.

| test | the guard | what it stops |
| --- | --- | --- |
| `test_ordered_rows_refuses_a_sequence_whose_order_is_unobservable` | an ordered claim over a constant sequence is refused | forward equals reverse, so order asserts nothing |
| `test_ordered_rows_refuses_two_empty_sequences` | two empty sides are refused here too | inherits `rows()`'s refusal instead of losing it |
| `test_ordered_rows_accepts_a_real_ordering` | **positive control** | a genuine ordered claim still passes |
| `test_ordered_rows_fails_on_the_wrong_order` | the oracle detects order | proves it can fail, not merely that it permits |
| `test_layer_refuses_sorting_the_input_to_an_ordered_claim` | `sorted()` feeding `ordered_rows` is uncollectable, found by AST | `ordered_rows(sorted(got), sorted(want))` cannot fail on order |
| `test_layer_refuses_a_name_bound_to_a_sorted_call` | `g = sorted(got)` one line above the claim is the same collapse | the inline spelling was the only one caught, so the guard was blind to the version least likely to be noticed |
| `test_layer_refuses_a_list_sorted_in_place` | `got.sort()` kills the order and leaves the name spelled the same | nothing at the call site says anything happened |
| `test_layer_allows_a_name_sorted_after_the_claim` | **control** | a name sorted AFTER the claim did not affect it; refusing that would be a false red |
| `test_the_order_killer_scan_is_one_function_deep` | **pinned limit** | a sort behind a helper is not caught, and this arm reddens if that documented limit ever moves |
| `test_ordering_observable_requires_the_two_directions_to_differ` | a fixture reading the same forwards and backwards is refused | the premise `pgc_check_ordered_oracle` asserts in bash |
| `test_ordering_observable_passes_when_the_directions_differ` | **positive control** | a real fixture is untouched |
| `test_the_two_oracles_are_different_instruments` | the set oracle and the sequence oracle must disagree on a permutation | if they agree, one of them is not the instrument it claims to be |
| `test_row_set_still_refuses_two_empty_sides` | **regression control** | adding the sequence oracle must not weaken the set one |

The third property is the one worth reading twice. Two oracles that always agree are
one oracle with two names, and a suite built on them would pass every ordering claim
by construction. The test feeds both a permutation and requires the set oracle to
accept while the sequence oracle rejects.

The AST scan matters for the same reason the broad-`except` scan does. A line regex
for `sorted(` fired inside the `pytester.makepyfile` string of the test that tests
it, so the guard rejected its own corpus. Walking the tree and looking at real call
nodes is the only version that distinguishes code from a string holding code.

## 10. test_runshape.py: the shape of the run itself

The other guards ask whether a test asserted anything. These six ask whether the
**run** did. Each of the three failure shapes turns a whole session green rather
than a single test, which is why they were built before the rest of the backlog.

| test | the guard | bare pytest, measured |
| --- | --- | --- |
| `test_layer_fails_when_a_collected_test_never_reports` | the reported node-id set is reconciled against the collected one | 6 collected, 5 reported; the crash is named, the lost test is not |
| `test_layer_accepts_a_run_where_every_test_reports` | **positive control** | an honest parallel run is untouched |
| `test_layer_rejects_a_parametrize_over_an_empty_list` | an empty parameter set fails the run | `1 skipped`, exit 0 |
| `test_layer_accepts_a_parametrize_with_cases` | **positive control** | a real parameter set is untouched |
| `test_layer_rejects_a_fixture_that_skips` | a skip arriving during setup fails the run | every dependent test skips, exit 0 |
| `test_layer_allows_a_declared_unrunnable_test` | **escape hatch and control** | `expect.cannot_run` records a counted assertion instead of skipping |
| `test_layer_allows_a_deliberately_selected_subset` | `-k` is a deliberate act, not tests lost | the guard reported 15 deselected tests as never reported and failed a healthy run |
| `test_layer_allows_an_explicitly_deselected_test` | `--deselect` reaches the same hook by another route | pinned separately so one fix cannot cover only one spelling |
| `test_a_run_that_both_deselects_and_loses_a_test_still_fails` | **the distinguishing arm** | subtracting the deselected ids is right only if a genuinely lost test is still caught |

Half of these are controls, and deliberately so: a run-shape guard fires on the whole
session, so a false positive costs the entire suite rather than one test.

Read that first row precisely, because bare pytest is not silent here: it exits 1
and prints `worker 'gw1' crashed while running 'test_loss.py::test_kills'`. What it
never mentions is `test_loss.py::test_d`, which was collected, assigned to the dead
worker, and never ran. Measured on a 6-test corpus under `-n 2
--max-worker-restart=0`: 6 collected, 5 node-ids reported, and the missing one
appears in no line of the output. A suite whose crash happens to land on a test
already expected to fail therefore reports exactly what you expected while running
fewer tests than you wrote.

Two things about the reconciliation took a measurement to get right. Under `xdist`
the **workers** collect, not the controller, so the controller's collected set stayed
empty and the guard was present and blind until it also listened to
`pytest_xdist_node_collection_finished`. And the state has to live on a per-config
plugin instance rather than module globals: `pytester.runpytest()` runs the inner
session in-process, so module-level sets leaked between these tests and the sessions
they drive. The corpus reported 44 passed and exited 1.

The empty-parametrize refusal carries its own message rather than folding into the
bare-skip refusal. When a corpus glob matches nothing, the cause the reader needs to
see is the corpus, not the marker.

## 11. test_zonemap_boundaries.py: exact boundaries

### `test_exact_zonemap_boundaries`

Pairs with `test/zonemap_boundaries.sh`. Two monotonic 1,000-row groups put
`1001` exactly at the second group's minimum and `1000` exactly at the first
group's maximum. Heap-row comparisons pin that `<= 1001` and `>= 1000` keep
their boundary rows. Work-done counters, with bloom disabled, pin the
correctness-preserving cases: `< 1001`, `> 1000`, and `= 1001` each remove one
group.

The five one-token strategy mutations make the corresponding assertion fail:
`<=` and `>=` lose one row, while `<`, `>`, and `=` remain row-correct but
remove no group. This distinguishes correctness coverage from
pruning-effectiveness coverage rather than relying on incidental fixtures
elsewhere in the matrix.

## 12. test_saop_element_pushdown.py: scattered set pruning

### `test_scattered_saop_prunes_each_element`

Ports the #752 additions to `test/native_saop_pushdown.sh`. A monotonic 40,000-row
fixture has twenty row groups. The scattered set `{100,20100,38100}` spans the
table, so its old `[min,max]` hull removes zero groups while per-element pruning
removes seventeen. The contiguous `{100,101,102}` set is the negative control:
its hull and its elements both remove nineteen groups. Exact 128- and 129-element
arms pin both sides of the bounded fallback.

A by-reference text set with three values plus NULL pins the NULL compaction
whose absence dereferences a null Datum. Its integer companion proves NULL
removal retains pruning. The `ov` fixture gives every group the same `[10,88]`
zone, so a set of absent odd values can remove groups only through the
per-element bloom loop.

The shell and pytest forms were both run red before implementation (`0`, wanted
`17`), green afterward, then red again with the per-element threshold mutated to
zero. The fixture row count and columnar plan marker are premises, and both query
answers are checked independently of the pruning counters.

## 13. test_hilbert_locality.py: what the Hilbert curve buys

The pytest twin of `test/hilbert_locality.sh`, written in the same change under the
owner's rule of 2026-09-09 that every new test ships in both harnesses. Twelve tests.

It measures one thing -- how many chunk groups a range query reads under Z-order
against Hilbert -- and spends most of its arms refusing to measure it when the
comparison would be meaningless.

| test | what it refuses |
| --- | --- |
| `test_every_layout_verb_ran_without_raising` | a verb that raised looks identical to a verb that no-opped |
| `test_the_source_holds_the_rows_both_arms_will_load` | an empty fixture |
| `test_both_arms_hold_the_identical_row_multiset` | the two arms holding DIFFERENT DATA, which made the first pilot's ratio a fact about the data rather than the curve |
| `test_the_fixture_is_two_dimensional` | a fixture where one column does not span, so the curve has nothing to interleave |
| `test_both_arms_have_the_group_count_measured` | a group meaning a different unit on each arm |
| `test_the_two_partitions_differ` | the case where the curves cut the SAME partition, where no query can separate them |
| `test_two_tables_on_the_same_curve_are_one_partition` | the null control: same curve twice must be one partition |
| `test_dense_dyadic_grid_is_one_partition` | the dense power-of-two grid, which provably cannot separate the curves |
| `test_both_arms_plan_as_a_columnar_scan` | a counter read from a plan that is not the columnar scan |
| `test_parallelism_is_off_so_a_counter_is_a_fact_about_the_layout` | a per-worker counter read as a whole-query one |
| `test_the_predicates_are_usable_and_the_denominators_match` | unequal denominators, and zero usable skip predicates |
| `test_groups_read_over_sixty_placements` | nothing -- this is the measurement |

**The two controls REFUSE rather than returning 1.0.** Both are cases where the
curves genuinely cut the same partition, so a ratio would be arithmetic on two
identical numbers. A harness that reported `1.0000` there would look like a
measurement and be an artifact.

**Why sixty placements and not one.** A single query-box origin measures where that
box happened to land. At one origin the differences were 1, 1, 0 and 1 groups, and
the ratio read `2.000` off a single group.

**What the twin does NOT carry**, and the bash suite does: the exact-integer pins.
The twin asserts Hilbert reads fewer groups at every box; `test/hilbert_locality.sh`
pins the eight counts exactly. Its header records why -- for a CURVE change the
digest pins upstream catch it first and the integers add nothing, so their real
domain is a changed READER at an unchanged layout.

## 14. Adding a test

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

## 15. What this corpus does NOT yet refuse

`VACUITY_MODES.md` is the inventory: 79 ways a pytest harness can report a pass while
asserting nothing, 73 of them demonstrated by an actual run. **This layer refuses 25
of them.** The other 47, of which 46 were demonstrated, are listed there with the
refusal design each would need and the order worth building them in.

Read it before adding a test. The gaps most likely to affect a new test are that
`pytest.raises` is still allowed to be broad enough that an unrelated failure of the
same family satisfies it, and that a write is not required to have written anything.
Both are named there with the refusal each needs.

## 16. Traps this corpus records

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
