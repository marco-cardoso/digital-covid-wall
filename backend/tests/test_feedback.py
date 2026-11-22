import sqlite3

import pytest

VALID = {
    "kind": "typo",
    "name": "Elena Marchetti",
    "message": "It reads 'Marchettti' on the Honors page, with three t's.",
    "contact": "visitor@example.com",
}


def saved(test_db):
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM feedback ORDER BY id")]
    finally:
        conn.close()


def test_feedback_is_saved(client, test_db):
    res = client.post("/api/feedback", json=VALID)
    assert res.status_code == 201
    assert res.json() == {"ok": True}

    (row,) = saved(test_db)
    assert row["kind"] == "typo"
    assert row["name"] == "Elena Marchetti"
    assert row["message"] == VALID["message"]
    assert row["contact"] == "visitor@example.com"
    assert row["created_at"]


def test_only_a_kind_and_a_message_are_needed(client, test_db):
    res = client.post("/api/feedback", json={"kind": "suggestion", "message": "Add a map."})
    assert res.status_code == 201

    (row,) = saved(test_db)
    assert row["name"] == ""
    assert row["contact"] == ""


def test_text_is_trimmed(client, test_db):
    client.post("/api/feedback", json=dict(VALID, name="  Elena  ", message="  hi  ", contact="  me  "))

    (row,) = saved(test_db)
    assert (row["name"], row["message"], row["contact"]) == ("Elena", "hi", "me")


@pytest.mark.parametrize("kind", ["typo", "missing", "suggestion", "other"])
def test_every_kind_is_accepted(client, kind):
    assert client.post("/api/feedback", json=dict(VALID, kind=kind)).status_code == 201


@pytest.mark.parametrize(
    "payload",
    [
        dict(VALID, kind="spam"),                      # not one of the kinds
        {k: v for k, v in VALID.items() if k != "kind"},
        dict(VALID, message=""),
        dict(VALID, message="   "),
        {k: v for k, v in VALID.items() if k != "message"},
        dict(VALID, message="x" * 2001),
        dict(VALID, name="x" * 201),
        dict(VALID, contact="x" * 201),
    ],
)
def test_bad_feedback_is_rejected_and_not_saved(client, test_db, payload):
    assert client.post("/api/feedback", json=payload).status_code == 422
    assert saved(test_db) == []


def test_bots_that_fill_the_hidden_field_are_told_it_worked_but_nothing_is_kept(client, test_db):
    res = client.post("/api/feedback", json=dict(VALID, website="http://spam.example"))
    assert res.status_code == 201
    assert saved(test_db) == []
