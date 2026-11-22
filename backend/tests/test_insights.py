import json

import pytest

from app import insights
from app.insights import MESSAGES, RELATIONSHIPS, count_mentions, hearts_summary, load_hearts


def labelled(counts):
    return {c["label"]: c["count"] for c in counts}


def test_messages_count_each_heart_once_per_group():
    texts = [
        "In loving memory of\nKen &\nAlec",
        "Miss you Mum xx",
        "Love you always, love",      # "love" twice is still one heart
        "RIP\nLaicy",
        "r.i.p dad",
        "Gerry",
    ]
    counts = labelled(count_mentions(texts, MESSAGES))
    assert counts["Love"] == 2                 # "loving memory", "Love you always"
    assert counts["Miss you"] == 1
    assert counts["Signed with kisses"] == 1
    assert counts["In loving memory"] == 1
    assert counts["Always, forever"] == 1
    assert counts["Rest in peace"] == 2        # RIP and r.i.p
    assert "Hero" not in counts                # nobody wrote it, so it is not listed


def test_a_kiss_is_a_lone_x_not_a_letter_in_a_word():
    counts = labelled(count_mentions(["Alex", "Max", "xxx", "Dad x", "Dixon"], MESSAGES))
    assert counts["Signed with kisses"] == 2


def test_relationships_ranked_and_limited():
    texts = ["Mum", "Mummy xx", "my Mom", "Dad", "Grandad Joe", "Nanny Pat", "Best friend"]
    ranked = count_mentions(texts, RELATIONSHIPS)
    assert ranked[0] == {"label": "Mum", "count": 3}
    assert all(r["count"] == 1 for r in ranked[1:])
    assert len(count_mentions(texts, RELATIONSHIPS, limit=2)) == 2
    assert labelled(ranked)["Grandad"] == 1 and labelled(ranked)["Nan, grandma"] == 1 and labelled(ranked)["Friend"] == 1


def test_hearts_summary_adds_up_the_photos():
    photos = [
        {"number": 1, "date": "2023-07-30", "hearts": 200, "writing": 80},
        {"number": 2, "date": "2023-08-20", "hearts": 300, "writing": 60},
    ]
    assert hearts_summary(photos) == {"total": 500, "with_writing": 140, "photos": 2}
    assert hearts_summary([]) == {"total": 0, "with_writing": 0, "photos": 0}


def test_load_hearts_reads_the_generated_file(tmp_path, monkeypatch):
    path = tmp_path / "hearts.json"
    path.write_text(json.dumps({"photos": [{"number": 1, "date": "", "hearts": 5, "writing": 2}]}))
    monkeypatch.setattr(insights, "HEARTS_PATH", path)
    load_hearts.cache_clear()
    try:
        assert load_hearts() == [{"number": 1, "date": "", "hearts": 5, "writing": 2}]
    finally:
        load_hearts.cache_clear()


@pytest.mark.parametrize("content", [None, "{not json"])
def test_load_hearts_is_empty_without_a_usable_file(tmp_path, monkeypatch, content):
    path = tmp_path / "hearts.json"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(insights, "HEARTS_PATH", path)
    load_hearts.cache_clear()
    try:
        assert load_hearts() == []
    finally:
        load_hearts.cache_clear()


def test_insights_endpoint_combines_hearts_and_writing(client):
    data = client.get("/api/insights").json()

    photos = data["per_photo"]
    assert data["hearts"]["photos"] == len(photos) > 0
    assert data["hearts"]["total"] == sum(p["hearts"] for p in photos) > 0
    assert 0 < data["hearts"]["with_writing"] <= data["hearts"]["total"]
    assert {"number", "date", "hearts", "writing"} <= photos[0].keys()
    assert [p["number"] for p in photos] == sorted(p["number"] for p in photos)

    messages = data["messages"]
    assert 0 < len(messages) <= 8
    assert [m["count"] for m in messages] == sorted((m["count"] for m in messages), reverse=True)
    relationships = data["relationships"]
    assert 0 < len(relationships) <= 10
    assert {"label", "count"} == set(relationships[0])


def test_insights_endpoint_without_hearts_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(insights, "HEARTS_PATH", tmp_path / "missing.json")
    load_hearts.cache_clear()
    try:
        data = client.get("/api/insights").json()
    finally:
        load_hearts.cache_clear()
    assert data["hearts"] == {"total": 0, "with_writing": 0, "photos": 0}
    assert data["per_photo"] == []
