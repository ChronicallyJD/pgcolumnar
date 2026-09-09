# ---- plan_marker must have all three of its guards ---------------------------
#
# WHY THIS EXISTS. @jdatcmd's #897 review named `plan_marker` as the guard to fix
# first: "both of its arms can be deleted independently with the suite green.
# Under one of those mutations the premise can never fail, so the provider-trap
# test would silently be about an ordinary plan."
#
# He was right, and it is the worst place in the layer for it to be true.
# plan_marker is the faithful port of pgc_is_columnar_scan; test_connection.py
# calls it three times, once as the PREMISE that the vectorized aggregate
# engaged. A premise that cannot fail turns its test into a test about an
# ordinary plan, and the test stays green while it happens.
#
# A THIRD HOLE SAT UNDER BOTH ARMS. An absence claim is satisfied by nothing
# being there at all: `plan_marker([], key, absent=True)` gave `1 passed`, exit 0,
# because a plan that never arrived looks exactly like a plan that legitimately
# lacks the node. That is now a refusal.
#
# WHY THE CHECKS ARE STATIC, same division as selftest 360. The behaviour is
# pinned by five arms in test/pytest/test_guards_pinned.py that run pytest inside
# pytest; those need pytest, psycopg and a virtualenv, and CI installs none of
# them. This half asserts the STRUCTURE they rest on, greppable from a checkout
# with nothing installed.

_pm_vac="$PGC_TESTDIR/pytest/pgc_vacuity.py"

check "premise: the pytest layer is where this part thinks it is" \
	"$([ -f "$_pm_vac" ] && echo yes || echo no)" "yes"

# The function body, cut out once so every arm below reads the same text. A
# grep over the WHOLE file would match these shapes wherever they occur and
# report a guard present that lives in another method.
_pm_body="$(awk '/^    def plan_marker\(/{f=1} f&&/^    def /&&!/plan_marker/{exit} f' "$_pm_vac")"

check "premise: plan_marker's body was actually cut out of the file" \
	"$([ "$(printf '%s\n' "$_pm_body" | wc -l)" -ge 20 ] && echo yes || echo "too short")" "yes"

# The present arm: asked "does this plan carry the marker", a plan that does not
# must fail.
check "plan_marker keeps the arm that fails when the key is absent" \
	"$(printf '%s\n' "$_pm_body" | grep -c 'if not absent and not found:')" "1"

# The absent arm: `absent=True` is how a test pins that a plan is NOT a scan.
check "plan_marker keeps the arm that fails when the key is present" \
	"$(printf '%s\n' "$_pm_body" | grep -c 'if absent and found:')" "1"

# And the refusal under both of them.
check "plan_marker refuses a plan with no nodes at all" \
	"$(printf '%s\n' "$_pm_body" | grep -c 'if not nodes:')" "1"

check "and that refusal is a VacuityError, not an ordinary assertion" \
	"$(printf '%s\n' "$_pm_body" | grep -A2 'if not nodes:' | grep -c 'raise VacuityError')" "1"

# The refusal has to come BEFORE the walk that sets `found`, or it is dead code:
# an empty plan leaves found=False and the absent arm returns a pass first.
_pm_ln_empty="$(printf '%s\n' "$_pm_body" | grep -n 'if not nodes:' | cut -d: -f1)"
_pm_ln_absent="$(printf '%s\n' "$_pm_body" | grep -n 'if absent and found:' | cut -d: -f1)"
check "premise: both line numbers were found, so the ordering arm can mean something" \
	"$([ -n "$_pm_ln_empty" ] && [ -n "$_pm_ln_absent" ] && echo yes || echo no)" "yes"

check "the empty-plan refusal precedes the arm it protects" \
	"$([ "$_pm_ln_empty" -lt "$_pm_ln_absent" ] && echo before || echo "AFTER, so it is dead code")" \
	"before"

# ---- and these greps must be able to FAIL -----------------------------------
#
# Every arm above passes on a healthy tree, which a grep that matches nothing
# also does. Each fixture is the real shape with ONE property removed.

_pm_fix="$PGC_WORKDIR/planmarker"; rm -rf "$_pm_fix"; mkdir -p "$_pm_fix"

printf '        if False and not absent and not found:\n' > "$_pm_fix/present.py"
check "a neutered present arm is caught" \
	"$(grep -c 'if not absent and not found:' "$_pm_fix/present.py")" "0"

printf '        if False and absent and found:\n' > "$_pm_fix/absent.py"
check "a neutered absent arm is caught" \
	"$(grep -c 'if absent and found:' "$_pm_fix/absent.py")" "0"

printf '        if False and not nodes:\n' > "$_pm_fix/empty.py"
check "a neutered empty-plan refusal is caught" \
	"$(grep -c 'if not nodes:' "$_pm_fix/empty.py")" "0"

# The mirror of the three above: the same greps on the REAL body return 1, so a
# zero is a missing guard rather than a broken pattern.
check "premise: while the real body satisfies all three, so the greps work" \
	"$(printf '%s\n' "$_pm_body" | grep -cE 'if not absent and not found:|if absent and found:|if not nodes:')" \
	"3"

unset _pm_vac _pm_body _pm_fix _pm_ln_empty _pm_ln_absent
