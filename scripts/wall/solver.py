"""Joint solve of camera poses, lens distortion and the wall's depth field for one run.

Unknowns: per camera (s, Y, d, rx, ry, rz); globally lens k1, k2 and the run's shared
aim (yaw, pitch); and the depth grid z(s, Y). Residuals:
  * matches: a point seen in photo i, cast onto the wall and re-projected into photo j,
    must land on its match (both directions), with Huber weighting;
  * lines: long horizontal / vertical segments in each photo stay horizontal / vertical
    on the wall;
  * priors: each photo aims near the run's shared aim; the photographer walked at a
    roughly constant distance and phone height (otherwise a slight phone yaw is
    indistinguishable from drifting closer to the wall, and it compounds over hundreds
    of photos); the depth grid is smooth along the wall and its mean stays near zero.
Least squares by Levenberg-Marquardt on sparse normal equations. Camera derivatives are
finite differences, colouring cameras so no residual sees two perturbed cameras at once.
"""
import numpy as np
from scipy.sparse import coo_matrix, csr_matrix, diags, vstack
from scipy.sparse.linalg import spsolve

from .features import NEIGH
from .geometry import F, H, W, DepthGrid, WallModel, hit, project, rodrigues

STEP = NEIGH + 1
LINE_SCALE = 1 / np.radians(0.5)       # line residual unit: 0.5 degree
HUBER = 2.0
SD_STEP, SD_ALL = 0.03, 0.15           # walk prior: change between shots, spread over the run
GRID_DS, GRID_DY = 1.0, 0.05
SMOOTH_S, SMOOTH_Y2, SMOOTH_Y1, SECTION_MEAN, SECTION_LEAN = 0.01, 0.03, 0.3, 0.1, 0.05
MAX_POINTS = 80                        # matches used per photo pair


