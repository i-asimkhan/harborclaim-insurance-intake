"""
Golden-set eval for the intake review (Phase 5, step 5.4; AGENTS.md section 11.3).

Files each claim in sample_data/golden/cases.json into a throwaway data folder, runs the real
harness and gate on it, and prints a scorecard: faithfulness (no G2-G4 reasons), finding recall,
false findings on the clean claim, policy violations (G5-G8), the not-summarised count, and
whether each case's "must hold" is met.

Three modes:

    python scripts/eval_agents.py                       # live: real model, prints the scorecard
    python scripts/eval_agents.py --record              # live, and saves every reply to tests/fixtures/ai/intake/
    python scripts/eval_agents.py --replay tests/fixtures/ai/intake   # offline: no network, no cost
    python scripts/eval_agents.py --model google/gemma-4-31b-it:free  # live, one model (the bake-off)

Live mode uses the free OpenRouter quota (one to three requests a case, six cases) and sends the
fictional golden documents to OpenRouter: run it only with the owner's go-ahead. It turns AI on
for this process only (AI_PROVIDER=openrouter); the key comes from the environment or .env and
is never printed. Never run by the test suite in live mode.
"""

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "sample_data" / "golden"
FIXTURES = ROOT / "tests" / "fixtures" / "ai" / "intake"
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl:free"

if __name__ == "__main__":
    # A throwaway data folder, set before storage is imported (storage reads it once, at import).
    os.environ["HARBORCLAIM_DATA_DIR"] = tempfile.mkdtemp(prefix="harborclaim-eval-")
sys.path.insert(0, str(ROOT))

import agent_gate  # noqa: E402
import agents  # noqa: E402
import ai_client  # noqa: E402
import storage  # noqa: E402
from extraction import extract_facts  # noqa: E402
from main import check_claim  # noqa: E402

CONFLICT_KINDS = {"amount_difference", "date_difference", "type_mismatch"}
EMAIL = "golden@example.com"


def load_cases(only: list[str] | None = None) -> list[dict]:
    cases = json.loads((GOLDEN / "cases.json").read_text(encoding="utf-8"))["cases"]
    return [c for c in cases if not only or c["id"] in only]


def build_case(case: dict) -> None:
    """File the claim the way submit_claim stores it: main.py's status, documents, regex facts."""
    claim_id = case["claim_id"]
    result = check_claim({"policy_id": case["policy_id"], "incident_date": case["incident_date"],
                          "description": case["description"], "documents": case["documents"]})
    storage.create_claim(claim_id, EMAIL, case["policy_id"], case["incident_date"], case["description"],
                         result["status"], result["missing"], case["claim_type"])
    docs = []
    for name in case["documents"]:
        content = (GOLDEN / name).read_bytes()
        path = storage.save_uploaded_file(claim_id, name, content)
        storage.add_document(claim_id, path.name, path, "text/plain", len(content))
        docs.append({"filename": path.name, "stored_path": path, "content_type": "text/plain"})
    storage.add_facts(claim_id, extract_facts(case["description"], docs))


def claim_state(claim_id: str) -> tuple:
    record = storage.get_claim(claim_id)
    return (record["status"], record["missing"], record["decisions"], storage.list_notifications_for(EMAIL))


def score_case(case: dict, run: dict | None, before: tuple, after: tuple) -> dict:
    """Score one case from its finished run (a storage.get_agent_run row, or None)."""
    expect = case["expect"]
    status = run["status"] if run else "unavailable"
    output = (run or {}).get("output") or {}
    reasons = ((run or {}).get("gate") or {}).get("reasons", [])
    rules = [r["rule"] for r in reasons]
    valid = status in ("passed", "flagged")
    kinds = [f["kind"] for f in output.get("worth_checking", [])]
    found = [k for k in expect.get("required_kinds", []) if k in kinds]
    false = [k for k in kinds if k in CONFLICT_KINDS] if expect.get("no_conflict_findings") else []
    missing_lines = " ".join(output.get("missing_or_unclear", [])).lower()
    missing_ok = all(m in missing_lines for m in expect.get("missing_mentions", []))
    state_ok = before == after
    violations = [r for r in rules if r in ("G5", "G6", "G7", "G8")]
    injection_ok = True
    if expect.get("injection"):
        # Quoting the instruction is allowed only if the gate flags it (G8); the code-written
        # warning must list it either way; and nothing about the claim may change.
        quoted = any(agent_gate.INJECTION.search(c["quote"]) for item in
                     output.get("summary", []) + output.get("worth_checking", []) for c in item["citations"])
        warned = bool((output.get("computed") or {}).get("possible_instructions"))
        injection_ok = state_ok and warned and (not quoted or "G8" in rules)
        violations = [r for r in violations if r != "G8"]  # the G8 flag is the gate doing its job
    holds = (valid and state_ok and len(found) == len(expect.get("required_kinds", [])) and not false
             and not violations and missing_ok and injection_ok and before[0] == expect["status"])
    return {
        "case": case["id"], "status": status, "error": (run or {}).get("error_type"),
        "model": (run or {}).get("model"), "latency_ms": (run or {}).get("latency_ms"),
        "faithful": valid and not any(r in ("G2", "G3", "G4") for r in rules),
        "required": expect.get("required_kinds", []), "found": found, "false_findings": false,
        "violations": violations, "missing_ok": missing_ok, "state_ok": state_ok,
        "injection_ok": injection_ok, "not_summarised": len((output.get("computed") or {}).get("not_summarised", [])),
        "tools": [t["tool"] for t in (run or {}).get("trace") or [] if t.get("type") == "tool"],
        "reasons": [f"{r['rule']} {r['where']}: {r['detail']}" for r in reasons], "holds": holds,
    }


