"""Render a solved run as a straight-on view of the wall, in blended vertical strips.

Each output pixel (s, Y) is looked up on the wall's surface and fetched from the photos
through the solved cameras. Photos meet along low-difference seams chosen once for the
whole run (at low resolution), brightness is balanced across the run, and strips are
blended with multi-band blending plus a margin so strip edges never show.
"""
import os
from multiprocessing import get_context

import cv2
import numpy as np

from .geometry import FULL_H, FULL_W, MATCH_DIV, WallModel

LOW = 8                       # seams and exposure are worked out at 1/LOW of the output scale
STRIP, MARGIN = 8192, 512
BACKGROUND = (26, 26, 26)
EDGE = np.concatenate([
    np.column_stack([np.linspace(0, FULL_W, 33), np.zeros(33)]), np.column_stack([np.full(33, FULL_W), np.linspace(0, FULL_H, 33)]),
    np.column_stack([np.linspace(0, FULL_W, 33), np.full(33, FULL_H)]), np.column_stack([np.zeros(33), np.linspace(0, FULL_H, 33)])])


def to_match(p):
    # JPEG 1/MATCH_DIV decoding puts reduced pixel q at full-res MATCH_DIV*q + (MATCH_DIV-1)/2
    return (p - (MATCH_DIV - 1) / 2) / MATCH_DIV


def to_full(q):
    return q * MATCH_DIV + (MATCH_DIV - 1) / 2


def source_maps(model, f, x0, y0, x1, y1, scale):
    """Full-res source pixel maps for output rectangle [x0,x1) x [y0,y1) at `scale` px per unit."""
    s, Y = np.meshgrid((np.arange(x0, x1) + 0.5) / scale, (np.arange(y0, y1) + 0.5) / scale)
    q, depth = model.project(f, s.ravel(), Y.ravel())
    p = to_full(q)
    p[depth <= 0] = -1e6
    return p[:, 0].reshape(s.shape).astype(np.float32), p[:, 1].reshape(s.shape).astype(np.float32)


def footprint(model, f):
    s, Y = model.hit(f, to_match(EDGE))
    return np.column_stack([s, Y])


