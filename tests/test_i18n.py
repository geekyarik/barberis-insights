"""The interface exists in Ukrainian and English: both catalogs have the same keys and placeholders, every key the
pages use exists, and pages render in both languages."""
import re
from pathlib import Path

import pytest

from barberis_insights.i18n import LANGUAGES, catalog, placeholders, t
from barberis_insights.metrics.registry import REGISTRY

SRC = Path(__file__).parents[1] / "src/barberis_insights"


@pytest.fixture
def web():
    from barberis_insights.config import settings
    if not (settings.data_dir / "insights.sqlite").exists():
        pytest.skip("local data not imported")
    from fastapi.testclient import TestClient

    from conftest import sign_in

    from barberis_insights.web.app import app
    return sign_in(TestClient(app, base_url="http://127.0.0.1:8765"))


def test_same_keys_and_placeholders():
    uk, en = catalog("uk"), catalog("en")
    assert sorted(set(uk) ^ set(en)) == []
    assert [k for k in en if placeholders(en[k]) != placeholders(uk[k])] == []
    assert [k for k in uk if not uk[k].strip()] == []


def test_every_key_used_exists():
    used = set()
    for f in [*SRC.glob("web/templates/*.html"), SRC / "web/app.py"]:
        used |= set(re.findall(r"""\bt\(\s*["']([a-z_]+(?:\.[a-z0-9_]+)+)["']""", f.read_text()))
    used |= {f"flash.{k}" for k in re.findall(r'back\(request, [^,]+, "([a-z_]+)"', (SRC / "web/app.py").read_text())}
    assert len(used) > 150
    assert sorted(k for k in used if k not in catalog("en")) == []


def test_every_metric_and_code_has_a_label():
    from barberis_insights.clients.risk import CALLABLE
    from barberis_insights.cases.service import ACTIVE, REJECT_REASONS, TRIGGER_OF
    need = {f"metric.{m}" for m in REGISTRY} | {f"case.status.{s}" for s in ACTIVE + ("closed",)} | {f"case.reason.{r}" for r in REJECT_REASONS}
    need |= {f"case.trigger.{t}" for t in TRIGGER_OF.values()} | {f"case.outcome.{o}" for o in ("visited", "rejected", "no_answer", "expired")}
    need |= {f"segment.{s}" for s in CALLABLE + ("slipping", "switched", "active")}
    need |= {f"goal.state.{s}" for s in ("done", "dropped", "no_data", "reached", "waiting", "on_track", "behind")}
    assert sorted(need - set(catalog("uk"))) == []


def test_fallbacks():
    assert t("nav.goals", "uk") == "Цілі" and t("nav.goals", "en") == "Goals"
    assert t("nav.goals", "de") == "Цілі"                       # unknown language → Ukrainian (default)
    assert t("no.such.key", "uk") == "no.such.key"               # a gap is visible, never a crash
    assert t("flash.case_booked", "uk").startswith("Збережено")


@pytest.mark.parametrize("lang,word", [("uk", "Огляд"), ("en", "Overview")])
def test_pages_render_in_both_languages(web, lang, word):
    web.cookies.set("lang", lang)
    for path in ("/", "/goals", "/risk", "/outreach", "/context", "/hypotheses", "/playbook", "/data"):
        r = web.get(path)
        assert r.status_code == 200, path
        assert f'<html lang="{lang}">' in r.text and word in r.text
        visible = re.sub(r"(?s)<style>.*?</style>", "", r.text)
        leaked = re.findall(r"\b(?:nav|common|metric|goal|goals|risk|col|status|offer|segment|hyp|verdict|flash|client|data|outreach|context)\.[a-z0-9_.]+", visible)
        assert leaked == [], (path, leaked)                       # no untranslated keys on the page


def test_language_switch(web):
    r = web.get("/lang/en?next=/goals", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/goals" and "lang=en" in r.headers["set-cookie"]
    assert web.get("/lang/en?next=//evil.example", follow_redirects=False).headers["location"] == "/"
    from barberis_insights.web.app import LANG_COOKIE
    web.cookies.delete(LANG_COOKIE)                              # keep the login, drop the language choice
    assert "Цілі" in web.get("/goals").text                      # default: Ukrainian
