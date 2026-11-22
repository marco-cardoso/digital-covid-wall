#!/usr/bin/env python3
"""Prepare the wall photos as a dataset to upload to Kaggle.

    python scripts/build_dataset.py --originals <folder of the full-size photos> --kaggle-user <name>

Output (build/kaggle/national-covid-memorial-wall-photos by default; build/ is git-ignored):
  images/            every unique photo, full size, with the GPS position taken out of its EXIF (nothing else changes)
  photos.csv         one row per photo: its place in the order along the wall, when it was taken, the camera
  wall/              a thumbnail strip of the stitched wall and where each photo sits along it
  README.md, dataset-metadata.json                       the dataset card and Kaggle's metadata

Photos replaced by smaller edits in --pictures are taken from --originals instead (the larger file wins).

With --with-boxes the detector's heart boxes (scripts/extract_hearts.py, results in build/hearts/photos) go in too, as
hearts.csv, COCO annotations_coco.json and YOLO labels/, with a suggested split in splits/ and data.yaml, under the
name national-covid-memorial-wall-hearts. The boxes are in the pixels of the photo that was searched, so there the
file must be the size its hearts were found on.

Then upload with the command the script prints.
"""
import argparse
import csv
import io
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hearts.exif import strip_gps  # noqa: E402
from locate_hearts import stretches  # noqa: E402
from wall.features import list_photos  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SLUG = 'national-covid-memorial-wall-photos'
TITLE = 'National Covid Memorial Wall: Photos'
BOXES_SLUG = 'national-covid-memorial-wall-hearts'
BOXES_TITLE = 'National Covid Memorial Wall: Hearts'
BOX_FILES = ('hearts.csv', 'annotations_coco.json', 'data.yaml')       # what --with-boxes adds, besides labels/ and splits/
LICENSE = 'CC-BY-NC-4.0'
CLASSES = ['heart', 'heart_with_writing']          # YOLO class ids 0 and 1; COCO ids 1 and 2
SPLITS = (0.70, 0.15)                              # train and validation shares of the wall; the rest is test
LICENSE_URL = 'https://creativecommons.org/licenses/by-nc/4.0/'


def clean_name(name):
    """'PXL_x - Copy.jpg' -> 'PXL_x.jpg': the ' - Copy' is a leftover of how the files were gathered."""
    return name.replace(' - Copy', '')


def find_source(name, record, pictures, originals=None):
    """Path of the file for a photo in the size its hearts were found on, or None (a smaller edit may have replaced it)."""
    for folder in (pictures, originals):
        path = os.path.join(folder, name) if folder else None
        if path and os.path.exists(path):
            with Image.open(path) as image:
                if image.size == (record.get('width'), record.get('height')):
                    return path
    return None


def pick_source(name, pictures, originals=None):
    """Path of the largest file called `name` in the folders (the first on a tie): a smaller edit never beats its original."""
    best, best_pixels = None, -1
    for folder in (pictures, originals):
        path = os.path.join(folder, name) if folder else None
        if path and os.path.exists(path):
            with Image.open(path) as image:
                pixels = image.width * image.height
            if pixels > best_pixels:
                best, best_pixels = path, pixels
    return best


def capture_info(jpeg):
    """(local capture time as ISO 8601 with its UTC offset, camera) from a JPEG's EXIF; blanks where it has none."""
    exif = Image.open(io.BytesIO(jpeg)).getexif()
    sub = exif.get_ifd(0x8769)
    taken = sub.get(0x9003) or exif.get(0x0132)
    when = ''
    if taken:
        try:
            when = datetime.strptime(str(taken), '%Y:%m:%d %H:%M:%S').isoformat() + (sub.get(0x9011) or '')
        except ValueError:
            when = ''
    return when, ' '.join(str(p) for p in (exif.get(0x010F), exif.get(0x0110)) if p)


