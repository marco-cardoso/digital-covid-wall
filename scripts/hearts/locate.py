"""Place the hearts found in one photo onto the stitched wall.

Hearts are found in the photos (hearts/detect.py), but visitors look at the stitched wall, where each
photo has been straightened and blended with its neighbours. A photo's pixels reach the wall by way of
the solver's camera model, which isn't kept; the wall itself is, so the photo is matched to it instead:

 1. SIFT features of the photo and of the wall around it give a homography. It is exact for the
    wall's main surface, but ledges and set-back sections stand out from it by up to a heart's width.
 2. Dense optical flow between the photo warped by that homography and the wall takes up the rest.

Checked against the exact geometry the first two photos were rendered with, the hearts land within
1 px (median) and 7 px (worst) on the wall's full-size pixels, where a heart is about 130 px across.
"""
from dataclasses import dataclass

import cv2
import numpy as np

WALL_DIV = 4               # the wall is read at 1/4 size (one pyramid level down from 1/2...) for matching
PHOTO_DIV = 3              # ... and the photo at 1/3, which brings its pixels to about the wall's
RATIO = 0.8                # Lowe's ratio test for a feature match
RANSAC_PX = 3.0            # a match fits the homography when it lands this close (at match size)
MIN_INLIERS = 60           # fewer than this and the photo is not placed
SCALE_RANGE = (0.5, 1.5)   # a photo covers this many wall-crop px per photo px (match size); a fit outside it is wrong
FLOW_WINDOW = 6            # flow is taken as the median over this many px either side of a point
MAX_FLOW = 100.0           # px (match size): a bigger shift than any ledge makes is a failed flow
MAX_SPREAD = 10.0          # px (match size): a heart's corners may be shifted this differently before its shape is in doubt
EDGE = 12                  # full-size photo px: a heart this close to the photo's edge is cut off by it
PAD = 2200                 # full-size wall px read on each side of a photo's own stretch to match against


@dataclass
class Registration:
    h: np.ndarray          # 3x3: photo pixels at 1/PHOTO_DIV size -> wall-crop pixels at 1/WALL_DIV size
    flow: np.ndarray       # (rows, cols, 2): what is left over, per pixel of the warped photo
    valid: np.ndarray      # bool (rows, cols): where the warped photo has pixels
    origin: int            # full-size wall x of the crop's left edge
    inliers: int
    matches: int

    def to_wall(self, points):
        """Full-size photo pixels (n, 2) -> (full-size wall pixels (n, 2), whether each is trustworthy, the flow's shift at each)."""
        points = np.asarray(points, np.float32).reshape(-1, 2)
        q = cv2.perspectiveTransform((points / PHOTO_DIV)[None], self.h)[0]
        shift = np.zeros_like(q)
        ok = np.zeros(len(q), bool)
        rows, cols = self.valid.shape
        for i, (x, y) in enumerate(q):
            cx, cy = int(round(x)), int(round(y))
            if not (0 <= cx < cols and 0 <= cy < rows) or not self.valid[cy, cx]:
                continue
            window = self.flow[max(0, cy - FLOW_WINDOW):cy + FLOW_WINDOW + 1, max(0, cx - FLOW_WINDOW):cx + FLOW_WINDOW + 1]
            inside = self.valid[max(0, cy - FLOW_WINDOW):cy + FLOW_WINDOW + 1, max(0, cx - FLOW_WINDOW):cx + FLOW_WINDOW + 1]
            shift[i] = np.median(window[inside], axis=0)
            ok[i] = bool(np.all(np.isfinite(shift[i])) and np.linalg.norm(shift[i]) <= MAX_FLOW)
        wall = (q + shift) * WALL_DIV
        wall[:, 0] += self.origin
        return wall, ok, shift


def _gray(image):
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def plausible(h, size):
    """Whether a homography puts a photo of `size` (width, height, at match size) on the wall as a photo could sit:
    not mirrored or folded over, and about as big as the wall's pixels make it. Repeating hearts can fool a fit."""
    width, height = size
    quad = cv2.perspectiveTransform(np.float32([[[0, 0], [width, 0], [width, height], [0, height]]]), h)[0]
    edges = np.roll(quad, -1, axis=0) - quad
    turns = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)     # each corner turns the same way
    if not (turns > 0).all():
        return False
    area = 0.5 * abs(np.dot(quad[:, 0], np.roll(quad[:, 1], -1)) - np.dot(quad[:, 1], np.roll(quad[:, 0], -1)))
    return SCALE_RANGE[0] <= np.sqrt(area / (width * height)) <= SCALE_RANGE[1]


