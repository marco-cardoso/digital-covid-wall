"""Numbers for the dashboard that come from the wall itself: the hearts counted in the photos, and what is written on them.

Heart counts per photo are regenerated with scripts/import_hearts.py. The writing is the text read off
the hearts (the `victims` table); it comes from OCR, so every figure here is a count of hearts whose text
mentions something, not of people.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

HEARTS_PATH = Path(__file__).resolve().parent / "hearts.json"


def _words(*alternatives: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)


# What people wrote. A heart counts once for every group its text mentions.
MESSAGES = [
    ("Love", _words(r"lov(?:e|ed|es|ing|ely)")),
    ("Rest in peace", re.compile(r"\br\.?\s?i\.?\s?p\b\.?|\brest\b|\bpeaceful?\b", re.IGNORECASE)),
    ("Signed with kisses", re.compile(r"(?<![a-z])x{1,6}(?![a-z])", re.IGNORECASE)),
    ("Miss you", _words(r"miss(?:ed|es|ing)?")),
    ("Always, forever", _words("always", "forever", "evermore")),
    ("In loving memory", re.compile(r"in\s+(?:loving\s+)?memory|memory\s+of|memories|remember(?:ed|ing)?", re.IGNORECASE)),
    ("Best, beloved", _words("best", "great", "amazing", "wonderful", "beloved")),
    ("Hero", _words(r"heroe?s?", "nhs", "nurse", "doctor", "carer")),
]

# Who they were to the person who wrote on the heart: the words people use for each.
RELATIONSHIPS = [
    ("Mum", _words("mum", "mummy", "mom", "mommy", "mother", "mam", "mama", "mumma")),
    ("Dad", _words("dad", "daddy", "father", "papa")),
    ("Grandad", _words("grandad", "granddad", "grandpa", "grandfather", "grampa", "gramps", "nonno")),
    ("Nan, grandma", _words("nan", "nana", "nanna", "nanny", "nannie", "gran", "granny", "grandma", "grandmother", "nonna")),
    ("Friend", _words("friend", "friends", "mate", "bestie")),
    ("Uncle", _words("uncle")),
    ("Auntie", _words("auntie", "aunty", "aunt")),
    ("Brother", _words("brother", "bro")),
    ("Husband", _words("husband", "hubby")),
    ("Sister", _words("sister", "sis")),
    ("Wife", _words("wife")),
    ("Son", _words("son")),
    ("Daughter", _words("daughter")),
    ("Cousin", _words("cousin")),
]


def count_mentions(texts: list[str], groups, limit: int | None = None) -> list[dict]:
    """How many of the texts mention each group, biggest first; groups nobody mentions are left out."""
    counts = [
        {"label": label, "count": sum(1 for text in texts if pattern.search(text))} for label, pattern in groups
    ]
    counts = sorted((c for c in counts if c["count"] > 0), key=lambda c: -c["count"])
    return counts[:limit]


@lru_cache(maxsize=1)
def load_hearts() -> list[dict]:
    """Heart counts per wall photo ([] when hearts.json has not been generated)."""
    try:
        return json.loads(HEARTS_PATH.read_text(encoding="utf-8")).get("photos", [])
    except (OSError, json.JSONDecodeError):
        return []


def hearts_summary(photos: list[dict]) -> dict:
    return {
        "total": sum(p["hearts"] for p in photos),
        "with_writing": sum(p["writing"] for p in photos),
        "photos": len(photos),
    }
