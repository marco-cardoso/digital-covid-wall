"""Join rendered runs into one Deep Zoom image and describe it for the website."""
import glob
import json
import os
import shutil
import time

import cv2
import numpy as np
import pyvips

SEAM_PX = 320                  # neighbouring runs meet along a cut chosen within this band
LEVEL_RAMP_PX = 2400           # brightness is matched at a join and eased back over this much
ALIGN_REACH_PX = 80            # how far a join may nudge a run up or down to line up the courses
FEATHER_PX = 240               # the wall's two outer ends fade into the background
BACKGROUND = [26, 26, 26]      # matches the viewer's canvas
GAP_LABEL = 'Not photographed'
OVERVIEW_SIZE = (2400, 48)     # the whole wall, squeezed, for the viewer's position map


def join_horizontally(images):
    """Edge-to-edge join (arrayjoin would pad every image to the widest one)."""
    while len(images) > 1:
        images = [images[i].join(images[i + 1], 'horizontal') if i + 1 < len(images) else images[i]
                  for i in range(0, len(images), 2)]
    return images[0]


def run_image(strip_dir, access='sequential'):
    strips = sorted(glob.glob(os.path.join(strip_dir, 'strip_*.jpg')))
    return join_horizontally([pyvips.Image.new_from_file(p, access=access) for p in strips])


def covered_span(strip_dir, shrink=8, tolerance=8, max_missing=0.08):
    """Columns [left, right) where the run covers (nearly) the full height.

    A run's first and last photos rarely end on a vertical line once straightened; cutting
    at the first and last fully covered columns gives each run clean, straight ends.
    """
    whole = run_image(strip_dir)
    small = whole.reduce(shrink, shrink).numpy().astype(np.int16)
    empty = (np.abs(small - np.array(BACKGROUND)) <= tolerance).all(axis=2)
    full = np.nonzero(empty.mean(axis=0) <= max_missing)[0]
    if not len(full):
        return 0, whole.width
    return int(full[0]) * shrink, min(int(full[-1] + 1) * shrink, whole.width)


def _edge(img, side, width, scale):
    part = img.crop(img.width - width, 0, width, img.height) if side == 'right' else img.crop(0, 0, width, img.height)
    rgb = part.resize(scale).numpy().astype(np.float32)
    return rgb, ~(np.abs(rgb - BACKGROUND) <= 10).all(axis=2)


def join_fit(a, b, sample=800, scale=0.25):
    """How to meet run b to the end of run a.

    Returns the vertical shift for b that lines up the wall's courses across the join
    (matching the row-by-row strength of horizontal edges either side), and the colour
    statistics (per-channel mean and spread) of each side right next to the join.
    """
    ra, va = _edge(a, 'right', min(sample, a.width), scale)
    rb, vb = _edge(b, 'left', min(sample, b.width), scale)
    h = min(len(ra), len(rb))
    ra, va, rb, vb = ra[:h], va[:h], rb[:h], vb[:h]

    def rows(rgb, valid):
        grey = rgb.mean(axis=2)
        edge = np.abs(np.diff(grey, axis=0)) * (valid[1:] & valid[:-1])
        p = edge.sum(axis=1) / np.maximum((valid[1:] & valid[:-1]).sum(axis=1), 1)
        return (p - p.mean()) / (p.std() + 1e-9)

    pa, pb = rows(ra, va), rows(rb, vb)
    reach = int(ALIGN_REACH_PX * scale)
    scores = []
    for d in range(-reach, reach + 1):           # b's row y lines up with a's row y + d
        x, y = (pa[d:], pb[:len(pb) - d]) if d >= 0 else (pa[:d], pb[-d:])
        scores.append(float(np.dot(x, y) / len(x)))
    best = int(np.argmax(scores))
    # only move when it clearly lines up better than staying put (no courses, no move)
    shift = (best - reach) / scale if scores[best] - scores[reach] > 0.05 else 0.0

    near = max(1, int(400 * scale))
    stats = lambda rgb, valid: ((rgb[valid].mean(axis=0), rgb[valid].std(axis=0) + 1e-3) if valid.any()
                                else (np.full(3, 128.0), np.full(3, 40.0)))
    return shift, stats(ra[:, -near:], va[:, -near:]), stats(rb[:, :near], vb[:, :near])


