"""Tests for the Kaggle dataset: taking GPS out of photos without touching anything else, and building the
files from photos, detector results and the wall's layout."""
import csv
import io
import json
import os
import struct
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_dataset  # noqa: E402
from hearts import exif as exif_tools  # noqa: E402

GPS = {1: 'N', 2: (51.0, 30.0, 2.06), 3: 'W', 4: (0.0, 7.0, 12.38), 6: 49.2}


def jpeg(size=(200, 300), seed=0, gps=True, taken='2023:07:30 09:49:39', offset='+01:00', exif=True):
    """A JPEG of noise, with the EXIF a Pixel writes: camera, time, and (optionally) a GPS position."""
    pixels = np.random.default_rng(seed).integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    info = Image.Exif()
    info[0x010F], info[0x0110] = 'Google', 'Pixel 6 Pro'
    if taken:
        info.get_ifd(0x8769)[0x9003] = taken
    if offset:
        info.get_ifd(0x8769)[0x9011] = offset
    if gps:
        info.get_ifd(0x8825).update(GPS)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, 'JPEG', quality=90, **({'exif': info} if exif else {}))
    return buffer.getvalue()


def tags(data):
    info = Image.open(io.BytesIO(data)).getexif()
    return {k: v for k, v in info.items() if k != 0x8825}, dict(info.get_ifd(0x8769)), dict(info.get_ifd(0x8825))


# ---- taking GPS out ---------------------------------------------------------------------------

def test_strip_gps_removes_the_position_and_nothing_else():
    original = jpeg()
    assert tags(original)[2]                                   # it has a position to begin with
    stripped = exif_tools.strip_gps(original)

    assert len(stripped) == len(original)
    assert tags(stripped)[2] == {}
    assert 0x8825 not in Image.open(io.BytesIO(stripped)).getexif()
    assert tags(stripped)[:2] == tags(original)[:2]            # camera, time and the rest are as they were
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(stripped))), np.asarray(Image.open(io.BytesIO(original))))
    # only the EXIF header differs: the picture's own bytes are the same
    start = original.index(b'\xff\xda')
    assert stripped[start:] == original[start:]


def test_strip_gps_leaves_no_trace_of_the_values():
    stripped = exif_tools.strip_gps(jpeg())
    for value in (struct.pack('<II', 12380, 1000), struct.pack('<II', 206, 100)):    # seconds of the position, as rationals
        assert value not in stripped


def test_strip_gps_leaves_a_photo_without_gps_alone_and_is_repeatable():
    plain = jpeg(gps=False)
    assert exif_tools.strip_gps(plain) == plain
    once = exif_tools.strip_gps(jpeg())
    assert exif_tools.strip_gps(once) == once
    assert exif_tools.strip_gps(jpeg(exif=False)) == jpeg(exif=False)


def test_strip_gps_rejects_what_is_not_a_jpeg():
    with pytest.raises(ValueError, match='not a JPEG'):
        exif_tools.strip_gps(b'GIF89a....')


def exif_jpeg(tiff):
    """A minimal JPEG whose EXIF is the given TIFF block."""
    payload = b'Exif\x00\x00' + tiff
    return b'\xff\xd8' + b'\xff\xe1' + struct.pack('>H', len(payload) + 2) + payload + b'\xff\xda\x00\x02' + b'\x00' * 8 + b'\xff\xd9'


def exif_of(data):
    """The EXIF of a JPEG made by exif_jpeg, as PIL reads it."""
    length = struct.unpack('>H', data[4:6])[0]
    info = Image.Exif()
    info.load(data[6:4 + length])
    return info


