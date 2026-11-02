"""Tests for the wall stitching pipeline, on synthetic walls with known geometry."""
import json
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wall import align, features, merge, render, solver, tiles  # noqa: E402
from wall.geometry import (F, FULL_H, FULL_W, H, W, DepthGrid, WallModel, distort, hit,  # noqa: E402
                           project, rodrigues, undistort)


# ---------------------------------------------------------------- synthetic scene
def ledge_grid(s0=-3.0, s1=12.0):
    """A wall whose upper part is set back by 0.15 units above Y = -0.1."""
    g = DepthGrid(s0, -1.5, 0.5, 0.05, int((s1 - s0) / 0.5) + 1, 61)
    _, Y = np.meshgrid(np.arange(g.ns), g.y0 + g.dy * np.arange(g.ny), indexing='ij')
    return g, np.where(Y.ravel() < -0.1, 0.15, 0.0)


def synthetic_model(n=8, spacing=0.45, yaw_deg=1.0, k1=-0.04):
    g, z = ledge_grid()
    cams = np.zeros((n, 6))
    cams[:, 0] = spacing * np.arange(n)
    cams[:, 1] = 0.02 * np.sin(np.arange(n))
    cams[:, 2] = 1.0 + 0.03 * np.cos(np.arange(n))
    cams[:, 4] = np.radians(yaw_deg)          # rotation about Y: a slight, consistent phone yaw
    lens = np.tile([k1, 0.02], (n, 1))
    return WallModel(cams, lens, z, g, 0, n - 1)


def synthetic_links(model, rng, per_pair=300):
    """Ground-truth matches: wall points seen by neighbouring cameras."""
    links = {}
    n = len(model.cams)
    for i in range(n):
        for j in range(i + 1, min(i + 1 + features.NEIGH, n)):
            p = rng.uniform([10, 10], [W - 10, H - 10], (per_pair * 3, 2))
            s, Y = model.hit(i, p)
            q, depth = model.project(j, s, Y)
            ok = (q[:, 0] > 5) & (q[:, 0] < W - 5) & (q[:, 1] > 5) & (q[:, 1] < H - 5) & (depth > 0)
            if ok.sum() >= 60:
                links[(i, j)] = (p[ok][:per_pair], q[ok][:per_pair] + rng.normal(0, 0.2, (ok.sum(), 2))[:per_pair])
    return links


def synthetic_lines(model):
    """Each photo sees three long horizontal courses and one vertical joint."""
    hl, vl = [], []
    for f, cam in enumerate(model.cams):
        hs, vs = [], []
        for Y in (-0.5, 0.0, 0.35):
            q, _ = model.project(f, cam[0] + np.array([-0.25, 0.25]), np.array([Y, Y]))
            hs.append(np.r_[q[0], q[1]])
        q, _ = model.project(f, np.array([cam[0] + 0.1] * 2), np.array([0.1, 0.4]))
        vs.append(np.r_[q[0], q[1]])
        hl.append(np.array(hs)); vl.append(np.array(vs))
    return hl, vl


# ---------------------------------------------------------------- geometry
def test_distortion_round_trip():
    p = np.random.default_rng(1).uniform([0, 0], [W, H], (500, 2))
    back = distort(undistort(p, -0.05, 0.04), -0.05, 0.04)
    assert np.abs(back - p).max() < 1e-6


def test_levelling_shifts_wall_heights_consistently():
    m = synthetic_model()
    p = np.random.default_rng(8).uniform([0, 0], [W, H], (200, 2))
    s, Y = m.hit(2, p)
    m.level = (0.0, 1.0, np.array([0.0, 0.1, 0.3, 0.3]))
    s2, Y2 = m.hit(2, p)
    assert np.allclose(s2, s) and np.allclose(Y - Y2, m.level_at(s))
    q, _ = m.project(2, s2, Y2)
    assert np.abs(q - p).max() < 1e-4


def test_hit_and_project_are_inverse_on_a_profiled_wall():
    m = synthetic_model()
    p = np.random.default_rng(2).uniform([0, 0], [W, H], (400, 2))
    s, Y = m.hit(3, p)
    q, depth = m.project(3, s, Y)
    assert np.abs(q - p).max() < 1e-4
    assert (depth > 0).all()
    # points on the set-back upper section really are deeper
    assert np.allclose(m.depth(s[Y < -0.2], Y[Y < -0.2]), 0.15)


