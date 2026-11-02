"""Camera and wall geometry shared by the solver and the renderer.

Wall coordinates are (s, Y, z): s runs along the wall, Y points down, z points into
the wall. The wall surface is z = depth(s, Y), a bilinear grid that captures ledges,
set-back sections and piers. Each camera is posed relative to the wall in front of it:
it sits at (s_i, Y_i) at distance d_i, rotated by the Rodrigues vector r_i, so

    camera coords = R_i (P - C_i),   C_i = (s_i, Y_i, -d_i),

and pixels follow a pinhole with two-term radial distortion. Pixel coordinates are in
the 1/MATCH_DIV-scale images used for matching; units are the distance of a reference
camera (roughly the photographer's distance from the wall).
"""
import numpy as np

MATCH_DIV = 4
FULL_W, FULL_H = 3072, 4080          # Pixel 6 Pro main camera, portrait
FOCAL_FULL = 2835.0                  # pixels, from the 24 mm (35 mm equivalent) EXIF focal length
W, H = FULL_W // MATCH_DIV, FULL_H // MATCH_DIV
F = FOCAL_FULL / MATCH_DIV
CENTRE = np.array([W / 2, H / 2])


def rodrigues(r):
    """Rotation matrices (n, 3, 3) for Rodrigues vectors (n, 3)."""
    r = np.atleast_2d(r)
    th = np.linalg.norm(r, axis=1)[:, None, None]
    k = r / np.maximum(np.linalg.norm(r, axis=1, keepdims=True), 1e-12)
    Kx = np.zeros((len(r), 3, 3))
    Kx[:, 0, 1], Kx[:, 0, 2], Kx[:, 1, 0] = -k[:, 2], k[:, 1], k[:, 2]
    Kx[:, 1, 2], Kx[:, 2, 0], Kx[:, 2, 1] = -k[:, 0], -k[:, 1], k[:, 0]
    return np.eye(3)[None] + np.sin(th) * Kx + (1 - np.cos(th)) * Kx @ Kx


def undistort(p, k1, k2):
    """Match-res pixels -> ideal normalised image coordinates (k1, k2 may be per point)."""
    xn = (p - CENTRE) / F
    r2 = (xn ** 2).sum(1, keepdims=True)
    return xn * (1 + np.reshape(k1, (-1, 1)) * r2 + np.reshape(k2, (-1, 1)) * r2 ** 2)


def distort(xu, k1, k2):
    """Ideal normalised coordinates -> match-res pixels (inverse of undistort)."""
    k1, k2 = np.reshape(k1, (-1, 1)), np.reshape(k2, (-1, 1))
    xn = xu.copy()
    for _ in range(6):
        r2 = (xn ** 2).sum(1, keepdims=True)
        xn = xu / (1 + k1 * r2 + k2 * r2 ** 2)
    return xn * F + CENTRE


class DepthGrid:
    """Bilinear depth field z(s, Y) on a regular grid of knots."""

    def __init__(self, s0, y0, ds, dy, ns, ny):
        self.s0, self.y0, self.ds, self.dy, self.ns, self.ny = s0, y0, ds, dy, int(ns), int(ny)

    @property
    def spec(self):
        return [self.s0, self.y0, self.ds, self.dy, self.ns, self.ny]

    def weights(self, s, Y):
        """Knot indices (n, 4) and bilinear weights (n, 4) at points (s, Y)."""
        fs = np.clip((s - self.s0) / self.ds, 0, self.ns - 1 - 1e-9)
        fy = np.clip((Y - self.y0) / self.dy, 0, self.ny - 1 - 1e-9)
        i = np.minimum(fs.astype(int), self.ns - 2)
        j = np.minimum(fy.astype(int), self.ny - 2)
        ts, ty = fs - i, fy - j
        idx = np.stack([i * self.ny + j, (i + 1) * self.ny + j, i * self.ny + j + 1, (i + 1) * self.ny + j + 1], 1)
        w = np.stack([(1 - ts) * (1 - ty), ts * (1 - ty), (1 - ts) * ty, ts * ty], 1)
        return idx, w

    def eval(self, z, s, Y):
        idx, w = self.weights(s, Y)
        return (z[idx] * w).sum(1)


