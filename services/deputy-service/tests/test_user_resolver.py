"""Deputy employee -> RingCentral extension ID resolution, including the stale-ID retry."""

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE_DIR), str(SERVICE_DIR.parents[1])]  # src package, repo-root shared package

from src import main, user_resolver  # noqa: E402
from src.timesheet_parser import DesiredDndStatus, ParsedTimesheetEvent, TimesheetAction  # noqa: E402

EXTENSIONS = [
    {"id": "639476107", "extension_number": "101", "name": "Ilse Segura Delgado", "email": "ilse@example.com", "type": "User"},
    {"id": "858011107", "extension_number": "105", "name": "Maria Prince", "email": "maria@example.com", "type": "User"},
    {"id": "857865107", "extension_number": "300", "name": "CSR Overflow", "email": None, "type": "Department"},
]


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, **kw):
        self.data[key] = value


def test_match_by_email_then_exact_name_never_guess():
    m = user_resolver.match_extension
    assert m(EXTENSIONS, {"ilse@example.com"}, "Someone Else")["id"] == "639476107"
    assert m(EXTENSIONS, set(), "  maria   PRINCE ")["id"] == "858011107"
    assert m(EXTENSIONS, set(), "CSR Overflow") is None  # call queues are not people
    assert m(EXTENSIONS, set(), "Maria") is None  # partial name: no guess
    dupes = EXTENSIONS + [{**EXTENSIONS[1], "id": "1"}]
    assert m(dupes, set(), "Maria Prince") is None  # ambiguous: no guess


def test_resolve_order_uses_extension_id_not_number(monkeypatch):
    redis = FakeRedis()

    async def fake_get_redis():
        return redis

    async def fake_lookup(deputy_id):
        return user_resolver.RingCentralTarget("999", "Looked Up", "lookup")

    monkeypatch.setattr(user_resolver, "get_redis", fake_get_redis)
    monkeypatch.setattr(user_resolver, "_lookup", fake_lookup)

    # Mapping file: must return ringcentral_member_id (858011107), never the extension number (105)
    t = asyncio.run(user_resolver.resolve_target("6"))
    assert (t.extension_id, t.source) == ("858011107", "mapping")
    # Learned Redis entry wins over the file
    redis.data[user_resolver.REDIS_KEY.format("6")] = json.dumps({"extension_id": "777", "name": "Maria Prince"})
    assert asyncio.run(user_resolver.resolve_target("6")).source == "redis"
    # Unknown employee, or refresh after a 404, goes to the live lookup
    assert asyncio.run(user_resolver.resolve_target("12345")).source == "lookup"
    assert asyncio.run(user_resolver.resolve_target("6", refresh=True)).source == "lookup"


def test_stale_id_404_re_resolves_and_retries(monkeypatch):
    calls, resolves = [], []

    async def fake_resolve(deputy_id, refresh=False):
        resolves.append(refresh)
        if refresh:
            return user_resolver.RingCentralTarget("639476107", "Ilse Segura Delgado", "lookup")
        return user_resolver.RingCentralTarget("111", "Ilse Segura Delgado", "mapping")

    async def fake_update(extension_id, dnd_status, employee_name):
        calls.append(extension_id)
        return (extension_id == "639476107", extension_id == "111")

    async def noop(*a, **kw):
        return True

    monkeypatch.setattr(main, "resolve_target", fake_resolve)
    monkeypatch.setattr(main, "update_ringcentral_dnd", fake_update)
    monkeypatch.setattr(main, "notify_dashboard_status", noop)
    monkeypatch.setattr(main, "mark_dedupe_completed", noop)

    event = ParsedTimesheetEvent(
        action=TimesheetAction.CLOCK_IN, desired_dnd_status=DesiredDndStatus.TAKE_ALL_CALLS,
        timesheet_id=1, employee_id=17, event_unix=0, dedupe_key="k", reason="test",
        timesheet_date=date.today().strftime("%Y-%m-%d"),
    )
    asyncio.run(main.process_timesheet_event(event))
    assert resolves == [False, True]
    assert calls == ["111", "639476107"]
