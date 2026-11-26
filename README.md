![The National COVID Memorial Wall](docs/national-covid-memorial-wall.jpg)

# The Memorial Wall

A web app for remembering lives lost to COVID-19: a stitched, zoomable panorama
of the National Covid Memorial Wall in London, the names read from its hearts,
and a tributes API.

## Stack

- **Backend** — FastAPI + SQLite (`backend/`), stdlib `sqlite3`, no ORM
- **Frontend** — React 19 + Vite (`frontend/`), OpenSeadragon for the wall
- **Wall pipeline** — Python (`scripts/build_wall.py`, `scripts/wall/`)

## Running with Docker

```bash
docker compose up -d --build
```

Then open http://localhost:8080 (set `PORT` to change it). The database lives in
the `memorial-data` volume. The wall tiles are not in git: build them first, or
copy them into `frontend/public/wall/`. The site runs without them, minus the wall.

## Running locally

Backend (port 8000):

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Frontend (port 5173, proxies `/api` to the backend):

```bash
cd frontend
npm install
npm run dev
```

Interactive API docs are at http://127.0.0.1:8000/docs.

## The wall

`scripts/build_wall.py` turns the photos in `frontend/public/pictures/` into Deep
Zoom tiles and `wall.json` in `frontend/public/wall/`. The photos (about 4 GB), the
cache in `build/wall/` and the tiles are all git-ignored, so a fresh clone needs
them copied in separately. A full run needs several GB of free disk.

```bash
python -m venv build/venv
build/venv/bin/pip install -r scripts/requirements.txt
build/venv/bin/python scripts/build_wall.py
```

Originals in `pictures/` are never modified.

## The names

`backend/app/victims.json` holds the text read from the hearts by OCR. The
backend loads it on startup whenever the `victims` table is empty. It is raw OCR
output, so it includes words and dates that aren't names, and it doesn't record
which photo each entry came from.

To regenerate it from the heart JSON files of the OCR project:

```bash
python scripts/import_victims.py --source path/to/pictures_hearts
```

The change reaches a database only when its `victims` table is empty.

### Heart crops for reading the names

`scripts/extract_hearts.py` is the pre-processing stage for reading the names with
vision models. It finds every red heart in the photos, counts them, and writes
model-ready crops only for the hearts with writing on them:

```bash
build/venv/bin/python scripts/extract_hearts.py            # --limit 10 to try it on a few photos
```

Output goes to `build/hearts/` (git-ignored):

- `manifest.json`: hearts detected and hearts with writing, in total and per photo,
  plus the list of crops to read (photo, box in the photo, crop paths)
- `photos/<photo>.json`: every heart found in one photo, with its box and ink score
- `crops/<heart>.jpg`: colour crop, 768–1024 px on the long side
- `crops/<heart>_enh.jpg`: the same crop as dark ink on white (red channel)

Each photo is cached, and redone only when the detection or crop settings change.
Known gaps: touching hearts sometimes come out as one crop. Writing that's scratched
in or written in silver, rather than in dark pen, isn't detected. The same heart in
two overlapping photos is cropped twice.

### Outlining the hearts on the wall

