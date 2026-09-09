#!/usr/bin/env bash
#
# pgColumnar: DROP COLUMN must not invalidate a materialized projection.
#
# Projections are extension metadata rather than pg_depend objects. PostgreSQL
# therefore accepted DROP COLUMN even when a projection stored that column.
# Dropping its sort key left the projection's attnum pointing at a dropped
# pg_attribute row; the next INSERT failed in lookup_type_cache with
# "type with OID 0 does not exist", making the table unwritable.
#
# Until projections can participate in DROP ... CASCADE, reject the dependent
# DROP at its public DDL boundary and tell the operator to drop the projection.
#
# Usage: test/projection_drop_column.sh [PG_CONFIG]
# Written fresh for pgColumnar.

set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
pgc_setup "${1:-/usr/local/pg17/bin/pg_config}"

sqlstate_as() {
	local role="$1" sql="$2" out code
	out="$(env PATH="$PGC_BINDIR:$PATH" psql -h 127.0.0.1 -p "$PGC_PORT" \
		-U "$role" -d "$PGC_DB" -Atq -v VERBOSITY=verbose \
		-c "\\set VERBOSITY verbose" -c "$sql" 2>&1)"
	code="$(printf '%s\n' "$out" |
		sed -n 's/.*ERROR:[[:space:]]*\([0-9A-Z]\{5\}\):.*/\1/p' |
		head -1)"
	if [ -n "$code" ]; then printf '%s\n' "$code"; else printf '00000\n'; fi
}
sqlstate() { sqlstate_as postgres "$1"; }

psql_run "CREATE TABLE pdc (id int, payload text, sort_key int) USING pgcolumnar;"
psql_run "SELECT pgcolumnar.add_projection(
	'pdc', 'by_sort', ARRAY['id','sort_key'], ARRAY['sort_key']);"
psql_run "INSERT INTO pdc
	SELECT g, 'row-' || g, g % 10 FROM generate_series(1,1000) g;"

# The pre-statement dependency check must not tell a stranger which column the
# projection covers, or let that role take the lock retained by the owner path.
psql_run "CREATE ROLE pdc_nobody LOGIN;"
check "a non-owner learns nothing from a projected column" \
	"$(sqlstate_as pdc_nobody 'ALTER TABLE pdc DROP COLUMN sort_key;')" "42501"
check "the same non-owner error is returned for an unprojected column" \
	"$(sqlstate_as pdc_nobody 'ALTER TABLE pdc DROP COLUMN payload;')" "42501"

# Red before the fix: PostgreSQL accepts this (00000), and the next INSERT
# reaches the projection writer with a type OID of zero.
check "dropping a projected column is refused as a dependency" \
	"$(sqlstate 'ALTER TABLE pdc DROP COLUMN sort_key;')" "2BP01"

psql_run "INSERT INTO pdc VALUES (1001, 'still-writable', 1);"
check "the rejected DDL leaves the table writable" \
	"$(q 'SELECT count(*) FROM pdc')" "1001"
check "and the projection still receives the row" \
	"$(q "SELECT count(*) FROM pgcolumnar.read_projection('pdc','by_sort')")" \
	"1001"

# A column outside every projection remains ordinary DDL.
psql_run "ALTER TABLE pdc DROP COLUMN payload;"
psql_run "INSERT INTO pdc VALUES (1002, 2);"
check "dropping an unrelated column remains allowed" \
	"$(q 'SELECT count(*) FROM pdc')" "1002"

# A partitioned parent has no storage itself, but DROP COLUMN recurses into its
# columnar partitions. The dependency check must walk the same hierarchy.
psql_run "CREATE TABLE pdc_parent (id int, sort_key int)
	PARTITION BY RANGE (id);"
psql_run "CREATE TABLE pdc_child PARTITION OF pdc_parent
	FOR VALUES FROM (0) TO (100) USING pgcolumnar;"
psql_run "SELECT pgcolumnar.add_projection(
	'pdc_child', 'child_sort', ARRAY['id','sort_key'], ARRAY['sort_key']);"
psql_run "INSERT INTO pdc_parent VALUES (1, 1);"
check "a parent DROP sees projections on columnar partitions" \
	"$(sqlstate 'ALTER TABLE pdc_parent DROP COLUMN sort_key;')" "2BP01"
psql_run "INSERT INTO pdc_parent VALUES (2, 2);"
check "the rejected parent DDL leaves its partition writable" \
	"$(q 'SELECT count(*) FROM pdc_parent')" "2"

pgc_summary
