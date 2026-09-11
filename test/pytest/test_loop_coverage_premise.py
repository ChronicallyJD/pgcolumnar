"""A loop that never runs asserts nothing, and the run still reports a pass.

WHAT THIS CLOSES, AND WHAT IT DOES NOT. `assert-inside-a-loop-over-zero-rows` in
VACUITY_MODES.md 3.5 is TWO shapes, and the layer already refuses one of them.

**Already refused.** If a loop's body holds the test's ONLY counted assertions, a
zero-trip loop leaves the count at 0 and `pytest_runtest_call` raises `VacuityError`.
Measured, on a planted test rather than by reading the hook:

    only assertion inside a zero-trip loop   VacuityError: made no counted assertion
    the same loop with one row               1 passed

So that half needs nothing, and this file does not pretend to add it.

**Still open, and what this file is for.** When the test ALSO asserts outside the
loop, the count is non-zero, the test passes, and the loop's assertions simply never
ran. Nothing notices. That is the shape a query returning no rows produces, and the
one a glob matching nothing produces.

THE POPULATION, measured over the whole corpus before this was written:

    non-empty by construction (literal, range, local literal)   20  cannot be zero-trip
    derived, loop holds the only assertions                      0  already refused
    derived, WITH assertions outside the loop                    2  AT RISK

Both at-risk loops already carry a premise, so this arm goes green on arrival. That is
the point rather than a weakness: the property is true today and nothing was holding it
there, so the next loop added without a premise is what this catches. It is not
insurance against an imagined shape -- it has a population of two and locks it in.

WHY THE RULE IS LOOSER THAN THE PROPERTY, said plainly. The honest requirement is "a
premise bounding the cardinality of THIS iterable". What is enforced is "a counted
assertion outside the loop that takes `len(...)` of something". The two differ, and the
reason is dataflow: `test_harness_deps.py`'s loop iterates `sorted(found)` while its
premise bounds `len(files)` -- `found` is built FROM `files` inside the loop that
precedes it. Matching premise to iterable through that needs more than a name
comparison, and a rule that demanded the names match would reject the correct code.
So this checks that a cardinality premise EXISTS, and a reviewer checks that it is the
right one.
"""

