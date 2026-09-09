#!/usr/bin/env python3
"""Compare a bash suite and its pytest port PROPERTY BY PROPERTY, by name.

Counting is the wrong instrument. The bash suite has 8 checks and the port has 7
tests, and that difference is legitimate: one pytest test carries two of the bash
assertions. A count comparison calls that a defect. A name comparison does not,
and it catches the thing that matters, which is a property asserted in one
harness and nowhere in the other.

The port makes this possible by passing each assertion the SAME name string the
bash check uses. That is a convention the port must keep, so this script is also
what enforces it.
"""
import re
import sys

bash_file, py_file = sys.argv[1], sys.argv[2]

# bash: check "NAME" ... / check_num "NAME" ... / check_ratio "NAME" ...
bash_src = open(bash_file).read()
bash_names = re.findall(r'\bcheck(?:_num|_ratio|_text|_timing)?\s+"([^"]+)"', bash_src)

# pytest: expect.<helper>(..., "NAME")  and  name="NAME"
py_src = open(py_file).read()
py_names = re.findall(r'expect\.\w+\([^)]*?"([^"]+)"\s*(?:,[^)]*)?\)', py_src, re.S)
py_names += re.findall(r'name\s*=\s*"([^"]+)"', py_src)

bset, pset = set(bash_names), set(py_names)

print(f"bash checks: {len(bash_names)} ({len(bset)} distinct)")
print(f"pytest named assertions: {len(py_names)} ({len(pset)} distinct)")
print()

missing = sorted(bset - pset)
extra = sorted(pset - bset)

print("PROPERTIES IN THE BASH SUITE AND NOT IN THE PORT:")
if missing:
    for n in missing:
        print(f"  MISSING  {n}")
else:
    print("  none -- every bash property is asserted by name in the port")
print()
print("ASSERTIONS IN THE PORT AND NOT IN THE BASH SUITE:")
if extra:
    for n in extra:
        print(f"  extra    {n}")
else:
    print("  none")
print()
print("VERDICT:", "PORT IS INCOMPLETE" if missing else "every bash property is covered")
sys.exit(1 if missing else 0)
