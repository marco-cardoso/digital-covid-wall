#!/usr/bin/env python3
"""Stitch the wall photos into one straight, zoomable image of the memorial wall.

    python scripts/build_wall.py            # photos in frontend/public/pictures -> frontend/public/wall

Steps (each cached under --work, so reruns pick up where they left off):
  1. features   SIFT keypoints and long straight lines for every unique portrait photo
  2. links      matches between each photo and its next few neighbours, plus retries
                across any break in the chain
  3. solve      camera poses, lens distortion and the wall's depth profile for every
                continuous run of photos (long runs in overlapping pieces, merged, then
                refined as one)
  4. render     each run levelled on the wall's courses and put on one scale, then drawn
                straight-on with seams and brightness balanced
  5. tiles      runs joined left to right (with marked gaps) as Deep Zoom tiles + wall.json
"""
import argparse
import json
import os
import pickle
import re
import sys
import time
from multiprocessing import get_context

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wall import align, features, merge, render, solver, tiles  # noqa: E402
from wall.geometry import WallModel  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = time.time()
LONG_RUN = 10            # runs this long find their own scale against the reference


def log(*args):
    print('[%5.0fs]' % (time.time() - T0), *args, flush=True)


def load_lines(work, photos):
    hl, vl = [], []
    for p in photos:
        d = np.load(features.feature_path(work, p))
        hl.append(d['h']); vl.append(d['v'])
    return hl, vl


def solve_piece(args):
    work, photos, first, last, links, path = args
    if os.path.exists(path):
        return path
    hl, vl = load_lines(work, photos[first:last + 1])
    model = solver.solve_run(first, last, links, hl, vl, log=lambda *a: log('[%d-%d]' % (first, last), *a))
    model.save(path)
    return path


