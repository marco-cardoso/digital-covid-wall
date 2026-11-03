VALID_TRIBUTE = {
    "name": "Ada Lovelace",
    "years": "1950–2021",
    "message": "A brilliant mind and a kinder heart.",
    "author": "Charles",
    "relationship": "Colleague",
}


def test_list_returns_seeded_tributes(client):
    res = client.get("/api/tributes")
    assert res.status_code == 200
    tributes = res.json()
    assert len(tributes) == 3
    names = {t["name"] for t in tributes}
    assert "Elena Marchetti" in names
    first = tributes[0]
    assert {"id", "name", "years", "message", "author", "relationship", "candles", "created_at"} <= first.keys()


def test_create_tribute_returns_full_record(client):
    res = client.post("/api/tributes", json=VALID_TRIBUTE)
    assert res.status_code == 201
    tribute = res.json()
    assert tribute["name"] == "Ada Lovelace"
    assert tribute["years"] == "1950–2021"
    assert tribute["message"] == VALID_TRIBUTE["message"]
    assert tribute["author"] == "Charles"
    assert tribute["relationship"] == "Colleague"
    assert tribute["candles"] == 0
    assert tribute["id"] > 0
    assert tribute["created_at"]


def test_create_tribute_strips_whitespace(client):
    payload = dict(VALID_TRIBUTE, name="  Ada Lovelace  ", author="  Charles  ")
    res = client.post("/api/tributes", json=payload)
    assert res.status_code == 201
    tribute = res.json()
    assert tribute["name"] == "Ada Lovelace"
    assert tribute["author"] == "Charles"


def test_create_tribute_optional_fields_default_to_empty(client):
    payload = {k: v for k, v in VALID_TRIBUTE.items() if k in ("name", "message", "author")}
    res = client.post("/api/tributes", json=payload)
    assert res.status_code == 201
    tribute = res.json()
    assert tribute["years"] == ""
    assert tribute["relationship"] == ""


def test_new_tribute_appears_first_in_list(client):
    created = client.post("/api/tributes", json=VALID_TRIBUTE).json()
    tributes = client.get("/api/tributes").json()
    assert tributes[0]["id"] == created["id"]
    assert len(tributes) == 4


def test_create_rejects_missing_required_field(client):
    payload = {k: v for k, v in VALID_TRIBUTE.items() if k != "name"}
    assert client.post("/api/tributes", json=payload).status_code == 422


def test_create_rejects_blank_name(client):
    payload = dict(VALID_TRIBUTE, name="   ")
    assert client.post("/api/tributes", json=payload).status_code == 422


def test_create_rejects_overlong_message(client):
    payload = dict(VALID_TRIBUTE, message="x" * 1001)
    assert client.post("/api/tributes", json=payload).status_code == 422


def test_light_candle_increments_count(client):
    tribute = client.get("/api/tributes").json()[0]
    before = tribute["candles"]

    res = client.post(f"/api/tributes/{tribute['id']}/candle")
    assert res.status_code == 200
    assert res.json()["candles"] == before + 1

    res = client.post(f"/api/tributes/{tribute['id']}/candle")
    assert res.json()["candles"] == before + 2


def test_light_candle_unknown_tribute_returns_404(client):
    res = client.post("/api/tributes/99999/candle")
    assert res.status_code == 404
    assert res.json()["detail"] == "Tribute not found"


def test_stats_reflect_seed_data(client):
    stats = client.get("/api/stats").json()
    tributes = client.get("/api/tributes").json()
    assert stats["tributes"] == len(tributes) == 3
    assert stats["candles"] == sum(t["candles"] for t in tributes)


def test_stats_count_the_names(client):
    assert client.get("/api/stats").json()["names"] == len(client.get("/api/victims").json())


def test_stats_update_after_create_and_candle(client):
    before = client.get("/api/stats").json()
    created = client.post("/api/tributes", json=VALID_TRIBUTE).json()
    client.post(f"/api/tributes/{created['id']}/candle")

    after = client.get("/api/stats").json()
    assert after["tributes"] == before["tributes"] + 1
    assert after["candles"] == before["candles"] + 1
