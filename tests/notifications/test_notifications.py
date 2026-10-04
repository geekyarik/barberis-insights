import datetime as dt

import pytest
from conftest import visit
from metric_helpers import F, T, shop

from barberis_insights.config import settings
from barberis_insights.db.models import Delivery, Recipient, ReportRun, Subscription
from barberis_insights.notifications import render, service
from barberis_insights.notifications.channels import ChannelError, register
from barberis_insights.notifications.channels.fake import FakeChannel
from barberis_insights.notifications.channels.telegram import TelegramChannel, split
from barberis_insights.reports import service as reports

NOSLEEP = lambda _: None


@pytest.fixture
def owner(s, monkeypatch):
    monkeypatch.setattr(settings, "telegram_owner_chat_id", 12345)
    fake = FakeChannel()
    register(fake)
    service.ensure_owner(s)
    return fake


def report(s):
    shop(s)
    visit(s, 40, "2026-03-04", 1, 500)
    return reports.weekly_review(s, F, T)


def test_owner_is_subscribed_once_even_when_set_up_twice(s, owner):
    service.ensure_owner(s)
    assert s.query(Recipient).count() == 1 and s.query(Subscription).count() == 2


def test_no_owner_without_a_chat_id(s, monkeypatch):
    monkeypatch.setattr(settings, "telegram_owner_chat_id", None)
    assert service.ensure_owner(s) is None


def test_weekly_review_is_composed_from_runs_and_frozen(s):
    r = report(s)
    assert r.report_key == "weekly_review" and len(r.analysis_run_ids) == 3
    assert r.content["team"]["revenue"] == 3500 and r.content["names"] == {"a": "A", "b": "B"}
    assert r.content["overdue"]["count"] == 0 and "goals" in r.content
    r.content = {}
    with pytest.raises(ValueError, match="immutable"):
        s.flush()
    s.rollback()


def test_a_report_is_delivered_once_per_recipient(s, owner):
    r = report(s)
    first = service.send_report(s, r, sleep=NOSLEEP)
    assert [d.status for d in first] == ["sent"] and len(owner.sent) == 1
    assert service.send_report(s, r, sleep=NOSLEEP) == [] and len(owner.sent) == 1


def test_delivery_is_retried_then_recorded(s, owner):
    owner.fail_times = 2
    d = service.send_report(s, report(s), sleep=NOSLEEP)[0]
    assert d.status == "sent" and d.attempts == 3


def test_a_failed_delivery_keeps_its_error_and_is_retried_next_time(s, owner):
    owner.fail_times = 99
    r = report(s)
    d = service.send_report(s, r, sleep=NOSLEEP)[0]
    assert d.status == "failed" and d.attempts == 3 and "simulated" in d.error
    owner.fail_times = 0
    again = service.send_report(s, r, sleep=NOSLEEP)[0]
    assert again.id == d.id and again.status == "sent" and again.attempts == 4


def test_an_alert_goes_out_once_a_day(s, owner):
    kw = dict(job="weekly_review", weeks="2026-W38", sleep=NOSLEEP)
    assert len(service.send_alert(s, "job_blocked", "2026-10-05", **kw)) == 1
    assert service.send_alert(s, "job_blocked", "2026-10-05", **kw) == []
    assert len(service.send_alert(s, "job_blocked", "2026-10-06", **kw)) == 1
    assert "barberis-goals-refresh" in owner.sent[0][1]


def test_the_message_is_in_the_recipients_language(s, owner):
    r = report(s)
    uk, en = render.weekly_review(r.content, "uk"), render.weekly_review(r.content, "en")
    assert "Тижневий огляд" in uk and "Weekly review" in en and "Виручка" in uk and "Revenue" in en


def test_client_names_are_shown_to_the_owner_but_never_phones(s, owner):
    from conftest import client
    for d in ("2026-01-05", "2026-01-12", "2026-01-19"):
        visit(s, 21, d, 1)
    client(s, 21, phone="+380501112233").name = "Олексій"
    r = reports.weekly_review(s, F, T)
    service.send_report(s, r, sleep=NOSLEEP)
    text = owner.sent[0][1]
    assert "Олексій" in text and "380501112233" not in text


def test_barbers_without_data_that_week_are_left_out(s):
    r = report(s)
    r.content["barbers"]["idle"] = {"revenue": None, "visits": None, "util": None, "rph": None, "check": None}
    r.content["names"]["idle"] = "Idle"
    assert "Idle" not in render.weekly_review(r.content, "en")


def test_telegram_messages_are_split_under_the_limit():
    text = "\n".join(f"line {i} " + "x" * 90 for i in range(200))
    parts = split(text)
    assert len(parts) > 1 and all(len(p) <= 4096 for p in parts) and "\n".join(parts) == text


def test_telegram_errors_never_contain_the_token(monkeypatch):
    import io
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b'{"ok": false, "description": "chat not found"}'))
    ch = TelegramChannel("SECRET-TOKEN")
    rcp = Recipient(name="Owner", lang="uk", telegram_chat_id=1)
    with pytest.raises(ChannelError) as e:
        ch.send(rcp, "hi")
    assert "SECRET-TOKEN" not in str(e.value) and "chat not found" in str(e.value)


def test_a_recipient_without_a_chat_id_gets_a_helpful_error():
    with pytest.raises(ChannelError, match="press Start"):
        TelegramChannel("t").send(Recipient(name="Owner", lang="uk", telegram_chat_id=None), "hi")