def describe_dates(dates):
    """['2023-07-30', '2023-08-01'] -> '30 July and 1 August 2023' (the year said once when it is the same)."""
    days = [datetime.strptime(d, '%Y-%m-%d') for d in sorted(set(dates))]
    if not days:
        return 'a few days'
    same_year = len({d.year for d in days}) == 1
    parts = [('%d %s' % (d.day, d.strftime('%B'))) + ('' if same_year else ' %d' % d.year) for d in days]
    text = parts[0] if len(parts) == 1 else ', '.join(parts[:-1]) + ' and ' + parts[-1]
    return text + (' %d' % days[0].year if same_year else '')


def assign_splits(numbers, shares=SPLITS):
    """Wall photo number -> 'train' | 'val' | 'test' | 'gap'.

    Neighbouring photos overlap by about a third and show the same hearts, so a random split would leak. The wall is
    cut into three runs instead, with one photo left out between runs (a photo only overlaps its neighbours).
    """
    ordered = sorted(numbers)
    train_end = round(len(ordered) * shares[0])
    val_end = train_end + round(len(ordered) * shares[1])
    out = {}
    for i, number in enumerate(ordered):
        out[number] = 'train' if i < train_end else 'val' if i < val_end and i > train_end else 'test' if i > val_end else 'gap'
    return out


def heart_rows(record, image):
    """One dict per heart of a photo's detector record, with its id cleaned of ' - Copy'."""
    stem = os.path.splitext(image)[0]
    rows = []
    for heart in record['hearts']:
        x, y, w, h = heart['box']
        rows.append(dict(
            heart_id='%s_%03d' % (stem, int(heart['id'].rsplit('_', 1)[1])), image='images/' + image,
            x=x, y=y, width=w, height=h, paint_area_px=heart['area'], ink_ratio=heart['ink'],
            ink_strokes=heart['strokes'], has_writing=bool(heart['has_writing'])))
    return rows


def yolo_lines(rows, width, height):
    """Detection labels in YOLO's format: class, then the box's centre and size as fractions of the image."""
    return ['%d %.6f %.6f %.6f %.6f' % (
        int(r['has_writing']), (r['x'] + r['width'] / 2) / width, (r['y'] + r['height'] / 2) / height,
        r['width'] / width, r['height'] / height) for r in rows]


def coco(photos, hearts):
    """COCO detection annotations for the photos and their hearts."""
    images, annotations, ids = [], [], {}
    for k, photo in enumerate(photos, start=1):
        ids[photo['image']] = k
        images.append(dict(id=k, file_name=photo['image'], width=photo['width'], height=photo['height'], license=1,
                           date_captured=photo['captured'], wall_photo_number=photo['wall_photo_number'] or None))
    for k, h in enumerate(hearts, start=1):
        annotations.append(dict(
            id=k, image_id=ids[h['image']], category_id=1 + int(h['has_writing']),
            bbox=[h['x'], h['y'], h['width'], h['height']], area=h['width'] * h['height'], iscrowd=0, heart_id=h['heart_id'],
            paint_area_px=h['paint_area_px'], ink_ratio=h['ink_ratio'], ink_strokes=h['ink_strokes']))
    return dict(
        info=dict(description=BOXES_TITLE, url='https://www.kaggle.com/datasets/', version='1.0', date_created=datetime.now().strftime('%Y-%m-%d')),
        licenses=[dict(id=1, name='CC BY-NC 4.0', url=LICENSE_URL)],
        categories=[dict(id=1 + i, name=name, supercategory='heart') for i, name in enumerate(CLASSES)],
        images=images, annotations=annotations)