def tiff_block(order):
    """IFD0 with Make, Orientation and a GPS pointer, then the GPS directory with a latitude out of line, in either byte order."""
    e = order
    gps_at = 8 + 2 + 3 * 12 + 4
    value_at = gps_at + 2 + 2 * 12 + 4
    ifd0 = struct.pack(e + 'H', 3)
    ifd0 += struct.pack(e + 'HHI4s', 0x010F, 2, 3, b'Hi\x00\x00')
    ifd0 += struct.pack(e + 'HHIHH', 0x0112, 3, 1, 1, 0)
    ifd0 += struct.pack(e + 'HHII', 0x8825, 4, 1, gps_at) + struct.pack(e + 'I', 0)
    gps = struct.pack(e + 'H', 2) + struct.pack(e + 'HHI4s', 1, 2, 2, b'N\x00\x00\x00') + struct.pack(e + 'HHII', 2, 5, 3, value_at) + struct.pack(e + 'I', 0)
    values = struct.pack(e + 'IIIIII', 51, 1, 30, 1, 2, 1)
    return (b'II' if e == '<' else b'MM') + struct.pack(e + 'HI', 42, 8) + ifd0 + gps + values


@pytest.mark.parametrize('order', ['<', '>'])
def test_strip_gps_works_in_either_byte_order(order):
    original = exif_jpeg(tiff_block(order))
    before = exif_of(original)
    assert before[0x010F] == 'Hi' and before.get_ifd(0x8825)

    stripped = exif_tools.strip_gps(original)
    after = exif_of(stripped)
    assert after[0x010F] == 'Hi' and after[0x0112] == 1        # the entries around the GPS pointer survive, in order
    assert not after.get_ifd(0x8825) and 0x8825 not in after
    assert struct.pack(order + 'IIIIII', 51, 1, 30, 1, 2, 1) not in stripped
    assert len(stripped) == len(original)


def test_strip_gps_refuses_a_header_that_points_outside_itself():
    tiff = bytearray(tiff_block('<'))
    gps_entry = 8 + 2 + 2 * 12                                   # the third entry of IFD0
    struct.pack_into('<I', tiff, gps_entry + 8, 5000)            # GPS directory "at" 5000
    with pytest.raises(ValueError, match='outside'):
        exif_tools.strip_gps(exif_jpeg(bytes(tiff)))
    assert exif_tools.strip_gps(exif_jpeg(b'XX' + bytes(tiff)[2:])) == exif_jpeg(b'XX' + bytes(tiff)[2:])      # not TIFF at all: untouched


# ---- pieces of the dataset ---------------------------------------------------------------------

def test_clean_name_drops_the_copy_suffix():
    assert build_dataset.clean_name('PXL_20230730_090155893 - Copy.jpg') == 'PXL_20230730_090155893.jpg'
    assert build_dataset.clean_name('PXL_20230730_090155893.jpg') == 'PXL_20230730_090155893.jpg'


def test_capture_info_reads_local_time_with_its_offset_and_the_camera():
    assert build_dataset.capture_info(jpeg()) == ('2023-07-30T09:49:39+01:00', 'Google Pixel 6 Pro')
    assert build_dataset.capture_info(jpeg(offset=None))[0] == '2023-07-30T09:49:39'
    assert build_dataset.capture_info(jpeg(exif=False)) == ('', '')
    assert build_dataset.capture_info(jpeg(taken='not a time'))[0] == ''


def test_describe_dates_names_the_days_and_says_the_year_once():
    assert build_dataset.describe_dates(['2023-08-21', '2023-07-30', '2023-08-20', '2023-07-30']) == '30 July, 20 August and 21 August 2023'
    assert build_dataset.describe_dates(['2023-08-21']) == '21 August 2023'
    assert build_dataset.describe_dates(['2023-12-30', '2024-01-02']) == '30 December 2023 and 2 January 2024'
    assert build_dataset.describe_dates([]) == 'a few days'


def test_splits_are_runs_along_the_wall_with_a_photo_left_out_between_them():
    split = build_dataset.assign_splits(range(1, 101))
    order = [split[n] for n in range(1, 101)]
    assert order == ['train'] * 70 + ['gap'] + ['val'] * 14 + ['gap'] + ['test'] * 14
    assert build_dataset.assign_splits([5, 3, 4])[3] == 'train'       # numbers need not start at 1 or arrive in order
    assert build_dataset.assign_splits([]) == {}


