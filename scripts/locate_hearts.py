#!/usr/bin/env python3
"""Put the detected hearts of some wall photos onto the stitched wall, as boxes the site can draw.

    python scripts/locate_hearts.py --photos 1-2        # the first two photos
    python scripts/locate_hearts.py                     # every photo on the wall

For each photo this finds its hearts (scripts/extract_hearts.py's detector; photos already done are
reused), matches the photo to the stitched wall (hearts/locate.py) and carries each heart's box across.
Neighbouring photos overlap, so a heart is kept only in the photo whose stretch of the wall it sits in.

Output, under --out (frontend/public/wall/hearts, next to the tiles, and just as git-ignored):
  <photo>.json   one photo's boxes, [x, y, w, h, writing, n] in full-size wall pixels, n being the
                 heart's number in the photo (the crop in build/hearts/crops is <photo file>_<n>.jpg)
  index.json     which wall build the boxes belong to and which photos have them. The site draws
                 boxes only for a wall they were made for, since a rebuilt wall moves everything.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_hearts  # noqa: E402
from hearts import locate  # noqa: E402
from hearts.dzi import Pyramid  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def parse_photos(spec):
    """'1-3,7' -> [1, 2, 3, 7]; an empty spec means every photo (None)."""
    if not spec:
        return None
    numbers = []
    for part in spec.split(','):
        low, _, high = part.strip().partition('-')
        numbers.extend(range(int(low), int(high or low) + 1))
    return sorted(set(numbers))


def stretches(wall):
    """Each photo's own stretch of the wall: from where it starts to where the next one does."""
    photos = sorted(wall['photos'], key=lambda p: p['number'])
    ends = [p['x'] for p in photos[1:]] + [wall['width']]
    starts = [0] + [p['x'] for p in photos[1:]]
    return {p['number']: (p, start, end) for p, start, end in zip(photos, starts, ends)}


def find_photo(name, record, pictures, originals=None):
    """The photo's pixels in the size its hearts were found on, or None. Boxes are in the pixels of the photo that was
    searched, so a file since replaced by a smaller edit would put them in the wrong places; its original is looked for."""
    for folder in (pictures, originals):
        image = cv2.imread(os.path.join(folder, name)) if folder else None
        if image is not None and image.shape[1::-1] == (record.get('width'), record.get('height')):
            return image
    return None


def chunk(photo, x0, x1, boxes):
    """One photo's boxes, as the site reads them, left to right."""
    rows = sorted(
        ([b['x'], b['y'], b['w'], b['h'], int(b['heart']['has_writing']), int(b['heart']['id'].rsplit('_', 1)[1])] for b in boxes),
        key=lambda r: (r[0], r[1]),
    )
    return dict(photo=photo['number'], file=photo['file'], x0=x0, x1=x1, hearts=rows)


def merge_index(old, dzi, entries, drop=()):
    """The index with `entries` (one per photo, replacing any earlier one) added.

    Boxes made for another wall build are dropped: they would sit in the wrong place.
    """
    kept = {e['number']: e for e in (old or {}).get('photos', [])} if (old or {}).get('dzi') == dzi else {}
    for number in drop:
        kept.pop(number, None)
    kept.update({e['number']: e for e in entries})
    return dict(dzi=dzi, generated=time.strftime('%Y-%m-%dT%H:%M:%S'), photos=[kept[n] for n in sorted(kept)])


def write_json(path, data):
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(data, separators=(',', ':')) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--photos', help='wall photo numbers to do, e.g. 1-2 or 5,9-12 (default: all)')
    ap.add_argument('--wall', type=Path, default=ROOT / 'frontend' / 'public' / 'wall' / 'wall.json')
    ap.add_argument('--pictures', default=str(ROOT / 'frontend' / 'public' / 'pictures'))
    ap.add_argument('--originals', help='full-size copies of photos that were replaced by smaller edits in --pictures')
    ap.add_argument('--hearts', default=str(ROOT / 'build' / 'hearts'), help='where the detector keeps its results')
    ap.add_argument('--out', type=Path, default=ROOT / 'frontend' / 'public' / 'wall' / 'hearts')
    ap.add_argument('--force', action='store_true', help='find the hearts again even where a result is kept')
    args = ap.parse_args()

    wall = json.loads(args.wall.read_text(encoding='utf-8'))
    pyramid = Pyramid(args.wall.parent.parent / wall['dzi'].lstrip('/'))
    level = pyramid.level_for(locate.WALL_DIV)
    plan = stretches(wall)
    wanted = parse_photos(args.photos) or sorted(plan)
    missing = [n for n in wanted if n not in plan]
    if missing:
        sys.exit('not on the wall: photo %s' % ', '.join(map(str, missing)))
    for sub in ('photos', 'crops'):
        os.makedirs(os.path.join(args.hearts, sub), exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)

    entries, failed = [], []
    for number in wanted:
        photo, x0, x1 = plan[number]
        started = time.time()
        record = extract_hearts.process((args.pictures, args.hearts, photo['file'], args.force))
        image = find_photo(photo['file'], record, args.pictures, args.originals)
        if image is None or not record['hearts']:
            print('photo %d: no hearts, or no photo the size its hearts were found on (see --originals)' % number)
            failed.append(number)
            continue
        left = max(0, x0 - locate.PAD) // locate.WALL_DIV
        crop = pyramid.read(level, left, (x1 + locate.PAD) // locate.WALL_DIV)
        registration = locate.register(image, crop, left * locate.WALL_DIV)
        if registration is None:
            print('photo %d: could not be matched to the wall' % number)
            failed.append(number)
            continue
        boxes = locate.owned(locate.place_hearts(registration, record['hearts'], (record['width'], record['height'])), x0, x1)
        data = chunk(photo, x0, x1, boxes)
        name = '%04d.json' % number
        write_json(args.out / name, data)
        entries.append(dict(number=number, file=name, x0=x0, x1=x1, hearts=len(boxes), writing=sum(r[4] for r in data['hearts'])))
        print('photo %d: %d hearts found, %d on its stretch of the wall (%d with writing); %d features agree; %.1fs' % (
            number, record['hearts_detected'], len(boxes), entries[-1]['writing'], registration.inliers, time.time() - started))

    index_path = args.out / 'index.json'
    old = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else None
    write_json(index_path, merge_index(old, wall['dzi'], entries, drop=failed))
    print('%d photos placed -> %s' % (len(entries), index_path))
    if failed:
        sys.exit('not placed: photo %s' % ', '.join(map(str, failed)))


if __name__ == '__main__':
    main()
