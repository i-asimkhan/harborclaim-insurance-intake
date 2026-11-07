"""
Writes PROMPTS.md from the code, so the submitted prompts are exactly the ones the app sends.

For each agent: the system prompt, the output schema, the tools it may call and its limits; then
the fixed replies written by code and the gate's rules. tests/test_agents.py fails if PROMPTS.md
is out of date, so change a prompt in agents.py, then run:

    python scripts/export_prompts.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent_gate  # noqa: E402
import agents  # noqa: E402
import ai_client  # noqa: E402

OUT = ROOT / "PROMPTS.md"

TITLES = {
    "intake": "Intake review (adjuster claim page)",
    "adjuster": "Ask about this claim (adjuster)",
    "claimant": "Ask a question (claimant, /help)",
    "request": "Request missing information (adjuster drafts with AI, edits and sends)",
}


def _fence(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text.rstrip()}\n```"


def render() -> str:
    parts = [
        "# HarborClaim prompts",
        "",
        "Generated from `agents.py`, `agent_gate.py` and `ai_client.py` by "
        "`python scripts/export_prompts.py`; do not edit by hand. The design behind them is "
        "`docs/design/AGENTS.md`; the test results are in `AI_USAGE.md`.",
        "",
        "## Models",
        "",
        "Free open-weight models on OpenRouter, temperature 0, in the order set by `AI_MODELS` "
        "(the next one answers when one is busy). Tested and configured:",
        "",
    ]
    for name, settings in ai_client.MODEL_SETTINGS.items():
        parts.append(f"- `{name}` -- request settings: `{json.dumps(settings)}`")
    parts += ["", f"Each run: at most {agents.MAX_MODEL_CALLS} model calls and {agents.MAX_TOOL_CALLS} "
              "tool calls. Every tool is read-only.", ""]

    for key, charter in agents.CHARTERS.items():
        parts += [
            f"## {TITLES.get(key, key)}",
            "",
            f"Prompt version `{agents.PROMPT_VERSION[key]}`; at most {charter.max_output_tokens} output "
            f"tokens; default daily limit {charter.default_daily_limit} runs (`{charter.daily_limit_setting}`).",
            "",
            "**System prompt**",
            "",
            _fence(charter.prompt),
            "",
            "**Tools**",
            "",
        ]
        for name, (_, spec) in charter.tools.items():
            fn = spec["function"]
            args = ", ".join(fn.get("parameters", {}).get("properties", {})) or "no arguments"
            parts.append(f"- `{name}` ({args}): {fn.get('description', '')}")
        parts += ["", "**Output schema** (strict JSON)", "", _fence(json.dumps(charter.schema, indent=2), "json"), ""]

    parts += [
        "## Fixed replies (written by code, never by a model)",
        "",
        "Decision and coverage questions are matched by `agents.DECISION_QUESTION` and answered with "
        "these before any model call. A claimant answer that fails the gate is replaced by the "
        "claimant reply.",
        "",
        f"- Adjuster: {agents.ADJUSTER_REFUSAL}",
        f"- Claimant: {agents.CLAIMANT_REFUSAL}",
        f"- Not in the records: {agents.NOT_FOUND}",
        "",
        "## The gate (`agent_gate.py`)",
        "",
        "Every output is checked by these rules before anyone sees it:",
        "",
        _fence(agent_gate.__doc__.strip()),
        "",
    ]
    return "\n".join(parts)


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