The wall has a **Hearts** button that draws a box around every heart the detector found: gold for those
with writing, white for the rest. Hover a box to see which heart it is; click or tap one to **open** it: a card
with that spot of the wall in a viewer of its own (zoom, look around), and a *Clearer writing* switch that shows
the pen dark against the paint. It is drawn from the wall's own tiles, so it works for every heart and needs no
extra files (the detector's crops come to 4.6 GB for the whole wall, too much to serve). The boxes exist only for
the photos that have been placed on the wall so far; the rest of the wall just has no outlines yet.

```bash
build/venv/bin/python scripts/locate_hearts.py --photos 1-2    # the first two photos
build/venv/bin/python scripts/locate_hearts.py                 # the whole wall: about a second per photo
```

For each photo it finds the hearts (reusing `build/hearts/photos/` where the detector has already run), matches
the photo to the stitched wall and carries each box across. The solver's camera models are not kept, so the match
is made against the wall itself: a homography from matched features, then optical flow for the ledges and
set-back sections that stand out from it. Against the exact geometry the first two photos were rendered with, the
boxes land within about 1 px (median; worst 15 px) on a wall where a heart is ~130 px across. Photos overlap, so each
heart is kept only in the photo whose stretch of the wall it sits in. A photo whose match is not one a photo
could have (mirrored, or the wrong size for the wall's pixels) is not placed, and says so.

Output goes to `frontend/public/wall/hearts/` (git-ignored, like the tiles): `index.json`, and one
`<photo>.json` per photo of `[x, y, w, h, writing, n]` boxes in full-size wall pixels, `n` being the heart's number
in its photo (its crop is `build/hearts/crops/<photo file>_<n>.jpg`). The site draws a photo's boxes only once
the view comes near it, and ignores boxes made for a different build of the wall, so **run it again after the wall
is rebuilt or switched**.

Notes for doing the whole wall:

- Photos 10–14, 17 and 18 are low-resolution edits in `frontend/public/pictures/`, but their hearts were found on
  the full-size originals. Boxes are in the pixels of the photo that was searched, so the script wants that size:
  pass `--originals <folder of the full-size photos>` and it will use those for photos whose file differs.
- The boxes are only as good as the detector: touching hearts sometimes come out as one big box, some hearts are
  missed, and hearts cut by a ledge give thin slivers. Outlining them makes this easy to see.

### The Kaggle dataset

The photos can be packaged as a dataset for Kaggle (CC BY-NC 4.0): the 520 full-size photos with the GPS position taken
out of their EXIF (the pictures themselves are not re-encoded), `photos.csv` (order along the wall, capture time, camera),
a thumbnail strip of the stitched wall with each photo's position, and a dataset card. It carries no heart boxes.

```bash
build/venv/bin/python scripts/build_dataset.py --originals <folder of the full-size photos> --kaggle-user <your Kaggle name>
```

It writes `build/kaggle/national-covid-memorial-wall-photos/` (about 2.9 GB, git-ignored), checks it (files, counts, sizes,
no GPS left) and prints the `kaggle datasets create` command. Photos 10–14, 17 and 18 are low-resolution edits in
`frontend/public/pictures/`; `--originals` points at a folder with the full-size ones, and the larger file wins.

`--with-boxes` builds the other variant (`national-covid-memorial-wall-hearts`): the detector's boxes as `hearts.csv`,
COCO and YOLO labels, a suggested split along the wall, and a card on their limits. It needs the detector's results
(`scripts/extract_hearts.py`). The boxes are automatic and unchecked, which is why the default leaves them out.

### The dashboard's numbers

The dashboard leads with the total of hearts counted and charts them along the wall,
beside what is written on them. The counts come from `backend/app/hearts.json`, which
keeps the per-photo counts from the manifest above for the photos on the wall, numbered
the way the wall numbers them:

```bash
python scripts/import_hearts.py      # build/hearts/manifest.json + wall.json -> backend/app/hearts.json
```

Run it again after `extract_hearts.py` or after the wall's photos change. The total is a
guide, not a census: neighbouring photos overlap, so a heart can be counted twice, and
some are missed. The charts of what people wrote (`/api/insights`) are counts of hearts
whose OCR text mentions something, so they carry the OCR's mistakes too.

## Testing

Backend, against a throwaway SQLite database per test:

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Frontend:

```bash
cd frontend
npm run coverage
```

Wall pipeline and heart crops:

```bash
build/venv/bin/python -m pytest scripts/tests
```

The contact form's Lambda (no AWS needed):

```bash
backend/.venv/bin/python -m pytest terraform/modules/contact-api/lambda
```

## Deploying to dev

Dev is https://dev.covidwall.co.uk: the built site in a private S3 bucket behind
CloudFront, from `terraform/environments/dev` (kept on disk, not in git). There is no
FastAPI backend there yet. The contact form is the one live API: CloudFront sends
`POST /api/feedback` to a Lambda (`terraform/modules/contact-api`) that keeps each
message in a DynamoDB table. The dashboard reads a snapshot of `/api/stats`,
`/api/insights` and `/api/tributes` that `scripts/snapshot_api.py` takes from the local
data at each deploy (tributes left out: the only ones are made-up seed examples).

```bash
scripts/deploy_dev.sh --dry-run    # what would change; uploads nothing
scripts/deploy_dev.sh --infra      # terraform apply for dev (it asks first), then deploy
scripts/deploy_dev.sh              # test, build, upload the app and wall tiles, clear the cache
```

It uses the shell's AWS credentials, uploads only the wall tiles that changed, and never
uploads the source photos. It also records the deploy's known-good list for the tamper
monitor (below).

## Tamper monitoring

Each site (dev and prod) is checked against a known-good list: every file the last deploy
put in its bucket, with its SHA-256, MD5 and size (`scripts/site_manifest.py`). The list is
kept in a private, versioned integrity bucket, and the site's bucket keeps old versions of
every file for 90 days to restore from. Alerts go by email, and alarms also by SMS.

- **At once:** every write or delete in a site's bucket is checked against the list as it
  happens (S3 → EventBridge → `terraform/modules/site-monitor`).
- **Every 5 minutes:** every object in the bucket, and the live site over HTTPS as visitors
  get it (the page and everything it loads, the dashboard data, a rotating sample of the wall
  tiles), which also catches a changed CloudFront origin, DNS or certificate. A page that
  loads anything from another site, or carries an inline script, is flagged too.
- **The list itself:** each rewrite is emailed (a deploy writes it twice). If you did not
  deploy, someone else did.
- **The monitor:** an alarm fires if the checks stop for 15 minutes or keep failing.
- **From outside AWS:** `.github/workflows/site-integrity.yml` runs the same live check every
  5 minutes (often later) with a read-only role, and fails, so GitHub emails you, if a site
  differs. It still works if someone with your AWS keys switches the monitor off.

Run the live check by hand:

```bash
aws s3 cp "s3://$(terraform -chdir=terraform/environments/dev output -raw integrity_bucket)/manifest.json" /tmp/manifest.json
python3 terraform/modules/site-monitor/lambda/checker.py --manifest /tmp/manifest.json
```

Its tests: `backend/.venv/bin/python -m pytest terraform/modules/site-monitor/lambda`. Read the messages with
`aws dynamodb scan --table-name "$(terraform -chdir=terraform/environments/dev output -raw contact_table)"`.

## API

| Method | Path                        | Description                       |
| ------ | --------------------------- | --------------------------------- |
| GET    | `/api/tributes`             | List tributes, newest first       |
| POST   | `/api/tributes`             | Add a tribute                     |
| POST   | `/api/tributes/{id}/candle` | Light a candle (increments count) |
| GET    | `/api/stats`                | Total tributes and candles        |
| GET    | `/api/victims`              | List the names read from the wall |

## Contributing

Setup, tests, and what not to commit are in [CONTRIBUTING.md](CONTRIBUTING.md).
Change one part (the backend, the frontend, or the wall scripts), run that part's
tests, and leave the photos, tiles, and local database out of git. Names on the wall
are real people: do not correct an OCR reading by guessing.
