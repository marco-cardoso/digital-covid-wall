"""Merge overlapping solved pieces of a run into one model."""
import cv2
import numpy as np

from .geometry import H, W, DepthGrid, WallModel, rodrigues

SAMPLE = np.array([(x, y) for y in np.linspace(20, H - 20, 9) for x in np.linspace(20, W - 20, 7)])
JUNCTION_SIGMA = 1.5          # photos around the hand-over that the fit concentrates on


def fit_transform(pa, pb, weights, rounds=3):
    """Similarity with a small rotation, pa ~ M pb + t, M = [[p, -q], [q, p]].

    Returns (p, q, b, c) and the weighted median residual. Each piece's ends settle on a
    fractionally different scale and level, so the fit is weighted towards the photos where
    one piece hands over to the next.
    """
    keep = np.ones(len(pa), bool)
    for _ in range(rounds):
        w = np.sqrt(weights[keep])
        n = keep.sum()
        A = np.zeros((2 * n, 4)); r = np.zeros(2 * n)
        A[0::2] = np.column_stack([pb[keep, 0], -pb[keep, 1], np.ones(n), np.zeros(n)]) * w[:, None]
        A[1::2] = np.column_stack([pb[keep, 1], pb[keep, 0], np.zeros(n), np.ones(n)]) * w[:, None]
        r[0::2], r[1::2] = pa[keep, 0] * w, pa[keep, 1] * w
        p, q, b, c = np.linalg.lstsq(A, r, rcond=None)[0]
        err = np.hypot(p * pb[:, 0] - q * pb[:, 1] + b - pa[:, 0], q * pb[:, 0] + p * pb[:, 1] + c - pa[:, 1])
        near = weights > 0.5 * weights.max()
        keep = err <= max(3 * np.median(err[near]), 1e-6)
    near = weights > 0.5 * weights.max()
    return (p, q, b, c), float(np.median(err[near]))


# A transform between pieces is (p, q, b, c, e): (s, Y) -> M (s, Y) + (b, c) with
# M = [[p, -q], [q, p]], and depth z -> |M| z + e (each piece fixes its own depth zero).

def compose(t1, t2):
    """t1 after t2."""
    p1, q1, b1, c1, e1 = t1; p2, q2, b2, c2, e2 = t2
    return (p1 * p2 - q1 * q2, p1 * q2 + q1 * p2, p1 * b2 - q1 * c2 + b1, q1 * b2 + p1 * c2 + c1, np.hypot(p1, q1) * e2 + e1)


def apply_points(t, s, Y):
    p, q, b, c = t[:4]
    return p * s - q * Y + b, q * s + p * Y + c


def invert(t):
    p, q, b, c, e = t
    k = p * p + q * q
    pi, qi = p / k, -q / k
    return (pi, qi, -(pi * b - qi * c), -(qi * b + pi * c), -e / np.sqrt(k))


def transform_camera(cam, t):
    """Camera params expressed in the target piece's coordinates."""
    p, q, b, c, e = t
    scale, theta = np.hypot(p, q), np.arctan2(q, p)
    out = cam.copy()
    out[0], out[1] = apply_points(t, cam[0], cam[1])
    out[2] = scale * cam[2] - e           # centre depth -d maps to -(scale*d) + e
    Rz = np.array([[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1.0]])
    R = rodrigues(cam[3:6][None])[0] @ Rz.T
    out[3:6] = cv2.Rodrigues(R)[0].ravel()
    return out


def merge(models, log=print):
    """Express every piece in the first piece's coordinates and combine them.

    Pieces are given in wall order and must overlap. Cameras up to the middle of each
    overlap come from the earlier piece, the rest from the later one, and each piece owns
    the depth field on its side of that hand-over.
    """
    T = [(1.0, 0.0, 0.0, 0.0, 0.0)]
    junctions = []
    for A, B in zip(models, models[1:]):
        junction = (B.first + A.last) // 2
        pa, pb, wt = [], [], []
        for f in range(B.first, A.last + 1):
            pa.append(np.column_stack(A.hit(f - A.first, SAMPLE)))
            pb.append(np.column_stack(B.hit(f - B.first, SAMPLE)))
            wt.append(np.full(len(SAMPLE), np.exp(-0.5 * ((f - junction - 0.5) / JUNCTION_SIGMA) ** 2)))
        pa, pb, wt = np.vstack(pa), np.vstack(pb), np.concatenate(wt)
        t, err = fit_transform(pa, pb, wt)
        # depth zero offset: the same wall points, measured in both pieces, near the hand-over
        near = wt > 0.5 * wt.max()
        dz = A.depth(pa[near, 0], pa[near, 1]) - np.hypot(t[0], t[1]) * B.depth(pb[near, 0], pb[near, 1])
        t = tuple(t) + (float(np.median(dz)),)
        # pa is in A's frame; take B into the first piece's frame through A's
        T.append(compose(T[-1], t))
        junctions.append(junction)
        log('  piece %d..%d joins at photo %d: scale %.4f, tilt %+.2f deg, depth offset %+.3f, residual %.5f units' % (
            B.first, B.last, junction, np.hypot(t[0], t[1]), np.degrees(np.arctan2(t[1], t[0])), t[4], err))

    first, last = models[0].first, models[-1].last
    owner_of = lambda g: int(np.searchsorted(junctions, g, side='left'))     # photo <= junction -> earlier piece
    cams = np.zeros((last - first + 1, 6)); lens = np.zeros((last - first + 1, 2))
    for g in range(first, last + 1):
        k = owner_of(g)
        m = models[k]
        cams[g - first] = transform_camera(m.cams[g - m.first], T[k])
        lens[g - first] = m.lens[g - m.first]

    # one depth grid in the first piece's frame; each piece owns it up to the hand-over line
    cuts = np.array([(cams[j - first, 0] + cams[j + 1 - first, 0]) / 2 for j in junctions])
    g0 = models[0].grid
    corners = []
    for m, t in zip(models, T):
        gs = m.grid
        for s_ in (gs.s0, gs.s0 + gs.ds * (gs.ns - 1)):
            for y_ in (gs.y0, gs.y0 + gs.dy * (gs.ny - 1)):
                corners.append(apply_points(t, s_, y_))
    corners = np.array(corners)
    s0, y0 = corners.min(0)
    ns = int(np.ceil((corners[:, 0].max() - s0) / g0.ds)) + 1
    ny = int(np.ceil((corners[:, 1].max() - y0) / g0.dy)) + 1
    grid = DepthGrid(s0, y0, g0.ds, g0.dy, ns, ny)
    S_, Y_ = np.meshgrid(s0 + g0.ds * np.arange(ns), y0 + g0.dy * np.arange(ny), indexing='ij')
    S_, Y_ = S_.ravel(), Y_.ravel()
    owner = np.searchsorted(cuts, S_)
    z = np.zeros(ns * ny)
    for k, (m, t) in enumerate(zip(models, T)):
        sel = owner == k
        sb, yb = apply_points(invert(t), S_[sel], Y_[sel])
        z[sel] = np.hypot(t[0], t[1]) * m.depth(sb, yb) + t[4]
    return WallModel(cams, lens, z, grid, first, last)