class RunSolver:
    def __init__(self, links, hlines, vlines, log=print, seed=0):
        """links: {(i, j): (pa, pb)} with indices local to the run; lines: per photo arrays."""
        self.log = log
        self.N = N = len(hlines)
        self.links = links
        self._init_cameras()
        self._observations(np.random.default_rng(seed))
        self.LH = np.concatenate([np.full(len(h), f) for f, h in enumerate(hlines)]).astype(int)
        self.LV = np.concatenate([np.full(len(v), f) for f, v in enumerate(vlines)]).astype(int)
        cat = lambda ls, a, b: np.concatenate([l[:, a:b] for l in ls]) if self.N else np.zeros((0, 2))
        self.H1, self.H2 = cat(hlines, 0, 2), cat(hlines, 2, 4)
        self.V1, self.V2 = cat(vlines, 0, 2), cat(vlines, 2, 4)
        self.ref = N // 2
        self.ref_pos = self.X[self.ref, :3].copy()
        self.angle_sigma = np.radians(2.0)
        self.lens_sigma = np.array([1e-4, 1e-4, 0.3, 0.3])    # k1, k2 held until the geometry settles
        I = np.eye(N); D = np.diff(I, axis=0); C0 = I - 1.0 / N; Z = np.zeros_like(D); Z0 = np.zeros_like(C0)
        self.walk_op = csr_matrix(np.vstack([np.hstack([D / SD_STEP, Z]), np.hstack([C0 / SD_ALL, Z0]),
                                             np.hstack([Z, D / SD_STEP]), np.hstack([Z0, C0 / SD_ALL])]))

    # ---------------------------------------------------------------- setup
    def _init_cameras(self):
        """Fronto-parallel cameras at unit distance, placed by chaining median image shifts."""
        self.X = np.zeros((self.N, 6)); self.X[:, 2] = 1.0
        for i in range(1, self.N):
            prev = max(k for (k, j) in self.links if j == i)
            pa, pb = self.links[(prev, i)]
            du, dv = np.median(pa - pb, axis=0)
            self.X[i, 0] = self.X[prev, 0] + du / F
            self.X[i, 1] = self.X[prev, 1] + dv / F

    def _observations(self, rng):
        oA, oB, pA, pB, oPair = [], [], [], [], []
        self.plist = sorted(self.links)
        for pid, (i, j) in enumerate(self.plist):
            pa, pb = self.links[(i, j)]
            # keep the wall: anything moving far less (the building behind it) is background
            med = np.median(pa - pb, axis=0)
            near = np.hypot(*(pa - pb - med).T) < 0.2 * np.hypot(*med)
            pa, pb = pa[near], pb[near]
            if len(pa) < 20:
                continue
            chunks = np.array_split(np.argsort(pa[:, 1]), 8)     # stratify so every height is represented
            k = np.concatenate([rng.choice(c, min(len(c), MAX_POINTS // 8), replace=False) for c in chunks if len(c)])
            oA.append(np.full(len(k), i)); oB.append(np.full(len(k), j)); pA.append(pa[k]); pB.append(pb[k]); oPair.append(np.full(len(k), pid))
        if not oA:            # a single photo: only its lines and the priors pose it
            oA, oB, oPair, pA, pB = [[np.zeros(0, int)]] * 3 + [[np.zeros((0, 2))]] * 2
        self.oA, self.oB, self.oPair = np.concatenate(oA), np.concatenate(oB), np.concatenate(oPair)
        self.pA, self.pB = np.concatenate(pA).astype(float), np.concatenate(pB).astype(float)
        # pairs that keep the chain connected are never pruned away entirely
        self.protect = {pid for pid, (i, j) in enumerate(self.plist) if j == i + 1 or (i, i + 1) not in self.links}

    def make_grid(self, margin=1.0):
        cams, lens = self.X, np.tile(self.lens()[:2], (self.N, 1))
        corners = np.array([[0, 0], [W, 0], [W, H], [0, H]], float)
        s, Y, _, _ = hit(cams, rodrigues(cams[:, 3:6]), lens, np.repeat(np.arange(self.N), 4), np.tile(corners, (self.N, 1)))
        s0, y0 = s.min() - margin, Y.min() - margin
        self.set_grid(DepthGrid(s0, y0, GRID_DS, GRID_DY, int(np.ceil((s.max() + margin - s0) / GRID_DS)) + 2,
                                int(np.ceil((Y.max() + margin - y0) / GRID_DY)) + 2), np.zeros(4))

    def set_grid(self, g, lens_aim, z=None):
        nk = g.ns * g.ny
        idx = np.arange(nk).reshape(g.ns, g.ny)
        def diff(a, b, w):
            r = np.arange(a.size)
            return coo_matrix((np.r_[np.full(a.size, -w), np.full(a.size, w)], (np.r_[r, r], np.r_[a.ravel(), b.ravel()])), shape=(a.size, nk))
        a, b, c = idx[:, :-2].ravel(), idx[:, 1:-1].ravel(), idx[:, 2:].ravel(); r = np.arange(a.size)
        yc = (np.arange(g.ny) - (g.ny - 1) / 2) * g.dy
        cols = np.repeat(np.arange(g.ns), g.ny)
        self.grid_op = vstack([
            diff(idx[:-1], idx[1:], 1 / SMOOTH_S),                      # smooth along the wall
            diff(idx[:, :-1], idx[:, 1:], 1 / SMOOTH_Y1),               # flat where unobserved
            coo_matrix((np.r_[np.full(a.size, 1 / SMOOTH_Y2), np.full(a.size, -2 / SMOOTH_Y2), np.full(a.size, 1 / SMOOTH_Y2)],
                        (np.r_[r, r, r], np.r_[a, b, c])), shape=(a.size, nk)),   # step-tolerant up the wall
            # Each section of wall keeps its mean depth near zero and does not lean: depth offset
            # and lean are otherwise interchangeable with camera distance and pitch. Per-section
            # rows keep the normal equations sparse (a whole-wall row would couple every knot).
            coo_matrix((np.full(nk, 1 / (g.ny * SECTION_MEAN)), (cols, idx.ravel())), shape=(g.ns, nk)),
            coo_matrix((np.tile(yc / ((yc ** 2).sum() * SECTION_LEAN), g.ns), (cols, idx.ravel())), shape=(g.ns, nk)),
        ]).tocsr()
        self.grid = g
        self.params = np.concatenate([self.X.ravel(), lens_aim, np.zeros(nk) if z is None else z])

    def init_from(self, model):
        """Start from an existing solution (e.g. merged pieces) instead of the fronto-parallel chain."""
        self.X = model.cams.copy()
        self.ref_pos = self.X[self.ref, :3].copy()
        self.set_grid(model.grid, np.r_[np.median(model.lens, axis=0), 0.0, 0.0], model.z.copy())

    # ---------------------------------------------------------------- model
    def unpack(self, params):
        N = self.N
        return params[:6 * N].reshape(N, 6), params[6 * N:6 * N + 4], params[6 * N + 4:]

    def lens(self):
        return self.unpack(self.params)[1] if hasattr(self, 'params') else np.zeros(4)

    def layout(self):
        m = len(self.oA)
        o = dict(m=m, lh=4 * m); o['lv'] = o['lh'] + len(self.LH); o['pr'] = o['lv'] + len(self.LV)
        o['g'] = o['pr'] + 2 * self.N; o['walk'] = o['g'] + 3; o['ln'] = o['walk'] + 4 * self.N - 2; o['zg'] = o['ln'] + 4
        return o

    def residuals(self, params):
        cams, gl, z = self.unpack(params)
        lens = np.tile(gl[:2], (self.N, 1)); R = rodrigues(cams[:, 3:6]); g = self.grid
        s1, y1, z1, _ = hit(cams, R, lens, self.oA, self.pA, g, z); q1, _ = project(cams, R, lens, self.oB, s1, y1, z1)
        s2, y2, z2, _ = hit(cams, R, lens, self.oB, self.pB, g, z); q2, _ = project(cams, R, lens, self.oA, s2, y2, z2)
        out = [np.concatenate([q1 - self.pB, q2 - self.pA]).ravel()]
        for L, A1, A2, horiz in ((self.LH, self.H1, self.H2, True), (self.LV, self.V1, self.V2, False)):
            sa, ya, _, _ = hit(cams, R, lens, L, A1, g, z); sb, yb, _, _ = hit(cams, R, lens, L, A2, g, z)
            ds, dy = sb - sa, yb - ya; n = np.hypot(ds, dy)
            out.append((dy / n * np.sign(ds + 1e-12) if horiz else ds / n * np.sign(dy + 1e-12)) * LINE_SCALE)
        ax = R[:, 2]
        out.append(np.column_stack([np.arctan2(ax[:, 0], ax[:, 2]) - gl[2],
                                    np.arctan2(-ax[:, 1], np.hypot(ax[:, 0], ax[:, 2])) - gl[3]]).ravel() / self.angle_sigma)
        out.append((cams[self.ref, :3] - self.ref_pos) * 1e4)
        out.append(self.walk_op @ cams[:, 1:3].T.ravel())
        out.append(gl / self.lens_sigma)
        out.append(self.grid_op @ z)
        return np.concatenate(out)

    def jacobian(self, params, r0):
        cams, gl, z = self.unpack(params)
        N, L, m = self.N, self.layout(), len(self.oA)
        ncol = len(params); zo = 6 * N + 4
        rows, cols, vals = [], [], []
        eps = 1e-6
        fa2, fb2 = np.r_[self.oA, self.oB], np.r_[self.oB, self.oA]
        for c in range(STEP):
            for k in range(6):
                pp = params.copy(); pp[:6 * N].reshape(N, 6)[c::STEP, k] += eps
                d = (self.residuals(pp) - r0) / eps
                fa = np.where(fa2 % STEP == c, fa2, np.where(fb2 % STEP == c, fb2, -1))
                sel = np.nonzero(fa >= 0)[0]
                rr = np.r_[2 * sel, 2 * sel + 1]
                rows.append(rr); cols.append(np.r_[fa[sel], fa[sel]] * 6 + k); vals.append(d[rr])
                for off, LL in ((L['lh'], self.LH), (L['lv'], self.LV)):
                    sel = np.nonzero(LL % STEP == c)[0]
                    rows.append(off + sel); cols.append(LL[sel] * 6 + k); vals.append(d[off + sel])
                fr = np.arange(c, N, STEP)
                rr = np.r_[L['pr'] + 2 * fr, L['pr'] + 2 * fr + 1]
                rows.append(rr); cols.append(np.r_[fr, fr] * 6 + k); vals.append(d[rr])
        rows.append(L['g'] + np.arange(3)); cols.append(self.ref * 6 + np.arange(3)); vals.append(np.full(3, 1e4))
        wk = self.walk_op.tocoo()
        rows.append(L['walk'] + wk.row); cols.append(np.where(wk.col < N, wk.col * 6 + 1, (wk.col - N) * 6 + 2)); vals.append(wk.data)
        for k in range(4):           # lens and shared aim touch every match / line / aim row
            if self.lens_sigma[k] < 1e-3:
                continue
            pp = params.copy(); pp[6 * N + k] += eps
            d = (self.residuals(pp) - r0) / eps
            nz = np.nonzero(d[:L['g']])[0]
            rows.append(nz); cols.append(np.full(len(nz), 6 * N + k)); vals.append(d[nz])
        rows.append(L['ln'] + np.arange(4)); cols.append(6 * N + np.arange(4)); vals.append(1 / self.lens_sigma)
        # depth knots, analytically: moving the surface slides each hit point along its ray
        lens = np.tile(gl[:2], (N, 1)); R = rodrigues(cams[:, 3:6]); g = self.grid
        for frm, to, pts, base in ((self.oA, self.oB, self.pA, 0), (self.oB, self.oA, self.pB, m)):
            s, Y, dz, ray = hit(cams, R, lens, frm, pts, g, z)
            _, cc = project(cams, R, lens, to, s, Y, dz)
            dc = np.einsum('nij,nj->ni', R[to], ray / ray[:, 2:3])
            du = F * (dc[:, 0] / cc[:, 2] - cc[:, 0] * dc[:, 2] / cc[:, 2] ** 2)
            dv = F * (dc[:, 1] / cc[:, 2] - cc[:, 1] * dc[:, 2] / cc[:, 2] ** 2)
            idx, w = g.weights(s, Y)
            ru = 2 * (base + np.arange(len(pts)))
            rows += [np.repeat(ru, 4), np.repeat(ru + 1, 4)]; cols += [idx.ravel() + zo] * 2
            vals += [(w * du[:, None]).ravel(), (w * dv[:, None]).ravel()]
        for LL, A1, A2, off, horiz in ((self.LH, self.H1, self.H2, L['lh'], True), (self.LV, self.V1, self.V2, L['lv'], False)):
            if not len(LL):
                continue
            sa, ya, _, da = hit(cams, R, lens, LL, A1, g, z); sb, yb, _, db = hit(cams, R, lens, LL, A2, g, z)
            ds, dy = sb - sa, yb - ya; n3 = np.hypot(ds, dy) ** 3
            sg = (np.sign(ds + 1e-12) if horiz else np.sign(dy + 1e-12)) * LINE_SCALE
            dr_s, dr_y = (-sg * dy * ds / n3, sg * ds * ds / n3) if horiz else (sg * dy * dy / n3, -sg * ds * dy / n3)
            rr = off + np.arange(len(LL))
            for se, ye, de, sign in ((sb, yb, db, 1.0), (sa, ya, da, -1.0)):
                gz = sign * (dr_s * de[:, 0] / de[:, 2] + dr_y * de[:, 1] / de[:, 2])
                idx, w = g.weights(se, ye)
                rows.append(np.repeat(rr, 4)); cols.append(idx.ravel() + zo); vals.append((w * gz[:, None]).ravel())
        G = self.grid_op.tocoo()
        rows.append(G.row + L['zg']); cols.append(G.col + zo); vals.append(G.data)
        return csr_matrix((np.concatenate([np.asarray(v, float) for v in vals]),
                           (np.concatenate([np.asarray(v) for v in rows]), np.concatenate([np.asarray(v) for v in cols]))),
                          shape=(len(r0), ncol))

    def solve(self, iters=40):
        params = self.params
        r = self.residuals(params); L = self.layout()
        robust = np.zeros(len(r), bool); robust[:L['pr']] = True
        def cost(r):
            a = np.abs(r)
            return np.sum(np.where(robust & (a >= HUBER), HUBER * (a - 0.5 * HUBER), 0.5 * r ** 2))
        def weights(r):
            w = np.ones(len(r)); a = np.abs(r[robust]); w[robust] = np.where(a < HUBER, 1.0, HUBER / np.maximum(a, 1e-12)); return w
        c, lam = cost(r), 1e-3
        for it in range(iters):
            J = self.jacobian(params, r)
            JW = J.T.multiply(weights(r)).tocsr()
            A = (JW @ J).tocsc(); g = JW @ r; dg = A.diagonal()
            while True:
                pn = params + spsolve(A + diags(lam * dg + 1e-9), -g)
                rn = self.residuals(pn); cn = cost(rn)
                if cn < c:
                    lam = max(lam / 3, 1e-9); break
                lam *= 4
                if lam > 1e8:
                    break
            if lam > 1e8:
                break
            done = (c - cn) < 1e-7 * c
            params, r, c = pn, rn, cn
            if done:
                break
        self.params, self.r = params, r
        return r

    def prune(self, thresh):
        r, m = self.r, len(self.oA)
        err = np.maximum(np.hypot(*r[:2 * m].reshape(m, 2).T), np.hypot(*r[2 * m:4 * m].reshape(m, 2).T))
        keep = err < thresh
        for pid in self.protect:
            sel = np.nonzero(self.oPair == pid)[0]
            if len(sel) and keep[sel].sum() < 15:
                keep[sel[np.argsort(err[sel])[:15]]] = True
        self.oA, self.oB, self.pA, self.pB, self.oPair = (a[keep] for a in (self.oA, self.oB, self.pA, self.pB, self.oPair))
        return m - keep.sum()

    def stats(self):
        L, r = self.layout(), self.r
        mm = r[:L['lh']]; lr = r[L['lh']:L['pr']] / LINE_SCALE
        cams, gl, _ = self.unpack(self.params)
        med = lambda a: float(np.median(np.abs(a))) if len(a) else float('nan')
        return dict(match_median=med(mm), match_rms=float(np.sqrt(np.mean(mm ** 2))) if len(mm) else float('nan'),
                    line_median_deg=float(np.degrees(med(lr))),
                    dist=(float(cams[:, 2].min()), float(cams[:, 2].max())), k1=float(gl[0]), k2=float(gl[1]))

    def run(self):
        """The full schedule: settle with cameras held frontal, free the lens, then prune outliers."""
        self.make_grid()
        self.solve(iters=200); self.log('  settled', self.stats())
        self.angle_sigma = np.radians(6.0)
        self.lens_sigma = np.array([0.1, 0.1, 0.3, 0.3])
        self.solve(iters=200); self.log('  relaxed', self.stats())
        for th in (40, 12, 5, 3):
            n = self.prune(th)
            self.solve(); self.log('  pruned %d above %d px' % (n, th), self.stats())
        cams, gl, z = self.unpack(self.params)
        return cams, np.tile(gl[:2], (self.N, 1)), z


def refine_run(model, links, hlines, vlines, log=print):
    """A few joint iterations over a whole run, starting from merged pieces.

    Pieces solved separately bend slightly near their ends (photos there have neighbours
    on one side only); solving the run as one removes the bends at the hand-overs.
    """
    first, last = model.first, model.last
    local = {(i - first, j - first): v for (i, j), v in links.items() if first <= i and j <= last}
    s = RunSolver(local, hlines, vlines, log=log)
    s.init_from(model)
    s.angle_sigma = np.radians(6.0)
    s.lens_sigma = np.array([0.1, 0.1, 0.3, 0.3])
    s.solve(iters=6); log('  joint', s.stats())
    for th in (12, 5, 3):
        n = s.prune(th)
        s.solve(iters=6); log('  joint, pruned %d above %d px' % (n, th), s.stats())
    cams, gl, z = s.unpack(s.params)
    return WallModel(cams, np.tile(gl[:2], (s.N, 1)), z, s.grid, first, last)


def solve_run(first, last, links, hlines, vlines, log=print):
    """Solve photos first..last (global indices); links keyed by global (i, j)."""
    local = {(i - first, j - first): v for (i, j), v in links.items() if first <= i and j <= last}
    solver = RunSolver(local, hlines, vlines, log=log)
    cams, lens, z = solver.run()
    return WallModel(cams, lens, z, solver.grid, first, last)
