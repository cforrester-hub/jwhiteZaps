"""Team chat posts for clock events (replaces the Zapier zap's Teams step)."""

import asyncio
import sys
from datetime import date
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE_DIR), str(SERVICE_DIR.parents[1])]  # src package, repo-root shared package

from src import main, teams_notify  # noqa: E402
from src.timesheet_parser import DesiredDndStatus, ParsedTimesheetEvent, TimesheetAction  # noqa: E402


def _inlines(message):
    return message["attachments"][0]["content"]["body"][0]["inlines"]


def test_message_matches_zap_wording_and_colors():
    runs = _inlines(teams_notify.build_message("Ilse Segura Delgado", TimesheetAction.BREAK_START))
    assert runs[0]["text"] == "Ilse ---> "
    assert (runs[1]["text"], runs[1]["color"]) == ("Break Started", "Attention")
    assert _inlines(teams_notify.build_message("Maria Prince", TimesheetAction.CLOCK_IN))[1]["color"] == "Good"
    assert _inlines(teams_notify.build_message("Eric Becerra", TimesheetAction.BREAK_END))[1]["text"] == "Break Ended"
    assert _inlines(teams_notify.build_message("Wendy Yinguez", TimesheetAction.CLOCK_OUT))[1]["color"] == "Attention"
    unannounced = [a for a in TimesheetAction if a not in teams_notify.LABELS]
    assert all(teams_notify.build_message("X", a) is None for a in unannounced)


class FakeClient:
    posts, status, fail = [], 202, False

    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json):
        if FakeClient.fail:
            raise ConnectionError("teams down")
        FakeClient.posts.append((url, json))
        return type("R", (), {"status_code": FakeClient.status, "text": ""})()


def test_post_disabled_without_url_and_never_raises(monkeypatch):
    monkeypatch.setattr(teams_notify.httpx, "AsyncClient", FakeClient)
    FakeClient.posts = []

    monkeypatch.setattr(teams_notify.settings, "teams_webhook_url", "")
    assert asyncio.run(teams_notify.post_clock_event("Ilse", TimesheetAction.CLOCK_IN)) is False
    assert FakeClient.posts == []

    monkeypatch.setattr(teams_notify.settings, "teams_webhook_url", "https://example.test/hook")
    assert asyncio.run(teams_notify.post_clock_event("Ilse", TimesheetAction.CLOCK_IN)) is True
    assert FakeClient.posts[0][0] == "https://example.test/hook"

    FakeClient.status = 500
    assert asyncio.run(teams_notify.post_clock_event("Ilse", TimesheetAction.CLOCK_IN)) is False
    FakeClient.status, FakeClient.fail = 202, True
    assert asyncio.run(teams_notify.post_clock_event("Ilse", TimesheetAction.CLOCK_IN)) is False
    FakeClient.fail = False


def test_event_posts_even_when_ringcentral_lookup_fails(monkeypatch):
    posted = []

    async def no_target(deputy_id, refresh=False):
        return None

    async def fake_post(name, action):
        posted.append((name, action))
        return True

    async def noop(*a, **kw):
        return True

    monkeypatch.setattr(main, "resolve_target", no_target)
    monkeypatch.setattr(main, "post_clock_event", fake_post)
    monkeypatch.setattr(main, "mark_dedupe_completed", noop)

    event = ParsedTimesheetEvent(
        action=TimesheetAction.CLOCK_IN, desired_dnd_status=DesiredDndStatus.TAKE_ALL_CALLS,
        timesheet_id=1, employee_id=99, event_unix=0, dedupe_key="k", reason="test",
        timesheet_date=date.today().strftime("%Y-%m-%d"),
    )
    asyncio.run(main.process_timesheet_event(event))
    assert posted == [("Employee #99", TimesheetAction.CLOCK_IN)]
