"""The ordered oracle, tested before it refuses anything.

lib.sh has pgc_seq_hash, diff_query_ordered and pgc_check_ordered_oracle; the port
had no way to express an ordered claim at all, so a test naming ORDER BY compared
with sorted lists could not fail on order (VACUITY_MODES.md, set-oracle-on-an-
ordered-claim).
"""


def test_ordered_rows_refuses_a_sequence_whose_order_is_unobservable(pytester, expect):
    """If every element is the same, forward equals reverse and order asserts nothing.

    This is pgc_check_ordered_oracle's premise ported: the bash version proves the
    oracle is order-sensitive by requiring forward != reverse on a real fixture.
    """
    pytester.makepyfile(
        """
        def test_all_the_same(expect):
            expect.ordered_rows(['x', 'x', 'x'], ['x', 'x', 'x'], "order of identicals")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "an unobservable ordering is refused", failed=1, passed=0)
    result.stdout.fnmatch_lines(["*order cannot be observed*"])


def test_ordered_rows_refuses_two_empty_sequences(pytester, expect):
    pytester.makepyfile(
        """
        def test_both_empty(expect):
            expect.ordered_rows([], [], "two empty sequences")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "two empty sequences are refused", failed=1, passed=0)


def test_ordered_rows_accepts_a_real_ordering(pytester, expect):
    """The positive control: a genuine ordered claim must still pass."""
    pytester.makepyfile(
        """
        def test_real_order(expect):
            expect.ordered_rows([1, 2, 3], [1, 2, 3], "a real ordering")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "a real ordering passes", passed=1, failed=0)


def test_ordered_rows_fails_on_the_wrong_order(pytester, expect):
    """And it must actually detect order, not merely permit the claim."""
    pytester.makepyfile(
        """
        def test_wrong_order(expect):
            expect.ordered_rows([3, 1, 2], [1, 2, 3], "the wrong order")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "the wrong order is caught", failed=1, passed=0)


def test_layer_refuses_sorting_the_input_to_an_ordered_claim(pytester, expect):
    """`ordered_rows(sorted(got), sorted(want))` cannot fail on order.

    This is the collapse itself: the helper is order-sensitive, so the vacuity is
    introduced at the CALL SITE. Found by ast, for the same reason the broad-except
    scan parses rather than greps.
    """
    pytester.makepyfile(
        """
        def test_sorted_into_an_ordered_claim(expect):
            got = [3, 1, 2]
            expect.ordered_rows(sorted(got), sorted([1, 2, 3]), "sorted away")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.run_failed(result, "sorting the input to an ordered claim is refused")
    result.stderr.fnmatch_lines(["*sorted*ordered*"])


def test_ordering_observable_requires_the_two_directions_to_differ(pytester, expect):
    """The ported premise: a fixture that reads the same forwards and backwards
    cannot support an ordering claim at all."""
    pytester.makepyfile(
        """
        def test_premise_fails(expect):
            expect.ordering_observable(['a', 'a'], ['a', 'a'], "a flat fixture")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "a flat fixture is refused as a premise", failed=1, passed=0)


def test_ordering_observable_passes_when_the_directions_differ(pytester, expect):
    pytester.makepyfile(
        """
        def test_premise_holds(expect):
            expect.ordering_observable([1, 2, 3], [3, 2, 1], "a real fixture")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "a real fixture passes the premise", passed=1, failed=0)


def test_the_two_oracles_are_different_instruments(pytester, expect):
    """pgc_check_ordered_oracle's third property, ported.

    The ordered oracle must be order-SENSITIVE and the set oracle order-BLIND. Without
    this control an ordered oracle could be implemented as a set one and every
    ordering test in the tree would go silent while staying green.
    """
    pytester.makepyfile(
        """
        FWD = [1, 2, 3]
        REV = [3, 2, 1]

        def test_the_set_oracle_is_order_blind(expect):
            # Order-blind BY DESIGN: the same rows in any order compare equal.
            expect.row_set(FWD, REV, "set oracle ignores order")

        def test_the_ordered_oracle_is_order_sensitive(expect):
            # And the ordered one must NOT: this comparison has to fail.
            try:
                expect.ordered_rows(FWD, REV, "ordered oracle sees order")
            except AssertionError:
                expect.num(1, 1, "the ordered oracle refused the reversed sequence")
            else:
                raise AssertionError("the ordered oracle did not detect the reversal")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "the two oracles behave differently", passed=2, failed=0)


def test_row_set_still_refuses_two_empty_sides(pytester, expect):
    """The set oracle inherits rows()'s refusal rather than losing it."""
    pytester.makepyfile(
        """
        def test_both_empty(expect):
            expect.row_set([], [], "two empty sets")
        """
    )
    result = pytester.runpytest("-p", "pgc_vacuity")
    expect.outcomes(result, "an empty set comparison is refused", failed=1, passed=0)
