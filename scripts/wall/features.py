"""Photo discovery, per-photo features and matching between neighbouring photos."""
import hashlib
import os
from multiprocessing import get_context

import cv2
import numpy as np

from .geometry import F, H, MATCH_DIV, W

NEIGH = 3                  # each photo is matched with the next NEIGH photos
K = np.array([[F, 0, W / 2], [0, F, H / 2], [0, 0, 1.0]])


def list_photos(pictures_dir):
    """Wall photos in shooting order: unique contents, portrait only.

    Byte-identical copies ("- Copy" files) are skipped, as are landscape shots, which
    are close-ups rather than wall segments.
    """
    seen, photos = set(), []
    for name in sorted(os.listdir(pictures_dir)):
        if not name.lower().endswith('.jpg'):
            continue
        path = os.path.join(pictures_dir, name)
        with open(path, 'rb') as fh:
            digest = hashlib.md5(fh.read()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        img = cv2.imread(path, cv2.IMREAD_REDUCED_GRAYSCALE_8)
        if img is None or img.shape[1] > img.shape[0]:
            continue
        photos.append(name)
    return photos


def _longest(lines, n):
    length = np.hypot(*(lines[:, 2:] - lines[:, :2]).T)
    return lines[np.argsort(-length)[:n]]


def extract(path, out_path):
    """SIFT keypoints plus long horizontal / vertical line segments for one photo."""
    if os.path.exists(out_path):
        return
    cv2.setNumThreads(1)
    gray = cv2.imread(path, cv2.IMREAD_REDUCED_GRAYSCALE_4)
    kp, des = cv2.SIFT_create(nfeatures=8000).detectAndCompute(gray, None)
    lines = cv2.createLineSegmentDetector().detect(gray)[0]
    lines = np.zeros((0, 4)) if lines is None else lines.reshape(-1, 4).astype(np.float64)
    d = lines[:, 2:] - lines[:, :2]
    length = np.hypot(d[:, 0], d[:, 1])
    angle = np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 180
    horiz = lines[(length > 80) & ((angle < 15) | (angle > 165))]
    vert = lines[(length > 50) & (np.abs(angle - 90) < 10)]
    np.savez(out_path, kp=np.float32([k.pt for k in kp]).reshape(-1, 2), des=des if des is not None else np.zeros((0, 128), np.float32),
             h=_longest(horiz, 30), v=_longest(vert, 15))


def match(args):
    """Matches between two photos, kept only if consistent with one rigid camera motion.

    Returns (pa, pb) match-res pixel arrays or None.
    """
    feat_a, feat_b = args
    cv2.setNumThreads(1)
    A, B = np.load(feat_a), np.load(feat_b)
    ka, da, kb, db = A['kp'], A['des'], B['kp'], B['des']
    if len(ka) < 50 or len(kb) < 50:
        return None
    flann = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64))
    good = [m for m, n in flann.knnMatch(da, db, k=2) if m.distance < 0.75 * n.distance]
    if len(good) < 40:
        return None
    pa = ka[[m.queryIdx for m in good]]
    pb = kb[[m.trainIdx for m in good]]
    # The essential matrix tolerates the wall's depth steps (ledges, piers), unlike a homography.
    E, inliers = cv2.findEssentialMat(pa, pb, K, cv2.USAC_MAGSAC, 0.999, 1.0)
    if E is None:
        return None
    inliers = inliers.ravel() > 0
    if inliers.sum() < 60:
        return None
    return pa[inliers], pb[inliers]


def feature_path(work, name):
    return os.path.join(work, 'features', name + '.npz')


def extract_all(pictures_dir, photos, work, workers):
    os.makedirs(os.path.join(work, 'features'), exist_ok=True)
    jobs = [(os.path.join(pictures_dir, p), feature_path(work, p)) for p in photos]
    with get_context('spawn').Pool(workers) as pool:
        pool.starmap(extract, jobs, chunksize=4)


def match_pairs(photos, work, pairs, workers):
    """Match the given (i, j) index pairs; returns {(i, j): (pa, pb)} for the ones that link."""
    jobs = [(feature_path(work, photos[i]), feature_path(work, photos[j])) for i, j in pairs]
    with get_context('spawn').Pool(workers) as pool:
        results = pool.map(match, jobs, chunksize=8)
    return {k: r for k, r in zip(pairs, results) if r is not None}


def neighbour_pairs(n):
    return [(i, j) for i in range(n) for j in range(i + 1, min(i + 1 + NEIGH, n))]


def bridge_candidates(n, links, reach=6):
    """Wider pairs around each break in the chain of consecutive links.

    A missed shot between two photos can still leave them overlapping with photos a
    little further away; only pairs within NEIGH can join a run.
    """
    linked = {i for i, j in links if j == i + 1}
    cands = set()
    for i in range(n - 1):
        if i in linked:
            continue
        for a in range(max(0, i - reach + 1), i + 1):
            for b in range(i + 1, min(n, i + 1 + reach)):
                if 0 < b - a <= NEIGH and (a, b) not in links:
                    cands.add((a, b))
    return sorted(cands)


def plan_runs(n, links):
    """Split photo indices 0..n-1 into runs that the links chain together."""
    runs, start = [], 0
    for i in range(n - 1):
        if not any(a <= i < b for a, b in links):
            runs.append((start, i))
            start = i + 1
    runs.append((start, n - 1))
    return runs


def split_run(first, last, max_len=150, overlap=20):
    """Overlapping pieces of a long run, solved separately and merged afterwards."""
    if last - first + 1 <= max_len:
        return [(first, last)]
    count = int(np.ceil((last - first + 1 - overlap) / (max_len - overlap)))
    step = (last - first + 1 - overlap) / count
    return [(first + int(round(k * step)), min(last, first + int(round(k * step + step)) + overlap - 1)) for k in range(count)]
