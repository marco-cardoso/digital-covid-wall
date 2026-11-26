"""Tests for the contact form's Lambda. No AWS needed: the table is a stand-in that keeps what it is given.

    backend/.venv/bin/python -m pytest terraform/modules/contact-api/lambda
"""

import base64
import json

import pytest

import handler

VALID = {
    "kind": "typo",
    "name": "Elena Marchetti",
    "message": "It reads 'Marchettti' on the Honors page, with three t's.",
    "contact": "visitor@example.com",
    "website": "",
}


class FakeTable:
    def __init__(self):
        self.items = []
        self.conditions = []

    def put_item(self, Item, ConditionExpression=None):
        self.items.append(Item)
        self.conditions.append(ConditionExpression)


@pytest.fixture
def table(monkeypatch):
    fake = FakeTable()
    monkeypatch.setattr(handler, "_table", fake)
    return fake


def post(body, method="POST", encode=False):
    raw = body if isinstance(body, str) else json.dumps(body)
    event = {"requestContext": {"http": {"method": method}}, "body": raw, "isBase64Encoded": False}
    if encode:
        event["body"] = base64.b64encode(raw.encode()).decode()
        event["isBase64Encoded"] = True
    reply = handler.handler(event, None)
    return reply["statusCode"], json.loads(reply["body"]), reply["headers"]


def test_a_message_is_stored(table):
    status, body, headers = post(VALID)

    assert status == 201
    assert body == {"ok": True}
    assert headers["Content-Type"] == "application/json"
    (item,) = table.items
    assert item["kind"] == "typo"
    assert item["name"] == "Elena Marchetti"
    assert item["message"] == VALID["message"]
    assert item["contact"] == "visitor@example.com"
    assert "website" not in item
    assert len(item["id"]) == 36
    assert item["created_at"].endswith("Z")
    assert table.conditions == ["attribute_not_exists(id)"]  # never overwrites another message


def test_only_a_kind_and_a_message_are_needed(table):
    status, _, _ = post({"kind": "suggestion", "message": "Add a map."})

    assert status == 201
    (item,) = table.items
    assert item["name"] == "" and item["contact"] == ""


def test_text_is_trimmed_and_null_counts_as_empty(table):
    post({"kind": "other", "message": "  Thank you.  ", "name": None, "contact": " a@b.c "})

    (item,) = table.items
    assert item["message"] == "Thank you."
    assert item["name"] == ""
    assert item["contact"] == "a@b.c"


def test_a_base64_body_is_read(table):
    status, _, _ = post(VALID, encode=True)

    assert status == 201
    assert table.items[0]["message"] == VALID["message"]


def test_a_bot_is_thanked_and_nothing_is_kept(table):
    status, body, _ = post({**VALID, "website": "http://spam.example"})

    assert status == 201
    assert body == {"ok": True}
    assert table.items == []


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"kind": "complaint"}, "Please choose what the message is about."),
        ({"kind": None}, "Please choose what the message is about."),
        ({"message": "   "}, "Please write a message."),
        ({"message": "x" * 2001}, "The message is too long: at most 2,000 characters."),
        ({"name": "x" * 201}, "The name is too long: at most 200 characters."),
        ({"contact": "x" * 201}, "The email is too long: at most 200 characters."),
        ({"name": 42}, "The name must be text."),
    ],
)
def test_a_message_that_breaks_the_rules_is_refused(table, change, detail):
    status, body, _ = post({**VALID, **change})

    assert status == 422
    assert body == {"detail": detail}
    assert table.items == []


def test_the_limits_themselves_are_allowed(table):
    status, _, _ = post({**VALID, "message": "x" * 2000, "name": "y" * 200, "contact": "z" * 200})

    assert status == 201


@pytest.mark.parametrize(
    ("raw", "encode"),
    [("not json", False), ("[1, 2]", False), ("", False), ("%%%", None)],
)
def test_an_unreadable_request_is_refused(table, raw, encode):
    if encode is None:
        event = {"requestContext": {"http": {"method": "POST"}}, "body": "%%%", "isBase64Encoded": True}
        reply = handler.handler(event, None)
        status, body = reply["statusCode"], json.loads(reply["body"])
    else:
        status, body, _ = post(raw, encode=encode)

    assert status == 422
    assert body == {"detail": "The request could not be read."}
    assert table.items == []


def test_an_oversized_request_is_refused(table):
    status, body, _ = post({**VALID, "padding": "x" * 20_000})

    assert status == 422
    assert body == {"detail": "The request is too large."}


def test_only_post_is_accepted(table):
    status, body, _ = post(VALID, method="GET")

    assert status == 405
    assert table.items == []


def test_the_table_is_made_once_from_the_environment(monkeypatch):
    made = []

    class FakeResource:
        def Table(self, name):
            made.append(name)
            return FakeTable()

    class FakeBoto3:
        @staticmethod
        def resource(service):
            assert service == "dynamodb"
            return FakeResource()

    monkeypatch.setattr(handler, "_table", None)
    monkeypatch.setenv("TABLE_NAME", "covid-wall-dev-contact-messages")
    monkeypatch.setitem(__import__("sys").modules, "boto3", FakeBoto3)

    first = handler.table()
    assert handler.table() is first
    assert made == ["covid-wall-dev-contact-messages"]
