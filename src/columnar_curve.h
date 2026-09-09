/*-------------------------------------------------------------------------
 *
 * columnar_curve.h
 *	  Space-filling curve keys for clustering (#889).
 *
 * Two pure functions over uint64 ordinals. Neither touches a PostgreSQL type
 * beyond uint64, which is what lets test/hilbert_curve.sh compile this file
 * against four-line stub headers and exercise the curve with no server tree.
 *
 * The clustering key is built in two steps:
 *
 *	  Z-order:	ordinals -> cluster_pack_interleave
 *	  Hilbert:	ordinals -> cluster_hilbert_transpose -> cluster_pack_interleave
 *
 * Skilling's observation is that the Hilbert index IS the MSB-round-first
 * interleave of the TRANSPOSED coordinates -- bit for bit the same packing
 * Z-order already used. So the two curves differ by one in-place pass and
 * share everything else, including the key width.
 *
 *-------------------------------------------------------------------------
 */
#ifndef COLUMNAR_CURVE_H
#define COLUMNAR_CURVE_H

/*
 * Transform ncols 64-bit coordinates in place, from axes to the Hilbert
 * transpose (Skilling 2004, AxestoTranspose, at b = 64).
 */
extern void cluster_hilbert_transpose(uint64 *X, int ncols);

/*
 * Interleave ncols 64-bit ordinals MSB-first into out[0 .. 8*ncols-1], so that
 * memcmp order over the result equals the curve's order. Establishes every one
 * of those bytes; the caller need not clear them.
 */
extern void cluster_pack_interleave(const uint64 *ord, int ncols,
									unsigned char *out);

#endif							/* COLUMNAR_CURVE_H */