BOX_PHOTO_COLUMNS = {'hearts_detected', 'hearts_with_writing', 'suggested_split'}
PHOTO_COLUMNS = [
    ('image', 'string', 'Path of the photo, relative to the dataset root.'),
    ('wall_photo_number', 'integer', "The photo's place in the order along the wall, 1 to 518 (empty for the two close-ups)."),
    ('on_wall', 'boolean', 'False for the two close-ups, which are not part of the stitched wall.'),
    ('captured', 'string', 'When it was taken: local time, ISO 8601, with its UTC offset (from the EXIF).'),
    ('capture_date', 'string', 'The day it was taken, YYYY-MM-DD.'),
    ('width', 'integer', 'Pixels across.'),
    ('height', 'integer', 'Pixels down.'),
    ('camera', 'string', 'Camera make and model, from the EXIF.'),
    ('hearts_detected', 'integer', 'Hearts the detector found in the photo (rows of hearts.csv).'),
    ('hearts_with_writing', 'integer', 'Of those, the ones it judged to have handwriting on them.'),
    ('wall_x_start', 'integer', "Where the photo's own stretch of the stitched wall begins, in the wall's full-size pixels (wall/layout.json)."),
    ('wall_x_end', 'integer', 'Where it ends (the next photo begins).'),
    ('suggested_split', 'string', "train, val or test: runs of the wall with a 'gap' photo between them, so overlapping photos never straddle a split. Empty for the close-ups."),
]
HEART_COLUMNS = [
    ('heart_id', 'string', 'Unique id: the photo\'s file name without extension, then the heart\'s number in the photo.'),
    ('image', 'string', 'The photo it was found in, relative to the dataset root.'),
    ('x', 'integer', "Left edge of the box, in the photo's pixels."),
    ('y', 'integer', 'Top edge of the box.'),
    ('width', 'integer', 'Width of the box.'),
    ('height', 'integer', 'Height of the box.'),
    ('paint_area_px', 'integer', "Pixels of red paint the detector found in the heart (not the box's area)."),
    ('ink_ratio', 'number', "Share of the heart's inside that is dark pen strokes."),
    ('ink_strokes', 'integer', 'Number of separate pen marks found inside the heart.'),
    ('has_writing', 'boolean', 'True when ink_ratio and ink_strokes pass the detector\'s thresholds (see the README).'),
]


def photo_columns(with_boxes):
    return [c for c in PHOTO_COLUMNS if with_boxes or c[0] not in BOX_PHOTO_COLUMNS]


def write_csv(path, columns, rows):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=[c[0] for c in columns])
        writer.writeheader()
        for row in rows:
            writer.writerow({c[0]: ('' if row.get(c[0]) is None else row[c[0]]) for c in columns})


def schema(columns):
    return dict(fields=[dict(name=n, description=d, type=t) for n, t, d in columns])