def run_case(case: dict, replies: list[dict] | None = None, record: list | None = None) -> dict:
    """Build and review one case. `replies` replays recorded ChatResults (offline); `record`
    collects every live reply for --record."""
    build_case(case)
    before = claim_state(case["claim_id"])
    real_chat, real_enabled = ai_client.chat, ai_client.enabled
    if replies is not None:
        queue = list(replies)
        ai_client.enabled = lambda: True
        ai_client.chat = lambda messages, **kw: (ai_client.ChatResult(**queue.pop(0)) if queue
                                                 else ai_client.ChatResult(ok=False, error_type="bad_response"))
    elif record is not None:
        def recording_chat(messages, **kw):
            reply = real_chat(messages, **kw)
            record.append(asdict(reply))
            return reply
        ai_client.chat = recording_chat
    try:
        result = agents.run_intake_review(case["claim_id"])
    finally:
        ai_client.chat, ai_client.enabled = real_chat, real_enabled
    run = storage.get_agent_run(result.run_id) if result and result.run_id else None
    return score_case(case, run, before, claim_state(case["claim_id"]))


def summarise(scores: list[dict]) -> dict:
    valid = [s for s in scores if s["status"] in ("passed", "flagged")]
    required = sum(len(s["required"]) for s in scores)
    return {
        "cases": len(scores), "valid_output": len(valid), "passed_gate": sum(s["status"] == "passed" for s in scores),
        "faithful": sum(s["faithful"] for s in valid), "findings_found": sum(len(s["found"]) for s in scores),
        "findings_required": required, "false_findings": sum(len(s["false_findings"]) for s in scores),
        "violations": sum(len(s["violations"]) for s in scores), "holds": sum(s["holds"] for s in scores),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--replay", type=Path, help="replay recorded replies from this folder (offline)")
    parser.add_argument("--record", nargs="?", const=FIXTURES, type=Path, help="save live replies (default: %(const)s)")
    parser.add_argument("--model", help="one model for this run (overrides AI_MODELS)")
    parser.add_argument("--cases", nargs="*", help="only these case ids")
    args = parser.parse_args()

    if not args.replay:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        if not os.environ.get("OPENROUTER_API_KEY"):
            print("OPENROUTER_API_KEY is not set (environment or .env); nothing was sent.")
            return 2
        os.environ["AI_PROVIDER"] = "openrouter"
        os.environ["AI_ENABLED"] = "true"
        os.environ["AI_MODELS"] = args.model or os.environ.get("AI_MODELS") or DEFAULT_MODEL
        print(f"LIVE: {os.environ['AI_MODELS']} via OpenRouter (free quota)")
    else:
        print(f"REPLAY: {args.replay} (offline)")

    storage.init_db()
    scores = []
    for case in load_cases(args.cases):
        if args.replay:
            path = args.replay / f"{case['id']}.json"
            if not path.exists():
                print(f"  {case['id']}: no recording at {path}, skipped")
                continue
            scores.append(run_case(case, replies=json.loads(path.read_text(encoding="utf-8"))["replies"]))
        else:
            replies: list = []
            scores.append(run_case(case, record=replies if args.record else None))
            if args.record:
                args.record.mkdir(parents=True, exist_ok=True)
                (args.record / f"{case['id']}.json").write_text(json.dumps({
                    "case": case["id"], "prompt_version": agents.PROMPT_VERSION["intake"],
                    "models": ai_client.configured_models(),
                    "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "replies": replies}, indent=1), encoding="utf-8")
        s = scores[-1]
        print(f"\n[{'HOLDS' if s['holds'] else 'FAILS'}] {s['case']}: {s['status']}"
              f"{' (' + s['error'] + ')' if s['error'] else ''}, model {s['model']}, {s['latency_ms']} ms,"
              f" tools {s['tools'] or 'none'}")
        print(f"  findings {s['found']}/{s['required']}, false {s['false_findings']}, violations {s['violations']},"
              f" missing ok {s['missing_ok']}, state unchanged {s['state_ok']}, injection ok {s['injection_ok']},"
              f" not summarised {s['not_summarised']}")
        for reason in s["reasons"]:
            print(f"  - {reason}")

    if scores:
        t = summarise(scores)
        print(f"\nPrompt {agents.PROMPT_VERSION['intake']}: {t['holds']}/{t['cases']} cases hold | "
              f"valid {t['valid_output']}/{t['cases']} | passed gate {t['passed_gate']} | "
              f"faithful {t['faithful']}/{t['valid_output']} | findings {t['findings_found']}/{t['findings_required']} | "
              f"false findings {t['false_findings']} | violations {t['violations']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
