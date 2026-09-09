# The vacuity modes: what is refused, what is not, and what nobody attacked

A vacuity defect is a test that reports PASS while asserting nothing. This file is
the inventory: every way a pytest harness can do that which anyone here has
demonstrated, which of them `pgc_vacuity.py` refuses today, and which it does not.

`TESTS.md` documents the tests that exist. This documents the ones that should.

## 1. Where these numbers come from, and what did not run

A five-angle enumeration ran in the audit container against pytest 9.1.1,
pytest-xdist 3.8.0 and psycopg 3.3.5. Each mode had to be demonstrated by an actual
run rather than described.

| stage | started | completed | failed |
| --- | ---: | ---: | ---: |
| enumerate the modes | 5 | 5 | 0 |
| design a refusal per mode | 79 | 74 | 5 |
| **attack each refusal** | **148** | **0** | **148** |
| synthesize the layer | 1 | 0 | 1 |

**The adversarial stage did not run.** It was cut off by a session limit, so the
summary line reading `defeated: 0` counts zero defeats out of **zero completed
attacks**. That number is not evidence that these refusals survive attack, and this
document is the synthesis the failed stage would have produced, written by hand from
the stage outputs that did complete.

So: 79 modes produced by the run, of which **72 are named here** (see 1a), and **73 demonstrated by a run**. 74 refusals designed, every one of them
stating a residual. None of the 74 has been adversarially tested.

## 1a. How to count a mode in this document

**A mode is a backticked kebab-case identifier of three or more words**, such as
`collected-but-nothing-asserted`. That is the counting rule, stated because the
document had none and its numbers therefore could not be checked — which is a
poor property for a document about claims that cannot be checked.

Counted that way, and this is a measurement of the file rather than a
recollection of the run:

| | modes |
| --- | ---: |
| named in section 2, refused today | 22 |
| named in section 3, not refused | 50 |
| **named in this document** | **72** |
| produced by the enumeration run | 79 |
| **named nowhere here** | **7** |

**The enumeration produced 79; this document names 72 of them.** The other seven
were counted by the run and never transcribed, so they cannot be cited, checked
or built against. They are not a secret reserve of coverage — they are a gap in
this file.

The run's own split was 23 refused and 56 not, against the 21 and 51 named here.
Those differ by exactly the seven that were never written down. Where the two
disagree, **the named ids are the record** and the run's totals are history:
an id can be read, argued with and turned into a test, and a number cannot.

## 2. What the layer refuses today

22 of the 79, counted by section 1a's rule. Each is enforced by a mechanism, not a convention, and each has a red
test in `test_layer.py` that fails without it.

| mechanism | modes it closes |
| --- | --- |
| a test must make a counted assertion | `collected-but-nothing-asserted`, `return-instead-of-assert`, `assert-hidden-in-an-uncalled-helper` |
| `expect.rows` refuses two empty sides | `empty-equals-empty`, `empty-rows-equal-empty-rows`, `empty-vs-empty-set` |
| `expect.hash` refuses self-comparison, error sentinels, two empties | `oracle-against-itself`, `md5-of-the-empty-oracle` |
| `expect.at_least` refuses a floor of zero | `tautological-bound` |
| `expect.plan_marker` matches a typed key, never a substring | `substring-superstring`, `plan-substring-matches-property-or-prefix` |
| `plan_marker` refuses an absence claim over an empty plan | `absence-assertion-over-empty-plan` |
| `expect.rowcount` refuses psycopg's `-1` | `rowcount-minus-one-is-truthy-and-numeric` |
| a broad `except` is uncollectable, found by AST | `aborted-transaction-swallowed-into-one-fallback` |
| a bare skip fails the run | `skip-family-exit-0`, `all-tests-skipped-exit-zero`, `all-skipped-exits-zero` |
| `xfail_strict = true` | `xfail-xpass-and-the-wrong-exception`, `xfail-and-xpass-are-green` |
| `--pgc-expect-tests` asserts the run's own shape | `zero-collected-exit-5`, `filters-select-nothing`, `partial-selection-exits-zero` |
| the connection fixture is autocommit | `uncommitted-fixture-measures-an-empty-table` |
| `ordered_rows` refuses an unobservable ordering, and the scan refuses `sorted()` feeding it | `set-oracle-on-an-ordered-claim` |

