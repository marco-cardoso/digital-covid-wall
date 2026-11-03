"""Find the painted red hearts in a photo and measure the ink written on each one.

Hearts are found on a 1/4-scale copy (fast, and the paint is large), touching hearts
are split by watershed, and ink is measured on the full-resolution pixels, where the
pen strokes are several pixels wide.
"""
from dataclasses import dataclass

import cv2
import numpy as np
from scipy import ndimage

SCALE = 4                  # detection runs on the photo reduced by this factor
MIN_SIDE = 80              # full-res px: smaller hearts are too small to carry legible writing
MAX_FRAC = 0.35            # a "heart" wider or taller than this fraction of the photo is a merged mass
SPLIT = 0.6                # watershed seeds: pixels deeper than this fraction of their blob's depth
INK_DARK = 0.75            # dark ink: red channel below this fraction of the heart's median paint
HAT = 0.15                 # ... and this much darker than the paint right around it
MIN_STROKE = 25            # full-res px: smaller marks are paint texture, not pen
WRITING_FRAC = 0.006       # share of a heart's interior covered by ink for it to count as written
WRITING_STROKES = 3        # ... and at least this many separate strokes


@dataclass
class Heart:
    x: int                 # full-resolution box
    y: int
    w: int
    h: int
    area: int              # full-res px of paint, approximately
    ink: float             # share of the heart's interior that is ink
    strokes: int           # separate ink marks inside the heart
    mask: np.ndarray       # uint8 heart region inside the box, full resolution

    @property
    def has_writing(self):
        return self.ink >= WRITING_FRAC and self.strokes >= WRITING_STROKES


def red_mask(bgr):
    """Saturated red paint, with pen strokes and small gaps closed over."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 90, 60), (10, 255, 255)) | cv2.inRange(hsv, (168, 90, 60), (180, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    mask = fill_holes(mask, max_area=2000)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))


def fill_holes(mask, max_area):
    """Fill enclosed gaps (writing that broke the paint mask) up to max_area pixels."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(255 - mask, connectivity=4)
    h, w = mask.shape
    out = mask.copy()
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area <= max_area and x > 0 and y > 0 and x + bw < w and y + bh < h:
            out[labels == i] = 255
    return out


def split_hearts(mask, bgr):
    """Label image with one id per heart: blobs split where they narrow between hearts."""
    blobs, n = ndimage.label(mask)
    if n == 0:
        return np.zeros(mask.shape, np.int32), 0
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    depth = np.asarray(ndimage.maximum(dist, blobs, np.arange(1, n + 1)))
    seeds = (dist > SPLIT * depth[np.maximum(blobs - 1, 0)]) & (blobs > 0) & (dist >= 2)
    markers, count = ndimage.label(seeds)
    markers = markers.astype(np.int32) + 1          # 1 = background, 2.. = hearts
    markers[(mask > 0) & ~seeds] = 0                # to be decided by the watershed
    cv2.watershed(bgr, markers)
    markers[mask == 0] = 0
    markers[markers > 0] -= 1                       # hearts 1..count, boundaries (-1) and background 0
    markers[markers < 0] = 0
    return markers, count


def measure_ink(crop, region):
    """(ink share, stroke count) for the heart's interior in a full-res crop."""
    edge = max(3, int(0.07 * min(region.shape)))
    inner = cv2.erode(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * edge + 1, 2 * edge + 1))) > 0
    if inner.sum() < 400:
        return 0.0, 0
    r = crop[:, :, 2].astype(np.float32)
    paint = np.median(r[inner])
    # Thin dark marks only: a black-hat keeps strokes and drops broad shading across the heart.
    hat = cv2.morphologyEx(crop[:, :, 2], cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    ink = inner & (r < INK_DARK * paint) & (hat > HAT * paint)
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    keep = stats[1:, cv2.CC_STAT_AREA] >= MIN_STROKE
    return float(stats[1:, cv2.CC_STAT_AREA][keep].sum() / inner.sum()), int(keep.sum())


def find_hearts(full):
    """Every heart in a full-resolution BGR photo, with its ink measured."""
    small = cv2.resize(full, (full.shape[1] // SCALE, full.shape[0] // SCALE), interpolation=cv2.INTER_AREA)
    labels, count = split_hearts(red_mask(small), small)
    hearts = []
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        ys, xs = sl
        x, y = xs.start * SCALE, ys.start * SCALE
        w, h = (xs.stop - xs.start) * SCALE, (ys.stop - ys.start) * SCALE
        if max(w, h) < MIN_SIDE or w > MAX_FRAC * full.shape[1] or h > MAX_FRAC * full.shape[0]:
            continue
        region = (labels[sl] == i).astype(np.uint8) * 255
        region = cv2.resize(region, (w, h), interpolation=cv2.INTER_LINEAR)
        region = (region > 127).astype(np.uint8) * 255
        ink, strokes = measure_ink(full[y:y + h, x:x + w], region)
        hearts.append(Heart(x, y, w, h, int((region > 0).sum()), ink, strokes, region))
    return hearts
