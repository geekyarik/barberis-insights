import pytest
from conftest import client

from barberis_insights.db.models import Client
from barberis_insights.ingest.clients import sync_client_list


def item(i, **kw):
    return {"id": i, "name": "X", "display_name": "X", "phone": "380501112233", "email": "", "comment": "", "sms_not": 0} | kw


def test_it_refreshes_the_clients_we_know_and_skips_the_ones_we_do_not(s):
    client(s, 1, phone=None); client(s, 2, phone="+380500000000")
    out = sync_client_list(s, [item(1), item(2, phone="380991112233"), item(99)])
    assert out["known"] == 2 and out["skipped_unknown"] == 1 and out["phones_added"] == 1 and out["phones_changed"] == 1
    assert s.get(Client, 1).phone == "+380501112233" and s.get(Client, 2).phone == "+380991112233" and s.get(Client, 99) is None


def test_a_staff_comment_that_says_do_not_call_marks_the_client_once(s):
    client(s, 1); client(s, 2)
    out = sync_client_list(s, [item(1, comment="Просив не дзвонити"), item(2, comment="любить машинку")])
    assert out["do_not_contact_set"] == 1 and s.get(Client, 1).do_not_contact is True and s.get(Client, 2).do_not_contact is False
    assert s.get(Client, 1).altegio_comment == "Просив не дзвонити"
    s.get(Client, 1).do_not_contact = False                                            # the owner lifted it by hand
    sync_client_list(s, [item(1, comment="Просив не дзвонити")])
    assert s.get(Client, 1).do_not_contact is False                                    # the same comment does not set it again
    sync_client_list(s, [item(1, comment="Просив не дзвонити. Ще раз: не турбувати")])
    assert s.get(Client, 1).do_not_contact is True                                     # but a new comment that says so does


def test_the_sms_flag_becomes_the_mass_notification_choice(s):
    client(s, 1); client(s, 2)
    sync_client_list(s, [item(1, sms_not=1), item(2, sms_not=0)])
    assert s.get(Client, 1).mass_notification_allowed is False and s.get(Client, 2).mass_notification_allowed is True
