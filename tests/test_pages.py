import pytest

ADMIN_PAGES = ["/dashboard", "/register_page", "/capture", "/recognize_page", "/records_page", "/qr_session"]
PHONE_PAGES = ["/qr_mobile", "/qr_verify", "/qr_result"]


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_admin_pages_redirect_anonymous_visitors_to_login(client, path):
    res = client.get(path)
    assert res.status_code == 302
    assert res.headers["Location"] == "/"


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_admin_pages_render_for_signed_in_admins(authenticated_client, path):
    res = authenticated_client.get(path)
    assert res.status_code == 200
    assert res.mimetype == "text/html"


@pytest.mark.parametrize("path", PHONE_PAGES)
def test_phone_check_in_pages_are_public(client, path):
    res = client.get(path)
    assert res.status_code == 200
    assert res.mimetype == "text/html"


def test_dashboard_is_never_cached(authenticated_client):
    res = authenticated_client.get("/dashboard")
    assert "no-store" in res.headers["Cache-Control"]


def test_login_page_sends_signed_in_admins_to_the_dashboard(authenticated_client):
    res = authenticated_client.get("/")
    assert res.status_code == 302
    assert res.headers["Location"] == "/dashboard"


def test_logout_clears_the_session(authenticated_client):
    res = authenticated_client.get("/logout")
    assert res.status_code == 302
    assert res.headers["Location"] == "/"
    assert "no-store" in res.headers["Cache-Control"]
    assert authenticated_client.get("/dashboard").status_code == 302
