from app import database


def test_init_db_creates_and_seeds(test_db):
    database.init_db()
    with database.db() as conn:
        rows = conn.execute("SELECT name FROM tributes").fetchall()
    assert len(rows) == len(database.SEED_TRIBUTES)


def test_init_db_does_not_reseed_existing_data(test_db):
    database.init_db()
    database.init_db()
    with database.db() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM tributes").fetchone()["n"]
    assert count == len(database.SEED_TRIBUTES)


def test_db_context_manager_commits(test_db):
    database.init_db()
    with database.db() as conn:
        conn.execute(
            "INSERT INTO tributes (name, message, author) VALUES (?, ?, ?)",
            ("Committed", "Persisted across connections.", "Tester"),
        )
    # A fresh connection must see the committed row.
    with database.db() as conn:
        row = conn.execute(
            "SELECT * FROM tributes WHERE name = 'Committed'"
        ).fetchone()
    assert row is not None
    assert row["candles"] == 0


def test_init_db_seeds_victims_once(test_db, tmp_path, monkeypatch):
    seed = tmp_path / "victims.json"
    seed.write_text('["Ann Lee", "Two\\nlines"]', encoding="utf-8")
    monkeypatch.setattr(database, "VICTIMS_PATH", seed)
    database.init_db()
    database.init_db()
    with database.db() as conn:
        rows = conn.execute("SELECT name FROM victims ORDER BY id").fetchall()
    assert [r["name"] for r in rows] == ["Ann Lee", "Two\nlines"]


def test_bundled_victims_file_loads(test_db):
    database.init_db()
    with database.db() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM victims").fetchone()["n"]
    assert count > 0
