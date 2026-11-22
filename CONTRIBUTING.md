# Contributing

The Memorial Wall is a record of real people. A wrong name, a dropped photo, or a
tribute that gets rewritten is worse than leaving the rough OCR alone. Change one
part, check it, and say what you checked.

There are three parts. [The README](README.md) has the full run instructions.

- **Backend** — FastAPI and SQLite in `backend/`. Python 3.12.
- **Frontend** — React 19 and Vite in `frontend/`. Node 22.
- **Wall pipeline** — stitching, heart detection, and imports in `scripts/`. Python 3.12.

## Setup

Backend, including the test dependencies:

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Frontend (port 5173, proxies `/api` to the backend):

```bash
cd frontend
npm install
npm run dev
```

Wall pipeline, only if you are changing stitching, heart detection, or the imports:

```bash
python -m venv build/venv
build/venv/bin/pip install -r scripts/requirements.txt
```

`docker compose up -d --build` runs the site on http://localhost:8080. The wall tiles
are not in the image: they are mounted from `frontend/public/wall/`.

## Tests

Run the suite for the part you changed.

```bash
cd backend && .venv/bin/python -m pytest          # coverage must stay at 95% or above
cd frontend && npm test && npm run lint           # Vitest, then oxlint
build/venv/bin/python -m pytest scripts/tests
```

`npm run coverage` is the frontend run the README uses. Backend tests each get a
throwaway SQLite database.

## What stays out of git

These are local or generated, and several are large:

- `frontend/public/pictures/` — the source photos, about 4 GB
- `frontend/public/wall/` — Deep Zoom tiles and heart boxes
- `build/` — stitch cache, heart crops, and the Kaggle package
- `*.db`, `*.sqlite3`, and `.env`

Do not add camera originals (`PXL_*.jpg` is ignored on purpose). Originals in
`pictures/` are never modified by the scripts.

## Pull requests

Keep a change to one concern: the API, the site, or the pipeline. In the description,
say why the change is there and which commands you ran.

Do not reformat files you did not otherwise change. Do not commit the photos, the
tiles, the heart crops, or a database.

## Names, hearts, and tributes

`backend/app/victims.json` is raw OCR. It includes words and dates that are not
names, and it does not record which photo an entry came from. Do not "fix" an entry
by guessing what was written. If you change how names are imported or read, show the
before and after on a few hearts.

Heart counts overlap between neighbouring photos, and some hearts are missed. Treat
the totals as a guide. Boxes and crops are only as good as the detector: say so if a
change moves them.

Tributes are what visitors wrote. Leave existing tribute text as it was stored.