def register(photo, crop, origin):
    """Match a full-size BGR photo to `crop`, the wall at 1/WALL_DIV size whose left edge is at full-size x `origin`.

    Returns a Registration, or None when the two can't be matched (too few features agree, or the fit is not
    one a photo of the wall could have).
    """
    small = cv2.resize(photo, None, fx=1 / PHOTO_DIV, fy=1 / PHOTO_DIV, interpolation=cv2.INTER_AREA)
    sift = cv2.SIFT_create(contrastThreshold=0.02)
    kp_a, des_a = sift.detectAndCompute(_gray(small), None)
    kp_b, des_b = sift.detectAndCompute(_gray(crop), None)
    if des_a is None or des_b is None or len(kp_a) < 2 or len(kp_b) < 2:
        return None
    pairs = cv2.BFMatcher().knnMatch(des_a, des_b, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < RATIO * p[1].distance]
    if len(good) < MIN_INLIERS:
        return None
    src = np.float32([kp_a[m.queryIdx].pt for m in good])
    dst = np.float32([kp_b[m.trainIdx].pt for m in good])
    h, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_PX)
    if h is None or int(mask.sum()) < MIN_INLIERS or not plausible(h, (small.shape[1], small.shape[0])):
        return None

    rows, cols = crop.shape[:2]
    warped = cv2.warpPerspective(small, h, (cols, rows), flags=cv2.INTER_LINEAR)
    valid = cv2.warpPerspective(np.full(small.shape[:2], 255, np.uint8), h, (cols, rows), flags=cv2.INTER_NEAREST) > 0
    valid = cv2.erode(valid.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    dis.setFinestScale(1)
    dis.setPatchSize(12)
    dis.setPatchStride(4)
    dis.setVariationalRefinementIterations(10)
    flow = dis.calc(_gray(warped), _gray(crop), None)
    return Registration(h, flow, valid, int(origin), int(mask.sum()), len(good))


def place_hearts(registration, hearts, size=None):
    """The hearts of one photo as boxes on the wall.

    `hearts` are records from hearts/detect (a `box` of [x, y, w, h] in photo pixels). Each box's corners
    are carried across; the wall is straight-on, so the box is the average of the corners' edges. Hearts
    the registration can't vouch for (off the photo's edge, or where the flow failed or tore the heart's
    shape) are left out.
    Hearts touching the photo's border (`size` is its width and height) are cut off by it: their boxes
    are partial and the neighbouring photo sees them whole.
    Returns dicts of full-size wall pixels: x, y, w, h and the heart's own record.
    """
    if size is not None:
        width, height = size
        hearts = [h for h in hearts if h['box'][0] > EDGE and h['box'][1] > EDGE
                  and h['box'][0] + h['box'][2] < width - EDGE and h['box'][1] + h['box'][3] < height - EDGE]
    if not hearts:
        return []
    corners = np.array([[(x, y), (x + w, y), (x + w, y + h), (x, y + h)] for x, y, w, h in (hh['box'] for hh in hearts)], np.float32)
    wall, ok, shift = registration.to_wall(corners.reshape(-1, 2))
    wall, ok, shift = wall.reshape(-1, 4, 2), ok.reshape(-1, 4), shift.reshape(-1, 4, 2)
    placed = []
    for heart, quad, fine, moved in zip(hearts, wall, ok, shift):
        # all four corners found, and moved together: a heart cut by the photo's edge or by a ledge is pulled out of shape
        if not fine.all() or np.abs(moved - moved.mean(0)).max() > MAX_SPREAD:
            continue
        left, right = quad[[0, 3], 0].mean(), quad[[1, 2], 0].mean()
        top, bottom = quad[[0, 1], 1].mean(), quad[[2, 3], 1].mean()
        placed.append(dict(x=int(round(left)), y=int(round(top)), w=int(round(right - left)), h=int(round(bottom - top)), heart=heart))
    return placed


def owned(boxes, x0, x1):
    """Boxes whose centre lies in [x0, x1): neighbouring photos overlap, and each heart belongs to one of them."""
    return [b for b in boxes if x0 <= b['x'] + b['w'] / 2 < x1]
