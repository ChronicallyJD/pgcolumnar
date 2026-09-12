#!/usr/bin/env bash
#
# pgColumnar objstore: userinfo in a URL is refused on EVERY entry point (#706).
#
# The read path (os_open) and the ABI http_request refused `user@host` in an
# http(s) authority from the start: userinfo smuggles bytes into the host part,
# the classic SSRF-parser-confusion shape. The write path (os_write_handle:
# export sink, delete, list) parsed the same authority WITHOUT the guard, so a
# userinfo URL sailed past the parse with the '@' embedded in the host field.
# It still failed closed -- the allow-list match at connect cannot match a host
# with an embedded '@' -- but as the wrong error (42501, an allow-list refusal)
# with the userinfo bytes carried through the handle, and fail-closed-by-
# accident is one endpoint-matching refactor away from not failing at all.
#
# These arms need no object-store server: both the guard (22023) and the
# allow-list refusal (42501) fire before any network I/O. The SQLSTATE is the
# discriminator -- 22023 comes only from the parse guards, 42501 only from the
# allow-list -- and the message arm pins WHICH 22023 guard fired.
#
# Removal proof: revert the os_write_handle guard and the write arms read
# 42501 again while the read arms stay 22023.
#
# Usage:  test/objstore_userinfo.sh [PG_CONFIG]
# Written fresh for pgColumnar.

set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
export PGC_EXTRA_CONF="pgcolumnar.objstore_allowed_endpoints='127.0.0.1'"
pgc_setup "${1:-/usr/local/pg17/bin/pg_config}"

q "CREATE EXTENSION IF NOT EXISTS pgcolumnar;" >/dev/null
q "CREATE TABLE ex (id int, v text) USING pgcolumnar;
   INSERT INTO ex SELECT g, 'v'||g FROM generate_series(1,100) g;" >/dev/null

sqlstate_of() {
	env PATH="$PGC_BINDIR:$PATH" psql -h 127.0.0.1 -p "$PGC_PORT" -U postgres \
		-d "$PGC_DB" -qtA 2>&1 <<SQLEOF | sed -n 's/^ERROR:  \([0-9A-Z]\{5\}\).*/\1/p' | head -1
\\set VERBOSITY sqlstate
$1;
SQLEOF
}

msg_of() {
	env PATH="$PGC_BINDIR:$PATH" psql -h 127.0.0.1 -p "$PGC_PORT" -U postgres \
		-d "$PGC_DB" -qtA -c "$1" 2>&1 | grep -c 'userinfo'
}

# msg_of answers only "does the message say userinfo", so a control built on it asserts an
# ABSENCE. That is not enough here: 28000 is raised by THREE different demands in
# os_resolve_s3 -- a missing endpoint, a missing credential, and the allow-list's own
# authorization refusal -- so a control that sees 28000 and no `userinfo` has not pinned
# WHICH refusal fired. Reported by @jdatcmd in review on #997.
msg_has() {	# msg_has SQL PATTERN -> count of matches in the ERROR MESSAGE alone
	# The message alone, not the whole output: the HINT beside it also names the
	# variable ("Set AWS_ENDPOINT_URL and restart"), so counting every line gives 2
	# and the arm would be pinned to how many places the hint mentions it rather
	# than to which refusal fired.
	env PATH="$PGC_BINDIR:$PATH" psql -h 127.0.0.1 -p "$PGC_PORT" -U postgres \
		-d "$PGC_DB" -qtA -c "$1" 2>&1 | sed -n 's/^ERROR:  //p' | grep -c -- "$2"
}

URL="http://u:p@127.0.0.1:1/x.parquet"

# --- premise: the read path refuses userinfo with the parse guard ------------
check "read_parquet refuses userinfo (22023, the parse guard)" \
	"$(sqlstate_of "SELECT * FROM pgcolumnar.read_parquet('$URL') AS t(v int)")" "22023"
check "and the read_parquet message names userinfo" \
	"$(msg_of "SELECT * FROM pgcolumnar.read_parquet('$URL') AS t(v int)")" "1"

# --- the gap: the write path must refuse with the SAME guard -----------------
# Pre-fix these read 42501: the parse admits the URL and the '@'-carrying host
# then fails the allow-list at connect -- fail closed, wrong reason.
check "export_parquet refuses userinfo (22023, not an allow-list 42501)" \
	"$(sqlstate_of "SELECT pgcolumnar.export_parquet('ex', '$URL')")" "22023"
check "and the export_parquet message names userinfo" \
	"$(msg_of "SELECT pgcolumnar.export_parquet('ex', '$URL')")" "1"
check "export_arrow refuses userinfo through the same handle (22023)" \
	"$(sqlstate_of "SELECT pgcolumnar.export_arrow('ex', 'http://u@127.0.0.1:1/x.arrow')")" "22023"