import ast
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def _counted(node):
    """An `expect.<assertion>(...)` call. `cannot_run` is excluded: it declares a test
    unrunnable rather than concluding anything, so it is not a conclusion to count."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "expect"
            and node.func.attr != "cannot_run")


def _nonempty_by_construction(fn, iterable):
    """True when the iterable cannot be empty, so a premise would assert nothing.

    A literal with elements, a `range(...)`, or a name bound in this function to a
    non-empty literal -- including through `.items()`, which is how the corpus spells
    a table of cases. Twenty of the corpus's twenty-two such loops are this.
    """
    if isinstance(iterable, (ast.List, ast.Tuple, ast.Set)) and iterable.elts:
        return True
    if (isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Name)
            and iterable.func.id == "range"):
        return True
    target = None
    if (isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Attribute)
            and iterable.func.attr in ("items", "keys", "values")):
        target = iterable.func.value
    elif isinstance(iterable, ast.Name):
        target = iterable
    if isinstance(target, ast.Name):
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == target.id for t in node.targets):
                value = node.value
                if isinstance(value, ast.Dict) and value.keys:
                    return True
                if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and value.elts:
                    return True
    return False


def _has_cardinality_premise(fn, loop):
    """A counted assertion OUTSIDE the loop whose arguments take `len(...)`."""
    inside = {id(n) for n in ast.walk(loop)}
    for node in ast.walk(fn):
        if id(node) in inside or not _counted(node):
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id == "len"):
                    return True
    return False


def unpremised_loops(directory):
    """-> ["file:line in test_name", ...] for every at-risk loop with no premise."""
    out = []
    for path in sorted(pathlib.Path(directory).glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                   and n.name.startswith("test_")]:
            counted_in_fn = [c for c in ast.walk(fn) if _counted(c)]
            for loop in [n for n in ast.walk(fn)
                         if isinstance(n, (ast.For, ast.AsyncFor))]:
                inner = [c for c in ast.walk(loop) if _counted(c)]
                if not inner:
                    continue
                if _nonempty_by_construction(fn, loop.iter):
                    continue
                # The loop holding every assertion is already refused at runtime.
                if len(counted_in_fn) == len(inner):
                    continue
                if not _has_cardinality_premise(fn, loop):
                    out.append(f"{path.name}:{loop.lineno} in {fn.name}")
    return out


def test_every_at_risk_loop_carries_a_coverage_premise(expect):
    """The corpus itself. Green on arrival, and that is the point."""
    offenders = unpremised_loops(HERE)
    expect.text(", ".join(offenders) or "none", "none",
                "every derived loop carrying an assertion has a cardinality premise")


def test_the_sweep_finds_the_loops_it_is_meant_to_police(expect):
    """The coverage premise this file's own sweep needs.

    A sweep that parses nothing reports no offenders, which is exactly what a clean
    corpus reports. So count the loops it classified, not just the ones it rejected.
    """
    total = 0
    for path in sorted(HERE.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for loop in [n for n in ast.walk(fn)
                         if isinstance(n, (ast.For, ast.AsyncFor))]:
                if any(_counted(c) for c in ast.walk(loop)):
                    total += 1
    expect.at_least(total, 15,
                    "premise: the sweep found loops carrying assertions to classify")


def test_a_loop_with_no_premise_is_caught(tmp_path, expect):
    """The removal proof, with the control beside it.

    The fixture is the real shape with one property removed -- the premise -- rather
    than an empty file, because an empty file is caught by a sweep that does nothing.
    """
    bad = tmp_path / "test_bad.py"
    bad.write_text(
        "def test_x(expect):\n"
        "    rows = query()\n"
        "    expect.num(1, 1, 'something outside the loop')\n"
        "    for r in rows:\n"
        "        expect.num(r, 1, 'never runs when rows is empty')\n",
        encoding="utf-8")
    expect.text(", ".join(unpremised_loops(tmp_path)), "test_bad.py:4 in test_x",
                "a derived loop with no cardinality premise is named")

    good = tmp_path / "test_good.py"
    good.write_text(
        "def test_y(expect):\n"
        "    rows = query()\n"
        "    expect.at_least(len(rows), 1, 'premise: the query returned rows')\n"
        "    for r in rows:\n"
        "        expect.num(r, 1, 'runs at least once')\n",
        encoding="utf-8")
    bad.unlink()
    expect.text(", ".join(unpremised_loops(tmp_path)) or "none", "none",
                "control: the same loop with a premise is clean")


def test_a_bounded_loop_needs_no_premise(tmp_path, expect):
    """A literal cannot be empty, so demanding a premise would be noise.

    Three spellings, because the corpus uses all three and a rule that rejected any of
    them would be edited away rather than obeyed.
    """
    for name, iterable in (("lit", "[1, 2]"), ("rng", "range(3)"),
                           ("dct", "cases.items()")):
        f = tmp_path / f"test_{name}.py"
        pre = "    cases = {'a': 1}\n" if name == "dct" else ""
        f.write_text(
            f"def test_{name}(expect):\n{pre}"
            "    expect.num(1, 1, 'outside')\n"
            f"    for r in {iterable}:\n"
            "        expect.num(1, 1, 'inside')\n",
            encoding="utf-8")
        expect.text(", ".join(unpremised_loops(tmp_path)) or "none", "none",
                    f"a loop over {name} is non-empty by construction")
        f.unlink()


def test_the_layer_already_refuses_a_loop_holding_every_assertion(expect):
    """The measured half, so this file does not claim the whole mode.

    `pytest_runtest_call` fails a test whose counted-assertion count is 0, which is
    what a zero-trip loop leaves behind when it holds them all. Read off the hook
    rather than re-run inside pytest: the behaviour is pinned by `test_layer.py`, and
    what matters here is that THIS file's sweep deliberately skips that shape.
    """
    import inspect
    import pgc_vacuity
    src = inspect.getsource(pgc_vacuity.pytest_runtest_call)
    expect.at_least(src.count("count == 0"), 1,
                    "the layer fails a test that counted nothing")
    mine = inspect.getsource(unpremised_loops)
    expect.at_least(mine.count("len(counted_in_fn) == len(inner)"), 1,
                    "and this sweep skips that shape rather than double-reporting it")
