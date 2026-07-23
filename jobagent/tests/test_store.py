from jobagent.store import Job, Store


def make_store(tmp_path):
    return Store(tmp_path / "test.db")


def test_upsert_and_get(tmp_path):
    store = make_store(tmp_path)
    job = Job(url="https://example.com/j/1", source="linkedin", title="IAM Engineer",
              company="Acme", description="desc", easy_apply=True)
    assert store.upsert_job(job) is True
    assert store.upsert_job(job) is False  # second time is not new

    got = store.get_job(job.url)
    assert got is not None
    assert got.title == "IAM Engineer"
    assert got.easy_apply is True
    assert got.status == "discovered"


def test_upsert_refresh_keeps_status_and_longer_description(tmp_path):
    store = make_store(tmp_path)
    url = "https://example.com/j/2"
    store.upsert_job(Job(url=url, source="indeed", title="T", description="long description"))
    store.update(url, status="scored", score=77)
    # re-scan with shorter description must not clobber anything important
    store.upsert_job(Job(url=url, source="indeed", title="", description="short"))
    got = store.get_job(url)
    assert got.status == "scored"
    assert got.score == 77
    assert got.description == "long description"
    assert got.title == "T"


def test_status_transitions_and_counts(tmp_path):
    store = make_store(tmp_path)
    for i, status in enumerate(["discovered", "scored", "applied"]):
        url = f"https://example.com/j/{i}"
        store.upsert_job(Job(url=url, source="linkedin"))
        if status != "discovered":
            store.update(url, status=status)
    counts = store.status_counts()
    assert counts == {"discovered": 1, "scored": 1, "applied": 1}
    assert store.count_applied_today() == 1


def test_invalid_status_rejected(tmp_path):
    store = make_store(tmp_path)
    store.upsert_job(Job(url="https://example.com/j/9", source="linkedin"))
    try:
        store.update("https://example.com/j/9", status="bogus")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_saved_flag_persists_and_filters(tmp_path):
    store = make_store(tmp_path)
    store.upsert_job(Job(url="s1", source="linkedin", saved=True))
    store.upsert_job(Job(url="n1", source="linkedin"))
    assert store.get_job("s1").saved is True
    assert store.get_job("n1").saved is False
    assert [j.url for j in store.list_jobs(saved=True)] == ["s1"]
    assert [j.url for j in store.list_jobs(saved=False)] == ["n1"]
    assert len(store.list_jobs()) == 2  # no filter returns both


def test_saved_flag_is_sticky_on_rescan(tmp_path):
    store = make_store(tmp_path)
    url = "https://example.com/j/7"
    store.upsert_job(Job(url=url, source="linkedin", saved=True))
    # later re-discovered via a normal search scan — must stay saved
    store.upsert_job(Job(url=url, source="linkedin", saved=False))
    assert store.get_job(url).saved is True


def test_migration_adds_saved_column_to_old_db(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE jobs (
        url TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT DEFAULT '',
        company TEXT DEFAULT '', location TEXT DEFAULT '', description TEXT DEFAULT '',
        easy_apply INTEGER DEFAULT 0, status TEXT DEFAULT 'discovered',
        score INTEGER, score_reasons TEXT DEFAULT '', resume_path TEXT DEFAULT '',
        cover_letter_path TEXT DEFAULT '', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, applied_at TEXT)""")
    conn.execute("""INSERT INTO jobs (url, source, created_at, updated_at)
                    VALUES ('old-job', 'linkedin', 't', 't')""")
    conn.commit()
    conn.close()

    store = Store(db)  # must not raise, and must add the column
    job = store.get_job("old-job")
    assert job is not None and job.saved is False
    store.upsert_job(Job(url="new-job", source="linkedin", saved=True))
    assert store.get_job("new-job").saved is True


def test_list_jobs_filters(tmp_path):
    store = make_store(tmp_path)
    store.upsert_job(Job(url="u1", source="linkedin"))
    store.upsert_job(Job(url="u2", source="indeed"))
    store.update("u1", status="scored", score=90)
    store.update("u2", status="scored", score=30)
    assert [j.url for j in store.list_jobs(source="indeed")] == ["u2"]
    assert [j.url for j in store.list_jobs(status="scored", min_score=60)] == ["u1"]