def test_depth_grid_weights_interpolate():
    g = DepthGrid(0, 0, 1, 1, 3, 3)
    z = np.arange(9, dtype=float)                # z = 3*i + j
    idx, w = g.weights(np.array([0.5, 1.25]), np.array([0.5, 1.75]))
    assert np.allclose(w.sum(1), 1)
    assert np.allclose(g.eval(z, np.array([0.5, 1.25]), np.array([0.5, 1.75])), [2.0, 5.5])


def test_rodrigues_is_a_rotation():
    R = rodrigues(np.array([[0.1, -0.2, 0.3], [0, 0, 0]]))
    assert np.allclose(R[0] @ R[0].T, np.eye(3)) and np.allclose(R[1], np.eye(3))


# ---------------------------------------------------------------- photos, links and runs
def test_list_photos_skips_copies_and_landscape_shots(tmp_path):
    rng = np.random.default_rng(3)
    portrait = rng.integers(0, 255, (64, 48, 3), np.uint8)
    cv2.imwrite(str(tmp_path / 'a.jpg'), portrait)
    (tmp_path / 'a - Copy.jpg').write_bytes((tmp_path / 'a.jpg').read_bytes())
    cv2.imwrite(str(tmp_path / 'b.jpg'), rng.integers(0, 255, (64, 48, 3), np.uint8))
    cv2.imwrite(str(tmp_path / 'sign.jpg'), rng.integers(0, 255, (48, 64, 3), np.uint8))
    (tmp_path / 'clip.mp4').write_bytes(b'')
    assert features.list_photos(tmp_path) == ['a - Copy.jpg', 'b.jpg']


def test_plan_runs_follows_links_and_bridges():
    links = {(0, 1): 0, (1, 2): 0, (3, 4): 0, (4, 6): 0, (5, 6): 0, (8, 9): 0}
    assert features.plan_runs(10, links) == [(0, 2), (3, 6), (7, 7), (8, 9)]


def test_bridge_candidates_reach_across_a_break():
    links = {(i, i + 1): 0 for i in range(9) if i != 4}
    cands = features.bridge_candidates(10, links)
    assert (3, 5) in cands and (4, 6) in cands and (2, 5) in cands
    assert all(a <= 4 < b and b - a <= features.NEIGH for a, b in cands)


def test_split_run_covers_with_overlap():
    parts = features.split_run(117, 517)
    assert parts[0][0] == 117 and parts[-1][1] == 517
    assert all(b - a + 1 <= 150 for a, b in parts)
    assert all(nxt[0] <= prev[1] - 19 for prev, nxt in zip(parts, parts[1:]))
    assert features.split_run(0, 40) == [(0, 40)]


# ---------------------------------------------------------------- solving
@pytest.fixture(scope='module')
def solved():
    truth = synthetic_model()
    links = synthetic_links(truth, np.random.default_rng(4))
    hl, vl = synthetic_lines(truth)
    model = solver.solve_run(0, len(truth.cams) - 1, links, hl, vl, log=lambda *a: None)
    return truth, model


def test_solver_recovers_camera_layout(solved):
    truth, model = solved

    def to_wall(mdl):
        # distance from each camera to the wall surface it looks at (the depth plane is a gauge)
        centre = np.array([[W / 2, H / 2]])
        return np.array([c[2] + mdl.depth(*mdl.hit(f, centre))[0] for f, c in enumerate(mdl.cams)])

    ref = len(truth.cams) // 2
    tw, mw = to_wall(truth), to_wall(model)
    t_s, m_s = truth.cams[:, 0] / tw[ref], model.cams[:, 0] / mw[ref]
    assert np.allclose(np.diff(m_s), np.diff(t_s), atol=0.01)                 # spacing along the wall
    assert np.allclose(mw / mw[ref], tw / tw[ref], atol=0.02)                 # distance, no drift
    assert abs(model.lens[0, 0] - truth.lens[0, 0]) < 0.02


def test_solver_maps_matches_consistently(solved):
    truth, model = solved
    p = np.random.default_rng(5).uniform([100, 100], [W - 300, H - 100], (200, 2))
    s, Y = truth.hit(2, p)
    q_true, _ = truth.project(3, s, Y)
    sm, Ym = model.hit(2, p)
    q_model, _ = model.project(3, sm, Ym)
    assert np.median(np.hypot(*(q_model - q_true).T)) < 0.5


