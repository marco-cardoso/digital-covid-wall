"""The site monitor's Lambda: checks the site against its known-good list and raises the alarm through SNS.

It is invoked three ways:

- {"mode": "scheduled"}, every few minutes: the whole bucket and the live site (checker.check_inventory and
  check_live). It alerts when the set of problems changes (so a hacked site is reported once, not every run, and
  every new change to it is reported again), and says so when the site is back to its known-good state.
- An S3 "Object Created" / "Object Deleted" event from the site's bucket: that one file, at once. At most one
  instant alert every INSTANT_QUIET seconds, so a flood of writes is one alert; the next scheduled run lists them.
- An S3 event for the known-good list itself (manifest.json in the integrity bucket): a note that it changed. Every
  deploy writes it twice; if you did not deploy, someone else wrote it.

Alerts carry a "severity" message attribute: "alert" (also sent by SMS) or "info" (email only).
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone

import checker

MANIFEST_KEY = "manifest.json"
STATE_KEY = "state/alerts.json"
INSTANT_QUIET = 300
MANIFEST_CACHE_SECONDS = 60
NAMESPACE = "CovidWall/SiteIntegrity"

_clients = {}
_manifest_cache = {"at": 0.0, "value": None}


def client(name):
    if name not in _clients:
        import boto3

        _clients[name] = boto3.client(name)
    return _clients[name]


def env(name):
    return os.environ[name]


# ---- Reading and writing what the monitor keeps -------------------------------------------------------------------


def get_manifest(fresh=False):
    """(manifest, written_at), or (None, None) when there is no list yet. Cached briefly between invocations."""
    now = time.monotonic()
    if not fresh and _manifest_cache["value"] and now - _manifest_cache["at"] < MANIFEST_CACHE_SECONDS:
        return _manifest_cache["value"]
    s3 = client("s3")
    try:
        response = s3.get_object(Bucket=env("INTEGRITY_BUCKET"), Key=MANIFEST_KEY)
    except s3.exceptions.NoSuchKey:
        return None, None
    value = (checker.load_manifest(response["Body"].read()), response["LastModified"])
    _manifest_cache.update(at=now, value=value)
    return value


def get_state():
    s3 = client("s3")
    try:
        body = s3.get_object(Bucket=env("INTEGRITY_BUCKET"), Key=STATE_KEY)["Body"].read()
        return json.loads(body)
    except s3.exceptions.NoSuchKey:
        return {}


def put_state(state):
    client("s3").put_object(
        Bucket=env("INTEGRITY_BUCKET"), Key=STATE_KEY, Body=json.dumps(state).encode(), ContentType="application/json"
    )


def list_bucket():
    paginator = client("s3").get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=env("SITE_BUCKET")):
        for item in page.get("Contents", []):
            yield item["Key"], item["Size"], item.get("ETag", "")


def metric(name, value):
    client("cloudwatch").put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[{"MetricName": name, "Value": value, "Unit": "Count",
                     "Dimensions": [{"Name": "Site", "Value": env("SITE_NAME")}]}],
    )


def notify(subject, lines, severity="alert", short=None):
    site, url = env("SITE_NAME"), env("SITE_URL")
    body = "\n".join([*lines, "", f"Site: {url}", f"Checked at {now_text()}."])
    client("sns").publish(
        TopicArn=env("TOPIC_ARN"),
        Subject=f"[covidwall {site}] {subject}"[:100],
        MessageStructure="json",
        Message=json.dumps({"default": body, "email": body, "sms": f"covidwall {site}: {short or subject}"[:150]}),
        MessageAttributes={"severity": {"DataType": "String", "StringValue": severity}},
    )


def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fingerprint(problems):
    return hashlib.sha256("\n".join(map(str, problems)).encode()).hexdigest() if problems else ""


def report(problems, limit=40):
    lines = [f"- {p}" for p in problems[:limit]]
    if len(problems) > limit:
        lines.append(f"- and {len(problems) - limit} more")
    return lines


# ---- The three ways in --------------------------------------------------------------------------------------------


def scheduled():
    manifest, written_at = get_manifest(fresh=True)
    if manifest is None:
        problems = [checker.Problem("no-manifest", "", "manifest")]
    else:
        in_deploy = checker.deploying(manifest, datetime.now(timezone.utc), written_at)
        problems = sorted(
            checker.check_inventory(list_bucket(), manifest, in_deploy)
            + checker.check_live(manifest, turn=int(time.time()) // 300, in_deploy=in_deploy)
        )

    state = get_state()
    mark = fingerprint(problems)
    if mark != state.get("fingerprint", ""):
        if problems:
            notify(
                "The website does not match what was deployed",
                ["The live site or its bucket differs from the last deploy's known-good list:", "", *report(problems),
                 "", "If you did not change it, it may have been tampered with. Earlier versions of every file are",
                 "kept in the bucket (versioning) to restore from."],
                short=f"{len(problems)} problem(s), e.g. {problems[0]}",
            )
        else:
            notify("The website matches its known-good list again", ["Every check passes again."],
                   short="back to normal")
        state["fingerprint"] = mark
        put_state(state)
    metric("ScheduledChecks", 1)
    metric("Problems", len(problems))
    return {"problems": [str(p) for p in problems]}


def site_object_event(detail, change):
    obj = detail.get("object", {})
    key = obj.get("key", "")
    manifest, written_at = get_manifest()
    if manifest is None:
        return {"problems": []}  # the scheduled check reports a missing list
    in_deploy = checker.deploying(manifest, datetime.now(timezone.utc), written_at)
    problems = checker.check_event(change, key, obj.get("size"), obj.get("etag"), manifest, in_deploy)
    if problems:
        # A deploy may just have written a new list: look again with it before raising the alarm.
        manifest, written_at = get_manifest(fresh=True)
        in_deploy = checker.deploying(manifest, datetime.now(timezone.utc), written_at)
        problems = checker.check_event(change, key, obj.get("size"), obj.get("etag"), manifest, in_deploy)
    if problems:
        state = get_state()
        if time.time() - state.get("instant_alert_at", 0) >= INSTANT_QUIET:
            notify(
                "A website file was changed outside a deploy",
                ["Just now, in the site's bucket:", "", *report(problems), "",
                 f"Further changes in the next {INSTANT_QUIET // 60} minutes are gathered into the next full check."],
                short=str(problems[0]),
            )
            state["instant_alert_at"] = time.time()
            put_state(state)
    return {"problems": [str(p) for p in problems]}


def manifest_event():
    manifest, _ = get_manifest(fresh=True)
    if manifest is None:
        notify("The known-good list was deleted", ["manifest.json is gone from the integrity bucket."])
        return {}
    state = "a deploy started" if manifest.get("deploying_until") else "a deploy finished"
    notify(
        "New known-good list recorded",
        [f"The known-good list was rewritten ({state}): {len(manifest['files']):,} files, recorded at "
         f"{manifest.get('recorded_at')}.", "", "If you did not deploy just now, someone else did."],
        severity="info",
    )
    return {}


def handler(event, context):
    if event.get("mode") == "scheduled":
        return scheduled()
    if event.get("source") == "aws.s3":
        detail = event.get("detail", {})
        if detail.get("bucket", {}).get("name") == env("INTEGRITY_BUCKET"):
            return manifest_event()
        change = "deleted" if event.get("detail-type") == "Object Deleted" else "created"
        return site_object_event(detail, change)
    raise ValueError(f"Unknown event: {json.dumps(event)[:200]}")