def fill_edge_holes(img, span=4000, max_fraction=0.15):
    """Inpaint the small gaps a run's end photos leave at the top or bottom edge.

    Near its ends a run's photos may stop just short of the crop, leaving notches of
    background along the edge; these are filled from the surrounding stone. Only holes
    touching the top or bottom edge, and no taller than max_fraction of the height, are
    filled, and only within `span` of either end.
    """
    w, h = img.width, img.height
    regions = [(0, w)] if w <= 2 * span else [(0, span), (w - span, w)]
    fixed = {}
    for x0, x1 in regions:
        arr = np.ascontiguousarray(img.crop(x0, 0, x1 - x0, h).numpy())
        empty = (np.abs(arr.astype(np.int16) - BACKGROUND) <= 10).all(axis=2).astype(np.uint8)
        n, labels, box, _ = cv2.connectedComponentsWithStats(empty)
        mask = np.zeros_like(empty)
        for k in range(1, n):
            top, height = box[k, cv2.CC_STAT_TOP], box[k, cv2.CC_STAT_HEIGHT]
            if (top == 0 or top + height == h) and height <= max_fraction * h:
                mask[labels == k] = 255
        if mask.any():
            arr = cv2.inpaint(arr, cv2.dilate(mask, np.ones((5, 5), np.uint8)), 7, cv2.INPAINT_TELEA)
        fixed[x0] = pyvips.Image.new_from_memory(arr.tobytes(), x1 - x0, h, 3, 'uchar')
    if len(regions) == 1:
        return fixed[0]
    return join_horizontally([fixed[0], img.crop(span, 0, w - 2 * span, h), fixed[w - span]])


def seam_mask(a, b, height, scale=0.25, soften=6.0):
    """Where to cut between the end of one run (a) and the start of the next (b).

    a and b are the same-sized band either side takes up; the cut runs top to bottom
    through bare stone between hearts (steering round the red ones, so none is cut in
    half) and away from anywhere either side has no photo. Returns a (height x width)
    weight: 1 takes a, 0 takes b, softened over a few pixels along the cut.
    """
    sa, sb = a.resize(scale).numpy().astype(np.float32), b.resize(scale).numpy().astype(np.float32)
    h, w = min(len(sa), len(sb)), min(sa.shape[1], sb.shape[1])
    sa, sb = sa[:h, :w], sb[:h, :w]
    red = lambda rgb: np.clip(rgb[..., 0] - rgb[..., 1:].max(axis=2), 0, None) / 255
    missing = lambda rgb: (np.abs(rgb - BACKGROUND) <= 10).all(axis=2).astype(np.float32)
    # cutting at column x takes a's columns left of x and b's from x on
    cost = red(sa) + red(sb) + 0.3 * np.abs(sa - sb).mean(axis=2) / 255
    cost += 4 * (np.cumsum(missing(sa), axis=1) - missing(sa) + np.cumsum(missing(sb)[:, ::-1], axis=1)[:, ::-1])
    cost += 0.05 * np.abs(np.arange(w) - w / 2) / w        # all else equal, both sides give up the same
    acc, back = cost.copy(), np.zeros(cost.shape, np.int8)
    for y in range(1, h):
        prev = acc[y - 1]
        options = np.vstack([np.r_[np.inf, prev[:-1]], prev, np.r_[prev[1:], np.inf]])
        pick = options.argmin(axis=0)
        acc[y] += options[pick, np.arange(w)]
        back[y] = pick - 1
    path = np.zeros(h, int)
    path[-1] = int(acc[-1].argmin())
    for y in range(h - 1, 0, -1):
        path[y - 1] = path[y] + back[y, path[y]]
    full_w = a.width
    cut = np.interp((np.arange(height) + 0.5) * scale - 0.5, np.arange(h), (path + 0.5) / scale)
    cols = np.arange(full_w)[None, :]
    return np.clip(0.5 - (cols - cut[:, None]) / (2 * soften), 0, 1).astype(np.float32)


