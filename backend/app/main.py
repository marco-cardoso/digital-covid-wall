from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, StringConstraints

from .database import db, init_db
from .insights import MESSAGES, RELATIONSHIPS, count_mentions, hearts_summary, load_hearts


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="COVID Memorial Wall API", lifespan=lifespan)

# The Vite dev server runs on a different origin than the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TrimmedStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TributeIn(BaseModel):
    name: Annotated[TrimmedStr, StringConstraints(max_length=100)]
    years: Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)] = ""
    message: Annotated[TrimmedStr, StringConstraints(max_length=1000)]
    author: Annotated[TrimmedStr, StringConstraints(max_length=100)]
    relationship: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] = ""


class Tribute(TributeIn):
    id: int
    candles: int = 0
    created_at: str


class Victim(BaseModel):
    id: int
    name: str
    model: int = 0
    created_at: str
    updated_at: str


class WallStats(BaseModel):
    names: int
    tributes: int
    candles: int


class HeartsStats(BaseModel):
    # Hearts counted in the wall photos; neighbouring photos overlap, so some hearts are counted twice.
    total: int
    with_writing: int
    photos: int


class PhotoHearts(BaseModel):
    number: int
    date: str
    hearts: int
    writing: int


class Mentions(BaseModel):
    label: str
    count: int


class Insights(BaseModel):
    hearts: HeartsStats
    per_photo: list[PhotoHearts]
    messages: list[Mentions]
    relationships: list[Mentions]


class FeedbackIn(BaseModel):
    kind: Literal["typo", "missing", "suggestion", "other"]
    # The name on the wall the message is about, when there is one.
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    message: Annotated[TrimmedStr, StringConstraints(max_length=2000)]
    # An email address or other way to reply; optional.
    contact: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    # A trap for bots: the form hides this field, so people leave it empty.
    website: str = ""


class FeedbackReceipt(BaseModel):
    ok: bool = True


def row_to_tribute(row) -> Tribute:
    return Tribute(
        id=row["id"],
        name=row["name"],
        years=row["years"] or "",
        message=row["message"],
        author=row["author"],
        relationship=row["relationship"] or "",
        candles=row["candles"],
        created_at=row["created_at"],
    )


@app.get("/api/tributes", response_model=list[Tribute])
def list_tributes():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM tributes ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [row_to_tribute(r) for r in rows]


@app.post("/api/tributes", response_model=Tribute, status_code=201)
def create_tribute(tribute: TributeIn):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO tributes (name, years, message, author, relationship)"
            " VALUES (?, ?, ?, ?, ?)",
            (tribute.name, tribute.years, tribute.message, tribute.author, tribute.relationship),
        )
        row = conn.execute(
            "SELECT * FROM tributes WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return row_to_tribute(row)


@app.post("/api/tributes/{tribute_id}/candle", response_model=Tribute)
def light_candle(tribute_id: int):
    with db() as conn:
        cur = conn.execute(
            "UPDATE tributes SET candles = candles + 1 WHERE id = ?", (tribute_id,)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Tribute not found")
        row = conn.execute(
            "SELECT * FROM tributes WHERE id = ?", (tribute_id,)
        ).fetchone()
    return row_to_tribute(row)


@app.get("/api/victims", response_model=list[Victim])
def list_victims():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, model, created_at, updated_at FROM victims"
            " ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
    return [
        Victim(
            id=r["id"],
            name=r["name"],
            model=r["model"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


@app.post("/api/feedback", response_model=FeedbackReceipt, status_code=201)
def send_feedback(feedback: FeedbackIn):
    # A bot filled in the hidden field: answer as if it worked, and keep nothing.
    if feedback.website:
        return FeedbackReceipt()
    with db() as conn:
        conn.execute(
            "INSERT INTO feedback (kind, name, message, contact) VALUES (?, ?, ?, ?)",
            (feedback.kind, feedback.name, feedback.message, feedback.contact),
        )
    return FeedbackReceipt()


@app.get("/api/stats", response_model=WallStats)
def wall_stats():
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS tributes, COALESCE(SUM(candles), 0) AS candles FROM tributes"
        ).fetchone()
        names = conn.execute("SELECT COUNT(*) AS n FROM victims").fetchone()["n"]
    return WallStats(names=names, tributes=row["tributes"], candles=row["candles"])


@app.get("/api/insights", response_model=Insights)
def wall_insights():
    photos = load_hearts()
    with db() as conn:
        texts = [r["name"] for r in conn.execute("SELECT name FROM victims")]
    return Insights(
        hearts=HeartsStats(**hearts_summary(photos)),
        per_photo=photos,
        messages=count_mentions(texts, MESSAGES, limit=8),
        relationships=count_mentions(texts, RELATIONSHIPS, limit=10),
    )