def readme(stats, settings=None, with_boxes=False):
    """The dataset card (Markdown). It is also Kaggle's description, minus its title line."""
    s = stats
    settings = settings or {}
    if with_boxes:
        title = BOXES_TITLE
        intro = (f"{s['photos']} photographs of the National Covid Memorial Wall on the Albert Embankment in London, with the hand-painted\n"
                 "hearts on it located automatically by bounding boxes, each flagged for whether it has handwriting on it.")
    else:
        title = TITLE
        intro = (f"{s['photos']} photographs of the National Covid Memorial Wall on the Albert Embankment in London: "
                 f"{s['wall_photos']} that run\nalong its length, and {s['closeups']} close-ups.")
    files = [
        f"| `images/` | {s['photos']} JPEGs: {s['wall_photos']} portrait photos that run along the wall ({s['wall_size']}) and {s['closeups']} landscape close-ups ({s['closeup_size']}). {s['gb']:.1f} GB. |",
        "| `photos.csv` | One row per photo: its place in the order along the wall, capture time, camera" + (", heart counts, a suggested split. |" if with_boxes else ". |"),
    ]
    if with_boxes:
        files += [
            f"| `hearts.csv` | One row per detected heart: **{s['hearts']:,}** boxes, **{s['written']:,}** of them flagged as having writing. |",
            "| `annotations_coco.json` | The same boxes as COCO detection annotations (2 classes). |",
            "| `labels/`, `data.yaml`, `splits/` | The same boxes as YOLO labels, ready for the suggested split. |",
        ]
    files.append("| `wall/` | A thumbnail strip of the stitched wall, and where each photo sits along it (`layout.json`). |")
    snippet = ('import pandas as pd\nphotos = pd.read_csv("photos.csv")\n' + (
        'hearts = pd.read_csv("hearts.csv")          # x, y, width, height are in the photo\'s own pixels, origin top left\n'
        'hearts[hearts.has_writing].groupby("image").size().describe()\n' if with_boxes else
        'photos[photos.on_wall].sort_values("wall_photo_number").head()    # in order along the wall\n'))
    parts = [f"# {title}\n", intro + "\n", (
        "The wall is covered in hand-painted hearts, one for each person who died of COVID-19 in the UK, and families and friends\n"
        f"write the person's name and a message on them. These are photographs of that memorial, taken on {s['visits']}.\n"),
        "## What is in it\n", "| | |\n|---|---|\n" + "\n".join(files) + "\n", f"```python\n{snippet}```\n"]
    if with_boxes:
        parts += [f"""## How the boxes were made

They were found automatically, **not by hand and not checked by a person**, so treat them as weak labels.
Each photo is reduced to a quarter of its size, the saturated red paint is masked, touching hearts are split with a
watershed, and boxes whose longer side is under {settings.get('detect.MIN_SIDE', 80)} px (too small to carry legible writing) are dropped, as are
masses wider or taller than {settings.get('detect.MAX_FRAC', 0.35):.0%} of the photo (merged hearts). Ink is then measured on the full-size
pixels: a heart is flagged `has_writing` when at least {settings.get('detect.WRITING_FRAC', 0.006):.1%} of its inside is dark pen
(thin strokes only, from a black-hat filter) in at least {settings.get('detect.WRITING_STROKES', 3)} separate marks.

Known limits, all visible when the boxes are drawn on the photos:

- **Missed hearts.** Many hearts, especially small, pale, partly hidden or very close to others, have no box. There is no
  count of how many; do not use the totals as a census of the wall.
- **Merged hearts.** Touching hearts sometimes come out as one large box.
- **Slivers.** Hearts cut by a ledge or by the edge of the photo give thin boxes.
- **Writing in silver or scratched in** (rather than dark pen) is not detected, so `has_writing` has false negatives. It is
  a heuristic, and will also be wrong in places in the other direction.
- **Duplicates.** Neighbouring photos overlap by about a third, so the same heart appears, with its own box, in two photos.
  Boxes are per photo and are not matched across photos.
- Only red paint is looked for: the pale pink, white and silver hearts on the wall are mostly not found.
""", """## Suggested split

`suggested_split` in `photos.csv` (also `splits/*.txt` and `data.yaml`) cuts the wall into three runs
(70 % train, 15 % validation, 15 % test by photo) with one photo left out between runs. A random split would put
the same hearts in training and test, because neighbouring photos overlap.
"""]
    else:
        parts += ["""## Using the photos

The photos carry no labels. Neighbouring photos overlap by about a third, so each shows part of the next: if you split them
into training and test sets, split by position along the wall (`wall_photo_number`), not at random, or the same hearts
will land on both sides.
"""]
    parts += [f"""## Photographs

Taken with a {s['camera']} on {s['visits']}. The files are the camera's own JPEGs, unedited except for one thing: the
**GPS position was removed from the EXIF**. Every pixel and every other tag (time, camera, exposure) is untouched.
Byte-identical copies of photos were left out.
""", """## Please read: this is a memorial

Every heart stands for a person who died, and many carry their name and a message written by someone who loved them.
The photographs show that writing. Please use the data with the respect that deserves.

- No commercial use (see the licence).
- Do not use it to look people up, to contact families, or to build anything that profiles the people named.
- Names and messages are other people's words: do not republish them out of context.
- If you are a family member and want a heart removed from the dataset, say so in the dataset's discussion tab on Kaggle
  and it will be taken out.

This dataset is independent. It is not affiliated with, or endorsed by, the organisers of the wall.
""", f"""## Licence and credit

[Creative Commons Attribution-NonCommercial 4.0 (CC BY-NC 4.0)]({LICENSE_URL}). Credit the dataset's author on Kaggle
and name the memorial.
"""]
    return "\n".join(parts)