def _profile(img, values):
    """A (width x 1 x bands) float profile as an image the height of img."""
    arr = np.ascontiguousarray(values.reshape(1, img.width, -1).astype(np.float32))
    return pyvips.Image.new_from_memory(arr.tobytes(), img.width, 1, arr.shape[2], 'float').zoom(1, img.height)


def adjust(img, left=None, right=None, fade_left=False, fade_right=False, ramp=LEVEL_RAMP_PX, feather_px=FEATHER_PX):
    """Ease colour to meet the neighbours at either end; fade the wall's outer ends.

    left / right are (k, m_from, m_to) per-channel maps v -> m_to + (v - m_from) * k applied
    fully at that end and eased out over `ramp`, so brightness and contrast meet the next
    run's at the join without a visible step.
    """
    x = np.arange(img.width, dtype=np.float32)
    scale = np.ones((img.width, 3), np.float32)
    offset = np.zeros((img.width, 3), np.float32)
    for end, dist in ((left, x), (right, img.width - 1 - x)):
        if end is not None:
            k, m_from, m_to = (np.asarray(v, np.float32) for v in end)
            r = np.clip(1 - dist / ramp, 0, 1)[:, None]
            scale, offset = scale * (1 + r * (k - 1)), offset * (1 + r * (k - 1)) + r * (m_to - m_from * k)
    img = img * _profile(img, scale) + _profile(img, offset)
    fade = np.ones(img.width, np.float32)
    if fade_left:
        fade = np.minimum(fade, np.clip(x / feather_px, 0, 1))
    if fade_right:
        fade = np.minimum(fade, np.clip((img.width - 1 - x) / feather_px, 0, 1))
    return (img - BACKGROUND) * _profile(img, fade) + BACKGROUND


