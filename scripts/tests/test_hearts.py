"""Tests for heart detection and crop preparation, on synthetic walls of painted hearts."""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import extract_hearts  # noqa: E402
from hearts import crops, detect  # noqa: E402

RED = (40, 40, 200)


def draw_heart(img, cx, cy, r, colour=RED):
    """Two lobes and a point, about 2r wide and 2r tall."""
    cv2.circle(img, (cx - r // 2, cy - r // 3), r // 2 + 2, colour, -1)
    cv2.circle(img, (cx + r // 2, cy - r // 3), r // 2 + 2, colour, -1)
    pts = np.array([[cx - r, cy - r // 4], [cx + r, cy - r // 4], [cx, cy + r]], np.int32)
    cv2.fillPoly(img, [pts], colour)


def wall(written=((700, 700),), blank=((1500, 700), (700, 1600), (1500, 1600)), r=220):
    """A grey wall with red hearts; the written ones carry two lines of dark pen."""
    rng = np.random.default_rng(0)
    img = np.clip(rng.normal(185, 12, (2400, 2400, 3)), 0, 255).astype(np.uint8)
    for cx, cy in list(written) + list(blank):
        draw_heart(img, cx, cy, r)
    for cx, cy in written:
        cv2.putText(img, 'ANN LEE', (cx - 150, cy - 30), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (20, 20, 20), 6)
        cv2.putText(img, '1950-2020', (cx - 160, cy + 60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 5)
    return img


def test_finds_every_heart_and_only_flags_the_written_one():
    hearts = detect.find_hearts(wall())
    assert len(hearts) == 4
    written = [h for h in hearts if h.has_writing]
    assert len(written) == 1
    h = written[0]
    assert abs(h.x + h.w / 2 - 700) < 40 and abs(h.y + h.h / 2 - 700) < 60


def test_touching_hearts_are_split():
    img = np.full((1600, 2400, 3), 185, np.uint8)
    draw_heart(img, 800, 800, 300)
    draw_heart(img, 1360, 800, 300)            # lobes overlap the first heart's
    assert len(detect.find_hearts(img)) == 2


def test_tiny_and_huge_red_areas_are_not_hearts():
    img = np.full((2400, 2400, 3), 185, np.uint8)
    draw_heart(img, 300, 300, 20)              # below MIN_SIDE
    cv2.rectangle(img, (0, 1200), (2399, 2399), RED, -1)   # a red object wider than MAX_FRAC
    assert detect.find_hearts(img) == []


def test_crops_are_sized_for_models_and_whiten_the_paint():
    img = wall()
    heart = next(h for h in detect.find_hearts(img) if h.has_writing)
    colour, enhanced, box = crops.prepare(img, heart)
    assert colour.ndim == 3 and enhanced.ndim == 2
    assert crops.MIN_LONG <= max(colour.shape[:2]) <= crops.MAX_LONG
    assert colour.shape[:2] == enhanced.shape
    x0, y0, x1, y1 = box
    assert x0 <= heart.x and y0 <= heart.y and x1 >= heart.x + heart.w and y1 >= heart.y + heart.h
    # In the enhanced crop the red paint is light and the pen is dark.
    c = enhanced[enhanced.shape[0] // 2 - 150:enhanced.shape[0] // 2 + 150, enhanced.shape[1] // 2 - 200:enhanced.shape[1] // 2 + 200]
    assert np.percentile(c, 90) > 150 and c.min() < 80


def test_small_hearts_are_enlarged_and_big_ones_reduced():
    assert max(crops.fit(np.zeros((100, 200, 3), np.uint8)).shape[:2]) == crops.MIN_LONG
    assert max(crops.fit(np.zeros((3000, 1500), np.uint8)).shape[:2]) == crops.MAX_LONG
    assert crops.fit(np.zeros((900, 800), np.uint8)).shape == (900, 800)


def test_extract_counts_every_heart_and_crops_only_written_ones(tmp_path):
    pictures, out = tmp_path / 'pictures', tmp_path / 'out'
    pictures.mkdir()
    for sub in ('photos', 'crops'):
        (out / sub).mkdir(parents=True)
    cv2.imwrite(str(pictures / 'a.jpg'), wall())
    cv2.imwrite(str(pictures / 'b - Copy.jpg'), wall(written=((700, 700), (1500, 1600)), blank=((1500, 700),)))

    records = [extract_hearts.process((str(pictures), str(out), p, False)) for p in ('a.jpg', 'b - Copy.jpg')]
    m = extract_hearts.manifest(records)
    assert m['photos'] == 2
    assert m['hearts_detected'] == 7
    assert m['hearts_with_writing'] == 3
    assert [p['hearts_with_writing'] for p in m['per_photo']] == [1, 2]
    assert len(m['crops']) == 3 and all(os.path.exists(out / c['crop']) and os.path.exists(out / c['enhanced'])
                                         for c in m['crops'])
    assert len(os.listdir(out / 'crops')) == 6
    assert json.load(open(out / 'photos' / 'a.json'))['hearts_detected'] == 4


def test_extract_reuses_the_cache_until_settings_change(tmp_path, monkeypatch):
    pictures, out = tmp_path / 'pictures', tmp_path / 'out'
    pictures.mkdir()
    for sub in ('photos', 'crops'):
        (out / sub).mkdir(parents=True)
    cv2.imwrite(str(pictures / 'a.jpg'), wall())
    job = (str(pictures), str(out), 'a.jpg', False)
    extract_hearts.process(job)

    calls = []
    monkeypatch.setattr(detect, 'find_hearts', lambda img: calls.append(1) or [])
    assert extract_hearts.process(job)['hearts_detected'] == 4 and not calls

    monkeypatch.setattr(extract_hearts, 'SETTINGS', dict(extract_hearts.SETTINGS, changed=1))
    assert extract_hearts.process(job)['hearts_detected'] == 0 and calls
    assert os.listdir(out / 'crops') == []      # stale crops removed