def camera_centres(cams):
    return np.column_stack([cams[:, 0], cams[:, 1], -cams[:, 2]])


def hit(cams, R, lens, ci, p, grid=None, z=None, iters=5):
    """Wall points hit by the rays through match-res pixels p of cameras ci.

    Returns (s, Y, depth, ray directions in wall coordinates).
    """
    q = np.column_stack([undistort(p, lens[ci, 0], lens[ci, 1]), np.ones(len(p))])
    d = np.einsum('nji,nj->ni', R[ci], q)
    C = camera_centres(cams)[ci]

    def at(depth):
        P = C + ((depth - C[:, 2]) / d[:, 2])[:, None] * d
        return P, (grid.eval(z, P[:, 0], P[:, 1]) - depth if grid is not None else 0 * depth)

    # Find where the ray meets the surface: root of g(depth) = surface depth there - depth.
    # Secant steps converge fast on smooth wall and still settle at ledges, where plain
    # fixed-point updates oscillate.
    d0 = np.zeros(len(p)); P, g0 = at(d0)
    if grid is not None:
        d1 = d0 + g0; P, g1 = at(d1)
        for _ in range(iters):
            den = g1 - g0
            ok = np.abs(den) > 1e-12
            d2 = np.where(ok, d1 - g1 * (d1 - d0) / np.where(ok, den, 1), d1)
            d2 = np.clip(d2, z.min(), z.max())
            d0, g0 = d1, g1
            d1 = d2; P, g1 = at(d1)
        P, _ = at(d1)
        depth = d1
    else:
        depth = d0
    return P[:, 0], P[:, 1], depth, d


def project(cams, R, lens, ci, s, Y, depth):
    """Match-res pixels of wall points (s, Y, depth) in cameras ci; also camera-space coords."""
    P = np.column_stack([s, Y, depth])
    c = np.einsum('nij,nj->ni', R[ci], P - camera_centres(cams)[ci])
    return distort(c[:, :2] / c[:, 2:3], lens[ci, 0], lens[ci, 1]), c


class WallModel:
    """A solved run: cameras, per-camera lens and the wall's depth field.

    `level` optionally straightens the run: a vertical offset L(s), sampled every `ds` from
    `s0`, taken off the wall's Y so its courses run level (see align.level_offsets). hit()
    and project() work in levelled coordinates; depth() takes raw ones.
    """

    def __init__(self, cams, lens, z, grid, first, last, level=None):
        self.cams = np.asarray(cams, float)
        self.lens = np.asarray(lens, float)
        self.z = np.asarray(z, float)
        self.grid = grid
        self.first, self.last = int(first), int(last)
        self.R = rodrigues(self.cams[:, 3:6])
        self.level = level

    def level_at(self, s):
        if self.level is None:
            return np.zeros_like(s)
        s0, ds, values = self.level
        return np.interp(s, s0 + ds * np.arange(len(values)), values)

    @classmethod
    def load(cls, path):
        M = np.load(path)
        cams = M['cams']
        lens = np.asarray(M['lens'], float)
        if lens.ndim == 1:
            lens = np.tile(lens, (len(cams), 1))
        level = (float(M['level_s0']), float(M['level_ds']), M['level']) if 'level' in M.files else None
        return cls(cams, lens[:, :2], M['z'], DepthGrid(*M['grid']), M['first'], M['last'], level)

    def save(self, path):
        extra = {} if self.level is None else dict(level_s0=self.level[0], level_ds=self.level[1], level=self.level[2])
        np.savez(path, cams=self.cams, lens=self.lens, z=self.z, grid=self.grid.spec, first=self.first, last=self.last, **extra)

    def depth(self, s, Y):
        return self.grid.eval(self.z, s, Y)

    def hit(self, f, p):
        """Wall (s, Y) for match-res pixels p of camera f (index within the run)."""
        s, Y, _, _ = hit(self.cams, self.R, self.lens, np.full(len(p), f), p, self.grid, self.z)
        return s, Y - self.level_at(s)

    def project(self, f, s, Y):
        """Match-res pixels in camera f of wall points (s, Y), plus their camera depth."""
        Y = Y + self.level_at(s)
        q, c = project(self.cams, self.R, self.lens, np.full(len(s), f), s, Y, self.depth(s, Y))
        return q, c[:, 2]
