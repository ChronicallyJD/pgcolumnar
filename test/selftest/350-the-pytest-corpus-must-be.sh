# ---- the gate must run the pytest corpus's guards ----------------------------
#
# WHAT THIS PART IS NOW (#432). It used to hold three groups of arms over
# test/pytest/: that every file and test is named in TESTS.md, that every
# contents-list link resolves, and that VACUITY_MODES.md's section 1a counts itself
# correctly. Fifty checks, and the subject of forty-six of them lived on the other
# side of the harness boundary.
#
# THE TWO HARNESSES ARE PARALLEL IN FUNCTIONALITY AND MUST NOT REFERENCE EACH OTHER
# (jd, 2026-09-10). Every one of those arms either globbed test/pytest/*.py and
# parsed Python out of it, or swept the markdown in that directory. The pytest
# corpus asserts all three properties natively in test_docs_cover_the_corpus.py,
# where the subject is, and the shell copy could only ever agree with it.
#
# WHAT MOVED RATHER THAN BEING DELETED. Two of the three rules were implemented on
# both sides and SELF-TESTED only here -- the side that cannot run the corpus it
# counts. Deleting those fixtures would have left the python implementation with no
# fixtures at all, so they went with them:
#
#   the mode-counting rule's edges   an id of fewer than three words, an id named
#                                   twice, stopping at the next heading, section
#                                   3's back-references, and the row reader taking
#                                   the value cell rather than a digit in its label
#   the contents-list anchor rule    GitHub's derivation, the broken link that
#                                   shipped, and a control beside it
#
# AND THE REASON THE DOCUMENT GAVE FOR KEEPING THE SHELL COPY WAS STALE. TESTS.md
# section 6 said "Nothing runs pytest. Not run_all_versions.sh, not any workflow
# under .github/", and concluded that the .sh half was therefore the enforcement.
# CI has a pytest-guards job. That argument was stale in three places at once --
# there, in selftest/360 and in selftest/380 -- each claiming the behavioural half
# could not run in CI. Nothing was wrong; the reason was, and a stale reason for
# keeping coverage in the wrong place is harder to find than a missing check,
# because nothing reddens.
#
# WHAT REMAINS HERE IS THE CI WORKFLOW, which belongs to neither harness. A shell
# part may read it for the same reason it may read the Makefile: ci.yml is not a
# test suite, and no pytest arm can assert that the gate runs pytest without
# assuming the very thing in question.
#
# THE MEMBERSHIP DECISION AND THE CONFTEST IMPORT ARE STILL NOT CHECKED HERE, and
# that was already jd's rule rather than an omission. An earlier version of this
# part read test/pytest/conftest.py and INVOKED test_harness_deps.py with
# `python3 ... --disagree`, which is the coupling rather than a second measurement:
# a shell arm driving the python decider agrees with it by construction and can
# never report it wrong. Both properties are asserted in the corpus:
#
#   conftest imports no driver at module scope
#       test_harness_deps.py::test_conftest_imports_no_database_driver_at_module_scope
#   the declaration is exactly the database-free half, both directions
#       test_harness_deps.py::test_the_declaration_is_exactly_the_database_free_half
#   the partition accounts for every file, and the three report cases
#       test_harness_deps.py and test_harness_deps_classifier.py

_hd_ci="$PGC_SRCDIR/.github/workflows/ci.yml"

check "premise: the CI workflow is where this part thinks it is" \
	"$([ -f "$_hd_ci" ] && echo yes || echo no)" "yes"

check "the gate runs the harness guards" \
	"$([ "$(grep -c 'pytest-guards:' "$_hd_ci")" -ge 1 ] && echo yes || echo no)" "yes"

# DERIVED, NOT REPEATED. A second copy of the file list is the defect this repo
# spent a day removing from TESTS.md.
check "and it derives the file list rather than repeating it" \
	"$([ "$(grep -c 'from test_harness_deps import NO_CLUSTER' "$_hd_ci")" -ge 1 ] \
		&& echo yes || echo no)" "yes"

# Presence, not a count: the comment block above the job names this file too,
# and an exact count would be an assertion about the prose as much as the code.
check "and derives the pins from requirements-test.txt" \
	"$([ "$(grep -c 'requirements-test.txt' "$_hd_ci")" -ge 1 ] && echo yes || echo no)" "yes"

# AND THE JOB MUST RUN WITHOUT THE DRIVER, which is what makes it able to run at
# all on a machine with no database. Without this the job could quietly install
# psycopg and the database-free claim would stop being tested while still being
# made. Added here because this part's subject is now the workflow, and this is a
# property of the workflow rather than of either harness.
check "and the job asserts the driver is absent rather than assuming it" \
	"$([ "$(grep -c 'pip show psycopg' "$_hd_ci")" -ge 1 ] && echo yes || echo no)" "yes"

unset _hd_ci
