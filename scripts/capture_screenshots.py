#!/usr/bin/env python
"""
Regenerates docs/screenshots/*.png from a real, running instance of the app.

This is the script tests/test_ui.py's module docstring refers to as
"the same way as the documentation screenshots (scripts/*)".

Claimant sign-in uses the same session-cookie-injection technique as
tests/test_ui.py and sample_data/seed_demo_data.py (a real, properly-signed
cookie built with SESSION_SECRET_KEY), since a Google OAuth round trip can't
run headlessly. Adjuster sign-in goes through the real login form, so the
login audit trail on the adjuster notifications page shows a real event.

Usage:
    .venv/Scripts/python.exe -m playwright install chromium   # once
    .venv/Scripts/python.exe scripts/capture_screenshots.py [name ...]

With no arguments, regenerates all 13 screenshots. With one or more names
(e.g. `03-claim-result-ready`), the full flow still runs -- later pages depend
on earlier ones -- but only those files are written.

Wipes the local database (data/) first, like tests/test_ui.py does.
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
SAMPLE = PROJ / "sample_data"

sys.path.insert(0, str(PROJ))
os.chdir(PROJ)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJ / ".env")

import itsdangerous  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import storage  # noqa: E402

CLAIMANT_EMAIL = "demo.claimant@example.com"
ADJUSTER_USERNAME = "d.reyes"
SEEDED_QUEUE_ADJUSTER = "a.irving"

READY_CLAIM = {
    "claim_type": "auto",
    "policy_id": "POL-48213",
    "incident_date": "2026-09-10",
    "description": (
        "Rear-end collision in a parking lot near the office. Minor bumper and taillight damage."
    ),
    "files": [SAMPLE / "police_report_sample.pdf", SAMPLE / "repair_estimate_sample.pdf"],
}
NEEDS_INFO_CLAIM = {
    "claim_type": "property",
    "policy_id": "POL-77410",
    "incident_date": "",
    "description": "Kitchen fire, water damage to adjoining room.",
    "files": [SAMPLE / "water_damage_notes_sample.pdf"],
}

ALL = [
    "01-signed-out",
    "02-new-claim-filled",
    "03-claim-result-ready",
    "04-claim-result-needs-information",
    "05-my-claims",
    "06-notifications",
    "07-adjuster-login",
    "08-adjuster-queue",
    "09-adjuster-claim-view",
    "10-adjuster-decision-recorded",
    "11-adjuster-notifications",
    "12-validation-errors",
    "13-seeded-adjuster-queue",
]


def _claimant_cookie() -> dict:
    signer = itsdangerous.TimestampSigner(os.environ["SESSION_SECRET_KEY"])
    payload = base64.b64encode(json.dumps({"user_email": CLAIMANT_EMAIL}).encode())
    return {"name": "session", "value": signer.sign(payload).decode(), "domain": "127.0.0.1", "path": "/"}


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
                return proc
        except OSError:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError(f"live server on port {PORT} never came up")


def fill_claim_form(page, claim):
    page.goto(BASE)
    page.select_option("#claim_type", claim["claim_type"])
    page.fill("#policy_id", claim["policy_id"])
    if claim["incident_date"]:
        page.fill("#incident_date", claim["incident_date"])
    page.fill("#description", claim["description"])
    page.set_input_files("#files", [str(f) for f in claim["files"]])


def submit(page):
    page.click("button.primary")
    page.wait_for_url(f"{BASE}/claims/*")
    return page.url.rsplit("/", 1)[-1]


def adjuster_login(page, username, password):
    page.goto(f"{BASE}/adjuster/login")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button.primary")
    page.wait_for_url(f"{BASE}/adjuster")


def run(selected: set[str]):
    def shot(page, name):
        if name in selected:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(OUT_DIR / f"{name}.png"), full_page=True)
            print(f"  wrote {name}.png")

    storage.init_db()
    storage.reset()
    storage.get_or_create_user(CLAIMANT_EMAIL, "Demo Claimant")
    adjuster_password = storage.create_adjuster(ADJUSTER_USERNAME, "D. Reyes")

    proc = start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            viewport = {"width": 1280, "height": 900}

            # --- Signed out: claimant landing page and the separate adjuster login ---
            page = browser.new_page(viewport=viewport)
            page.goto(BASE)
            shot(page, "01-signed-out")
            page.goto(f"{BASE}/adjuster/login")
            shot(page, "07-adjuster-login")
            page.close()

            # --- Claimant: one complete claim, one missing its incident date ---
            claimant = browser.new_page(viewport=viewport)
            claimant.context.add_cookies([_claimant_cookie()])
            fill_claim_form(claimant, READY_CLAIM)
            shot(claimant, "02-new-claim-filled")
            ready_id = submit(claimant)
            shot(claimant, "03-claim-result-ready")

            fill_claim_form(claimant, NEEDS_INFO_CLAIM)
            submit(claimant)
            shot(claimant, "04-claim-result-needs-information")

            claimant.goto(f"{BASE}/claims")
            shot(claimant, "05-my-claims")
            claimant.goto(f"{BASE}/notifications")
            shot(claimant, "06-notifications")

            # Rejected before anything is stored, so it doesn't add a claim.
            claimant.goto(BASE)
            claimant.fill("#policy_id", "P" * 50)
            claimant.fill("#incident_date", "2026-09-10")
            claimant.fill("#description", "Testing the validation error display.")
            claimant.click("button.primary")
            claimant.wait_for_selector("text=Please fix the following")
            shot(claimant, "12-validation-errors")
            claimant.close()

            # --- Adjuster: real login, queue, review, decision, notifications ---
            adjuster = browser.new_page(viewport=viewport)
            adjuster_login(adjuster, ADJUSTER_USERNAME, adjuster_password)
            shot(adjuster, "08-adjuster-queue")
            adjuster.goto(f"{BASE}/adjuster/claims/{ready_id}")
            shot(adjuster, "09-adjuster-claim-view")
            adjuster.get_by_role("button", name="Approved").click()
            adjuster.wait_for_selector("text=Decisions recorded")
            shot(adjuster, "10-adjuster-decision-recorded")
            adjuster.goto(f"{BASE}/adjuster/notifications")
            shot(adjuster, "11-adjuster-notifications")
            adjuster.close()

            # --- A fuller queue, from the fictional scenarios in sample_data/claims.json ---
            if "13-seeded-adjuster-queue" in selected:
                subprocess.run(
                    [sys.executable, str(SAMPLE / "seed_demo_data.py"), "--reset", "--base-url", BASE],
                    cwd=str(PROJ), check=True, stdout=subprocess.DEVNULL,
                )
                seeded_password = storage.create_adjuster(SEEDED_QUEUE_ADJUSTER, "A. Irving")
                queue = browser.new_page(viewport=viewport)
                adjuster_login(queue, SEEDED_QUEUE_ADJUSTER, seeded_password)
                shot(queue, "13-seeded-adjuster-queue")
                queue.close()

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    names = set(sys.argv[1:]) or set(ALL)
    unknown = names - set(ALL)
    if unknown:
        sys.exit(f"unknown screenshot name(s): {', '.join(sorted(unknown))}")
    run(names)
