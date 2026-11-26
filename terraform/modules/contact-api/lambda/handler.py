"""Stores a message sent through the site's contact form in DynamoDB.

CloudFront passes POST /api/feedback to this function's URL. It checks the message the same way the local
FastAPI backend does (backend/app/main.py, FeedbackIn), so the form behaves alike on both:

- kind is one of typo, missing, suggestion, other;
- message is required, at most 2,000 characters once trimmed;
- name and contact are optional, at most 200 characters once trimmed;
- website is a trap for bots: the form hides it, so a filled-in one is answered as if it worked and nothing is kept.

Replies are JSON. A problem with the message comes back as 422 with a sentence in "detail", which the form shows.
Message text is never logged.
"""

import base64
import binascii
import json
import os
import uuid
from datetime import datetime, timezone

KINDS = ("typo", "missing", "suggestion", "other")
MAX_MESSAGE = 2000
MAX_SHORT = 200
MAX_BODY = 16 * 1024  # bytes; a full form is well under 10 KB

_table = None


def table():
    """The DynamoDB table, made on first use (boto3 is in the Lambda runtime, not needed to test the rest)."""
    global _table
    if _table is None:
        import boto3

        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


class Invalid(Exception):
    """The message cannot be stored as sent; the text says why, for the visitor."""


def respond(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body),
    }


def text(data, key, limit, label):
    value = data.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise Invalid(f"The {label} must be text.")
    value = value.strip()
    if len(value) > limit:
        raise Invalid(f"The {label} is too long: at most {limit:,} characters.")
    return value


def parse(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            raise Invalid("The request could not be read.") from None
    if len(body.encode("utf-8")) > MAX_BODY:
        raise Invalid("The request is too large.")
    try:
        data = json.loads(body)
    except ValueError:
        raise Invalid("The request could not be read.") from None
    if not isinstance(data, dict):
        raise Invalid("The request could not be read.")

    kind = data.get("kind")
    if kind not in KINDS:
        raise Invalid("Please choose what the message is about.")
    message = text(data, "message", MAX_MESSAGE, "message")
    if not message:
        raise Invalid("Please write a message.")
    return {
        "kind": kind,
        "name": text(data, "name", MAX_SHORT, "name"),
        "message": message,
        "contact": text(data, "contact", MAX_SHORT, "email"),
        "website": text(data, "website", MAX_SHORT, "website"),
    }


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method != "POST":
        return respond(405, {"detail": "Messages are sent with POST."})

    try:
        feedback = parse(event)
    except Invalid as problem:
        return respond(422, {"detail": str(problem)})

    # A bot filled in the hidden field: answer as if it worked, and keep nothing.
    if feedback.pop("website"):
        return respond(201, {"ok": True})

    table().put_item(
        Item={
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **feedback,
        },
        ConditionExpression="attribute_not_exists(id)",
    )
    return respond(201, {"ok": True})
