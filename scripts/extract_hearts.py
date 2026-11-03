#!/usr/bin/env python3
"""Find the hearts in every wall photo and prepare crops of the ones with writing.

    python scripts/extract_hearts.py        # photos in frontend/public/pictures -> build/hearts

This is the pre-processing stage for reading the names: only hearts with writing get
crops, sized for vision models. Every heart found is still counted.

Output (under --out):
  photos/<photo>.json   every heart found in one photo, with its box and ink measure
                        (cached: a photo is redone only when missing or the settings change)
  crops/<heart>.jpg     colour crop of a heart with writing
  crops/<heart>_enh.jpg the same crop as high-contrast ink on white
  manifest.json         heart counts per photo and in total, and the list of crops to read
"""
import argparse
import glob
import json
import os
import sys
import time
from multiprocessing import get_context

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hearts import crops, detect  # noqa: E402
from wall.features import list_photos  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = time.time()
SETTINGS = {m.__name__.split('.')[-1] + '.' + k: v for m in (detect, crops) for k, v in vars(m).items()
            if k.isupper() and isinstance(v, (int, float))}


def log(*args):
    print('[%5.0fs]' % (time.time() - T0), *args, flush=True)


def heart_id(photo, i):
    return '%s_%03d' % (os.path.splitext(photo)[0].replace(' ', '_'), i)


def process(args):
    """Detect, crop and record one photo; returns its record (from cache when current)."""
    pictures, out, photo, force = args
    record_path = os.path.join(out, 'photos', os.path.splitext(photo)[0] + '.json')
    if not force and os.path.exists(record_path):
        record = json.load(open(record_path))
        if record.get('settings') == SETTINGS:
            return record
    cv2.setNumThreads(1)
    full = cv2.imread(os.path.join(pictures, photo))
    if full is None:
        return dict(photo=photo, error='unreadable', hearts_detected=0, hearts_with_writing=0, hearts=[])
    for old in glob.glob(os.path.join(out, 'crops', glob.escape(heart_id(photo, 0)[:-3]) + '[0-9][0-9][0-9]*')):
        os.remove(old)                  # crops from earlier settings
    hearts = []
    for i, h in enumerate(detect.find_hearts(full), start=1):
        entry = dict(id=heart_id(photo, i), box=[h.x, h.y, h.w, h.h], area=h.area,
                     ink=round(h.ink, 4), strokes=h.strokes, has_writing=h.has_writing)
        if h.has_writing:
            colour, enhanced, box = crops.prepare(full, h)
            stem = os.path.join(out, 'crops', entry['id'])
            jpg, png = crops.save(stem, colour, enhanced)
            entry.update(crop_box=list(box), crop=os.path.relpath(jpg, out), enhanced=os.path.relpath(png, out),
                         crop_size=[colour.shape[1], colour.shape[0]])
        hearts.append(entry)
    record = dict(photo=photo, width=full.shape[1], height=full.shape[0], settings=SETTINGS,
                  hearts_detected=len(hearts), hearts_with_writing=sum(e['has_writing'] for e in hearts), hearts=hearts)
    tmp = record_path + '.tmp'
    json.dump(record, open(tmp, 'w'), indent=1)
    os.replace(tmp, record_path)        # written last, so an interrupted photo is redone
    return record


def manifest(records):
    written = [dict(photo=r['photo'], **{k: e[k] for k in ('id', 'box', 'crop', 'enhanced', 'crop_size', 'ink')})
               for r in records for e in r['hearts'] if e['has_writing']]
    return dict(
        generated=time.strftime('%Y-%m-%dT%H:%M:%S'),
        settings=SETTINGS,
        photos=len(records),
        hearts_detected=sum(r['hearts_detected'] for r in records),
        hearts_with_writing=sum(r['hearts_with_writing'] for r in records),
        per_photo=[{k: r[k] for k in ('photo', 'hearts_detected', 'hearts_with_writing')} for r in records],
        crops=written,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pictures', default=os.path.join(ROOT, 'frontend', 'public', 'pictures'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'build', 'hearts'))
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument('--limit', type=int, help='only the first N photos (for trying settings)')
    ap.add_argument('--force', action='store_true', help='redo every photo, ignoring the cache')
    args = ap.parse_args()
    for sub in ('photos', 'crops'):
        os.makedirs(os.path.join(args.out, sub), exist_ok=True)

    # Close-ups (landscape) are kept: they show the writing best.
    photos = list_photos(args.pictures, portrait_only=False)[:args.limit]
    log('%d unique photos' % len(photos))
    jobs = [(args.pictures, args.out, p, args.force) for p in photos]
    records = []
    with get_context('spawn').Pool(min(len(jobs), args.workers) or 1) as pool:
        for i, record in enumerate(pool.imap(process, jobs), start=1):
            records.append(record)
            if i % 25 == 0 or i == len(jobs):
                log('%d/%d photos, %d hearts, %d with writing' % (
                    i, len(jobs), sum(r['hearts_detected'] for r in records), sum(r['hearts_with_writing'] for r in records)))

    m = manifest(records)
    json.dump(m, open(os.path.join(args.out, 'manifest.json'), 'w'), indent=1)
    log('%d hearts detected, %d with writing -> %s' % (
        m['hearts_detected'], m['hearts_with_writing'], os.path.join(args.out, 'manifest.json')))


if __name__ == '__main__':
    main()
