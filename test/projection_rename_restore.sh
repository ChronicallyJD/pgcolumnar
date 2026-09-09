#!/usr/bin/env bash
#
# pgColumnar: a projection declaration must follow a column rename.
#
# The materialized projection records attnums and survives a rename, but the
# declaration carried by pg_dump records names. The rename hook maintained the
# table sort_by option and physical ordering mark, but not projection
# declarations. A backup therefore restored the old column name and
# rebuild_projections() failed instead of recreating the projection.
#
# This test stays at the public boundary: create, rename, pg_dump, restore,
# rebuild, and read. It does not infer correctness from internal catalog rows.
#
# Usage: test/projection_rename_restore.sh [PG_CONFIG]
# Written fresh for pgColumnar.

set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
pgc_setup "${1:-/usr/local/pg17/bin/pg_config}"

DUMP="$PGC_WORKDIR/projection-rename.sql"
RESTORE_DB="${PGC_DB}_renamed"
run() { env PATH="$PGC_BINDIR:$PATH" "$@"; }
on() { run psql -h 127.0.0.1 -p "$PGC_PORT" -U postgres -d "$1" -Atq -c "$2"; }

psql_run "CREATE TABLE prr (id int, payload text, sort_key int) USING pgcolumnar;"
psql_run "SELECT pgcolumnar.add_projection(
	'prr', 'by_sort', ARRAY['id','sort_key'], ARRAY['sort_key']);"
psql_run "INSERT INTO prr
	SELECT g, 'row-' || g, (g * 7) % 100 FROM generate_series(1,2000) g;"
psql_run "ALTER TABLE prr RENAME COLUMN sort_key TO renamed_key;"

check "the live projection still reads after the rename" \
	"$(q "SELECT count(*) FROM pgcolumnar.read_projection('prr','by_sort')")" \
	"2000"

# A rename on a non-columnar partitioned parent reaches a separate columnar
# relation with its own declaration. This protects the inheritor walk: using
# the named parent's oid in place of each descendant leaves this arm stale.
psql_run "CREATE TABLE prr_parent (id int, sort_key int)
	PARTITION BY RANGE (id);"
psql_run "CREATE TABLE prr_child PARTITION OF prr_parent
	FOR VALUES FROM (0) TO (100) USING pgcolumnar;"
psql_run "SELECT pgcolumnar.add_projection(
	'prr_child', 'child_sort', ARRAY['id','sort_key'], ARRAY['sort_key']);"
psql_run "INSERT INTO prr_parent SELECT g, g % 10 FROM generate_series(1,99) g;"
psql_run "ALTER TABLE prr_parent RENAME COLUMN sort_key TO renamed_key;"
check "the child projection still reads after a parent rename" \
	"$(q "SELECT count(*) FROM pgcolumnar.read_projection(
		'prr_child','child_sort')")" "99"

run pg_dump -h 127.0.0.1 -p "$PGC_PORT" -U postgres -d "$PGC_DB" \
	-f "$DUMP"; dump_rc=$?
check "pg_dump succeeds" "$dump_rc" "0"

on postgres "DROP DATABASE IF EXISTS $RESTORE_DB;" >/dev/null 2>&1
on postgres "CREATE DATABASE $RESTORE_DB;" >/dev/null
run psql -h 127.0.0.1 -p "$PGC_PORT" -U postgres -d "$RESTORE_DB" \
	-v ON_ERROR_STOP=1 -q -f "$DUMP" >/dev/null 2>&1; restore_rc=$?
check "restore succeeds" "$restore_rc" "0"

# Red before the fix: this errors because the declaration still names sort_key.
rebuilt="$(on "$RESTORE_DB" "SELECT pgcolumnar.rebuild_projections('prr');" 2>&1)"
check "the renamed projection rebuilds after restore" "$rebuilt" "1"
check "the rebuilt projection contains every restored row" \
	"$(on "$RESTORE_DB" \
		"SELECT count(*) FROM pgcolumnar.read_projection('prr','by_sort');")" \
	"2000"
check "the descendant declaration follows the parent rename" \
	"$(on "$RESTORE_DB" \
		"SELECT pgcolumnar.rebuild_projections('prr_child');")" "1"
check "the rebuilt child projection contains every restored row" \
	"$(on "$RESTORE_DB" \
		"SELECT count(*) FROM pgcolumnar.read_projection(
			'prr_child','child_sort');")" "99"

on postgres "DROP DATABASE $RESTORE_DB;" >/dev/null
pgc_summary
