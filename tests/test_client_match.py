from barberis_insights.ingest.client_match import match_row, norm_name, norm_phone

BY_MINUTE = {("2026-07-20", "10:00"): {1, 2}, ("2025-03-01", "12:00"): {1}, ("2026-08-01", "15:00"): {3}}
NAMES = {1: "андрій", 2: "олег", 3: "тарас"}


def test_phone_normalisation():
    assert norm_phone(380000000123.0) == "+380000000123"
    assert norm_phone("+38 (000) 000-01-23") == "+380000000123"
    assert norm_phone("0000000123") == "+380000000123"
    assert norm_phone("") is None


def test_match_by_both_visits():
    assert match_row({"name": "Андрій", "last_visit": "2026-07-20 10:00", "first_visit": "2025-03-01 12:00"}, BY_MINUTE, NAMES) == (1, "matched")


def test_name_breaks_ties_and_rejects_mismatch():
    assert match_row({"name": "Олег", "last_visit": "2026-07-20 10:00", "first_visit": "2019-01-01 10:00"}, BY_MINUTE, NAMES) == (2, "matched")
    assert match_row({"name": "Іван", "last_visit": "2026-07-20 10:00"}, BY_MINUTE, NAMES) == (None, "ambiguous")
    assert match_row({"name": "Іван", "last_visit": "2026-08-01 15:00"}, BY_MINUTE, NAMES) == (None, "name mismatch")
    assert match_row({"name": "Тарас", "last_visit": "2019-05-05 10:00"}, BY_MINUTE, NAMES) == (None, "no visit in data")


def test_norm_name():
    assert norm_name("  Мар’ян  Іванів ") == norm_name("мар'ян іванів")
