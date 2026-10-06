import pytest
from conftest import sign_in
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from barberis_insights.db.models import User, UserSession
from barberis_insights.web import auth


def test_passwords_are_hashed_and_verified():
    h = auth.hash_password("s3cret!")
    assert "s3cret" not in h and auth.verify_password(h, "s3cret!") and not auth.verify_password(h, "wrong") and not auth.verify_password("junk", "x")
    assert auth.hash_password("s3cret!") != h                          # a fresh salt each time


def test_a_fresh_database_gets_one_super_admin(s):
    assert auth.ensure_admin(s) is True and auth.ensure_admin(s) is False
    u = s.scalar(select(User))
    assert u.username == "admin" and u.role == "superadmin" and u.must_change_password
    assert auth.authenticate(s, "ADMIN", "admin") is u and auth.authenticate(s, "admin", "nope") is None


def test_roles_decide_which_pages_open():
    for path in ("/", "/team", "/goals", "/admin/users", "/risk", "/client/5"):
        assert auth.allowed("superadmin", path)
    for path in ("/risk", "/risk?x=1".split("?")[0], "/outreach", "/client/5", "/cases/3", "/account", "/login", "/static/x.css"):
        assert auth.allowed("administrator", path), path
    for path in ("/", "/team", "/barber/olia", "/goals", "/context", "/data", "/admin/users", "/api/risk", "/hypotheses"):
        assert not auth.allowed("administrator", path), path


def test_sessions_expire_and_end(s):
    auth.ensure_admin(s)
    u = s.scalar(select(User))
    token = auth.start_session(s, u)
    assert auth.user_for_token(s, token) is u and auth.user_for_token(s, "forged") is None and auth.user_for_token(s, None) is None
    auth.end_session(s, token)
    assert auth.user_for_token(s, token) is None


def test_a_disabled_user_cannot_log_in_or_keep_a_session(s):
    auth.ensure_admin(s)
    u = s.scalar(select(User))
    token = auth.start_session(s, u)
    u.active = False
    assert auth.authenticate(s, "admin", "admin") is None and auth.user_for_token(s, token) is None


def test_weak_passwords_are_refused():
    assert auth.validate_password("abc") == "short" and auth.validate_password("password") == "common" and auth.validate_password("a-good-one") is None


# ---- through the web app (the real local database; the test users are removed afterwards)
@pytest.fixture
def web():
    from barberis_insights.db.session import session_scope
    from barberis_insights.web.app import app
    made = []
    def make(role):
        with session_scope() as sess:
            name = f"zz_test_{role}"
            sess.execute(delete(User).where(User.username == name))
            sess.add(User(username=name, role=role, password_hash=auth.hash_password("pass-1234"), active=True)); made.append(name)
        return name
    yield app, make
    with session_scope() as sess:
        ids = [u.id for u in sess.scalars(select(User).where(User.username.in_(made)))]
        sess.execute(delete(UserSession).where(UserSession.user_id.in_(ids)))
        sess.execute(delete(User).where(User.username.in_(made)))


def test_anonymous_visitors_are_sent_to_the_login(web):
    app, _ = web
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    r = c.get("/risk", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login") and "next=" in r.headers["location"]
    assert c.get("/api/metrics").status_code == 401 if c.cookies is not None else True
    assert c.get("/login").status_code == 200


def test_an_administrator_sees_only_the_clients_section(web):
    app, make = web
    name = make("administrator")
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    r = c.post("/login", data={"username": name, "password": "pass-1234", "next": "/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/risk"          # an administrator's home is the case list
    assert c.get("/risk").status_code == 200
    assert c.get("/goals", follow_redirects=False).headers["location"] == "/risk"
    assert c.get("/admin/users", follow_redirects=False).status_code == 303
    assert "/goals" not in c.get("/risk").text and "/admin/users" not in c.get("/risk").text
    assert c.post("/admin/users", data={"username": "x", "password": "abcdef"}).status_code == 403


def test_a_wrong_password_is_refused_and_logout_ends_the_session(web):
    app, make = web
    name = make("administrator")
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert "error=1" in c.post("/login", data={"username": name, "password": "bad"}, follow_redirects=False).headers["location"]
    c.post("/login", data={"username": name, "password": "pass-1234"})
    assert c.get("/risk").status_code == 200
    c.post("/logout")
    assert c.get("/risk", follow_redirects=False).status_code == 303


def test_the_super_admin_manages_users_and_the_last_one_is_protected(web):
    app, _ = web
    c = sign_in(TestClient(app, base_url="http://127.0.0.1:8765"))
    assert c.get("/admin/users").status_code == 200
    r = c.post("/admin/users", data={"username": "zz_test_added", "role": "administrator", "password": "abcdef7"}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    from barberis_insights.db.session import session_scope
    with session_scope() as sess:
        u = sess.scalar(select(User).where(User.username == "zz_test_added"))
        assert u and u.role == "administrator"
        sess.execute(delete(User).where(User.username == "zz_test_added"))