def heart(i, box, ink=0.0, strokes=0, writing=False):
    return dict(id='PXL_x_-_Copy_%03d' % i, box=box, area=900, ink=ink, strokes=strokes, has_writing=writing)


def test_heart_rows_carry_the_detectors_measures_under_a_clean_id():
    rows = build_dataset.heart_rows(dict(hearts=[heart(7, [10, 20, 30, 40], 0.12, 4, True)]), 'PXL_x.jpg')
    assert rows == [dict(heart_id='PXL_x_007', image='images/PXL_x.jpg', x=10, y=20, width=30, height=40, paint_area_px=900,
                         ink_ratio=0.12, ink_strokes=4, has_writing=True)]


def test_yolo_lines_give_class_and_a_box_as_fractions_of_the_image():
    rows = [dict(x=100, y=200, width=50, height=100, has_writing=False), dict(x=0, y=0, width=200, height=400, has_writing=True)]
    assert build_dataset.yolo_lines(rows, 400, 800) == ['0 0.312500 0.312500 0.125000 0.125000', '1 0.250000 0.250000 0.500000 0.500000']
    assert build_dataset.yolo_lines([], 400, 800) == []


def test_coco_ties_boxes_to_images_and_classes():
    photos = [dict(image='images/a.jpg', width=300, height=400, captured='2023-07-30T09:00:00+01:00', wall_photo_number=1),
              dict(image='images/b.jpg', width=400, height=300, captured='', wall_photo_number=None)]
    hearts = [dict(image='images/b.jpg', x=5, y=6, width=7, height=8, has_writing=True, heart_id='b_001', paint_area_px=30, ink_ratio=0.1, ink_strokes=3),
              dict(image='images/a.jpg', x=1, y=2, width=3, height=4, has_writing=False, heart_id='a_001', paint_area_px=9, ink_ratio=0.0, ink_strokes=0)]
    data = build_dataset.coco(photos, hearts)

    assert [c['name'] for c in data['categories']] == ['heart', 'heart_with_writing']
    assert [(i['id'], i['file_name'], i['wall_photo_number']) for i in data['images']] == [(1, 'images/a.jpg', 1), (2, 'images/b.jpg', None)]
    first, second = data['annotations']
    assert (first['image_id'], first['category_id'], first['bbox'], first['area']) == (2, 2, [5, 6, 7, 8], 56)
    assert (second['image_id'], second['category_id']) == (1, 1)
    assert data['licenses'][0]['name'] == 'CC BY-NC 4.0'


def test_write_csv_leaves_missing_values_blank(tmp_path):
    columns = [('a', 'integer', ''), ('b', 'string', '')]
    build_dataset.write_csv(tmp_path / 't.csv', columns, [dict(a=1, b=None), dict(a=None, b='x, y')])
    assert (tmp_path / 't.csv').read_text().splitlines() == ['a,b', '1,', ',"x, y"']


def test_find_source_wants_the_size_the_hearts_were_found_on(tmp_path):
    pictures, originals = tmp_path / 'pictures', tmp_path / 'originals'
    pictures.mkdir()
    originals.mkdir()
    (pictures / 'same.jpg').write_bytes(jpeg((300, 400)))
    (pictures / 'edit.jpg').write_bytes(jpeg((150, 200)))
    (originals / 'edit.jpg').write_bytes(jpeg((300, 400)))
    record = dict(width=300, height=400)

    assert build_dataset.find_source('same.jpg', record, str(pictures)) == str(pictures / 'same.jpg')
    assert build_dataset.find_source('edit.jpg', record, str(pictures)) is None
    assert build_dataset.find_source('edit.jpg', record, str(pictures), str(originals)) == str(originals / 'edit.jpg')
    assert build_dataset.find_source('gone.jpg', record, str(pictures), str(originals)) is None