def shot_time(name):
    m = re.search(r'_(\d{8})_(\d{6})', name)
    return time.mktime(time.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S')) if m else None


def break_kind(prev_last, next_first):
    """'divider' within one walk, 'gap' between visits (or when the times are unknown)."""
    a, b = shot_time(prev_last), shot_time(next_first)
    return 'divider' if a is not None and b is not None and 0 <= b - a < 30 * 60 else 'gap'


def render_cached(model_path, photo_paths, strip_dir, scale, top, bottom, workers):
    """Render unless the strips already match this model, scale and crop, and are all there."""
    key = dict(model=os.path.getmtime(model_path), scale=round(scale, 6), top=round(top, 6), bottom=round(bottom, 6),
               photos=len(photo_paths))
    stamp = os.path.join(strip_dir, 'render.json')
    if os.path.exists(stamp):
        done = json.load(open(stamp))
        have = len([f for f in os.listdir(strip_dir) if f.startswith('strip_')])
        if done.get('key') == key and done.get('strips') == have:
            return
        os.remove(stamp)                 # an interrupted render must not look finished
    width, _ = render.render(model_path, photo_paths, strip_dir, scale, top, bottom, workers, log=log)
    json.dump(dict(key=key, strips=(width + render.STRIP - 1) // render.STRIP), open(stamp, 'w'))


def date_label(names):
    dates = sorted({re.search(r'_(\d{8})_', n).group(1) for n in names if re.search(r'_(\d{8})_', n)})
    fmt = lambda d: time.strftime('%-d %b %Y', time.strptime(d, '%Y%m%d'))
    if not dates:
        return ''
    return 'Photographed ' + (fmt(dates[0]) if len(dates) == 1 else '%s – %s' % (fmt(dates[0]), fmt(dates[-1])))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pictures', default=os.path.join(ROOT, 'frontend', 'public', 'pictures'))
    ap.add_argument('--work', default=os.path.join(ROOT, 'build', 'wall'), help='cache directory')
    ap.add_argument('--out', default=os.path.join(ROOT, 'frontend', 'public', 'wall'), help='tiles + wall.json')
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument('--px-per-unit', type=float, default=2600,
                    help='output scale; ~2600 keeps the photos\' full detail (wall ~3000 px tall)')
    ap.add_argument('--min-run', type=int, default=1,
                    help='shortest run of overlapping photos to include (1 keeps every photo)')
    ap.add_argument('--band', type=float, nargs=2, metavar=('TOP', 'BOTTOM'),
                    help='vertical crop in the reference run\'s wall units (default: automatic)')
    args = ap.parse_args()
    work = args.work
    os.makedirs(work, exist_ok=True)

    # 1. photos and features
    photos = features.list_photos(args.pictures)
    log('%d unique wall photos' % len(photos))
    features.extract_all(args.pictures, photos, work, args.workers)
    log('features ready')

    # 2. links between neighbours (+ retries across breaks)
    links_path = os.path.join(work, 'links.pkl')
    cached = pickle.load(open(links_path, 'rb')) if os.path.exists(links_path) else {}
    if cached.get('photos') != photos:
        links = features.match_pairs(photos, work, features.neighbour_pairs(len(photos)), args.workers)
        links.update(features.match_pairs(photos, work, features.bridge_candidates(len(photos), links), args.workers))
        pickle.dump({'photos': photos, 'links': links}, open(links_path, 'wb'))
    else:
        links = cached['links']
    runs = features.plan_runs(len(photos), links)
    kept = [r for r in runs if r[1] - r[0] + 1 >= args.min_run]
    skipped = sum(r[1] - r[0] + 1 for r in runs if r not in kept)
    log('%d links; runs: %s; %d photos in runs shorter than %d left out' % (
        len(links), ', '.join('%d-%d' % r for r in kept), skipped, args.min_run))

    # 3. solve every run (pieces in parallel), merging long runs
    models = []
    pieces = [(run, features.split_run(*run)) for run in kept]
    jobs = []
    for run, parts in pieces:
        if os.path.exists(os.path.join(work, 'run_%d_%d.npz' % run)):
            continue
        for a, b in parts:
            sub = {k: v for k, v in links.items() if a <= k[0] and k[1] <= b}
            jobs.append((work, photos, a, b, sub, os.path.join(work, 'piece_%d_%d.npz' % (a, b))))
    if jobs:
        with get_context('spawn').Pool(min(len(jobs), args.workers)) as pool:
            pool.map(solve_piece, jobs, chunksize=1)
    for run, parts in pieces:
        path = os.path.join(work, 'run_%d_%d.npz' % run)
        if not os.path.exists(path):
            parts_m = [WallModel.load(os.path.join(work, 'piece_%d_%d.npz' % p)) for p in parts]
            if len(parts_m) > 1:
                merged = merge.merge(parts_m, log=log)
                hl, vl = load_lines(work, photos[run[0]:run[1] + 1])
                run_links = {k: v for k, v in links.items() if run[0] <= k[0] and k[1] <= run[1]}
                solver.refine_run(merged, run_links, hl, vl, log=log).save(path)
            else:
                parts_m[0].save(path)
        models.append((run, path))
    log('solved %d runs' % len(models))

    # 4. level each run, put all runs on one physical scale, then render
    profiles = []
    for (a, b), path in models:
        m = WallModel.load(path)
        hl = load_lines(work, photos[a:b + 1])[0]
        if m.level is None:
            m.level = align.level_offsets(m, hl)
            m.save(path)
            if m.level is not None:
                log('run %d-%d levelled (correction %.3f..%.3f units)' % (a, b, m.level[2].min(), m.level[2].max()))
        profiles.append(align.course_profile(m, hl))
    ref = int(np.argmax([b - a for (a, b), _ in models]))
    ref_model = WallModel.load(models[ref][1])
    top, bottom = args.band or align.wall_band(ref_model, profiles[ref])
    log('crop band %.3f..%.3f in run %d-%d units' % ((top, bottom) + models[ref][0]))
    # Long runs register on their own. A short run has too few courses to measure its own
    # scale, so it takes the scale implied by the closest long run from the same walk: the
    # photographer stood about as far from the wall as for that run's nearest photo, and a
    # run's unit is its own reference camera's distance. Its vertical offset starts from
    # the phone height at that photo and is fine-tuned on the courses.
    kinds = [None] + [break_kind(photos[models[k - 1][0][1]], photos[models[k][0][0]]) for k in range(1, len(models))]
    walk = np.cumsum([kind != 'divider' for kind in kinds])
    long_ = [(b - a + 1) >= LONG_RUN for (a, b), _ in models]
    loaded = [WallModel.load(path) for _, path in models]
    camera_height = lambda m, f: m.cams[f, 1] - m.level_at(np.array([m.cams[f, 0]]))[0]
    reg = {}
    for k in sorted(range(len(models)), key=lambda k: not long_[k]):
        near = [j for j in reg if long_[j] and walk[j] == walk[k]]
        if k == ref:
            reg[k] = (1.0, 0.0)
        elif long_[k] or not near:
            reg[k] = align.register(profiles[ref], profiles[k])
        else:
            j = min(near, key=lambda j: abs(j - k))
            fj, fk = (0, -1) if k < j else (-1, 0)          # the photos where the two runs meet
            aj, bj = reg[j]
            a_k = aj * loaded[j].cams[fj, 2] / loaded[k].cams[fk, 2]
            b_guess = aj * camera_height(loaded[j], fj) + bj - a_k * camera_height(loaded[k], fk)
            reg[k] = (a_k, align.register_offset(profiles[ref], profiles[k], a_k, b_guess))
    rendered = []
    for k, ((a, b), path) in enumerate(models):
        sa, sb = reg[k]
        log('run %d-%d: scale %.4f, offset %+.3f relative to the reference' % (a, b, sa, sb))
        strip_dir = os.path.join(work, 'strips_%d_%d' % (a, b))
        render_cached(path, [os.path.join(args.pictures, p) for p in photos[a:b + 1]], strip_dir,
                      args.px_per_unit * sa, (top - sb) / sa, (bottom - sb) / sa, args.workers)
        rendered.append((strip_dir, date_label(photos[a:b + 1]), kinds[k]))

    # 5. tiles
    info = tiles.build(rendered, args.out, log=log)
    log('done: %s (%d x %d px)' % (os.path.join(args.out, os.path.basename(info['dzi'])), info['width'], info['height']))


if __name__ == '__main__':
    main()
