"""
Prints the AI run log (the append-only agent_runs table): who ran what, which model answered,
the gate result, tokens and time. Read-only; no model call. Run: python scripts/show_ai_runs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import storage  # noqa: E402

with storage._connect() as conn:
    rows = conn.execute(
        """SELECT id, started_at, agent, claim_id, actor, status, error_type, model, prompt_version,
                  input_tokens, output_tokens, latency_ms, question
           FROM agent_runs ORDER BY id DESC LIMIT 30""").fetchall()

today = storage.agent_runs_today
print(f"Today (UTC): intake {today('intake')}, adjuster {today('adjuster')}, claimant {today('claimant')} runs\n")
for r in rows:
    secs = f"{(r['latency_ms'] or 0) / 1000:.1f}s"
    tokens = f"{r['input_tokens'] or 0}/{r['output_tokens'] or 0} tok"
    status = r["status"] + (f" ({r['error_type']})" if r["error_type"] else "")
    print(f"#{r['id']:<4} {r['started_at'][:19]}  {r['agent']:<8} {r['claim_id'] or '-':<13} {status:<24} "
          f"{r['model'] or '-'}  {r['prompt_version']}  {tokens}  {secs}  by {r['actor']}")
    if r["question"]:
        print(f"      Q: {r['question'][:100]}")