def build(pictures, originals, hearts_dir, wall_path, out, kaggle_user='YOUR-KAGGLE-USERNAME', log=print, with_boxes=False):
    """Make the dataset in `out`. Returns the statistics the card quotes."""
    out = Path(out)
    slug, title = (BOXES_SLUG, BOXES_TITLE) if with_boxes else (SLUG, TITLE)
    if (out / 'dataset-metadata.json').exists():                  # ours, from an earlier run: start clean
        for sub in ('images', 'labels', 'splits', 'wall'):
            shutil.rmtree(out / sub, ignore_errors=True)
        for name in BOX_FILES:
            (out / name).unlink(missing_ok=True)
    for sub in ('images', 'wall') + (('labels', 'splits') if with_boxes else ()):
        (out / sub).mkdir(parents=True, exist_ok=True)

    wall = json.loads(Path(wall_path).read_text(encoding='utf-8'))
    plan = {p['file']: (n, x0, x1) for n, (p, x0, x1) in stretches(wall).items()}
    splits = assign_splits([n for n, _, _ in plan.values()])

    names = list_photos(pictures, portrait_only=False)
    log('%d unique photos' % len(names))
    photos, hearts, missing, used, replaced = [], [], [], set(), 0
    for name in names:
        record = None
        if with_boxes:
            record_path = Path(hearts_dir) / 'photos' / (os.path.splitext(name)[0] + '.json')
            if not record_path.exists():
                missing.append('%s: no detector result (run scripts/extract_hearts.py)' % name)
                continue
            record = json.loads(record_path.read_text(encoding='utf-8'))
            source = find_source(name, record, pictures, originals)
            if source is None:
                missing.append('%s: no file of %dx%d, the size its hearts were found on (see --originals)' % (name, record['width'], record['height']))
                continue
        else:
            source = pick_source(name, pictures, originals)
        image = clean_name(name)
        if image in used:
            missing.append('%s: file name collides with another photo after cleaning' % name)
            continue
        used.add(image)
        replaced += os.path.normpath(os.path.dirname(source)) != os.path.normpath(pictures)
        jpeg = Path(source).read_bytes()
        (out / 'images' / image).write_bytes(strip_gps(jpeg))
        with Image.open(io.BytesIO(jpeg)) as picture:
            width, height = picture.size
        captured, camera = capture_info(jpeg)
        number, x0, x1 = plan.get(name, (None, None, None))
        row = dict(image='images/' + image, wall_photo_number=number, on_wall=number is not None, captured=captured,
                   capture_date=captured[:10], width=width, height=height, camera=camera, wall_x_start=x0, wall_x_end=x1)
        if with_boxes:
            rows = heart_rows(record, image)
            row.update(hearts_detected=len(rows), hearts_with_writing=sum(r['has_writing'] for r in rows),
                       suggested_split=splits.get(number, '') if number else '')
            hearts.extend(rows)
            (out / 'labels' / (os.path.splitext(image)[0] + '.txt')).write_text(
                '\n'.join(yolo_lines(rows, width, height)) + ('\n' if rows else ''), encoding='utf-8')
        photos.append(row)
        if len(photos) % 100 == 0:
            log('%d photos' % len(photos))
    if missing:
        raise SystemExit('cannot build the dataset:\n  ' + '\n  '.join(missing))

    photos.sort(key=lambda p: (p['wall_photo_number'] is None, p['wall_photo_number'] or 0, p['image']))
    write_csv(out / 'photos.csv', photo_columns(with_boxes), photos)
    if with_boxes:
        write_csv(out / 'hearts.csv', HEART_COLUMNS, hearts)
        (out / 'annotations_coco.json').write_text(json.dumps(coco(photos, hearts), separators=(',', ':')), encoding='utf-8')
        for split in ('train', 'val', 'test'):
            (out / 'splits' / (split + '.txt')).write_text(
                ''.join(p['image'] + '\n' for p in photos if p['suggested_split'] == split), encoding='utf-8')
        (out / 'data.yaml').write_text(
            'path: .\ntrain: splits/train.txt\nval: splits/val.txt\ntest: splits/test.txt\nnames:\n'
            + ''.join('  %d: %s\n' % (i, c) for i, c in enumerate(CLASSES)), encoding='utf-8')

    overview = wall.get('overview')
    overview_file = Path(wall_path).parent.parent / overview.lstrip('/') if overview else None
    layout = dict(width=wall['width'], height=wall['height'], overview=None, photos=[
        dict(number=p['wall_photo_number'], image=p['image'], x_start=p['wall_x_start'], x_end=p['wall_x_end'])
        for p in photos if p['on_wall']])
    if overview_file and overview_file.exists():
        shutil.copyfile(overview_file, out / 'wall' / 'overview.jpg')
        with Image.open(out / 'wall' / 'overview.jpg') as ov:
            layout['overview'] = dict(file='overview.jpg', width=ov.width, height=ov.height)
    (out / 'wall' / 'layout.json').write_text(json.dumps(layout, indent=1) + '\n', encoding='utf-8')

    settings = {}
    if with_boxes:
        for p in sorted((Path(hearts_dir) / 'photos').glob('*.json'))[:1]:
            settings = json.loads(p.read_text(encoding='utf-8')).get('settings', {})
    dates = sorted({p['capture_date'] for p in photos if p['capture_date']})
    stats = dict(
        photos=len(photos), wall_photos=sum(p['on_wall'] for p in photos), closeups=sum(not p['on_wall'] for p in photos),
        hearts=len(hearts), written=sum(h['has_writing'] for h in hearts), originals_used=replaced,
        gb=sum(os.path.getsize(out / p['image']) for p in photos) / 1e9, first=dates[0] if dates else '', last=dates[-1] if dates else '')
    stats['visits'] = describe_dates(dates)
    common = lambda items: Counter(items).most_common(1)[0][0] if items else ''
    stats['camera'] = common([p['camera'] for p in photos]) or 'camera'
    stats['wall_size'] = '%d x %d' % common([(p['width'], p['height']) for p in photos if p['on_wall']])[:2] if stats['wall_photos'] else ''
    stats['closeup_size'] = '%d x %d' % common([(p['width'], p['height']) for p in photos if not p['on_wall']])[:2] if stats['closeups'] else ''
    card = readme(stats, settings, with_boxes)
    (out / 'README.md').write_text(card, encoding='utf-8')

    subtitle = ('%d photos of the memorial wall with %s auto-detected heart boxes' % (stats['photos'], format(stats['hearts'], ','))
                if with_boxes else '%d photographs of the National Covid Memorial Wall in London' % stats['photos'])
    assert 20 <= len(subtitle) <= 80 and 6 <= len(title) <= 50 and 3 <= len(slug) <= 50
    resources = [dict(path='photos.csv', description='One row per photo.', schema=schema(photo_columns(with_boxes)))]
    if with_boxes:
        resources += [
            dict(path='hearts.csv', description='One row per detected heart (automatic, not checked by a person).', schema=schema(HEART_COLUMNS)),
            dict(path='annotations_coco.json', description='The boxes as COCO detection annotations.')]
    resources.append(dict(path='wall/layout.json', description='Where each photo sits along the stitched wall.'))
    (out / 'dataset-metadata.json').write_text(json.dumps(dict(
        title=title, id='%s/%s' % (kaggle_user, slug), subtitle=subtitle,
        description=card.split('\n', 2)[2].lstrip('\n'), licenses=[dict(name=LICENSE)],
        keywords=(['computer-vision', 'object-detection', 'image', 'handwriting', 'ocr', 'covid19'] if with_boxes
                  else ['image', 'computer-vision', 'photography', 'covid19']),
        resources=resources), indent=2) + '\n', encoding='utf-8')
    return stats


