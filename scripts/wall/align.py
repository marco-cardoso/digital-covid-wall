"""Put separately solved runs on one physical scale, using the wall's horizontal courses.

Runs that never overlap each other each have their own unit (roughly the photographer's
distance that day). The wall's coping, decorative bands and ledges run at the same
heights all along it, so the height profile of horizontal lines in one run is a
stretched and shifted copy of another's.
"""
import cv2
import numpy as np

from .render import FULL_H, FULL_W, to_match

BINS = 600


def course_lines(model, hlines):
    """Centre s, centre Y and length of every horizontal line, in a run's wall coordinates."""
    out = []
    for f, h in enumerate(hlines):
        if not len(h):
            continue
        s1, y1 = model.hit(f, h[:, :2]); s2, y2 = model.hit(f, h[:, 2:])
        out.append(np.column_stack([(s1 + s2) / 2, (y1 + y2) / 2, np.hypot(s2 - s1, y2 - y1)]))
    return np.vstack(out)


def histogram(ys, ws, lo=-2.0, hi=2.0):
    hist, edges = np.histogram(ys, bins=BINS, range=(lo, hi), weights=ws)
    hist = cv2.GaussianBlur(hist.astype(np.float64).reshape(1, -1), (0, 0), 1.5).ravel()
    return (edges[:-1] + edges[1:]) / 2, hist / max(hist.max(), 1e-12)


def course_profile(model, hlines):
    """Length-weighted histogram of horizontal-line heights (Y) in a run's wall coordinates."""
    lines = course_lines(model, hlines)
    return histogram(lines[:, 1], lines[:, 2])


def level_offsets(model, hlines, window=10.0, step=2.0, follow=0.1, rounds=3):
    """Vertical offset L(s) that makes the wall's courses run level along a run.

    The coping, bands and ledges are level on the real wall, so a slow bend left in a long
    solve (photos near the ends of separately solved pieces have neighbours on one side
    only) shows up as the local course pattern drifting up or down. Walking along the run,
    each window's pattern is slid against the run's overall pattern, searching only near the
    previous window's offset so the estimate follows the bend instead of jumping between
    courses. The reference pattern sharpens as the run levels.
    Returns (s0, ds, offsets) for WallModel.level, or None for very short runs.
    """
    lines = course_lines(model, hlines)
    s, y, w = lines.T
    centres = np.arange(s.min() + window / 2, s.max() - window / 2 + step, step)
    if len(centres) < 2:
        return None
    offsets = np.zeros(len(centres))
    for _ in range(rounds):
        yr, ref = histogram(y - np.interp(s, centres, offsets), w)
        bin_ = yr[1] - yr[0]
        reach = int(round(follow / bin_))
        found, prev = np.zeros(len(centres)), 0
        for k, c in enumerate(centres):
            sel = np.abs(s - c) < window / 2
            if w[sel].sum() >= 3.0:
                _, local = histogram(y[sel], w[sel])
                shifts = np.arange(prev - reach, prev + reach + 1)
                prev = int(shifts[np.argmax([np.dot(ref, np.roll(local, -d)) for d in shifts])])
            found[k] = prev * bin_
        offsets = cv2.GaussianBlur(found.reshape(1, -1), (0, 0), 1.5, borderType=cv2.BORDER_REPLICATE).ravel()
        offsets -= np.median(offsets)
    return float(centres[0]), float(step), offsets


def peaks(profile, min_strength=0.2):
    """Heights and strengths of the distinct courses in a profile."""
    ys, h = profile
    k = [i for i in range(1, len(h) - 1) if h[i] > h[i - 1] and h[i] >= h[i + 1] and h[i] > min_strength]
    return ys[k], h[k]


def correlation(ref, other, a, b, cover):
    """Correlation of the reference profile with the other one mapped by Y = a*y + b,
    over the heights the other run covers (mean removed, so stretching is not rewarded)."""
    yr, hr = ref; yo, ho = other
    y_other = (yr - b) / a
    ok = (y_other >= cover[0]) & (y_other <= cover[1])
    if ok.sum() < 20:
        return -np.inf
    w = np.interp(y_other[ok], yo, ho)
    if w.std() < 1e-9 or hr[ok].std() < 1e-9:
        return -np.inf
    return float(np.corrcoef(hr[ok], w)[0, 1])


def register(ref, other, scales=np.exp(np.linspace(np.log(0.6), np.log(1.8), 221))):
    """(a, b) with Y_ref = a * Y_other + b that best overlays the two course profiles.

    A coarse search by correlation, then a fit to paired course heights: the spacing of
    distinct courses is the sharpest ruler there is (a correlation also weighs every
    faint line, which drifts the scale by a few percent).
    """
    yo, ho = other
    cover = (yo[ho > 0.02].min(), yo[ho > 0.02].max())
    shifts = np.linspace(-1.5, 1.5, 1201)
    _, a, b = max((correlation(ref, other, a, b, cover), a, b) for a in scales for b in shifts[::8])
    pr, sr = peaks(ref); po, so = peaks(other)
    for _ in range(3):
        mapped = a * po + b
        pairs = [(i, int(np.argmin(np.abs(pr - m)))) for i, m in enumerate(mapped)]
        pairs = [(i, j) for i, j in pairs if abs(pr[j] - mapped[i]) < 0.03]
        if len({j for _, j in pairs}) < 2:
            break
        w = np.array([min(so[i], sr[j]) for i, j in pairs])
        A = np.column_stack([po[[i for i, _ in pairs]], np.ones(len(pairs))]) * w[:, None]
        a, b = np.linalg.lstsq(A, pr[[j for _, j in pairs]] * w, rcond=None)[0]
    return float(a), float(b)


def register_offset(ref, other, a, b0, reach=0.08):
    """Best vertical offset for a fixed scale, searched near a prior guess b0."""
    yo, ho = other
    cover = (yo[ho > 0.02].min(), yo[ho > 0.02].max())
    shifts = b0 + np.linspace(-reach, reach, 161)
    return float(shifts[int(np.argmax([correlation(ref, other, a, b, cover) for b in shifts]))])


def wall_band(model, profile, margin=0.2):
    """Vertical crop (y_top, y_bottom) for a run: just above its strongest course, down to
    where most photos still reach."""
    ys, hist = profile
    top = ys[np.argmax(hist)] - margin
    edge_bottom = np.column_stack([np.linspace(0, FULL_W, 9), np.full(9, FULL_H)])
    bottoms = [np.median(model.hit(f, to_match(edge_bottom))[1]) for f in range(len(model.cams))]
    return top, float(np.percentile(bottoms, 25))