# ---- building the whole dataset -------------------------------------------------------------------

def make_world(tmp_path, with_originals=True):
    """Three photos (one with a byte-identical ' - Copy', one a close-up, one since replaced by a smaller edit), their
    detector results, a wall layout and an overview."""
    pictures, originals, hearts = tmp_path / 'pictures', tmp_path / 'originals', tmp_path / 'hearts'
    (hearts / 'photos').mkdir(parents=True)
    pictures.mkdir()
    originals.mkdir()
    (tmp_path / 'wall').mkdir()
    full = {'a - Copy.jpg': jpeg((300, 400), 1), 'b.jpg': jpeg((300, 400), 2, taken='2023:08:20 10:00:00'), 'c.jpg': jpeg((400, 300), 3, taken='2023:08:13 18:00:00')}
    (pictures / 'a - Copy.jpg').write_bytes(full['a - Copy.jpg'])
    (pictures / 'a.jpg').write_bytes(full['a - Copy.jpg'])                      # byte-identical: left out
    (pictures / 'b.jpg').write_bytes(jpeg((150, 200), 2, exif=False))           # the edit that replaced it
    (originals / 'b.jpg').write_bytes(full['b.jpg'])
    (pictures / 'c.jpg').write_bytes(full['c.jpg'])
    boxes = {'a - Copy': [[10, 20, 60, 80, 0.2, 5, True], [100, 120, 50, 50, 0.0, 0, False]], 'b': [[30, 40, 90, 90, 0.0, 0, False]], 'c': []}
    sizes = {'a - Copy': (300, 400), 'b': (300, 400), 'c': (400, 300)}
    for stem, rows in boxes.items():
        record = dict(photo=stem + '.jpg', width=sizes[stem][0], height=sizes[stem][1], settings={'detect.MIN_SIDE': 80},
                      hearts=[dict(id='%s_%03d' % (stem.replace(' ', '_'), i), box=r[:4], area=800, ink=r[4], strokes=r[5], has_writing=r[6]) for i, r in enumerate(rows, 1)])
        (hearts / 'photos' / (stem + '.json')).write_text(json.dumps(record))
    wall = dict(dzi='/wall/w.dzi', overview='/wall/w-overview.jpg', width=1000, height=100,
                photos=[dict(x=0, number=1, file='a - Copy.jpg'), dict(x=500, number=2, file='b.jpg')])
    (tmp_path / 'wall' / 'wall.json').write_text(json.dumps(wall))
    Image.new('RGB', (200, 10), (200, 30, 40)).save(tmp_path / 'wall' / 'w-overview.jpg')
    return dict(pictures=str(pictures), originals=str(originals) if with_originals else None, hearts_dir=str(hearts),
                wall_path=str(tmp_path / 'wall' / 'wall.json'), out=str(tmp_path / 'out'))


