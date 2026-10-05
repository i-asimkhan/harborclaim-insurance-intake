#!/usr/bin/env python
"""
Seeds a running HarborClaim instance with the fictional scenarios in
claims.json -- via real HTTP requests against a live server, not inserted
directly into the database. Every claim really goes through
POST /claims (the completeness checker, validation.py, extraction.py,
summary.py, the notification stub) exactly as a real browser submission
would; every decision really goes through POST /adjuster/claims/{id}/decision
(including the separation-of-duties check). There is no shortcut pipeline
that bypasses the real logic just because the data is fictional.

Session cookies are injected (signed with the real SESSION_SECRET_KEY --
the same technique used for the documentation screenshots and tests/test_ui.py)
rather than requiring five real Google sign-ins or memorizing a generated
adjuster password on every run. That's what makes this script safely
re-runnable: it never needs to recall a secret from a previous run.

Usage (server must already be running separately):
    .venv/Scripts/python.exe -m uvicorn app:app --port 8123 &
    .venv/Scripts/python.exe sample_data/seed_demo_data.py [--reset] [--base-url URL]
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).parent.parent
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJ / ".env")

import httpx  # noqa: E402
import itsdangerous  # noqa: E402

import storage  # noqa: E402

DATA = json.loads((PROJ / "sample_data" / "claims.json").read_text(encoding="utf-8"))
SEED_ADJUSTER_USERNAME = "demo.seed.adjuster"


def _cookie(session_data: dict) -> str:
    signer = itsdangerous.TimestampSigner(os.environ["SESSION_SECRET_KEY"])
    return signer.sign(base64.b64encode(json.dumps(session_data).encode())).decode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8123")
    parser.add_argument("--reset", action="store_true", help="Wipe the database before seeding.")
    args = parser.parse_args()

    storage.init_db()
    if args.reset:
        storage.reset()
        print("Database reset.")

    if storage.get_adjuster(SEED_ADJUSTER_USERNAME) is None:
        storage.create_adjuster(SEED_ADJUSTER_USERNAME, "Demo Seed Adjuster")
        print(f"Provisioned adjuster account: {SEED_ADJUSTER_USERNAME}")

    claimant_emails = {s["claimant_email"] for s in DATA["scenarios"]} | {
        v["claimant_email"] for v in DATA["validation_failures"]
    }
    for email in claimant_emails:
        storage.get_or_create_user(email, email.split("@")[0].replace(".", " ").title())

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        try:
            client.get("/")
        except httpx.ConnectError:
            print(f"Could not reach {args.base_url} -- is the server running?", file=sys.stderr)
            sys.exit(1)

        print("\n=== Seeding scenarios (real POST /claims, real pipeline) ===")
        seeded = 0
        for s in DATA["scenarios"]:
            client.cookies.set("session", _cookie({"user_email": s["claimant_email"]}))
            files = [
                ("files", (name, (PROJ / "sample_data" / name).read_bytes(), "application/pdf"))
                for name in s["documents"]
            ]
            resp = client.post(
                "/claims",
                data={
                    "policy_id": s["policy_id"],
                    "incident_date": s["incident_date"],
                    "description": s["description"],
                },
                files=files or None,
                follow_redirects=False,
            )
            if resp.status_code != 303:
                print(f"  [FAIL] {s['id']}: expected 303 redirect, got {resp.status_code}")
                continue
            claim_id = resp.headers["location"].rsplit("/", 1)[-1]

            decision = s.get("adjuster_decision")
            if decision:
                client.cookies.set("session", _cookie({"adjuster_username": SEED_ADJUSTER_USERNAME}))
                dresp = client.post(
                    f"/adjuster/claims/{claim_id}/decision", data={"decision": decision}, follow_redirects=False
                )
                if dresp.status_code != 303:
                    print(f"  [FAIL] {s['id']}: decision POST expected 303, got {dresp.status_code}")

            record = storage.get_claim(claim_id)
            actual_status = record["status"]
            match = "OK" if actual_status == s["expected_status"] else "MISMATCH"
            seeded += 1
            print(
                f"  [{match}] {s['id']:<32} -> {claim_id}  "
                f"status={actual_status:<17} decision={decision or '-'}"
            )

        print("\n=== Confirming validation failures are actually rejected (not seeded) ===")
        all_rejected = True
        for v in DATA["validation_failures"]:
            client.cookies.set("session", _cookie({"user_email": v["claimant_email"]}))
            files = []
            for name in v["documents"]:
                path = PROJ / "sample_data" / name
                content = path.read_bytes() if path.exists() else b"placeholder bytes, content is irrelevant here"
                files.append(("files", (name, content, "application/octet-stream")))
            resp = client.post(
                "/claims",
                data={
                    "policy_id": v["policy_id"],
                    "incident_date": v["incident_date"],
                    "description": v["description"],
                },
                files=files or None,
                follow_redirects=False,
            )
            ok = resp.status_code == v["expect_http_status"] and v["expect_error_contains"] in resp.text
            all_rejected = all_rejected and ok
            print(f"  [{'OK' if ok else 'FAIL'}] {v['id']:<24} -> HTTP {resp.status_code} (expected {v['expect_http_status']})")

    claimants = {s["claimant_email"] for s in DATA["scenarios"]}
    print(f"\n=== Done. Seeded {seeded}/{len(DATA['scenarios'])} claims across {len(claimants)} claimants. ===")
    if not all_rejected:
        print("WARNING: at least one validation-failure case was NOT rejected as expected -- see FAIL lines above.")
    print(f"Sign in as the adjuster ({SEED_ADJUSTER_USERNAME}) to browse a populated queue:")
    print("  No password to give you here -- the seed script authenticated by injecting a signed")
    print("  session cookie, not a real password. For an interactive login, provision a fresh")
    print("  adjuster yourself: storage.create_adjuster('your.username', 'Your Name')")
    print(f"Or sign in as any seeded claimant ({', '.join(sorted(claimants))}) via real Google OAuth")
    print("  to see their own claims (Google only knows real email addresses it can authenticate --")
    print("  these fictional ones won't actually let you sign in that way; use the cookie-injection")
    print("  technique in tests/test_ui.py if you need to view a seeded claimant's pages directly).")


if __name__ == "__main__":
    main()
