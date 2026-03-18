"""
tests/test_api.py
Integration tests for the FastAPI routes.
Uses TestClient (no real AWS calls — store and S3 are mocked).
"""
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


# ── /health ───────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


# ── /config ───────────────────────────────────────────────────────────────────

def test_config_returns_limits(client):
    r = client.get("/config")
    assert r.status_code == 200
    data = r.json()
    assert "max_duration_seconds" in data
    assert "allowed_mime_types" in data
    assert isinstance(data["allowed_mime_types"], list)


# ── /upload-url ───────────────────────────────────────────────────────────────

def test_upload_url_rejects_unsupported_mime(client):
    """
    Bug 7.1 regression: backend must explicitly reject unsupported formats.
    Previously all webm was rejected; now we test an actually bad format.
    """
    with patch("app.routers.analysis.store.put_pending"):
        r = client.post("/upload-url", json={
            "filename": "recording.mp4",
            "mime_type": "video/mp4",        # not in allowlist
            "file_size_bytes": 100_000,
        })
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


def test_upload_url_accepts_webm(client):
    """
    Bug 7.1 regression: audio/webm must now be accepted.
    """
    fake_url = "https://s3.example.com/presigned"
    with (
        patch("app.routers.analysis.boto3.client") as mock_s3,
        patch("app.routers.analysis.store.put_pending"),
    ):
        mock_s3.return_value.generate_presigned_url.return_value = fake_url
        r = client.post("/upload-url", json={
            "filename": "recording.webm",
            "mime_type": "audio/webm;codecs=opus",
            "file_size_bytes": 200_000,
        })
    assert r.status_code == 201
    data = r.json()
    assert "audio_id" in data
    assert data["upload_url"] == fake_url


def test_upload_url_rejects_oversized_file(client):
    with patch("app.routers.analysis.store.put_pending"):
        r = client.post("/upload-url", json={
            "filename": "huge.webm",
            "mime_type": "audio/webm",
            "file_size_bytes": 999_999_999,   # way over 5 MB
        })
    assert r.status_code == 400
    assert "large" in r.json()["detail"].lower()


# ── /result/{audio_id} ────────────────────────────────────────────────────────

def test_result_returns_404_for_unknown_id(client):
    """
    Bug 7.3 regression: unknown IDs must return 404, not 500.
    """
    with patch("app.routers.analysis.store.get_result", return_value=None):
        r = client.get("/result/nonexistent-id")
    assert r.status_code == 404


def test_result_returns_pending_status(client):
    with patch("app.routers.analysis.store.get_result", return_value={"status": "pending"}):
        r = client.get("/result/some-id")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert r.json()["result"] is None


def test_result_returns_failed_status(client):
    with patch("app.routers.analysis.store.get_result", return_value={
        "status": "failed",
        "error": "Recording too short"
    }):
        r = client.get("/result/some-id")
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    assert "short" in r.json()["error_message"]