def test_solver_poses_a_lone_photo_from_its_lines():
    truth = synthetic_model(n=1)
    truth.cams[0, 5] = np.radians(2.0)          # phone rolled 2 degrees
    truth.R = rodrigues(truth.cams[:, 3:6])
    hl, vl = synthetic_lines(truth)
    model = solver.solve_run(0, 0, {}, hl, vl, log=lambda *a: None)
    # the courses come out level once posed
    for h in hl[0]:
        s, Y = model.hit(0, np.array([h[:2], h[2:]]))
        assert abs(np.degrees(np.arctan2(Y[1] - Y[0], s[1] - s[0]))) < 0.3


# ---------------------------------------------------------------- merging and aligning
def test_merge_recovers_overlapping_pieces():
    m = synthetic_model(n=10)
    # piece 2 lives in its own units, slightly tilted, with its own depth zero
    a, theta, b, c, e = 1.3, np.radians(0.6), 0.7, -0.2, 0.09
    t_true = (a * np.cos(theta), a * np.sin(theta), b, c, e)

    def piece(first, last, t=None):
        if t is None:
            return WallModel(m.cams[first:last + 1], m.lens[first:last + 1], m.z, m.grid, first, last)
        inv = merge.invert(t)
        cams = np.array([merge.transform_camera(cam, inv) for cam in m.cams[first:last + 1]])
        # resample the depth field onto a grid in the piece's own coordinates
        g = DepthGrid(-3.0, -2.0, 0.25, 0.025, 61, 161)
        S_, Y_ = np.meshgrid(g.s0 + g.ds * np.arange(g.ns), g.y0 + g.dy * np.arange(g.ny), indexing='ij')
        s_w, y_w = merge.apply_points(t, S_.ravel(), Y_.ravel())
        return WallModel(cams, m.lens[first:last + 1], (m.depth(s_w, y_w) - e) / a, g, first, last)

    merged = merge.merge([piece(0, 6), piece(3, 9, t_true)], log=lambda *x: None)
    assert (merged.first, merged.last) == (0, 9)
    assert np.allclose(merged.cams, m.cams, atol=1e-6)
    # photos from both pieces see the wall the same way after the merge
    for f in (2, 7):
        p = np.random.default_rng(f).uniform([50, 50], [W - 50, H - 50], (100, 2))
        s_t, y_t = m.hit(f, p); s_m, y_m = merged.hit(f, p)
        err = np.hypot(s_m - s_t, y_m - y_t)
        assert np.median(err) < 1e-6 and err.max() < 0.03     # only the re-gridded ledge step differs


def test_register_course_profiles():
    ys = np.linspace(-2, 2, align.BINS)
    peaks = [-0.42, -0.35, -0.3, 0.05, 0.5]
    prof = lambda y, scale, shift: sum(np.exp(-0.5 * ((y - (p - shift) / scale) / 0.01) ** 2) for p in peaks)
    ref = (ys, prof(ys, 1.0, 0.0))
    other = (ys, prof(ys, 1.25, 0.1))          # Y_ref = 1.25 * Y_other + 0.1
    a, b = align.register(ref, other)
    assert abs(a - 1.25) < 0.01 and abs(b - 0.1) < 0.01


class BentRun:
    """Stand-in model whose wall coordinates sag along the run like an unlevelled solve."""

    level = None
    bend = staticmethod(lambda s: 0.004 * (s - 20) ** 2 / 20)     # 0 at s=20, +0.8 at both ends

    def hit(self, f, p):
        s = p[:, 0] / 700 + 0.4 * f
        return s, p[:, 1] / 700 - 0.7 + self.bend(s)


def test_level_offsets_follow_a_slow_bend():
    rng = np.random.default_rng(7)
    courses = np.array([-0.62, -0.55, -0.31, 0.05, 0.38])          # level on the real wall
    hl = []
    for f in range(100):                                             # 100 photos, s 0..40
        rows = (courses + 0.7) * 700
        xs = rng.uniform(0, 300, len(rows))
        hl.append(np.column_stack([xs, rows, xs + 300, rows]))
    run = BentRun()
    s0, ds, offsets = align.level_offsets(run, hl)
    s = s0 + ds * np.arange(len(offsets))
    expected = run.bend(s) - np.median(run.bend(s))
    assert np.abs(offsets - expected).max() < 0.03