def verify(out):
    """Problems found in a built dataset (empty when it is sound). Checks the boxes too, when it has them."""
    out = Path(out)
    problems = []
    with open(out / 'photos.csv', newline='', encoding='utf-8') as fh:
        photos = list(csv.DictReader(fh))
    with_boxes = (out / 'hearts.csv').exists()
    by_image, labelled = {}, 0
    if with_boxes:
        with open(out / 'hearts.csv', newline='', encoding='utf-8') as fh:
            hearts = list(csv.DictReader(fh))
        for h in hearts:
            by_image.setdefault(h['image'], []).append(h)
        annotations = json.loads((out / 'annotations_coco.json').read_text(encoding='utf-8'))
        if len(annotations['annotations']) != len(hearts) or len(annotations['images']) != len(photos):
            problems.append('COCO and the CSVs disagree on the counts')
    elif any((out / name).exists() for name in BOX_FILES + ('labels', 'splits')):
        problems.append('boxes left over in a dataset without them')
    on_disk = sorted(p.name for p in (out / 'images').iterdir())
    if on_disk != sorted(os.path.basename(p['image']) for p in photos):
        problems.append('images/ and photos.csv list different files')
    for p in photos:
        data = (out / p['image']).read_bytes()
        if strip_gps(data) != data:
            problems.append('%s still has GPS' % p['image'])
        with Image.open(io.BytesIO(data)) as image:
            if image.size != (int(p['width']), int(p['height'])):
                problems.append('%s is %s, not %sx%s' % (p['image'], image.size, p['width'], p['height']))
        if not with_boxes:
            continue
        rows = by_image.get(p['image'], [])
        if len(rows) != int(p['hearts_detected']):
            problems.append('%s: hearts.csv has %d rows, photos.csv says %s' % (p['image'], len(rows), p['hearts_detected']))
        for h in rows:
            x, y, w, hh = int(h['x']), int(h['y']), int(h['width']), int(h['height'])
            if x < 0 or y < 0 or w <= 0 or hh <= 0 or x + w > int(p['width']) or y + hh > int(p['height']):
                problems.append('%s: box outside the photo' % h['heart_id'])
        label = out / 'labels' / (os.path.splitext(os.path.basename(p['image']))[0] + '.txt')
        if len([line for line in label.read_text(encoding='utf-8').splitlines() if line]) != len(rows):
            problems.append('%s: label file has the wrong number of boxes' % p['image'])
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pictures', default=str(ROOT / 'frontend' / 'public' / 'pictures'))
    ap.add_argument('--originals', help='full-size copies of photos that were replaced by smaller edits in --pictures')
    ap.add_argument('--with-boxes', action='store_true', help="also include the detector's heart boxes (hearts.csv, COCO, YOLO)")
    ap.add_argument('--hearts', default=str(ROOT / 'build' / 'hearts'), help="where the detector keeps its results (with --with-boxes)")
    ap.add_argument('--wall', default=str(ROOT / 'frontend' / 'public' / 'wall' / 'wall.json'))
    ap.add_argument('--out', help='where to build it (default build/kaggle/<dataset name>)')
    ap.add_argument('--kaggle-user', default='YOUR-KAGGLE-USERNAME', help='your Kaggle username, for the dataset id')
    args = ap.parse_args()
    out = args.out or str(ROOT / 'build' / 'kaggle' / (BOXES_SLUG if args.with_boxes else SLUG))

    stats = build(args.pictures, args.originals, args.hearts, args.wall, out, args.kaggle_user, with_boxes=args.with_boxes)
    print('%(photos)d photos (%(wall_photos)d on the wall, %(closeups)d close-ups), %(gb).2f GB' % stats
          + (', %(hearts)d hearts (%(written)d with writing)' % stats if args.with_boxes else ''))
    problems = verify(out)
    if problems:
        sys.exit('problems:\n  ' + '\n  '.join(problems[:30]))
    print('checked: files, counts, sizes and no GPS left' + (', boxes inside photos' if args.with_boxes else ''))
    print('\nTo upload (needs the Kaggle CLI and your API token):\n  kaggle datasets create -p %s --dir-mode tar' % out)


if __name__ == '__main__':
    main()
