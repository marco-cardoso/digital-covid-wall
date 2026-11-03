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

Wall pipeline:

```bash
build/venv/bin/python -m pytest scripts/tests
```

## API

| Method | Path                        | Description                       |
| ------ | --------------------------- | --------------------------------- |
| GET    | `/api/tributes`             | List tributes, newest first       |
| POST   | `/api/tributes`             | Add a tribute                     |
| POST   | `/api/tributes/{id}/candle` | Light a candle (increments count) |
| GET    | `/api/stats`                | Total tributes and candles        |
| GET    | `/api/victims`              | List the names read from the wall |