def plan(model, photo_paths, scale, y_top, y_bottom, layout_path):
    """Seams, exposure gains and the strip layout for a run; saved for the strip workers."""
    N = len(photo_paths)
    feet = [footprint(model, f) for f in range(N)]
    centres = np.array([model.hit(f, to_match(np.array([[FULL_W / 2, FULL_H / 2]])))[0][0] for f in range(N)])
    order = np.argsort(centres)

    def box(f, sc):
        fp = feet[f] * sc
        return (int(np.floor(fp[:, 0].min())), int(np.floor(max(fp[:, 1].min(), y_top * sc))),
                int(np.ceil(fp[:, 0].max())), int(np.ceil(min(fp[:, 1].max(), y_bottom * sc))))

    X0 = int(np.floor(min(fp[:, 0].min() for fp in feet) * scale)); X1 = int(np.ceil(max(fp[:, 0].max() for fp in feet) * scale))
    Y0, Y1 = int(np.floor(y_top * scale)), int(np.ceil(y_bottom * scale))

    # low-resolution warps for exposure and seams
    sl = scale / LOW
    low = []
    for f in range(N):
        x0, y0, x1, y1 = box(f, sl)
        img = cv2.imread(photo_paths[f], cv2.IMREAD_REDUCED_COLOR_8)
        u, v = source_maps(model, f, x0, y0, max(x1, x0 + 1), max(y1, y0 + 1), sl)
        warp = cv2.remap(img, u / 8, v / 8, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        valid = (u >= 8) & (u < FULL_W - 8) & (v >= 8) & (v < FULL_H - 8)
        low.append((x0, y0, warp.astype(np.float32), valid))
    LY0 = int(np.floor(Y0 / LOW)) - 1
    LH = (Y1 - Y0) // LOW + 4

    def region(f, x0, y0, x1, y1):
        bx, by, w, m = low[f]
        img = np.zeros((y1 - y0, x1 - x0, 3), np.float32); msk = np.zeros((y1 - y0, x1 - x0), bool)
        ix0, iy0, ix1, iy1 = max(x0, bx), max(y0, by), min(x1, bx + w.shape[1]), min(y1, by + w.shape[0])
        if ix0 < ix1 and iy0 < iy1:
            img[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] = w[iy0 - by:iy1 - by, ix0 - bx:ix1 - bx]
            msk[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] = m[iy0 - by:iy1 - by, ix0 - bx:ix1 - bx]
        return img, msk

    # exposure: per-photo, per-channel log gains balancing overlaps with the next two photos
    rows, rhs = [], []
    for k in range(N):
        for k2 in (k + 1, k + 2):
            if k2 >= N:
                continue
            a, b = order[k], order[k2]
            (ax, ay, aw, _), (bx, by, bw, _) = low[a], low[b]
            x0, x1 = max(ax, bx), min(ax + aw.shape[1], bx + bw.shape[1])
            y0, y1 = max(ay, by), min(ay + aw.shape[0], by + bw.shape[0])
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            A, ma = region(a, x0, y0, x1, y1); B, mb = region(b, x0, y0, x1, y1)
            both = ma & mb
            if both.sum() < 200:
                continue
            row = np.zeros(N); row[a], row[b] = 1, -1
            rows.append(row); rhs.append(np.log(B[both].mean(0) + 1) - np.log(A[both].mean(0) + 1))
    lam = 0.05
    gains = np.exp(np.linalg.lstsq(np.vstack(rows + [np.sqrt(lam) * np.eye(N)]),
                                   np.vstack(rhs + [np.zeros((N, 3))]), rcond=None)[0]) if rows else np.ones((N, 3))

    # seams: minimum-difference top-to-bottom paths between neighbours, inside a band between their centres
    seams = []
    for k in range(N - 1):
        a, b = order[k], order[k + 1]
        ca, cb = centres[a] * sl, centres[b] * sl
        d = max(cb - ca, 2.0)
        bx0 = int(ca + 0.1 * d); bx1 = max(int(cb - 0.1 * d) + 1, bx0 + 1)
        A, ma = region(a, bx0, LY0, bx1, LY0 + LH); B, mb = region(b, bx0, LY0, bx1, LY0 + LH)
        diff = cv2.GaussianBlur(np.abs(A * gains[a] - B * gains[b]).sum(2), (0, 0), 1)
        cost = np.where(ma & mb, diff, 1e4)
        acc = cost.copy(); back = np.zeros(cost.shape, np.int8)
        for y in range(1, LH):
            prev = acc[y - 1]
            st = np.vstack([np.r_[np.inf, prev[:-1]], prev, np.r_[prev[1:], np.inf]]); arg = st.argmin(0)
            acc[y] += st[arg, np.arange(len(prev))]; back[y] = arg - 1
        path = np.zeros(LH, int); path[-1] = int(acc[-1].argmin())
        for y in range(LH - 1, 0, -1):
            path[y - 1] = path[y] + back[y, path[y]]
        seams.append(path + bx0)
    boxes = np.array([box(f, scale) for f in range(N)])
    np.savez(layout_path, X0=X0, X1=X1, Y0=Y0, Y1=Y1, LY0=LY0, LH=LH, scale=scale, gains=gains,
             seams=np.array(seams, float).reshape(-1, LH), order=order, boxes=boxes)
    return X1 - X0, Y1 - Y0


_W = {}


def _init_worker(model_path, layout_path, photo_paths, out_dir):
    cv2.setNumThreads(2)
    L = np.load(layout_path)
    _W.update({k: L[k] for k in L.files})
    for k in ('X0', 'X1', 'Y0', 'Y1', 'LY0', 'LH'):
        _W[k] = int(_W[k])
    _W.update(model=WallModel.load(model_path), paths=photo_paths, out=out_dir)


def _seam_x(k, ys):
    yl = (ys + 0.5) / LOW - _W['LY0']
    return np.interp(yl, np.arange(_W['LH']), _W['seams'][k]) * LOW


def render_strip(si):
    w = _W
    X0, X1, Y0, Y1, scale, order, N = w['X0'], w['X1'], w['Y0'], w['Y1'], float(w['scale']), w['order'], len(w['order'])
    MH = Y1 - Y0
    sx0 = X0 + si * STRIP; sx1 = min(sx0 + STRIP, X1)
    rx0, rx1 = sx0 - MARGIN, sx1 + MARGIN
    involved = [k for k in range(N) if w['boxes'][order[k]][2] > rx0 and w['boxes'][order[k]][0] < rx1]
    path = os.path.join(w['out'], 'strip_%04d.jpg' % si)
    if not involved:
        cv2.imwrite(path, np.full((MH, sx1 - sx0, 3), BACKGROUND, np.uint8))
        return si
    width = rx1 - rx0
    ys, xs = np.arange(Y0, Y1), np.arange(rx0, rx1)
    label = np.full((MH, width), -1, np.int32)
    for k in involved:
        left = _seam_x(k - 1, ys) if k > 0 else np.full(MH, -np.inf)
        right = _seam_x(k, ys) if k < N - 1 else np.full(MH, np.inf)
        label[(xs[None, :] >= left[:, None]) & (xs[None, :] < right[:, None])] = k
    warps = {}
    for k in involved:
        f = order[k]
        bx0, by0, bx1, by1 = w['boxes'][f]
        x0, x1, y0, y1 = max(bx0, rx0), min(bx1, rx1), max(by0, Y0), min(by1, Y1)
        if x1 <= x0 or y1 <= y0:
            continue
        img = cv2.imread(w['paths'][f], cv2.IMREAD_COLOR)
        u, v = source_maps(w['model'], f, x0, y0, x1, y1, scale)
        warp = cv2.remap(img, u, v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        valid = (u >= 2) & (u < FULL_W - 3) & (v >= 2) & (v < FULL_H - 3)
        warps[k] = (x0, y0, warp, valid)
    # pixels whose seam owner has no data go to any neighbour that does
    have = np.zeros((MH, width), bool); masks = {}
    for k, (x0, y0, warp, valid) in warps.items():
        sl = (slice(y0 - Y0, y0 - Y0 + warp.shape[0]), slice(x0 - rx0, x0 - rx0 + warp.shape[1]))
        masks[k] = (label[sl] == k) & valid
        have[sl] |= masks[k]
    for k, (x0, y0, warp, valid) in warps.items():
        sl = (slice(y0 - Y0, y0 - Y0 + warp.shape[0]), slice(x0 - rx0, x0 - rx0 + warp.shape[1]))
        hole = valid & ~have[sl]
        masks[k] |= hole; have[sl] |= hole
    blender = cv2.detail.MultiBandBlender()
    blender.setNumBands(6)
    blender.prepare((rx0, Y0, width, MH))
    for k, (x0, y0, warp, valid) in warps.items():
        img = np.clip(warp.astype(np.float32) * w['gains'][order[k]], 0, 255).astype(np.int16)
        blender.feed(img, masks[k].astype(np.uint8) * 255, (x0, y0))
    res, res_mask = blender.blend(None, None)
    res = np.clip(res, 0, 255).astype(np.uint8)
    res[res_mask == 0] = BACKGROUND
    cv2.imwrite(path, res[:, MARGIN:MARGIN + (sx1 - sx0)], [cv2.IMWRITE_JPEG_QUALITY, 95])
    return si


def render(model_path, photo_paths, out_dir, scale, y_top, y_bottom, workers=4, log=print):
    """Render one run to out_dir/strip_NNNN.jpg; returns (width, height) in pixels."""
    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):
        if old.startswith('strip_'):
            os.remove(os.path.join(out_dir, old))
    layout = os.path.join(out_dir, 'layout.npz')
    width, height = plan(WallModel.load(model_path), photo_paths, scale, y_top, y_bottom, layout)
    n = (width + STRIP - 1) // STRIP
    log('  %d x %d px in %d strips' % (width, height, n))
    with get_context('spawn').Pool(workers, initializer=_init_worker, initargs=(model_path, layout, photo_paths, out_dir)) as pool:
        for _ in pool.imap_unordered(render_strip, range(n)):
            pass
    return width, height