Three of those were added after checking this layer against the inventory rather
than reasoning about it, and all three had passed silently before:

- `plan_marker(absent=True)` returned a pass against `[]`. An absence assertion is
  satisfied by nothing being there at all, which is the case most worth catching.
- `expect.num(-1, -1)` passed. `cursor.rowcount` is `-1` when no count is available
  and `1` for an unfetched `SELECT`; both are numbers.
- A broad `except` was forbidden **in a comment**, which enforces nothing.

## 3. What it does not refuse

55 modes by the run's count, **50 of them named below**, **49 demonstrated by a run**. 51 have a refusal already designed.
Grouped by what a reader needs to decide about them.

### 3.1 The run can lose tests and still exit 0

The layer asserts how many tests were **collected**. It does not assert how many
**reported**.

- `crashed-worker-silently-loses-tests` — measured under `--max-worker-restart=0`:
  8 collected, summary says "1 failed, 6 passed", and one named test never reported.
  pytest prints no warning.
- `xdist-drops-the-deselected-count`, `env-deselect-passes-xdist-divergence-guard`,
  `session-fixture-runs-once-per-worker`, `xdist-split-makes-a-loop-assert-vacuous`
- `process-exits-0-mid-run`, `retry-wrapper-greens-a-lossy-run`,
  `junit-records-a-crash-as-error-failures-zero`

The designed refusal is to reconcile the collected node-id **set** against the
reported node-id **set** in the controlling process, and fail on any difference.
That is strictly stronger than the count check the layer has, and it subsumes it.

### 3.2 The invocation throws the verdict away

- `exit-5-lost-through-a-pipe` — measured: `pytest -q -k nosuch | tee run.log`
  exits **0** without `pipefail` and **5** with it. The tee-the-log habit discards
  the only vacuity guard pytest ships.
- `ci-step-swallows-the-exit-code`, `n-zero-silently-serial` — measured: `-n 0` runs
  in-process with no workers, no warning, exit 0. So `-n "$PGC_JOBS"` with the
  variable empty turns the parallel gate serial in silence.

These are not fixable inside the plugin. They belong to whatever invokes it, which
is the same reason `test/run_all_versions.sh` carries its own accounting.

### 3.3 Collection can go quiet

- `empty-parametrize-is-a-silent-skip` — measured: a corpus glob matching nothing
  turns a data-driven suite into one `s` and exit 0. This is the shape most likely
  to bite a port, because the bash suites read corpora from disk.
- `session-fixture-skip-greens-the-whole-suite` — a session fixture calling
  `pytest.skip()` skips every dependent test. "The cluster would not start" becomes
  exit 0. The enumerating agent called this the single largest blast radius.
- `conftest-import-failure`, `collection-error-and-continue-flag`,
  `collection-error-loses-a-module-silently`, `collect-only-and-collect_ignore`,
  `mark-typos-and-bare-marks`

### 3.4 The assertion is shaped so it cannot fail

- `raises-too-broad`, `raises-catches-setup` — `pytest.raises(psycopg.Error)` is
  satisfied by an unrelated failure of the same family.
- `same-broken-helper-both-sides`, `truthy-error-string`, `assert-not-unset-error`,
  `zero-on-both-arms`, `tuple-assert-always-true`, `approx-of-nothing`

### 3.5 The fixture built the wrong situation

- `insert-wrote-no-rows` — `INSERT ... SELECT ... WHERE false` writes nothing and
  raises nothing; `rowcount` is 0 and nobody reads it.
- `mutation-arm-unobservable` — both arms of an A/B produce the identical answer and
  both are green. The assertion that would catch it, that the arms must **differ**,
  is the one nobody writes.
