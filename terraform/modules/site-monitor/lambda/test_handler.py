"""Tests for the site monitor's Lambda, with stand-ins for S3, SNS and CloudWatch."""

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

import checker
import handler

SITE = {"index.html": b"<html><body>wall</body></html>", "api/stats": b'{"names":1}'}


def entry(body):
    return {"sha256": hashlib.sha256(body).hexdigest(), "md5": hashlib.md5(body).hexdigest(), "size": len(body)}


def manifest(**changes):
    value = {"site": "dev", "url": "https://dev.example.org", "recorded_at": "2026-11-26T12:00:00Z",
             "deploying_until": None, "files": {k: entry(v) for k, v in SITE.items()}}
    value.update(changes)
    return value


class NoSuchKey(Exception):
    pass


class FakeS3:
    class exceptions:
        NoSuchKey = NoSuchKey

    def __init__(self):
        self.objects = {}  # (bucket, key) -> (bytes, last_modified)
        self.gets = 0

    def put(self, bucket, key, body, when=None):
        self.objects[(bucket, key)] = (body, when or datetime.now(timezone.utc))

    def get_object(self, Bucket, Key):
        self.gets += 1
        if (Bucket, Key) not in self.objects:
            raise NoSuchKey(Key)
        body, when = self.objects[(Bucket, Key)]

        class Body:
            def read(self_inner):
                return body

        return {"Body": Body(), "LastModified": when}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.put(Bucket, Key, Body)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        s3 = self

        class Paginator:
            def paginate(self, Bucket):
                contents = [{"Key": k, "Size": len(b), "ETag": f'"{hashlib.md5(b).hexdigest()}"'}
                            for (bucket, k), (b, _) in s3.objects.items() if bucket == Bucket]
                yield {"Contents": contents}

        return Paginator()


class FakeSNS:
    def __init__(self):
        self.messages = []

    def publish(self, **kwargs):
        message = json.loads(kwargs["Message"])
        self.messages.append({"subject": kwargs["Subject"], "email": message["email"], "sms": message["sms"],
                              "severity": kwargs["MessageAttributes"]["severity"]["StringValue"],
                              "topic": kwargs["TopicArn"]})


class FakeCloudWatch:
    def __init__(self):
        self.metrics = []

    def put_metric_data(self, Namespace, MetricData):
        for datum in MetricData:
            self.metrics.append((Namespace, datum["MetricName"], datum["Value"], datum["Dimensions"][0]["Value"]))


@pytest.fixture
def aws(monkeypatch):
    s3, sns, cloudwatch = FakeS3(), FakeSNS(), FakeCloudWatch()
    monkeypatch.setattr(handler, "_clients", {"s3": s3, "sns": sns, "cloudwatch": cloudwatch})
    monkeypatch.setattr(handler, "_manifest_cache", {"at": 0.0, "value": None})
    for name, value in {"SITE_NAME": "dev", "SITE_URL": "https://dev.example.org", "SITE_BUCKET": "site",
                        "INTEGRITY_BUCKET": "integrity", "TOPIC_ARN": "arn:topic"}.items():
        monkeypatch.setenv(name, value)
    s3.put("integrity", "manifest.json", json.dumps(manifest()).encode())
    for key, body in SITE.items():
        s3.put("site", key, body)
    monkeypatch.setattr(checker, "fetch", lambda url: SITE.get(url.removeprefix("https://dev.example.org/") or "index.html", b"?"))
    return s3, sns, cloudwatch


def s3_event(bucket, key, detail_type="Object Created", body=None):
    obj = {"key": key}
    if body is not None:
        obj.update(size=len(body), etag=hashlib.md5(body).hexdigest())
    return {"source": "aws.s3", "detail-type": detail_type, "detail": {"bucket": {"name": bucket}, "object": obj}}


# ---- scheduled ----------------------------------------------------------------------------------------------------


def test_a_clean_check_sends_nothing_and_reports_its_heartbeat(aws):
    s3, sns, cloudwatch = aws
    assert handler.handler({"mode": "scheduled"}, None) == {"problems": []}
    assert sns.messages == []
    assert ("CovidWall/SiteIntegrity", "ScheduledChecks", 1, "dev") in cloudwatch.metrics
    assert ("CovidWall/SiteIntegrity", "Problems", 0, "dev") in cloudwatch.metrics


def test_a_tampered_site_is_reported_once_then_again_when_it_changes_and_when_it_recovers(aws, monkeypatch):
    s3, sns, _ = aws
    s3.put("site", "index.html", b"<h1>hacked</h1>")
    hacked = {**SITE, "index.html": b"<h1>hacked</h1>"}
    monkeypatch.setattr(checker, "fetch", lambda url: hacked.get(url.removeprefix("https://dev.example.org/") or "index.html"))

    handler.handler({"mode": "scheduled"}, None)
    assert len(sns.messages) == 1
    alert = sns.messages[0]
    assert alert["subject"] == "[covidwall dev] The website does not match what was deployed"
    assert alert["severity"] == "alert"
    assert "- index.html: changed (bucket)" in alert["email"]
    assert "- /: changed (live site): the home page" in alert["email"]
    assert alert["sms"].startswith("covidwall dev: 2 problem(s)")

    handler.handler({"mode": "scheduled"}, None)
    assert len(sns.messages) == 1  # the same problems: not reported again

    s3.put("site", "evil.js", b"x")
    handler.handler({"mode": "scheduled"}, None)
    assert len(sns.messages) == 2 and "evil.js" in sns.messages[1]["email"]

    s3.put("site", "index.html", SITE["index.html"])
    del s3.objects[("site", "evil.js")]
    monkeypatch.setattr(checker, "fetch", lambda url: SITE.get(url.removeprefix("https://dev.example.org/") or "index.html"))
    handler.handler({"mode": "scheduled"}, None)
    assert sns.messages[-1]["subject"] == "[covidwall dev] The website matches its known-good list again"
    assert sns.messages[-1]["severity"] == "alert"