def build(runs, out_dir, url_prefix='/wall', seam_px=SEAM_PX, ramp_px=LEVEL_RAMP_PX, feather_px=FEATHER_PX, log=print):
    """runs: [(strip_dir, label, break_before)] in wall order, all rendered at the same height.

    Neighbouring runs are joined into one continuous wall: lined up on the courses,
    matched in brightness and cut together along a path between the hearts. break_before records what kind of join it is,
    'divider' (photos from one walk that do not overlap) or 'gap' (a stretch between visits
    nobody photographed), so the viewer can mark it; it is ignored for the first run.
    Writes out_dir/wall-<build>.dzi, out_dir/wall-<build>_files/, an overview image and
    out_dir/wall.json. Each build gets new URLs (tiles are cached for days), wall.json
    (never cached) points to the current one, and earlier builds are removed.
    """
    imgs, labels, kinds = [], [], []
    for strip_dir, label, kind in runs:
        left, right = covered_span(strip_dir)
        whole = run_image(strip_dir, access='random')
        imgs.append(fill_edge_holes(whole.crop(left, 0, right - left, whole.height)))
        labels.append(label); kinds.append(kind)
    height = max(img.height for img in imgs)
    n = len(imgs)
    fits = [join_fit(imgs[k], imgs[k + 1]) for k in range(n - 1)]

    # vertical placement: the longest run stays put, the others line up join by join
    ref = int(np.argmax([img.width for img in imgs]))
    dy = np.zeros(n)
    for k in range(ref - 1, -1, -1):
        dy[k] = dy[k + 1] - fits[k][0]
    for k in range(ref + 1, n):
        dy[k] = dy[k - 1] + fits[k - 1][0]
    dy = np.round(dy).astype(int)

    # colour: both sides of each join meet halfway in brightness and contrast
    ends_left, ends_right = [None] * n, [None] * n
    for k, (_, (ma, sa), (mb, sb)) in enumerate(fits):
        mean, spread = (ma + mb) / 2, np.sqrt(sa * sb)
        ends_right[k] = (np.clip(spread / sa, 0.7, 1.4), ma, mean)
        ends_left[k + 1] = (np.clip(spread / sb, 0.7, 1.4), mb, mean)

    placed = []
    for k, img in enumerate(imgs):
        img = adjust(img, ends_left[k], ends_right[k], fade_left=k == 0, fade_right=k == n - 1,
                     ramp=ramp_px, feather_px=feather_px)
        placed.append(img.embed(0, int(dy[k]) + (height - img.height) // 2, img.width, height,
                                extend='background', background=BACKGROUND))

    wall, segments, breaks = placed[0], [dict(x=0, width=placed[0].width, label=labels[0])], []
    for k in range(1, n):
        b = placed[k]
        c = int(min(seam_px, wall.width // 2, b.width // 2))
        zone_a, zone_b = wall.crop(wall.width - c, 0, c, height), b.crop(0, 0, c, height)
        weight = seam_mask(zone_a, zone_b, height)
        weight = pyvips.Image.new_from_memory(np.ascontiguousarray(weight).tobytes(), c, height, 1, 'float')
        blend = zone_a * weight + zone_b * (1 - weight)
        start = wall.width - c
        wall = join_horizontally([wall.crop(0, 0, start, height), blend, b.crop(c, 0, b.width - c, height)])
        entry = dict(x=start + c // 2, kind='gap' if kinds[k] == 'gap' else 'seam')
        if kinds[k] == 'gap':
            entry['label'] = GAP_LABEL
        breaks.append(entry)
        segments.append(dict(x=start, width=b.width, label=labels[k]))

    # drop the rows that runs nudged up or down left uncovered
    top, bottom = max(0, int(dy.max())), max(0, int(-dy.min()))
    wall = wall.crop(0, top, wall.width, height - top - bottom).cast('uchar')
    os.makedirs(out_dir, exist_ok=True)
    name = 'wall-%d' % int(time.time())
    wall.dzsave(os.path.join(out_dir, name), tile_size=512, overlap=1, suffix='.jpg[Q=82,strip]', layout='dz')
    overview = wall_overview(os.path.join(out_dir, name + '_files'), wall.width, wall.height)
    overview.write_to_file(os.path.join(out_dir, name + '-overview.jpg[Q=85,strip]'))
    info = dict(dzi='%s/%s.dzi' % (url_prefix, name), overview='%s/%s-overview.jpg' % (url_prefix, name),
                width=wall.width, height=wall.height, segments=segments, breaks=breaks)
    with open(os.path.join(out_dir, 'wall.json.tmp'), 'w') as fh:
        json.dump(info, fh, indent=2)
    os.replace(os.path.join(out_dir, 'wall.json.tmp'), os.path.join(out_dir, 'wall.json'))
    keep = (name + '.dzi', name + '_files', name + '-overview.jpg', 'wall.json')
    for old in os.listdir(out_dir):                      # earlier builds (and the unversioned layout)
        if old.startswith('wall') and old not in keep:
            path = os.path.join(out_dir, old)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    log('  wall %d x %d px, %d runs, joins nudged %s px' % (wall.width, wall.height, n, [int(f[0]) for f in fits]))
    return info


def wall_overview(files_dir, width, height):
    """The whole wall at OVERVIEW_SIZE, assembled from a small Deep Zoom level."""
    levels = sorted(int(d) for d in os.listdir(files_dir) if d.isdigit())
    top = levels[-1]
    # smallest level that is still at least as wide as the overview
    level = next(l for l in levels if width / 2 ** (top - l) >= OVERVIEW_SIZE[0] or l == top)
    tiles = sorted(glob.glob(os.path.join(files_dir, str(level), '*_0.jpg')), key=lambda p: int(os.path.basename(p).split('_')[0]))
    strip = []
    for k, path in enumerate(tiles):
        t = pyvips.Image.new_from_file(path)
        left = 1 if k else 0                             # drop the 1 px tile overlap
        width_k = t.width - left - (1 if k < len(tiles) - 1 else 0)
        strip.append(t.crop(left, 0, width_k, t.height))
    img = join_horizontally(strip)
    level_h = int(np.ceil(height / 2 ** (top - level)))
    img = img.crop(0, 0, img.width, min(img.height, level_h))
    return img.resize(OVERVIEW_SIZE[0] / img.width, vscale=OVERVIEW_SIZE[1] / img.height)
