"""Interface localisation (Ukrainian and English).

Code, identifiers and docs stay in English; everything a person reads in the dashboard or the call sheet comes
from the catalogs `uk.json` / `en.json`, keyed by stable English ids (e.g. "nav.goals", "metric.util").

    t("risk.proposed_n", "uk", n=3)  → "Запропоновано: 3 …"

Missing keys fall back to English, then to the key itself, so a gap is visible but never crashes a page.
`tests/test_i18n.py` keeps the two catalogs in step (same keys, same placeholders).
"""
from __future__ import annotations

import json
import string
from functools import lru_cache
from pathlib import Path

LANGUAGES = {"uk": "Українська", "en": "English"}
DEFAULT = "uk"
_DIR = Path(__file__).parent


@lru_cache
def catalog(lang: str) -> dict[str, str]:
    return json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def normalize(lang: str | None) -> str:
    lang = (lang or "").lower()[:2]
    return lang if lang in LANGUAGES else DEFAULT


def t(key: str, lang: str = DEFAULT, **params) -> str:
    text = catalog(normalize(lang)).get(key) or catalog("en").get(key) or key
    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def placeholders(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def translator(lang: str):
    """A `t` bound to one language, for templates: {{ t('nav.goals') }}."""
    lang = normalize(lang)
    return lambda key, **params: t(key, lang, **params)


def all_labels(prefix: str) -> dict[str, dict[str, str]]:
    """{suffix: {lang: label}} for every key under prefix, e.g. all_labels("outcome.")."""
    out: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        for k, v in catalog(lang).items():
            if k.startswith(prefix):
                out.setdefault(k[len(prefix):], {})[lang] = v
    return out