- `error-swallowed-to-empty` — two queries raise, a helper turns each into the same
  falsy value, and they compare equal. `lib.sh` closed this deliberately with a
  unique `QUERY_ERROR.$seq` per failure. **The port has the sentinel constant but
  nothing produces it.**
- `guc-set-but-path-never-engaged`, `aggregate-masks-empty-fixture`,
  `db-derived-empty-parametrize`, `null-filter-matches-nothing`,
  `loop-over-zero-rows`, `assert-inside-a-loop-over-zero-rows`

### 3.6 psycopg's typed results introduce their own

- `sql-null-to-python-none`, `none-conflates-null-no-row-and-missing-column`
- `dict-row-collapses-duplicate-columns`, `decimal-scale-and-null-aggregate`
- `truthy-cursor-from-execute`, `lossy-row-render`
- `only-first-result-set-fetched`, `multistatement-execute-positions-on-the-first-result`
- `executemany-returning-fetchall-sees-only-the-first-batch`,
  `server-cursor-rowcount-is-not-a-row-count`, `empty-query-string-succeeds`

The enumerating agent's own summary is worth keeping: psycopg **fixes** the half of
issue #418 where an error read as empty, because a failed statement raises and `[]`
can only mean zero rows. That improvement is exactly what will tempt a port to drop
the sentinels that close the other half, empty compared with empty.

### 3.7 The guard itself goes quiet

- `guard-as-teardown-fixture-still-reports-passed` — a guard implemented as a
  teardown fixture leaves the test reporting PASSED.
- `session-accounting-guard`, `session-exit-rewrite-masks-a-real-failure`,
  `description-guard-reopens-psycopg-raise`,
  `mitigations-measured-and-the-one-that-does-not-work`

## 4. The false-positive budget

A guard that rejects legitimate tests gets switched off, and then the thing it
replaced is gone too. The layer has four escape hatches, each costing more to type
than the honest form: `allow_empty` takes a reason, `--pgc-expect-tests` takes the
real number, `cannot_run` takes a reason from a closed list, and `absent=True`
requires a plan that arrived.

One false positive has already been hit and fixed. The broad-`except` refusal was
first written as a line regex and immediately rejected this layer's own tests,
because they contain the forbidden shape inside a `pytester.makepyfile` string. It
now parses with `ast`, where a handler inside a string literal is not an
`ExceptHandler` node. **A line regex over source cannot tell code from a string, which
is the same mistake as matching a plan by substring.**

## 5. What to add next, in order

Each entry names the red test to write first.

1. `test_layer_fails_when_a_reported_test_is_missing` — reconcile collected node-ids
   against reported node-ids. Subsumes the count check and closes §3.1.
2. `test_layer_rejects_an_empty_parametrize` — closes the shape most likely to bite
   a corpus-driven port.
3. `test_layer_rejects_a_fixture_that_skips` — closes the largest blast radius.
5. `test_expect_query_error_sentinel_is_unique_per_failure` — make something produce
   `QUERY_ERROR.<seq>`; the constant exists and nothing writes it.
6. `test_layer_requires_a_write_to_have_written` — closes `insert-wrote-no-rows`.
7. `test_layer_requires_ab_arms_to_differ` — closes `mutation-arm-unobservable`.
8. `test_raises_requires_a_sqlstate` — closes `raises-too-broad`.

Items 1 to 3 are worth more than the rest combined, because each turns a whole run
green rather than one test.

## 6. What this document cannot tell you

None of the 74 refusal designs has been adversarially tested: the stage that would
have tried to defeat them did not run. Every design states its own residual, and
those residuals are the authors' own, unchallenged.

So treat §2 as measured, §3 as measured, and §5 as a plan that has not yet met an
adversary. The layer is known to refuse 22 demonstrated modes -- the ids named in section 2,
not the run's larger total, for the reason section 1a gives. It is not known to be
undefeatable on any of them.
