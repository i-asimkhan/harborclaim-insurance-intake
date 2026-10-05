"""
Real browser UI tests -- separate from tests/test_app.py on purpose.

test_app.py exercises HTTP responses in-process (FastAPI's TestClient) and
checks whether expected text shows up in the rendered HTML. It's fast and
doesn't need a real browser, but it can't catch what a real browser renders
-- a CSS rule making text unreadable, a form that doesn't actually submit,
a button a user can't actually click. This suite does, using Playwright
against a real, live uvicorn process.

Run on demand, not as part of the regular test command (needs Playwright's
browser binaries installed, and takes several seconds to spin a server up):

    .venv/Scripts/python.exe -m playwright install chromium   # once
    .venv/Scripts/python.exe -m pytest tests/test_ui.py -v

Claimant login is simulated the same way as the documentation screenshots
(scripts/*) -- a real, properly-signed session cookie built with the actual
SESSION_SECRET_KEY, not an interactive Google consent screen, which can't be
automated headlessly. This only needs SESSION_SECRET_KEY in .env, not real
Google OAuth credentials -- so this suite runs even without ever completing
the Google Cloud Console setup. Adjuster login is exercised for real, by
typing credentials into the real form, the same as tests/test_app.py does.
"""

import base64
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJ = Path(__file__).parent.parent
PORT = 8199
BASE = f"http://127.0.0.1:{PORT}"

sys.path.insert(0, str(PROJ))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJ / ".env")

import itsdangerous  # noqa: E402

