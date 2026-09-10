#!/usr/bin/env bash
# Serial join runtime filter public-seam regression (#752).
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
pgc_setup "${1:-/usr/lib/postgresql/18/bin/pg_config}"
q "CREATE EXTENSION IF NOT EXISTS pgcolumnar; CREATE TABLE d(k int);
INSERT INTO d SELECT g FROM generate_series(8001,8200) g; INSERT INTO d VALUES(8100),(NULL);
CREATE TABLE f(k int,p text) USING pgcolumnar;
SELECT pgcolumnar.set_options('f',stripe_row_limit=>1000);
INSERT INTO f SELECT g,repeat(md5(g::text),8) FROM generate_series(1,20000) g;
CREATE TABLE h AS SELECT * FROM f; ANALYZE d; ANALYZE f;" >/dev/null
pc(){ env PATH="$PGC_BINDIR:$PATH" psql -h 127.0.0.1 -p "$PGC_PORT" -U postgres -d "$PGC_DB" -At -v ON_ERROR_STOP=1 -c "$1" 2>&1; }
SQL="SELECT count(*),sum(f.k),sum(length(f.p)) FROM f JOIN d ON f.k=d.k"
rf_on=""
rf_off=""
if [[ "$(pc "SELECT current_setting('pgcolumnar.enable_join_runtime_filter', true) IS NOT NULL" | tail -1)" == t ]]; then
  rf_on="SET pgcolumnar.enable_join_runtime_filter=on;"
  rf_off="SET pgcolumnar.enable_join_runtime_filter=off;"
fi
base="$(pc "${rf_off}SET max_parallel_workers_per_gather=0;SET enable_nestloop=off;SET enable_mergejoin=off;EXPLAIN(ANALYZE,TIMING off,SUMMARY off)$SQL")"
on="$(pc "${rf_on}SET max_parallel_workers_per_gather=0;SET enable_nestloop=off;SET enable_mergejoin=off;EXPLAIN(ANALYZE,TIMING off,SUMMARY off)$SQL")"
val(){ sed -n "s/.*$1: \([0-9]*\).*/\1/p" <<<"$2" | head -1; }
check "baseline core Hash Join" "$(grep -c 'Hash Join' <<<"$base")" 1
check "baseline reads all groups" "$(val 'Columnar Chunk Groups Read' "$base")" 20
check "plan has runtime coordinator" "$(grep -c 'Columnar Runtime Filter Coordinator' <<<"$on")" 1
check "plan has build tap" "$(grep -c 'Columnar Runtime Filter Build Tap' <<<"$on")" 1
check "plan retains core Hash Join" "$(grep -c 'Hash Join' <<<"$on")" 1
check "build rows omit NULL" "$(val 'Runtime Filter Build Rows' "$on")" 201
check "filter ready before scan" "$(grep -c 'Runtime Filter Ready: true' <<<"$on")" 1
check "clustered groups removed" "$(val 'Runtime Filter Groups Removed' "$on")" 19
check "clustered reads fewer groups" "$(val 'Columnar Chunk Groups Read' "$on")" 1
check "runtime answer equals off" "$(pc "${rf_on}$SQL"|tail -1)" "$(pc "${rf_off}$SQL"|tail -1)"
check "runtime answer equals heap" "$(pc "${rf_on}$SQL"|tail -1)" "$(q 'SELECT count(*),sum(h.k),sum(length(h.p)) FROM h JOIN d ON h.k=d.k')"
for shape in \
 "LEFT|SELECT count(*) FROM f LEFT JOIN d ON f.k=d.k" \
 "SEMI|SELECT count(*) FROM f WHERE EXISTS(SELECT 1 FROM d WHERE d.k=f.k)" \
 "ANTI|SELECT count(*) FROM f WHERE NOT EXISTS(SELECT 1 FROM d WHERE d.k=f.k)" \
 "CROSS|SELECT count(*) FROM f JOIN (SELECT k::bigint k FROM d)x ON f.k=x.k"; do
 n=${shape%%|*}; s=${shape#*|}; p="$(pc "${rf_on}EXPLAIN $s")"; check "$n refusal" "$(grep -c 'Columnar Runtime Filter Coordinator'<<<"$p")" 0
done
pgc_summary
