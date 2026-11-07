#!/usr/bin/env python
"""
Screenshots of the Phase 5 AI features, from a real running app and the real model.

Unlike scripts/capture_screenshots.py this one calls the live model, so it spends free
OpenRouter quota: about 12 requests (an intake review, two adjuster and two claimant questions --
one each a decision question answered by code with no model call -- a drafted request, which
calls tools, and a second intake review after the claimant answers it). It needs AI_PROVIDER,
OPENROUTER_API_KEY and AI_MODELS in .env, and asks before sending anything.

    python scripts/capture_ai_screenshots.py

Writes docs/screenshots/20-*.png to 29-*.png. Uses a throwaway data folder, like the other
script, so the data/ folder a dev server is using is never touched. Every AI text in these
screenshots is what the model really returned on that run, labelled as the app labels it.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJ = Path(__file__).parent.parent
_data_dir = tempfile.mkdtemp(prefix="harborclaim-ai-shots-")
os.environ["HARBORCLAIM_DATA_DIR"] = _data_dir
PORT = 8298
BASE = f"http://127.0.0.1:{PORT}"
OUT_DIR = PROJ / "docs" / "screenshots"
DEMO = PROJ / "sample_data" / "demo"

sys.path.insert(0, str(PROJ))
os.chdir(PROJ)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJ / ".env")
os.environ["AI_CLAIMANT_CHAT"] = "true"

import base64  # noqa: E402
import json  # noqa: E402

import itsdangerous  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import storage  # noqa: E402

CLAIMANT_EMAIL = "demo.claimant@example.com"


# The same three helpers as scripts/capture_screenshots.py (importing that script would switch
# this run to its own data folder).
def _claimant_cookie() -> dict:
    signer = itsdangerous.TimestampSigner(os.environ["SESSION_SECRET_KEY"])
    payload = base64.b64encode(json.dumps({"user_email": CLAIMANT_EMAIL}).encode())
    return {"name": "session", "value": signer.sign(payload).decode(), "domain": "127.0.0.1", "path": "/"}


def fill_claim_form(page, claim):
    page.goto(BASE)
    page.click(f"label[for='claim_type_{claim['claim_type']}']")
    page.fill("#policy_id", claim["policy_id"])
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

DEMO_CLAIM = {
    "claim_type": "auto",
    "policy_id": "HC-AUTO-5318",
    "incident_date": "2026-10-27",
    "description": (
        "Another driver rear-ended my 2021 Honda Civic while I was stopped at a red light on Harbor "
        "Avenue at Palm Street on 2026-10-27. The rear bumper, trunk lid and left tail lamp are "
        "damaged. The body shop quoted $3,250.00 to repair it."
    ),
    "files": [DEMO / "bayport_police_report.pdf", DEMO / "bayshore_repair_estimate.pdf"],
}
FALLBACK_CLAIM = {**DEMO_CLAIM, "policy_id": "HC-AUTO-5319"}


def start_server(ai_on: bool):
    env = dict(os.environ, AI_ENABLED="true" if ai_on else "false")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--port", str(PORT)],
                            cwd=str(PROJ), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                return proc
        except OSError:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("server never came up")


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def shot(target, name):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target.screenshot(path=str(OUT_DIR / f"{name}.png"), **({"full_page": True} if hasattr(target, "goto") else {}))
    print(f"  wrote {name}.png")


def ask(page, url, question):
    page.goto(url)
    page.fill(".ai-ask-form input[name=question]", question)
    with page.expect_navigation(timeout=120_000):     # the answer comes back with the redirect
        page.click(".ai-ask-form button")


def main():
    if not os.environ.get("AI_PROVIDER") or not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("AI is not configured in .env (AI_PROVIDER, OPENROUTER_API_KEY): nothing sent.")
    if input("This sends about 12 requests to the free OpenRouter model. Continue? [y/N] ").strip().lower() != "y":
        sys.exit("Nothing sent.")

    storage.init_db()
    storage.reset()
    storage.get_or_create_user(CLAIMANT_EMAIL, "Demo Claimant")
    password = storage.create_adjuster("d.reyes", "D. Reyes")
    viewport = {"width": 1280, "height": 900}

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # 1. AI off: the labelled template fallback, no model call.
        proc = start_server(ai_on=False)
        try:
            claimant = browser.new_page(viewport=viewport)
            claimant.context.add_cookies([_claimant_cookie()])
            fill_claim_form(claimant, FALLBACK_CLAIM)
            fallback_id = submit(claimant)
            adjuster = browser.new_page(viewport=viewport)
            adjuster_login(adjuster, "d.reyes", password)
            adjuster.goto(f"{BASE}/adjuster/claims/{fallback_id}")
            shot(adjuster.locator(".mock-card").first, "26-ai-off-template-fallback")
            browser.close()
        finally:
            stop(proc)

        # 2. AI on: the demo claim, reviewed and questioned by the real model.
        browser = p.chromium.launch()
        proc = start_server(ai_on=True)
        try:
            claimant = browser.new_page(viewport=viewport)
            claimant.context.add_cookies([_claimant_cookie()])
            fill_claim_form(claimant, DEMO_CLAIM)
            claim_id = submit(claimant)

            adjuster = browser.new_page(viewport=viewport)
            adjuster_login(adjuster, "d.reyes", password)
            url = f"{BASE}/adjuster/claims/{claim_id}"
            for _ in range(60):                   # the review runs after the claimant's response
                adjuster.goto(url)
                if adjuster.locator("#ai_review .ai-tag").count():
                    break
                time.sleep(2)
            shot(adjuster, "20-adjuster-claim-with-ai-review")
            shot(adjuster.locator("#ai_review"), "21-ai-intake-review")
            adjuster.locator("#ai_review details.ai-trace summary").first.click()
            shot(adjuster.locator("#ai_review"), "22-ai-review-trace-open")

            ask(adjuster, url, "Should I approve this claim?")
            ask(adjuster, url, "What does the repair estimate total?")
            adjuster.evaluate("document.querySelectorAll('#ask details.ai-qa').forEach(d => d.open = true)")
            shot(adjuster.locator("#ask"), "23-ask-about-this-claim")

            ask(claimant, f"{BASE}/help", "Will my claim be paid?")
            ask(claimant, f"{BASE}/help", "What do I still need to send for my claim?")
            claimant.evaluate("document.querySelectorAll('details.ai-qa').forEach(d => d.open = true)")
            shot(claimant, "24-claimant-ask-a-question")

            # The one action: the request agent drafts, the adjuster sends, the claimant answers.
            adjuster.goto(url)
            with adjuster.expect_navigation(timeout=120_000):
                adjuster.click("#request form.inline-form button")
            if adjuster.locator("#request details.ai-trace summary").count():
                adjuster.locator("#request details.ai-trace summary").first.click()
            shot(adjuster.locator("#request"), "27-request-agent-draft")
            with adjuster.expect_navigation():
                adjuster.click("#request form.request-form button")
            claimant.goto(f"{BASE}/claims/{claim_id}")
            shot(claimant, "28-claimant-sees-request")

            with tempfile.TemporaryDirectory() as tmp:
                photo_log = Path(tmp) / "damage_photo_log.txt"
                photo_log.write_text("Photo log (fictional): four photos of the rear bumper, trunk lid and left "
                                     "tail lamp, taken 2026-10-27 at Harbor Avenue and Palm Street.", encoding="utf-8")
                claimant.set_input_files("#add-documents input[type=file]", str(photo_log))
                claimant.fill("#add-documents textarea", "Photo log attached; the photos are on my phone if needed.")
                with claimant.expect_navigation():
                    claimant.click("#add-documents button")
            adjuster.goto(url)
            shot(adjuster.locator("#request"), "29-request-answered")
            time.sleep(45)                        # let the second intake review (new document) finish

            adjuster.goto(f"{BASE}/adjuster/ai")
            shot(adjuster, "25-adjuster-ai-usage")
            browser.close()
        finally:
            stop(proc)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(_data_dir, ignore_errors=True)
