import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.services.job_queue import job_queue


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app_name"] == "ClipStudio"
        assert data["database"] == "ok"


@pytest.mark.asyncio
async def test_workspace_crud():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create workspace
        create_res = await client.post(
            "/api/v1/workspaces",
            json={
                "name": "Default Creator Studio",
                "description": "Primary creator workspace",
                "local_storage_path": "D:/dharmendra/clipstudio/data/media",
            },
        )
        assert create_res.status_code == 201
        ws = create_res.json()
        assert ws["name"] == "Default Creator Studio"
        ws_id = ws["id"]

        # Get workspace
        get_res = await client.get(f"/api/v1/workspaces/{ws_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == ws_id


@pytest.mark.asyncio
async def test_job_persistence_and_lifecycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Trigger test job
        job_res = await client.post("/api/v1/jobs/test", json={"test": True})
        assert job_res.status_code == 201
        job = job_res.json()
        assert job["job_type"] == "test_job"
        assert job["status"] in ["queued", "running"]
        job_id = job["id"]

        # Fetch job
        fetch_res = await client.get(f"/api/v1/jobs/{job_id}")
        assert fetch_res.status_code == 200
        fetched = fetch_res.json()
        assert fetched["id"] == job_id


def test_alembic_url_precedence(tmp_path):
    """Verifies that programmatic sqlalchemy.url overrides default settings in isolated DB."""
    import sqlite3
    from alembic import command
    from alembic.config import Config

    # 1. Programmatic override test against isolated database
    isolated_db = tmp_path / "isolated_precedence_test.db"
    isolated_url = f"sqlite:///{isolated_db.as_posix()}"

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", isolated_url)
    command.upgrade(cfg, "head")

    conn = sqlite3.connect(isolated_db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    conn.close()

    assert "workspaces" in tables
    assert "imported_videos" in tables
    assert "processing_jobs" in tables
    assert "alembic_version" in tables

