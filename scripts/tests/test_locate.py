"""Tests for placing detected hearts on the stitched wall: reading the wall's tiles, matching a photo to
the wall, carrying boxes across, and the files the site reads."""
import json
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import locate_hearts  # noqa: E402
from hearts import locate  # noqa: E402
from hearts.dzi import Pyramid  # noqa: E402


# ---- reading a Deep Zoom pyramid --------------------------------------------------------------

def write_pyramid(tmp_path, image, tile=64, overlap=1, name='wall'):
    """Save `image` as the top level of a Deep Zoom pyramid (the only level these tests read)."""
    height, width = image.shape[:2]
    level = int(np.ceil(np.log2(max(width, height))))
    folder = tmp_path / (name + '_files') / str(level)
    folder.mkdir(parents=True)
    for col in range(-(-width // tile)):
        for row in range(-(-height // tile)):
            x0, y0 = max(0, col * tile - overlap), max(0, row * tile - overlap)
            x1, y1 = min(width, (col + 1) * tile + overlap), min(height, (row + 1) * tile + overlap)
            cv2.imwrite(str(folder / ('%d_%d.png' % (col, row))), image[y0:y1, x0:x1])
    path = tmp_path / (name + '.dzi')
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" '
        'Format="png" Overlap="%d" TileSize="%d"><Size Height="%d" Width="%d"/></Image>' % (overlap, tile, height, width))
    return path


def test_pyramid_reads_back_any_stretch_of_the_image(tmp_path):
    image = np.random.default_rng(1).integers(0, 255, (100, 300, 3), dtype=np.uint8)
    pyramid = Pyramid(write_pyramid(tmp_path, image))

    assert (pyramid.width, pyramid.height, pyramid.tile, pyramid.overlap) == (300, 100, 64, 1)
    assert pyramid.max_level == 9
    assert pyramid.size_at(pyramid.max_level) == (300, 100)
    assert pyramid.level_for(1) == 9 and pyramid.level_for(4) == 7
    # across tile joins, from the first column, and clipped at the right edge
    for x0, x1 in [(0, 300), (60, 70), (63, 129), (250, 400)]:
        assert np.array_equal(pyramid.read(9, x0, x1), image[:, x0:min(x1, 300)])


def test_pyramid_leaves_missing_tiles_black_and_empty_ranges_empty(tmp_path):
    image = np.full((50, 200, 3), 200, np.uint8)
    path = write_pyramid(tmp_path, image)
    os.remove(tmp_path / 'wall_files' / '8' / '1_0.png')
    pyramid = Pyramid(path)

    got = pyramid.read(8, 0, 200)
    assert got[:, 64:128].max() == 0 and got[:, :64].min() == 200
    assert pyramid.read(8, 300, 400).shape == (50, 0, 3)


# ---- matching a photo to the wall --------------------------------------------------------------

def textured(rows, cols, seed=3):
    """Blobs and strokes in all sizes: plenty to match, none of it repeating."""
    rng = np.random.default_rng(seed)
    img = np.full((rows, cols, 3), 170, np.uint8)
    for _ in range(900):
        centre = (int(rng.integers(0, cols)), int(rng.integers(0, rows)))
        colour = tuple(int(c) for c in rng.integers(20, 235, 3))
        if rng.random() < 0.5:
            cv2.circle(img, centre, int(rng.integers(3, 14)), colour, -1)
        else:
            cv2.line(img, centre, (centre[0] + int(rng.integers(-30, 30)), centre[1] + int(rng.integers(-30, 30))), colour, 2)
    return cv2.GaussianBlur(img, (0, 0), 1.2)


def photo_of(crop, h_photo_to_crop, size):
    """The photo that would register to `crop` with the given photo(1/PHOTO_DIV size)->crop homography."""
    small = cv2.warpPerspective(crop, np.linalg.inv(h_photo_to_crop), size, flags=cv2.INTER_CUBIC)
    return cv2.resize(small, None, fx=locate.PHOTO_DIV, fy=locate.PHOTO_DIV, interpolation=cv2.INTER_CUBIC)


# the photo's pixels at 1/PHOTO_DIV size land on the crop a little smaller, turned a little and moved
H_TRUE = np.array([[0.9, -0.05, 120.0], [0.04, 0.9, 60.0], [0.0, 0.0, 1.0]])


def test_register_finds_where_a_photo_sits_on_the_wall():
    crop = textured(500, 900)
    photo = photo_of(crop, H_TRUE, (640, 420))
    registration = locate.register(photo, crop, origin=4000)

    assert registration is not None and registration.inliers >= locate.MIN_INLIERS
    points = np.array([[200.0, 150.0], [1200.0, 400.0], [1700.0, 1000.0]])        # photo pixels, full size
    wall, ok, _ = registration.to_wall(points)
    expected = cv2.perspectiveTransform((points / locate.PHOTO_DIV)[None].astype(np.float32), H_TRUE)[0] * locate.WALL_DIV
    expected[:, 0] += 4000
    assert ok.all()
    assert np.abs(wall - expected).max() < 6          # full-size wall pixels; a heart is ~130 across


def test_register_follows_a_ledge_that_stands_out_from_the_wall():
    """Parallax: part of the wall sits nearer the camera, so the photo shows it displaced from the flat fit."""
    crop = textured(500, 900)
    photo = photo_of(crop, H_TRUE, (640, 420))
    band = crop.copy()
    band[200:260] = np.roll(crop[200:260], 8, axis=1)      # the ledge's strip is 8 px (32 full-size) off in the wall
    registration = locate.register(photo, band, origin=0)

    ledge = np.array([[300.0, 0.0]])
    # a photo point whose flat-fit position is on the ledge strip: find it by pushing the strip's centre back
    on_strip = cv2.perspectiveTransform(np.array([[[450.0, 230.0]]], np.float32), np.linalg.inv(H_TRUE))[0] * locate.PHOTO_DIV
    wall, ok, shift = registration.to_wall(on_strip)
    flat = cv2.perspectiveTransform((on_strip / locate.PHOTO_DIV)[None].astype(np.float32), H_TRUE)[0] * locate.WALL_DIV
    assert ok.all() and ledge.size
    assert wall[0, 0] - flat[0, 0] == pytest.approx(32, abs=10)    # the flow took up the displacement
    assert shift[0, 0] == pytest.approx(8, abs=2.5)


def test_register_gives_up_when_the_photo_does_not_belong_to_the_wall():
    crop = textured(500, 900, seed=3)
    stranger = textured(1260, 1920, seed=99)
    assert locate.register(stranger, crop, origin=0) is None
    assert locate.register(np.full((300, 300, 3), 128, np.uint8), crop, origin=0) is None      # nothing to match


def test_plausible_accepts_a_photo_sized_footprint_and_refuses_the_rest():
    size = (1024, 1360)
    assert locate.plausible(np.diag([0.9, 0.9, 1.0]), size)
    assert locate.plausible(np.array([[0.9, -0.05, 120.0], [0.04, 0.9, 60.0], [0.0, 0.0, 1.0]]), size)    # turned and moved
    assert not locate.plausible(np.diag([2.5, 2.5, 1.0]), size)                  # far bigger than the wall's pixels allow
    assert not locate.plausible(np.diag([0.2, 0.2, 1.0]), size)                  # far smaller
    assert not locate.plausible(np.diag([-0.9, 0.9, 1.0]), size)                 # mirrored
    assert not locate.plausible(np.array([[0.9, 0.0, 0.0], [0.0, 0.9, 0.0], [0.002, 0.0, 1.0]]), size)  # folded over by perspective


def test_register_refuses_a_fit_that_no_photo_could_have(monkeypatch):
    crop = textured(500, 900)
    photo = photo_of(crop, H_TRUE, (640, 420))
    monkeypatch.setattr(locate, 'SCALE_RANGE', (2.0, 3.0))
    assert locate.register(photo, crop, origin=0) is None


# ---- carrying boxes across ---------------------------------------------------------------------

class Flat:
    """A registration that moves points by a fixed amount, standing in for a solved photo."""

    def __init__(self, move=(0.0, 0.0), rows=400, cols=600, origin=1000, shifts=None):
        self.h = np.eye(3)
        self.flow = np.zeros((rows, cols, 2), np.float32) + np.float32(move)
        self.valid = np.ones((rows, cols), bool)
        self.origin = origin
        self.shifts = shifts

    to_wall = locate.Registration.to_wall


def heart(x, y, w, h, n=1, writing=False):
    return dict(box=[x, y, w, h], id='PXL_x_%03d' % n, has_writing=writing)


def test_to_wall_scales_by_the_photo_and_wall_reductions_and_adds_the_origin():
    reg = Flat(origin=1000)
    reg.h = np.diag([locate.PHOTO_DIV / locate.WALL_DIV, locate.PHOTO_DIV / locate.WALL_DIV, 1.0])   # photo px -> wall px 1:1
    wall, ok, shift = reg.to_wall(np.array([[300.0, 200.0]]))
    assert wall[0].tolist() == pytest.approx([1000 + 300.0, 200.0])
    assert ok.all() and not shift.any()


def test_to_wall_refuses_points_off_the_photo_and_failed_flow():
    reg = Flat()
    reg.valid[:, 300:] = False                                  # the photo ends at column 300
    reg.flow[:100] = locate.MAX_FLOW + 1                        # flow ran away in the top rows
    reg.flow[110, 10] = np.nan
    # (column, row) at match size: fine, in the runaway rows, on the nan, past the photo's end, left of it, below it
    spots = np.array([[100, 200], [100, 20], [10, 110], [450, 150], [-10, 16], [20, 9999]], float)
    _, ok, _ = reg.to_wall(spots * locate.PHOTO_DIV)
    assert ok.tolist() == [True, False, False, False, False, False]


def test_place_hearts_averages_a_boxs_corners_into_a_wall_box():
    reg = Flat(move=(5.0, -2.0))
    placed = locate.place_hearts(reg, [heart(300, 600, 120, 150, n=7, writing=True)])

    assert len(placed) == 1
    box = placed[0]
    # moving the flow by (5, -2) match-size px moves a box by (20, -8) full-size wall px, which keeps its size
    left = 300 / locate.PHOTO_DIV * locate.WALL_DIV + 1000 + 20
    assert (box['x'], box['w'], box['h']) == (round(left), 120 / locate.PHOTO_DIV * locate.WALL_DIV, 150 / locate.PHOTO_DIV * locate.WALL_DIV)
    assert box['y'] == round(600 / locate.PHOTO_DIV * locate.WALL_DIV - 8)
    assert box['heart']['id'] == 'PXL_x_007'
    assert locate.place_hearts(reg, []) == []


def test_place_hearts_leaves_out_hearts_it_cannot_vouch_for():
    reg = Flat()
    reg.valid[:, 300:] = False                                                          # the photo ends at column 300
    reg.flow[:, :, 0] = np.linspace(0, locate.MAX_FLOW * 0.9, reg.flow.shape[1])        # shift grows steeply across the photo
    steep = heart(150, 300, 600, 300, n=1)                                              # its corners move very differently
    fine = heart(30, 60, 30, 30, n=2)
    off = heart(300 * locate.PHOTO_DIV, 100, 60, 60, n=3)                               # beyond the photo
    kept = locate.place_hearts(reg, [steep, fine, off])
    assert [b['heart']['id'] for b in kept] == ['PXL_x_002']


def test_place_hearts_drops_hearts_cut_off_by_the_photos_border():
    reg = Flat()
    hearts = [heart(5, 300, 100, 100, n=1), heart(400, 3, 100, 100, n=2), heart(2900, 300, 172, 100, n=3),
              heart(400, 3950, 100, 125, n=4), heart(400, 300, 100, 100, n=5)]
    kept = locate.place_hearts(reg, hearts, size=(3072, 4080))
    assert [b['heart']['id'] for b in kept] == ['PXL_x_005']


def test_find_photo_wants_the_size_the_hearts_were_found_on(tmp_path):
    pictures, originals = tmp_path / 'pictures', tmp_path / 'originals'
    pictures.mkdir()
    originals.mkdir()
    record = dict(width=300, height=200)
    cv2.imwrite(str(pictures / 'same.jpg'), np.zeros((200, 300, 3), np.uint8))
    cv2.imwrite(str(pictures / 'edited.jpg'), np.zeros((100, 150, 3), np.uint8))      # replaced by a smaller edit
    cv2.imwrite(str(originals / 'edited.jpg'), np.zeros((200, 300, 3), np.uint8))

    assert locate_hearts.find_photo('same.jpg', record, str(pictures)).shape[:2] == (200, 300)
    assert locate_hearts.find_photo('edited.jpg', record, str(pictures)) is None
    assert locate_hearts.find_photo('edited.jpg', record, str(pictures), str(originals)).shape[:2] == (200, 300)
    assert locate_hearts.find_photo('missing.jpg', record, str(pictures), str(originals)) is None


def test_owned_keeps_only_boxes_centred_in_the_photos_own_stretch():
    boxes = [dict(x=80, y=0, w=20, h=20), dict(x=100, y=0, w=20, h=20), dict(x=190, y=0, w=20, h=20), dict(x=181, y=0, w=20, h=20)]
    # centres 90, 110, 200, 191: the stretch is [100, 200)
    assert [b['x'] for b in locate.owned(boxes, 100, 200)] == [100, 181]


# ---- the files the site reads -----------------------------------------------------------------

def test_parse_photos_reads_numbers_and_ranges():
    assert locate_hearts.parse_photos('1-3,7') == [1, 2, 3, 7]
    assert locate_hearts.parse_photos('5, 2-3, 3') == [2, 3, 5]
    assert locate_hearts.parse_photos('') is None and locate_hearts.parse_photos(None) is None


def test_stretches_run_from_where_a_photo_starts_to_where_the_next_does():
    wall = dict(width=9000, photos=[
        dict(number=2, x=3000, file='b.jpg'), dict(number=1, x=168, file='a.jpg'), dict(number=3, x=6000, file='c.jpg')])
    plan = locate_hearts.stretches(wall)
    assert [(n, plan[n][1], plan[n][2]) for n in (1, 2, 3)] == [(1, 0, 3000), (2, 3000, 6000), (3, 6000, 9000)]
    assert plan[2][0]['file'] == 'b.jpg'


def test_chunk_lists_a_photos_boxes_left_to_right_with_their_numbers():
    boxes = [dict(x=300, y=10, w=50, h=60, heart=heart(0, 0, 1, 1, n=12, writing=True)),
             dict(x=100, y=90, w=40, h=40, heart=heart(0, 0, 1, 1, n=5)),
             dict(x=100, y=20, w=40, h=40, heart=heart(0, 0, 1, 1, n=6))]
    data = locate_hearts.chunk(dict(number=4, file='d.jpg'), 0, 500, boxes)
    assert data == dict(photo=4, file='d.jpg', x0=0, x1=500,
                        hearts=[[100, 20, 40, 40, 0, 6], [100, 90, 40, 40, 0, 5], [300, 10, 50, 60, 1, 12]])


def entry(number):
    return dict(number=number, file='%04d.json' % number, x0=0, x1=1, hearts=1, writing=0)


def test_merge_index_adds_and_replaces_photos_for_the_same_wall():
    old = dict(dzi='/wall/a.dzi', photos=[entry(1), entry(2)])
    new = locate_hearts.merge_index(old, '/wall/a.dzi', [dict(entry(2), hearts=9), entry(5)])
    assert new['dzi'] == '/wall/a.dzi'
    assert [(e['number'], e['hearts']) for e in new['photos']] == [(1, 1), (2, 9), (5, 1)]
    assert new['generated']


def test_merge_index_forgets_boxes_made_for_another_wall_and_dropped_photos():
    old = dict(dzi='/wall/a.dzi', photos=[entry(1), entry(2)])
    assert [e['number'] for e in locate_hearts.merge_index(old, '/wall/b.dzi', [entry(3)])['photos']] == [3]
    assert [e['number'] for e in locate_hearts.merge_index(old, '/wall/a.dzi', [], drop=[1])['photos']] == [2]
    assert locate_hearts.merge_index(None, '/wall/a.dzi', [entry(1)])['photos'][0]['number'] == 1


def test_write_json_replaces_the_file_in_one_piece(tmp_path):
    target = tmp_path / 'index.json'
    locate_hearts.write_json(target, dict(a=[1, 2]))
    locate_hearts.write_json(target, dict(a=[3]))
    assert json.loads(target.read_text()) == dict(a=[3])
    assert [p.name for p in tmp_path.iterdir()] == ['index.json']