import storage  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def live_server():
    """Starts a real `uvicorn app:app` subprocess on a dedicated test port
    (8199, distinct from the usual 8123) so this suite never collides with a
    dev server you might already have running, and tears it down afterward.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--port", str(PORT)],
        cwd=str(PROJ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError(f"live server on port {PORT} never came up")

    yield

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(autouse=True)
def clean_db():
    """Same database file the live server itself uses (data/harborclaim.db)
    -- there's no separate test database (see STATUS.md for the known
    tradeoff this shares with test_app.py). Reset before every test so UI
    tests don't see claims left over from a previous test or a manual
    click-through session.
    """
    storage.init_db()
    storage.reset()
    storage.get_or_create_user("ui.claimant@example.com", "UI Test Claimant")
    yield


def _claimant_cookie_header() -> dict:
    signer = itsdangerous.TimestampSigner(os.environ["SESSION_SECRET_KEY"])
    payload = base64.b64encode(json.dumps({"user_email": "ui.claimant@example.com"}).encode())
    return {"name": "session", "value": signer.sign(payload).decode(), "domain": "127.0.0.1", "path": "/"}


def _relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG relative luminance -- used below to actually measure contrast,
    not just eyeball a screenshot. This is the exact kind of check that
    would have caught the mock-card-on-dark-theme bug automatically.
    """
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = channel(r), channel(g), channel(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(rgb_a: tuple, rgb_b: tuple) -> float:
    l1, l2 = _relative_luminance(*rgb_a), _relative_luminance(*rgb_b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _parse_rgb(css_rgb: str) -> tuple:
    nums = css_rgb.replace("rgba(", "").replace("rgb(", "").replace(")", "").split(",")
    return tuple(int(float(n)) for n in nums[:3])


def test_signed_out_page_shows_the_google_sign_in_button(page):
    page.goto(BASE)
    assert page.get_by_text("Sign in with Google").is_visible()


def test_full_claimant_flow_with_a_real_file_upload(page):
    page.context.add_cookies([_claimant_cookie_header()])
    page.goto(BASE)
    page.fill("#policy_id", "POL-UI-1")
    page.fill("#incident_date", "2026-09-10")
    page.fill("#description", "Rear-end collision, minor damage.")
    page.set_input_files("#files", [str(PROJ / "sample_data" / "police_report_sample.pdf")])
    page.click("button.primary")
    page.wait_for_url(f"{BASE}/claims/*")

    assert page.get_by_text("READY_FOR_REVIEW").is_visible()
    assert page.get_by_text("MOCK -- not AI-generated").is_visible()
    assert page.get_by_text("MOCK -- plain regex, not AI").is_visible()
    # The extraction actually ran, not just the mock label -- a real value
    # pulled from the real sample PDF's text should be in the facts table.
    # "Collision" appears twice on the page (summary prose + facts table),
    # so scope to the table specifically rather than a bare text search.
    assert page.locator("table.facts-table").get_by_text("Collision").first.is_visible()


def test_validation_error_is_visible_and_input_values_survive(page):
    page.context.add_cookies([_claimant_cookie_header()])
    page.goto(BASE)
    page.fill("#policy_id", "P" * 50)
    page.fill("#incident_date", "2026-09-10")
    page.fill("#description", "Should not be submitted.")
    page.click("button.primary")

    assert page.get_by_text("Please fix the following").is_visible()
    assert page.get_by_text("too long").is_visible()
    assert page.locator("#incident_date").input_value() == "2026-09-10"
    assert page.locator("#description").input_value() == "Should not be submitted."


def test_real_adjuster_login_flow(page):
    password = storage.create_adjuster("ui.adjuster", "UI Test Adjuster")
    page.goto(f"{BASE}/adjuster/login")
    page.fill("#username", "ui.adjuster")
    page.fill("#password", password)
    page.click("button.primary")
    page.wait_for_url(f"{BASE}/adjuster")

    assert page.get_by_text("Needs attention").is_visible()
    # "ui.adjuster" also appears inside the subtitle prose ("...because
    # ui.adjuster has a provisioned adjuster account...") -- scope to the
    # nav's identity hint specifically rather than a bare text search.
    assert page.locator("header.app-header span.hint", has_text="ui.adjuster").is_visible()


def test_claimant_route_is_unreachable_with_only_an_adjuster_session(page):
    # File a claim as a claimant in one browser context...
    claimant_ctx = page.context
    claimant_ctx.add_cookies([_claimant_cookie_header()])
    page.goto(BASE)
    page.fill("#policy_id", "POL-UI-SEP")
    page.fill("#incident_date", "2026-09-11")
    page.fill("#description", "x")
    page.set_input_files("#files", [str(PROJ / "sample_data" / "theft_report_sample.pdf")])
    page.click("button.primary")
    page.wait_for_url(f"{BASE}/claims/*")
    claim_url = page.url
    claim_id = claim_url.rsplit("/", 1)[-1]

    # ...then, with no claimant cookie in a fresh context, confirm an
    # adjuster-only session can't open that claimant URL at all.
    adjuster_page = page.context.browser.new_page()
    password = storage.create_adjuster("sep.ui.adjuster")
    adjuster_page.goto(f"{BASE}/adjuster/login")
    adjuster_page.fill("#username", "sep.ui.adjuster")
    adjuster_page.fill("#password", password)
    adjuster_page.click("button.primary")
    adjuster_page.wait_for_url(f"{BASE}/adjuster")

    # /claims/{id} with no claimant session redirects to /auth/login, which
    # itself immediately redirects to real accounts.google.com -- block that
    # external hop so the test never actually depends on a live Google
    # round trip, and check what actually matters: the claim's own content
    # is never exposed, regardless of exactly where the redirect chain ends.
    adjuster_page.route("https://accounts.google.com/**", lambda route: route.abort())
    try:
        adjuster_page.goto(f"{BASE}/claims/{claim_id}")
    except Exception:
        pass
    assert "POL-UI-SEP" not in adjuster_page.content()
    adjuster_page.close()


def test_mock_card_text_is_actually_readable_on_the_adjuster_dark_theme(page):
    """Regression test for a real bug found this session: .mock-card has a
    fixed cream background, and the adjuster theme redefines --ink to a
    near-white meant for a navy background -- combined, the mock card's text
    was nearly invisible. This measures actual rendered contrast instead of
    relying on a human looking at a screenshot.
    """
    claimant_ctx = page.context
    claimant_ctx.add_cookies([_claimant_cookie_header()])
    page.goto(BASE)
    page.fill("#policy_id", "POL-UI-CONTRAST")
    page.fill("#incident_date", "2026-09-12")
    page.fill("#description", "x")
    page.set_input_files("#files", [str(PROJ / "sample_data" / "repair_estimate_sample.pdf")])
    page.click("button.primary")
    page.wait_for_url(f"{BASE}/claims/*")
    claim_id = page.url.rsplit("/", 1)[-1]

    adjuster_page = page.context.browser.new_page()
    password = storage.create_adjuster("contrast.ui.adjuster")
    adjuster_page.goto(f"{BASE}/adjuster/login")
    adjuster_page.fill("#username", "contrast.ui.adjuster")
    adjuster_page.fill("#password", password)
    adjuster_page.click("button.primary")
    adjuster_page.wait_for_url(f"{BASE}/adjuster")

    adjuster_page.goto(f"{BASE}/adjuster/claims/{claim_id}")
    adjuster_page.wait_for_selector(".mock-card")

    colors = adjuster_page.eval_on_selector(
        ".mock-card p",
        "el => { const s = getComputedStyle(el); return [s.color, getComputedStyle(el.closest('.mock-card')).backgroundColor]; }",
    )
    text_rgb = _parse_rgb(colors[0])
    bg_rgb = _parse_rgb(colors[1])
    ratio = _contrast_ratio(text_rgb, bg_rgb)

    # WCAG AA for normal-size body text is 4.5:1. The pre-fix version of
    # this page measured well under 2:1 here.
    assert ratio >= 4.5, f"mock-card text contrast is only {ratio:.2f}:1 (text={text_rgb}, bg={bg_rgb})"
    adjuster_page.close()


def test_adjuster_decision_round_trip_is_visible_in_the_browser(page):
    claimant_ctx = page.context
    claimant_ctx.add_cookies([_claimant_cookie_header()])
    page.goto(BASE)
    page.fill("#policy_id", "POL-UI-DECIDE")
    page.fill("#incident_date", "2026-09-13")
    page.fill("#description", "x")
    page.set_input_files("#files", [str(PROJ / "sample_data" / "water_damage_notes_sample.pdf")])
    page.click("button.primary")
    page.wait_for_url(f"{BASE}/claims/*")
    claim_id = page.url.rsplit("/", 1)[-1]

    adjuster_page = page.context.browser.new_page()
    password = storage.create_adjuster("decide.ui.adjuster")
    adjuster_page.goto(f"{BASE}/adjuster/login")
    adjuster_page.fill("#username", "decide.ui.adjuster")
    adjuster_page.fill("#password", password)
    adjuster_page.click("button.primary")
    adjuster_page.wait_for_url(f"{BASE}/adjuster")

    adjuster_page.goto(f"{BASE}/adjuster/claims/{claim_id}")
    adjuster_page.click("button[value='NEEDS_MORE_REVIEW']")
    adjuster_page.wait_for_load_state("networkidle")
    assert adjuster_page.get_by_text("Needs More Review", exact=False).is_visible()
    adjuster_page.close()

    page.goto(f"{BASE}/claims/{claim_id}")
    assert page.get_by_text("NEEDS_MORE_REVIEW").is_visible()