def test_no_known_good_list_is_itself_a_problem(aws):
    s3, sns, _ = aws
    del s3.objects[("integrity", "manifest.json")]
    assert handler.handler({"mode": "scheduled"}, None)["problems"] == ["/: no known-good list to check against (manifest)"]
    assert len(sns.messages) == 1


def test_a_deploy_under_way_is_not_an_alarm(aws, monkeypatch):
    s3, sns, _ = aws
    now = datetime.now(timezone.utc)
    m = manifest(recorded_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 deploying_until=(now + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    m["files"]["index.html"] = entry(b"the new build")
    s3.put("integrity", "manifest.json", json.dumps(m).encode())
    assert handler.handler({"mode": "scheduled"}, None) == {"problems": []}
    assert sns.messages == []


# ---- instant: one file in the site's bucket ----------------------------------------------------------------------


def test_a_write_that_matches_the_list_is_quiet(aws):
    _, sns, _ = aws
    assert handler.handler(s3_event("site", "index.html", body=SITE["index.html"]), None) == {"problems": []}
    assert sns.messages == []


def test_a_write_outside_a_deploy_raises_the_alarm_at_once_but_not_twice_in_five_minutes(aws):
    _, sns, _ = aws
    result = handler.handler(s3_event("site", "index.html", body=b"<h1>hacked</h1>"), None)
    assert result == {"problems": ["index.html: changed (bucket)"]}
    assert sns.messages[0]["subject"] == "[covidwall dev] A website file was changed outside a deploy"
    assert sns.messages[0]["sms"] == "covidwall dev: index.html: changed (bucket)"

    handler.handler(s3_event("site", "evil.js", body=b"x"), None)
    handler.handler(s3_event("site", "api/stats", detail_type="Object Deleted"), None)
    assert len(sns.messages) == 1


def test_another_instant_alert_comes_once_the_quiet_time_has_passed(aws, monkeypatch):
    s3, sns, _ = aws
    s3.put("integrity", "state/alerts.json", json.dumps({"instant_alert_at": time.time() - 301}).encode())
    handler.handler(s3_event("site", "evil.js", body=b"x"), None)
    assert len(sns.messages) == 1


def test_a_list_written_just_now_is_read_again_before_raising_the_alarm(aws):
    s3, sns, _ = aws
    handler.handler(s3_event("site", "index.html", body=SITE["index.html"]), None)  # caches the list
    new = manifest()
    new["files"]["index.html"] = entry(b"the new build")
    s3.put("integrity", "manifest.json", json.dumps(new).encode())

    assert handler.handler(s3_event("site", "index.html", body=b"the new build"), None) == {"problems": []}
    assert sns.messages == []


def test_the_list_is_cached_between_quick_events(aws):
    s3, _, _ = aws
    handler.handler(s3_event("site", "index.html", body=SITE["index.html"]), None)
    reads = s3.gets
    handler.handler(s3_event("site", "api/stats", body=SITE["api/stats"]), None)
    assert s3.gets == reads


def test_events_before_any_list_exists_wait_for_the_scheduled_check(aws):
    s3, sns, _ = aws
    del s3.objects[("integrity", "manifest.json")]
    assert handler.handler(s3_event("site", "x", body=b"x"), None) == {"problems": []}
    assert sns.messages == []


# ---- the known-good list itself ----------------------------------------------------------------------------------


def test_a_new_list_is_announced_by_email_only(aws):
    s3, sns, _ = aws
    handler.handler(s3_event("integrity", "manifest.json"), None)
    note = sns.messages[0]
    assert note["severity"] == "info"
    assert note["subject"] == "[covidwall dev] New known-good list recorded"
    assert "a deploy finished): 2 files" in note["email"]

    m = manifest(deploying_until="2026-11-26T12:30:00Z")
    s3.put("integrity", "manifest.json", json.dumps(m).encode())
    handler.handler(s3_event("integrity", "manifest.json"), None)
    assert "a deploy started" in sns.messages[1]["email"]


def test_a_deleted_list_raises_the_alarm(aws):
    s3, sns, _ = aws
    del s3.objects[("integrity", "manifest.json")]
    handler.handler(s3_event("integrity", "manifest.json", detail_type="Object Deleted"), None)
    assert sns.messages[0]["severity"] == "alert"
    assert sns.messages[0]["subject"] == "[covidwall dev] The known-good list was deleted"


def test_an_unknown_event_is_an_error(aws):
    with pytest.raises(ValueError):
        handler.handler({"something": "else"}, None)


def test_long_reports_are_cut_short():
    problems = [checker.Problem("unexpected", f"f{i:03}", "bucket") for i in range(45)]
    lines = handler.report(problems)
    assert len(lines) == 41 and lines[-1] == "- and 5 more"


def test_the_aws_clients_are_made_once(monkeypatch):
    made = []

    class FakeBoto3:
        @staticmethod
        def client(name):
            made.append(name)
            return object()

    monkeypatch.setattr(handler, "_clients", {})
    monkeypatch.setitem(__import__("sys").modules, "boto3", FakeBoto3)
    first = handler.client("sns")
    assert handler.client("sns") is first
    assert made == ["sns"]