# --- the same gap on the s3/gs path, which was never closed (#995) -----------
#
# Measured on main with an endpoint configured: the userinfo is percent-encoded
# INTO THE BUCKET NAME -- `HEAD /u%3Ap%40pgc-bucket/vh.parquet`, Host untouched --
# and the caller is told the object does not exist, which is true and useless. The
# object does not exist because we made `u:p@pgc-bucket` a bucket name. Under
# virtual-host addressing the same string becomes the leftmost label of the
# hostname and fails at DNS.
#
# Nothing splits the authority at '@', so this is a wrong-reason defect rather
# than an SSRF. The write path is the half with a consequence: `export_parquet`
# raised NO error and PUT to a bucket the caller never named.
#
# NO OBJECT-STORE SERVER IS NEEDED. The guard is in the bucket parse, which runs
# BEFORE the endpoint is resolved, so it fires whether or not one is configured --
# which is also why these arms can live in this suite beside the http ones.
S3UI="s3://u:p@mybucket/x.parquet"
check "read_parquet refuses userinfo in an s3:// bucket authority (22023)" \
	"$(sqlstate_of "SELECT * FROM pgcolumnar.read_parquet('$S3UI') AS t(v int)")" "22023"
check "and the s3 read message names userinfo" \
	"$(msg_of "SELECT * FROM pgcolumnar.read_parquet('$S3UI') AS t(v int)")" "1"
check "a gs:// bucket authority is refused by the same guard" \
	"$(sqlstate_of "SELECT * FROM pgcolumnar.read_parquet('gs://u@mybucket/x.parquet') AS t(v int)")" "22023"
check "export_parquet refuses it on the WRITE path too, where acceptance writes to a bucket nobody named" \
	"$(sqlstate_of "SELECT pgcolumnar.export_parquet('ex', '$S3UI')")" "22023"
check "and the s3 write message names userinfo" \
	"$(msg_of "SELECT pgcolumnar.export_parquet('ex', '$S3UI')")" "1"

# THE CONTROL, without which the five arms above are worth nothing. My first probe
# of this gap proved exactly nothing: with no credentials every s3 URL returned
# 28000, the CLEAN ONE INCLUDED, so a userinfo refusal was indistinguishable from
# an unreachable object store. A clean URL must still reach the endpoint demand.
check "control: a clean s3:// URL is not refused as userinfo, it demands an endpoint" \
	"$(sqlstate_of "SELECT * FROM pgcolumnar.read_parquet('s3://mybucket/x.parquet') AS t(v int)")" "28000"
check "control: and that refusal NAMES AWS_ENDPOINT_URL, pinning which 28000 fired" \
	"$(msg_has "SELECT * FROM pgcolumnar.read_parquet('s3://mybucket/x.parquet') AS t(v int)" \
		'AWS_ENDPOINT_URL')" "1"
check "control: and it does not name userinfo, so the new guard did not fire on it" \
	"$(msg_of "SELECT * FROM pgcolumnar.read_parquet('s3://mybucket/x.parquet') AS t(v int)")" "0"
# The gs arm's 28000 is a DIFFERENT demand from the s3 arm's, which is the whole reason the
# two controls above are needed: gs defaults its endpoint to the interop host and then
# demands a credential, so it never reaches the endpoint demand at all.
check "control: the gs:// refusal names a CREDENTIAL, not the endpoint -- same 28000, other cause" \
	"$(msg_has "SELECT * FROM pgcolumnar.read_parquet('gs://mybucket/x.parquet') AS t(v int)" \
		'AWS_ACCESS_KEY_ID')" "1"
check "control: a malformed s3:// URL is still the bucket/key refusal, naming no userinfo" \
	"$(msg_of "SELECT * FROM pgcolumnar.read_parquet('s3://nokey') AS t(v int)")" "0"
# The false positive this guard could plausibly have: '@' is legal in an S3 KEY,
# and refusing one would break a working read. The guard scans only up to the first
# slash, so the key is outside it -- asserted rather than trusted to the comment.
check "control: an '@' in the KEY is not userinfo, and is not refused as it" \
	"$(msg_of "SELECT * FROM pgcolumnar.read_parquet('s3://mybucket/my@file.parquet') AS t(v int)")" "0"
check "control: and such a URL still reaches the endpoint demand, so it was not refused earlier" \
	"$(sqlstate_of "SELECT * FROM pgcolumnar.read_parquet('s3://mybucket/my@file.parquet') AS t(v int)")" "28000"

# --- the allow-list still does its own job on a clean URL --------------------
# The guard must not have swallowed the 42501 class: a userinfo-free URL to a
# non-allowed endpoint is still the allow-list's refusal.
check "a clean URL to a non-allowed endpoint is still the allow-list's 42501" \
	"$(sqlstate_of "SELECT pgcolumnar.export_parquet('ex', 'http://127.0.0.2:1/x.parquet')")" "42501"

check "backend alive" "$(q 'SELECT 1;')" "1"

pgc_summary