def read(path):
    with open(path, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def test_build_with_boxes_makes_a_checked_dataset_from_photos_boxes_and_layout(tmp_path):
    world = make_world(tmp_path)
    stats = build_dataset.build(**world, kaggle_user='someone', log=lambda *a: None, with_boxes=True)
    out = tmp_path / 'out'

    assert build_dataset.verify(out) == []
    assert sorted(os.listdir(out / 'images')) == ['a.jpg', 'b.jpg', 'c.jpg']              # clean names, no duplicate
    assert (stats['photos'], stats['wall_photos'], stats['closeups'], stats['hearts'], stats['written']) == (3, 2, 1, 3, 1)
    assert stats['originals_used'] == 1 and stats['wall_size'] == '300 x 400' and stats['closeup_size'] == '400 x 300'
    assert stats['camera'] == 'Google Pixel 6 Pro'

    # the photo that had been replaced is the full-size original, and no photo keeps its position
    assert Image.open(out / 'images' / 'b.jpg').size == (300, 400)
    assert all(not tags((out / 'images' / n).read_bytes())[2] for n in os.listdir(out / 'images'))
    assert tags((out / 'images' / 'a.jpg').read_bytes())[:2] == tags(jpeg((300, 400), 1))[:2]

    photos = read(out / 'photos.csv')
    assert [(p['image'], p['wall_photo_number'], p['on_wall'], p['wall_x_start'], p['wall_x_end']) for p in photos] == [
        ('images/a.jpg', '1', 'True', '0', '500'), ('images/b.jpg', '2', 'True', '500', '1000'), ('images/c.jpg', '', 'False', '', '')]
    assert photos[0]['captured'] == '2023-07-30T09:49:39+01:00' and photos[0]['hearts_with_writing'] == '1'
    assert [p['suggested_split'] for p in photos] == ['train', 'gap', '']                  # two photos: one to train on, one left out
    hearts = read(out / 'hearts.csv')
    assert [h['heart_id'] for h in hearts] == ['a_001', 'a_002', 'b_001'] and hearts[0]['has_writing'] == 'True'
    assert (out / 'labels' / 'c.txt').read_text() == ''                                  # a photo with no hearts: an empty label file
    assert len((out / 'labels' / 'a.txt').read_text().splitlines()) == 2
    assert (out / 'splits' / 'train.txt').read_text() == 'images/a.jpg\n' and (out / 'splits' / 'test.txt').read_text() == ''
    assert 'heart_with_writing' in (out / 'data.yaml').read_text()

    layout = json.loads((out / 'wall' / 'layout.json').read_text())
    assert layout['overview'] == dict(file='overview.jpg', width=200, height=10) and [p['x_start'] for p in layout['photos']] == [0, 500]
    assert len(json.loads((out / 'annotations_coco.json').read_text())['annotations']) == 3


def test_build_with_boxes_writes_kaggle_metadata_that_meets_its_rules(tmp_path):
    build_dataset.build(**make_world(tmp_path), kaggle_user='someone', log=lambda *a: None, with_boxes=True)
    meta = json.loads((tmp_path / 'out' / 'dataset-metadata.json').read_text())

    assert meta['id'] == 'someone/national-covid-memorial-wall-hearts'
    assert meta['licenses'] == [dict(name='CC-BY-NC-4.0')]
    assert 6 <= len(meta['title']) <= 50 and 20 <= len(meta['subtitle']) <= 80
    assert meta['subtitle'].startswith('3 photos of the memorial wall') and 'auto-detected' in meta['subtitle']
    assert [r['path'] for r in meta['resources']][:2] == ['photos.csv', 'hearts.csv']
    assert {f['name'] for f in meta['resources'][1]['schema']['fields']} == set(read(tmp_path / 'out' / 'hearts.csv')[0])
    assert not meta['description'].startswith('#') and 'not checked by a person' in meta['description']
    card = (tmp_path / 'out' / 'README.md').read_text()
    assert card.startswith('# National Covid Memorial Wall: Hearts') and '30 July, 13 August and 20 August 2023' in card


def test_build_with_boxes_can_be_run_again_over_its_own_output(tmp_path):
    world = make_world(tmp_path)
    build_dataset.build(**world, log=lambda *a: None, with_boxes=True)
    (tmp_path / 'out' / 'images' / 'stale.jpg').write_bytes(b'x')
    build_dataset.build(**world, log=lambda *a: None, with_boxes=True)

    assert not (tmp_path / 'out' / 'images' / 'stale.jpg').exists()
    assert build_dataset.verify(tmp_path / 'out') == []


def test_build_stops_and_says_why_when_a_photo_cannot_be_had_at_the_size_it_was_searched(tmp_path):
    with pytest.raises(SystemExit) as stopped:
        build_dataset.build(**make_world(tmp_path, with_originals=False), log=lambda *a: None, with_boxes=True)
    assert 'b.jpg' in str(stopped.value) and '300x400' in str(stopped.value) and '--originals' in str(stopped.value)


def test_build_stops_for_a_photo_the_detector_has_not_seen(tmp_path):
    world = make_world(tmp_path)
    os.remove(os.path.join(world['hearts_dir'], 'photos', 'c.json'))
    with pytest.raises(SystemExit) as stopped:
        build_dataset.build(**world, log=lambda *a: None, with_boxes=True)
    assert 'c.jpg' in str(stopped.value) and 'extract_hearts' in str(stopped.value)


def test_verify_reports_what_is_wrong_with_a_dataset_with_boxes(tmp_path):
    build_dataset.build(**make_world(tmp_path), log=lambda *a: None, with_boxes=True)
    out = tmp_path / 'out'
    (out / 'images' / 'a.jpg').write_bytes(jpeg((300, 400), 1))                              # a photo that still has its position
    rows = read(out / 'hearts.csv')
    rows[0]['x'] = '290'                                                                      # a box running off the photo
    with open(out / 'hearts.csv', 'w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / 'labels' / 'b.txt').write_text('')

    problems = ' | '.join(build_dataset.verify(out))
    assert 'images/a.jpg still has GPS' in problems
    assert 'a_001: box outside the photo' in problems
    assert 'images/b.jpg: label file has the wrong number of boxes' in problems


# ---- the photos-only dataset (the default) --------------------------------------------------------

def test_pick_source_takes_the_largest_file_and_the_first_on_a_tie(tmp_path):
    pictures, originals = tmp_path / 'pictures', tmp_path / 'originals'
    pictures.mkdir()
    originals.mkdir()
    (pictures / 'edit.jpg').write_bytes(jpeg((150, 200)))
    (originals / 'edit.jpg').write_bytes(jpeg((300, 400)))
    (pictures / 'same.jpg').write_bytes(jpeg((300, 400)))
    (originals / 'same.jpg').write_bytes(jpeg((300, 400), seed=9))
    (pictures / 'only.jpg').write_bytes(jpeg((300, 400)))

    assert build_dataset.pick_source('edit.jpg', str(pictures), str(originals)) == str(originals / 'edit.jpg')
    assert build_dataset.pick_source('same.jpg', str(pictures), str(originals)) == str(pictures / 'same.jpg')
    assert build_dataset.pick_source('only.jpg', str(pictures), str(originals)) == str(pictures / 'only.jpg')
    assert build_dataset.pick_source('only.jpg', str(pictures)) == str(pictures / 'only.jpg')
    assert build_dataset.pick_source('gone.jpg', str(pictures), str(originals)) is None


def photos_only(tmp_path, **kwargs):
    world = make_world(tmp_path, **kwargs)
    world['hearts_dir'] = None                      # no detector results are needed
    return world


def test_photos_only_dataset_has_no_boxes_at_all(tmp_path):
    world = photos_only(tmp_path)
    stats = build_dataset.build(**world, kaggle_user='someone', log=lambda *a: None)
    out = tmp_path / 'out'

    assert sorted(os.listdir(out)) == ['README.md', 'dataset-metadata.json', 'images', 'photos.csv', 'wall']
    assert sorted(os.listdir(out / 'images')) == ['a.jpg', 'b.jpg', 'c.jpg']
    assert (stats['photos'], stats['wall_photos'], stats['closeups'], stats['hearts'], stats['originals_used']) == (3, 2, 1, 0, 1)
    assert Image.open(out / 'images' / 'b.jpg').size == (300, 400)               # the original, not the smaller edit
    assert all(not tags((out / 'images' / n).read_bytes())[2] for n in os.listdir(out / 'images'))
    assert build_dataset.verify(out) == []


def test_photos_only_photos_csv_keeps_order_and_position_but_no_heart_columns(tmp_path):
    build_dataset.build(**photos_only(tmp_path), log=lambda *a: None)
    rows = read(tmp_path / 'out' / 'photos.csv')

    assert list(rows[0]) == ['image', 'wall_photo_number', 'on_wall', 'captured', 'capture_date', 'width', 'height', 'camera', 'wall_x_start', 'wall_x_end']
    assert [(r['image'], r['wall_photo_number'], r['width'], r['height']) for r in rows] == [
        ('images/a.jpg', '1', '300', '400'), ('images/b.jpg', '2', '300', '400'), ('images/c.jpg', '', '400', '300')]
    assert rows[0]['captured'] == '2023-07-30T09:49:39+01:00' and rows[1]['wall_x_start'] == '500'
    layout = json.loads((tmp_path / 'out' / 'wall' / 'layout.json').read_text())
    assert [p['number'] for p in layout['photos']] == [1, 2] and layout['overview']['file'] == 'overview.jpg'


def test_photos_only_card_and_metadata_say_nothing_of_boxes(tmp_path):
    build_dataset.build(**photos_only(tmp_path), kaggle_user='someone', log=lambda *a: None)
    out = tmp_path / 'out'
    meta = json.loads((out / 'dataset-metadata.json').read_text())
    card = (out / 'README.md').read_text()

    assert meta['id'] == 'someone/national-covid-memorial-wall-photos' and meta['title'] == 'National Covid Memorial Wall: Photos'
    assert meta['licenses'] == [dict(name='CC-BY-NC-4.0')]
    assert 6 <= len(meta['title']) <= 50 and 20 <= len(meta['subtitle']) <= 80 and meta['subtitle'].startswith('3 photographs')
    assert [r['path'] for r in meta['resources']] == ['photos.csv', 'wall/layout.json']
    assert 'object-detection' not in meta['keywords']
    for text in (card, meta['description'], meta['subtitle']):
        for word in ('box', 'hearts.csv', 'detect', 'YOLO', 'COCO', 'has_writing'):
            assert word not in text, word
    assert card.startswith('# National Covid Memorial Wall: Photos') and 'split by position along the wall' in card
    assert '3 photographs of the National Covid Memorial Wall on the Albert Embankment in London: 2 that run' in card and '1 close-ups.' in card
    assert 'GPS position was removed' in card and 'this is a memorial' in card and 'CC BY-NC 4.0' in card


def test_photos_only_needs_no_detector_results_and_takes_the_larger_file_without_being_told_why(tmp_path):
    world = photos_only(tmp_path, with_originals=False)
    build_dataset.build(**world, log=lambda *a: None)                            # b.jpg is only the small edit here: it is used
    assert Image.open(tmp_path / 'out' / 'images' / 'b.jpg').size == (150, 200)


def test_a_photos_only_run_clears_the_boxes_an_earlier_run_left_in_the_same_folder(tmp_path):
    world = make_world(tmp_path)
    build_dataset.build(**world, log=lambda *a: None, with_boxes=True)
    out = tmp_path / 'out'
    assert (out / 'hearts.csv').exists() and (out / 'labels').exists()

    build_dataset.build(**dict(world, hearts_dir=None), log=lambda *a: None)
    assert sorted(os.listdir(out)) == ['README.md', 'dataset-metadata.json', 'images', 'photos.csv', 'wall']
    assert build_dataset.verify(out) == []


def test_verify_notices_boxes_left_in_a_dataset_that_should_not_have_them(tmp_path):
    build_dataset.build(**photos_only(tmp_path), log=lambda *a: None)
    out = tmp_path / 'out'
    (out / 'data.yaml').write_text('names: {}\n')
    (out / 'images' / 'a.jpg').write_bytes(jpeg((300, 400), 1))                 # and a photo that still has its position

    problems = ' | '.join(build_dataset.verify(out))
    assert 'boxes left over' in problems and 'images/a.jpg still has GPS' in problems