# ---------------------------------------------------------------- rendering and tiles
def test_render_reproduces_the_wall(tmp_path):
    """Photograph a textured synthetic wall, then render it back straight-on."""
    m = synthetic_model(n=3, spacing=0.4)
    rng = np.random.default_rng(6)
    texture = cv2.resize(rng.integers(0, 255, (60, 300), np.uint8), (3000, 600), interpolation=cv2.INTER_CUBIC)
    tex_scale, tex_s0, tex_y0 = 200.0, -2.0, -1.5
    def wall_colour(s, Y):
        u = ((s - tex_s0) * tex_scale).astype(np.float32); v = ((Y - tex_y0) * tex_scale).astype(np.float32)
        return cv2.remap(texture, u, v, cv2.INTER_LINEAR)
    paths = []
    for f in range(3):
        # photograph at quarter density (sample centres line up with cv2.resize), then upscale
        gy, gx = np.mgrid[1.5:FULL_H:4, 1.5:FULL_W:4]
        s, Y = m.hit(f, render.to_match(np.column_stack([gx.ravel(), gy.ravel()])))
        img = wall_colour(s.reshape(gx.shape), Y.reshape(gx.shape))
        img = cv2.resize(img, (FULL_W, FULL_H), interpolation=cv2.INTER_LINEAR)
        paths.append(str(tmp_path / ('p%d.jpg' % f)))
        cv2.imwrite(paths[-1], cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), [cv2.IMWRITE_JPEG_QUALITY, 97])
    model_path = str(tmp_path / 'model.npz'); m.save(model_path)
    scale = 200.0
    width, height = render.render(model_path, paths, str(tmp_path / 'strips'), scale, -0.5, 0.4, workers=1, log=lambda *a: None)
    out = cv2.imread(str(tmp_path / 'strips' / 'strip_0000.jpg'), cv2.IMREAD_GRAYSCALE)
    assert out.shape == (height, width)
    L = np.load(str(tmp_path / 'strips' / 'layout.npz'))
    ys, xs = np.mgrid[0:height, 0:width]
    expected = wall_colour((xs + int(L['X0']) + 0.5) / scale, (ys + int(L['Y0']) + 0.5) / scale)
    core = (slice(20, -20), slice(40, -40))
    err = np.abs(out[core].astype(float) - expected[core].astype(float))
    assert np.median(err) < 6


def _strip(tmp_path, name, img):
    d = tmp_path / name
    d.mkdir()
    cv2.imwrite(str(d / 'strip_0000.png'.replace('.png', '.jpg')), img, [cv2.IMWRITE_JPEG_QUALITY, 98])
    return str(d)


def test_tiles_join_runs_into_one_continuous_wall(tmp_path):
    runs = [(_strip(tmp_path, 'a', np.full((120, 300, 3), 200, np.uint8)), 'Photographed 30 Jul 2023', None),
            (_strip(tmp_path, 'b', np.full((120, 100, 3), 200, np.uint8)), 'Photographed 30 Jul 2023', 'divider'),
            (_strip(tmp_path, 'c', np.full((120, 200, 3), 200, np.uint8)), 'Photographed 21 Aug 2023', 'gap')]
    info = tiles.build(runs, str(tmp_path / 'out'), seam_px=20, feather_px=10, log=lambda *a: None)
    assert (info['width'], info['height']) == (300 + 100 + 200 - 2 * 20, 120)     # no spaces, short seams
    assert [(seg['x'], seg['width']) for seg in info['segments']] == [(0, 300), (280, 100), (360, 200)]
    assert info['breaks'] == [{'x': 290, 'kind': 'seam'}, {'x': 370, 'kind': 'gap', 'label': tiles.GAP_LABEL}]
    assert json.load(open(tmp_path / 'out' / 'wall.json')) == info
    name = os.path.basename(info['dzi'])[:-4]
    assert info['dzi'] == '/wall/%s.dzi' % name and name.startswith('wall-')
    assert (tmp_path / 'out' / (name + '.dzi')).exists() and (tmp_path / 'out' / (name + '_files')).is_dir()
    overview = cv2.imread(str(tmp_path / 'out' / (name + '-overview.jpg')))
    assert overview.shape[:2] == tiles.OVERVIEW_SIZE[::-1]
    assert info['overview'] == '/wall/%s-overview.jpg' % name

    # a later build replaces the earlier one under new URLs
    import time; time.sleep(1.1)
    again = tiles.build(runs, str(tmp_path / 'out'), seam_px=20, feather_px=10, log=lambda *a: None)
    assert again['dzi'] != info['dzi']
    new = os.path.basename(again['dzi'])[:-4]
    assert sorted(os.listdir(tmp_path / 'out')) == sorted([new + '.dzi', new + '_files', new + '-overview.jpg', 'wall.json'])


