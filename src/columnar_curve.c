/*-------------------------------------------------------------------------
 *
 * columnar_curve.c
 *	  Space-filling curve keys for clustering (#889).
 *
 * Both curves produce a fixed-width byte string whose memcmp order IS the
 * curve's order, so the rewrite can sort on it with the ordinary bytea
 * operator and nothing downstream needs to know which curve produced it.
 *
 * Held by test/hilbert_curve.sh, which compiles this file against stub headers
 * and checks the properties that define a Hilbert curve rather than the
 * arithmetic that happens to implement one: that the index set is exactly the
 * contiguous range, that consecutive indices are unit-adjacent, and that every
 * dyadic sub-cube occupies a contiguous run. The first two alone are not
 * enough -- a boustrophedon order satisfies adjacency and is not a Hilbert
 * curve, and Z-order satisfies contiguity and is the curve we already had --
 * so the suite carries both as deliberately wrong controls.
 *
 *-------------------------------------------------------------------------
 */
#include "postgres.h"

#include "columnar_curve.h"

/*
 * cluster_hilbert_transpose
 *		Axes to Hilbert transpose, in place, at b = 64 bits per coordinate.
 *
 * Skilling, "Programming the Hilbert curve", AIP Conf. Proc. 707 (2004),
 * AxestoTranspose, public domain. Transcribed with b fixed at 64 and the
 * coordinate type fixed at uint64; the structure is unchanged.
 *
 * After this returns, X holds the transpose of the Hilbert index: the index's
 * bits distributed across the ncols words so that taking bit r of every word,
 * most significant round first, spells the index. That is exactly what
 * cluster_pack_interleave then does, which is why the two curves share a
 * packer and a width.
 *
 * ncols == 1 is the identity. The Q loop's two passes cancel, the Gray encode
 * has no neighbour to fold in, and the final t is zero -- so a one-column
 * Hilbert key is the plain big-endian ordinal, byte for byte what Z-order
 * produces. The suite pins that both relatively and against fixed hex, because
 * the relative half alone would survive a packing bug that hit both curves.
 */
void
cluster_hilbert_transpose(uint64 *X, int ncols)
{
	const uint64 M = ((uint64) 1) << 63;
	uint64		P;
	uint64		Q;
	uint64		t;
	int			i;

	/* Inverse undo. */
	for (Q = M; Q > 1; Q >>= 1)
	{
		P = Q - 1;
		for (i = 0; i < ncols; i++)
		{
			if (X[i] & Q)
				X[0] ^= P;		/* invert */
			else
			{
				/* exchange */
				t = (X[0] ^ X[i]) & P;
				X[0] ^= t;
				X[i] ^= t;
			}
		}
	}

	/* Gray encode. */
	for (i = 1; i < ncols; i++)
		X[i] ^= X[i - 1];

	t = 0;
	for (Q = M; Q > 1; Q >>= 1)
	{
		if (X[ncols - 1] & Q)
			t ^= Q - 1;
	}
	for (i = 0; i < ncols; i++)
		X[i] ^= t;
}

/*
 * cluster_pack_interleave
 *		Interleave ncols ordinals MSB-first into 8*ncols bytes.
 *
 * Moved verbatim from cluster_zorder_key in columnar_vacuum.c, where it has
 * always been the second half of the Z-order key. The output bit stream is
 * ord[0].bit63, ord[1].bit63, ..., ord[n-1].bit63, ord[0].bit62, ... packed
 * MSB-first within each byte.
 *
 * Why memcmp order equals the curve's order, in two steps that are both
 * arithmetic rather than assertion. Sixty-four rounds of ncols bits fill
 * 8*ncols bytes exactly, with no padding, so the result is the fixed-width
 * big-endian base-2^ncols expansion of a single integer. And memcmp over two
 * equal-length big-endian expansions is numeric order, because the first
 * differing byte sits at place value 256^k and everything after it sums to at
 * most 256^k - 1. Every key in one rewrite has the same length, ncols being
 * fixed for the whole run, so bytea's length tie-break can never fire.
 *
 * Establishes every byte it is given rather than OR-ing into whatever was
 * there, so a caller cannot leave stale bits in the tail and a test cannot
 * mistake a memset for a key.
 */
void
cluster_pack_interleave(const uint64 *ord, int ncols, unsigned char *out)
{
	int			keybytes = ncols * 8;
	int			outbit = 0;
	int			c;
	int			r;

	memset(out, 0, keybytes);

	for (r = 63; r >= 0; r--)
	{
		for (c = 0; c < ncols; c++)
		{
			if ((ord[c] >> r) & 1)
				out[outbit >> 3] |= (unsigned char) (0x80 >> (outbit & 7));
			outbit++;
		}
	}
}
