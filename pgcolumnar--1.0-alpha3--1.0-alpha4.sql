/*
 * pgcolumnar--1.0-alpha3--1.0-alpha4.sql
 *
 * Upgrade from 1.0-alpha3 to 1.0-alpha4.
 *
 * 1.0-alpha3 is a PUBLISHED pre-release (tag v1.0-alpha3, 2026-09-03), so
 * pgcolumnar--1.0-alpha2--1.0-alpha3.sql is a shipped artifact and must not
 * change. Adding these functions there would leave two databases both reporting
 * 1.0-alpha3 with different function sets and no upgrade path between them --
 * exactly what extension versioning exists to prevent.
 */


-- The two Hilbert clustering verbs (#889). New functions, so plain CREATE: an
-- alpha2 install has neither name. They mirror cluster() and recluster()
-- element for element in argument types, variadic element type, return type and
-- volatility, because the two pairs are one surface and a caller switches
-- between them by name alone.

CREATE FUNCTION pgcolumnar.cluster_hilbert(
	tablename regclass,
	VARIADIC columns name[])
	RETURNS void
	LANGUAGE C
	AS 'MODULE_PATHNAME', 'pgcolumnar_cluster_hilbert';

COMMENT ON FUNCTION pgcolumnar.cluster_hilbert(regclass, name[])
	IS 'eager reorg on the Hilbert curve: as cluster(), but the rows are ordered by the Hilbert index over the given columns, which keeps neighbouring keys neighbouring in storage more tightly than Z-order does. Holds AccessExclusiveLock like CLUSTER/VACUUM FULL; the online counterpart is recluster_hilbert() (#889)';

CREATE FUNCTION pgcolumnar.recluster_hilbert(
	tablename regclass,
	VARIADIC columns name[])
	RETURNS bigint
	LANGUAGE C
	AS 'MODULE_PATHNAME', 'pgcolumnar_recluster_hilbert';

COMMENT ON FUNCTION pgcolumnar.recluster_hilbert(regclass, name[])
	IS 'lazy online reclustering on the Hilbert curve: as recluster(), but re-establishes Hilbert clustering over the given columns under ShareUpdateExclusiveLock (concurrent reads and writes). The curve is sticky -- plain recluster() maintains a Hilbert table rather than converting it, and naming this verb is how a Z-ordered table is switched (#889)';