def test_joins_match_brightness_and_line_up_the_courses():
    def wall(value, course_rows, width):
        img = np.full((160, width, 3), value, np.uint8)
        for r in course_rows:
            img[r:r + 3] = 40                                       # dark horizontal courses
        return img
    import pyvips
    as_vips = lambda arr: pyvips.Image.new_from_memory(np.ascontiguousarray(arr).tobytes(), arr.shape[1], arr.shape[0], 3, 'uchar')
    a = as_vips(wall(120, (40, 90, 130), 600))
    b = as_vips(wall(180, (50, 100, 140), 400))                   # 50% brighter, courses 10 px lower
    shift, (ma, sa), (mb, sb) = tiles.join_fit(a, b, sample=400, scale=1.0)
    assert shift == -10                                           # lift b by 10 px to line up
    mean, spread = (ma + mb) / 2, np.sqrt(sa * sb)
    adjusted = tiles.adjust(a, right=(spread / sa, ma, mean), ramp=200).numpy()
    end = adjusted[:, -1]
    assert np.allclose(end.mean(axis=0), mean, atol=2)            # meets b halfway at the join
    assert np.allclose(end.std(axis=0), spread, atol=2)           # in contrast too
    assert abs(adjusted[5, 300].mean() - 120) < 1                 # and is untouched away from it


def test_small_holes_at_run_edges_are_filled():
    import pyvips
    img = np.full((200, 600, 3), 170, np.uint8)
    img[::20] = 90                                                # some texture
    img[180:, 20:80] = tiles.BACKGROUND                           # a notch along the bottom, near the start
    img[90:110, 300:320] = tiles.BACKGROUND                       # an interior hole: not an edge gap, left alone
    vimg = pyvips.Image.new_from_memory(img.tobytes(), 600, 200, 3, 'uchar')
    out = tiles.fill_edge_holes(vimg, span=150).numpy()
    is_bg = lambda a: (np.abs(a.astype(int) - tiles.BACKGROUND) <= 10).all(axis=2)
    assert not is_bg(out[180:, 20:80]).any()
    assert is_bg(out[90:110, 300:320]).all()
    assert out.shape == img.shape


def test_seams_run_between_the_hearts():
    import pyvips
    rng = np.random.default_rng(9)
    def band(seed):
        img = np.full((200, 80, 3), 190, np.uint8)            # pale stone
        r = np.random.default_rng(seed)
        for _ in range(12):                                     # red hearts (as discs)
            cv2.circle(img, (int(r.integers(0, 80)), int(r.integers(0, 200))), 7, (210, 40, 40), -1)
        img[:, 38:42] = 190                                     # a clear stone lane down the middle
        return img
    a, b = band(1), band(2)
    a[:, 38:42] = 190; b[:, 38:42] = 190
    to_vips = lambda arr: pyvips.Image.new_from_memory(np.ascontiguousarray(arr).tobytes(), arr.shape[1], arr.shape[0], 3, 'uchar')
    weight = tiles.seam_mask(to_vips(a), to_vips(b), 200, scale=1.0, soften=1.0)
    cut = (weight > 0.5).sum(axis=1)                            # columns taken from a, per row
    reds = lambda img, x: img[np.arange(200), np.clip(x, 0, 79), 0] > 200
    # along the cut neither side shows red: the path found the stone lane
    assert not reds(a, cut - 1).any() and not reds(b, cut).any()


def test_runs_are_trimmed_to_straight_fully_covered_ends(tmp_path):
    img = np.full((80, 400, 3), 200, np.uint8)
    for y in range(80):                                   # ragged, slanted photo edges at both ends
        img[y, :40 + y // 2] = tiles.BACKGROUND
        img[y, 360 - y // 4:] = tiles.BACKGROUND
    cv2.imwrite(str(tmp_path / 'strip_0000.jpg'), img)
    left, right = tiles.covered_span(str(tmp_path), shrink=2, max_missing=0.02)
    assert 76 <= left <= 84 and 336 <= right <= 344
