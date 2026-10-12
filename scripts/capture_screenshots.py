#!/usr/bin/env python
"""
Regenerates docs/screenshots/*.png from a real, running instance of the app.

This is the script tests/test_ui.py's module docstring refers to as
"the same way as the documentation screenshots (scripts/*)" -- it existed
before but was never actually committed to this repo, which left that
docstring pointing at nothing. This is that script, for real, so the claim
is true and the screenshots stay reproducible instead of hand-captured and
forgotten about.

Uses the same session-cookie-injection technique as tests/test_ui.py and
sample_data/seed_demo_data.py (a real, properly-signed cookie built with
SESSION_SECRET_KEY) rather than a real Google OAuth round trip, so this
runs headlessly with no interactive sign-in.

Usage:
    .venv/Scripts/python.exe -m playwright install chromium   # once
    .venv/Scripts/python.exe scripts/capture_screenshots.py [name ...]

With no arguments, regenerates every screenshot this script knows how to
produce. With one or more names (e.g. `03-claim-result-ready`), regenerates
only those -- useful after a UI wording change touches just a few pages
instead of the whole set.
"""

import base64
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path(__file__).parent.parent
PORT = 8299
BASE = f"http://127.0.0.1:{PORT}"
OUT_DIR = PROJ / "docs" / "screenshots"

sys.path.insert(0, str(PROJ))
os.chdir(PROJ)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJ / ".env")

import itsdangerous  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import storage  # noqa: E402

CLAIMANT_EMAIL = "demo.claimant@example.com"
ADJUSTER_USERNAME = "d.reyes"


def _cookie(session_data: dict) -> dict:
    signer = itsdangerous.TimestampSigner(os.environ["SESSION_SECRET_KEY"])
    payload = base64.b64encode(json.dumps(session_data).encode())
    return {
        "name": "session",
        "value": signer.sign(payload).decode(),
        "domain": "127.0.0.1",
        "path": "/",
    }


def _claimant_cookie() -> dict:
    return _cookie({"user_email": CLAIMANT_EMAIL})


def _adjuster_cookie() -> dict:
    return _cookie({"adjuster_username": ADJUSTER_USERNAME})


def start_server():
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
    return proc


def seed():
    storage.init_db()
    storage.reset()
    storage.get_or_create_user(CLAIMANT_EMAIL, "Demo Claimant")
    storage.create_adjuster(ADJUSTER_USERNAME, "D. Reyes")


def submit_claim(page, *, policy_id, incident_date, description, files):
    page.goto(BASE)
    page.fill("#policy_id", policy_id)
    if incident_date:
        page.fill("#incident_date", incident_date)
    page.fill("#description", description)
    if files:
        page.set_input_files("#files", files)
    page.click("button.primary")
    page.wait_for_url(f"{BASE}/claims/*")
    return page.url.rsplit("/", 1)[-1]


def shot(page, name: str):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT_DIR / f"{name}.png"), full_page=True)
    print(f"  wrote {name}.png")


def run(selected: set[str] | None):
    def wanted(name: str) -> bool:
        return selected is None or name in selected

    proc = start_server()
    try:
        seed()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})

            # Two claimant submissions, same scenario every run: one
            # complete (READY_FOR_REVIEW), one missing incident_date
            # (NEEDS_INFORMATION) -- mirrors the build guide's own
            # normal/failure demonstration pair.
            page.context.add_cookies([_claimant_cookie()])

            ready_id = submit_claim(
                page,
                policy_id="POL-48213",
                incident_date="2026-09-10",
                description=(
                    "Rear-end collision in a parking lot near the office. "
                    "Minor bumper and taillight damage."
                ),
                files=[
                    str(PROJ / "sample_data" / "police_report_sample.pdf"),
                    str(PROJ / "sample_data" / "repair_estimate_sample.pdf"),
                ],
            )
            if wanted("03-claim-result-ready"):
                shot(page, "03-claim-result-ready")

            needs_info_id = submit_claim(
                page,
                policy_id="POL-77410",
                incident_date="",
                description="Kitchen fire, water damage to adjoining room.",
                files=[str(PROJ / "sample_data" / "water_damage_notes_sample.pdf")],
            )
            if wanted("04-claim-result-needs-information"):
                shot(page, "04-claim-result-needs-information")

            if wanted("06-notifications"):
                page.goto(f"{BASE}/notifications")
                shot(page, "06-notifications")

            # Switch to the adjuster role in the same browser context --
            # the session cookie can hold both roles' keys at once, same
            # as a real browser that signed in as both.
            page.context.add_cookies([_adjuster_cookie()])

            if wanted("09-adjuster-claim-view"):
                page.goto(f"{BASE}/adjuster/claims/{ready_id}")
                shot(page, "09-adjuster-claim-view")

            if wanted("10-adjuster-decision-recorded"):
                page.get_by_role("button", name="Approved").click()
                page.wait_for_selector("text=Decisions recorded")
                shot(page, "10-adjuster-decision-recorded")

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    args = sys.argv[1:]
    run(set(args) if args else None)
