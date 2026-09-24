"""Deputy webhooks must carry Authorization: Bearer <DEPUTY_WEBHOOK_SECRET>."""

import os
import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE_DIR), str(SERVICE_DIR.parents[1])]  # src package, repo-root shared package
os.environ["DEPUTY_WEBHOOK_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from src import main  # noqa: E402

URL = "/api/deputy/webhook/timesheet"


def test_timesheet_webhook_requires_secret(monkeypatch):
    client = TestClient(main.app)

    assert client.post(URL, json={}).status_code == 401
    assert client.post(URL, json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401

    # An empty payload is ignored before any Redis or RingCentral call
    ok = client.post(URL, json={}, headers={"Authorization": "Bearer test-secret"})
    assert ok.json()["status"] == "ignored"

    # Fail closed: with no secret configured, even an empty bearer token is rejected
    monkeypatch.setattr(main.settings, "deputy_webhook_secret", "")
    assert client.post(URL, json={}, headers={"Authorization": "Bearer "}).status_code == 401
