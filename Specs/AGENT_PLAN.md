# AGENT_PLAN.md — Build the Benchmark Orchestrator Agent

You are an autonomous coding agent (Claude Code or Gemini via OpenCode) working in the
root of a clone of `HughMann01134/Opencode` — an ASR benchmark harness specified in
`asr_benchmark_master_blueprint.md`. A separate remediation pass (`REMEDIATION_PLAN.md`)
should already be complete; if `Code/writer.py` does not yet define module-level
`DETAIL_FIELDS`/`SUMMARY_FIELDS` constants and the CSVs lack `split`/`engine` columns,
STOP and tell the user to run REMEDIATION_PLAN.md first.

## Goal

Add a thin **agent layer** on top of the existing harness: a single new module,
`Code/agent.py`, exposing a CLI (`python -m Code.agent "<natural-language goal>"`).
The agent receives a goal like:

> "Benchmark tiny and medium.en on whatever hardware I have and publish a report."

…and autonomously plans, acts through tools, observes results, recovers from
failures, and finishes — a genuine perceive → plan → act → observe → iterate loop,
per the course's Day-1 agent definition. The existing `Skills/` modules and
`Code/main.py` become the agent's **tools**. Do not rewrite the harness; wrap it.

## Hard constraints (read first)

1. **The LLM never writes code and never gets shell access.** The agent's action
   space is a fixed, whitelisted tool registry (below). The LLM chooses *which*
   tool to call with *which validated arguments*; Python executes it. This is the
   project's read/draft/act governance story — keep it intact.
2. **Human-in-the-loop gates (Action-Allowed tier):** two operations require an
   interactive `y/n` confirmation before executing, exactly like the existing
   pattern in `Skills/gemini_escalation.py::escalate_to_gemini`:
   - any asset download whose estimated size exceeds 1 GB, and
   - `publish_report` **with push enabled** (a `--no-push` publish may run
     unattended). Add a `--yes` CLI flag that pre-approves both, for demo recording.
3. **No secrets in code or logs.** API key comes only from the `GEMINI_API_KEY`
   env var (same as `gemini_escalation.py`). If absent, print a clear message and
   exit 2. Never echo the key. Never write it to any file. The final transcript
   must pass `python Skills/check_no_pii.py path <transcript>`.
4. **Budget caps:** hard limits of `--max-steps` (default 20) LLM turns and
   `--max-retries` (default 2) recovery attempts per failed tool call. On
   exhaustion, the agent writes a partial-results summary and exits 1 — it never
   loops forever. Every LLM call and tool call increments counters printed in the
   final summary.
5. **Full auditability:** append every event (LLM request summary, chosen tool,
   arguments, truncated result, retries, approvals) as JSON lines to
   `output/agent_transcript.jsonl`, and maintain the blueprint's
   `agent_progress.json` contract: update `current_stage`,
   `metadata.consecutive_failures` (increment on tool failure, reset on success).
6. **Dependencies — IMPORTANT, do not copy the repo's existing SDK usage:**
   the repo's `Skills/gemini_escalation.py` uses the legacy `google-generativeai`
   package, which reached end-of-life on 2025-11-30 and must NOT be used here.
   Use the unified **`google-genai`** SDK instead:
   `from google import genai; client = genai.Client()` (it reads `GEMINI_API_KEY`
   from the environment automatically). Default model `gemini-2.5-flash` with a
   `--model` override; on a model-not-found API error, print the error and the
   list of goals for the `--model` flag rather than retrying. Add `google-genai`
   to `requirements.txt` and `pyproject.toml`; do not add `google-generativeai`.
   Use the SDK's native **function-calling / tools support** in
   `generate_content` (declare the tool registry via
   `types.GenerateContentConfig(tools=...)`) — do not parse tool choices out of
   free text with regex. If unsure of exact API shapes, consult the official
   migration guide at https://ai.google.dev/gemini-api/docs/migrate rather than
   guessing from memory.
7. Follow repo conventions: type hints, docstrings, `datetime.now(timezone.utc)`,
   dynamic project root (`Path(__file__).resolve().parent.parent`), no hardcoded
   `/mnt/d/...` or `/tmp/...` paths.

## The tool registry

Implement each tool as a plain Python function in `Code/agent.py` (or a small
`Code/agent_tools.py`) with a JSON-schema declaration for the LLM. Every tool
returns a dict: `{"ok": bool, "summary": str, "data": {...}}` — `summary` is a
short human-readable line; large outputs (CSV contents, logs) must be truncated
to ~2000 chars before entering the LLM context.

| Tool | Wraps | Notes |
|---|---|---|
| `detect_hardware()` | `Skills.manage_device.detect_device` + `plan_device_passes` | Returns available device(s), planned passes, GPU name via torch if present. Read-only. |
| `list_assets()` | filesystem probe of `models/` and `data/LibriSpeech/` | Returns which model aliases are downloaded (validate: directory exists AND contains `model.bin`) and which splits are extracted. Read-only. |
| `acquire_models(aliases: list[str])` | `subprocess` → `Skills/acquire_assets.py models --models <aliases>` | Gate: >1 GB estimate requires approval (Hard constraint 2). Validate aliases against `Code.config.MODEL_CONFIG` before running. |
| `acquire_datasets(splits: list[str])` | `subprocess` → `Skills/acquire_assets.py datasets --which <splits>` | Validate splits ∈ {test-clean, test-other}. |
| `run_benchmark(models, device, limit, engine)` | `subprocess` → `python -m Code.main ...` | Always pass `--no-resume` off (i.e. allow resume) unless the goal says fresh; capture stdout+stderr; on nonzero exit return `ok=False` with the **last 40 lines** of output as `data["tail"]`. Validate every arg against the harness's own choices lists. |
| `read_results(latest_only: bool = True)` | reads `output/summary.csv` (+ failure counts) | Returns rows as list-of-dicts, deduped to latest per (model, engine, device, compute_type, split) when `latest_only`. Read-only. |
| `inspect_failures(n: int = 5)` | reads `output/details.csv` | Returns the most recent rows where `error != ""` (utt_id + error text), so the LLM can diagnose. Read-only. |
| `publish_report(no_push: bool = True)` | `subprocess` → `Skills/publish_report.py publish [--no-push]` | Gate: push requires approval. |
| `finish(summary: str)` | terminates the loop | The LLM must call this with a 3–6 sentence results narrative (which models won on which split, RTF trade-offs, any failures encountered and how they were resolved). Printed to console and appended to the transcript. |

Every `subprocess` call uses `sys.executable`, `cwd=project_root`, a sane timeout
(`--tool-timeout`, default 3600 s), and `capture_output=True`. Never `shell=True`.

## The agent loop

```
goal (argv) → system prompt + tool declarations → loop:
    LLM turn → either tool_call(s) or finish
    execute tool → append observation to conversation + transcript
    on ok=False: increment consecutive_failures; the NEXT LLM turn receives the
      error tail and must choose: retry with changed args, take a remedial tool
      action, or finish with a partial-results explanation. After max-retries
      for the same tool+intent, remove that option and force degrade-or-finish.
until finish() or max-steps.
```

System prompt requirements (write it as a module constant, ≤ 400 words): state
the goal variable; enumerate tools and when to use them; require a
plan-before-first-action turn (the LLM states its plan in text before the first
tool call — log it); require checking `list_assets` before any acquisition and
`detect_hardware` before choosing `--device`; state the failure protocol above;
state that `finish` is mandatory and must summarize honestly, including anything
that did not work; forbid inventing tool names or arguments.

**Known failure modes it must handle** (encode these as brief hints in the system
prompt, since they are real behaviors of this harness):
- `ffmpeg` missing → `[Errno 2] No such file or directory: 'ffmpeg'` in the tail.
  Correct response: do NOT retry; `finish` with instructions for the human to
  install ffmpeg (the agent has no shell tool, by design).
- Model directory absent → `run_benchmark` fails at load. Correct response:
  `list_assets`, then `acquire_models` for the missing alias, then retry once.
- CUDA out-of-memory on a large model → retry that model with `--device cpu`, or
  drop the model and note it in `finish`.
- Illegal device/compute combo `ValueError` → do not retry the same args.

## Escalation integration (closes the loop on existing code)

When `consecutive_failures >= 3` (read via
`Skills.gemini_escalation.check_if_stuck()`), the agent assembles a payload with
`assemble_escalation_payload(...)` using the failing tool name, the captured
error tail, and the attempted arguments (NOT source code), and calls
`escalate_to_gemini(...)` — preserving that function's existing human-approval
prompt. The returned advice text is injected into the next LLM turn as an
observation labeled `escalation_advice`. This turns the repo's dormant
escalation skill into live agent infrastructure; mention it in the docstring.

Required sub-task: **migrate `Skills/gemini_escalation.py` to the `google-genai`
SDK** (its current `import google.generativeai` / `gemini-1.5-flash` code is
end-of-life and will fail at runtime). Preserve its behavior exactly: the
printed prompt preview, the saved `gemini_query_prompt.md`, the interactive
approval, and the missing-key fallback message. Also make its hardcoded paths
dynamic if REMEDIATION_PLAN Task 7 did not already do so. Add a unit test that
exercises `assemble_escalation_payload` and `check_if_stuck` (no network).

## Deliverables

1. `Code/agent.py` (and optionally `Code/agent_tools.py`) — fully commented,
   including a module docstring mapping the design onto the course's
   perceive/plan/act/observe loop and the read-only vs action-allowed tool tiers.
2. CLI: `python -m Code.agent "<goal>" [--max-steps N] [--max-retries N]
   [--model NAME] [--yes] [--tool-timeout S] [--dry-run]`.
   `--dry-run` swaps the tool executor for stubs that return canned successes
   (and one scripted failure on the first `run_benchmark` call so the recovery
   path is exercised) — this makes the whole agent demonstrable and testable
   with **no API cost beyond the LLM calls and no downloads**. In `--dry-run`,
   `run_benchmark` stubs should also route to the real harness's **mock engine**
   if LibriSpeech data exists locally, else return canned rows.
3. `tests/test_agent_tools.py` — offline unit tests, no network, no GEMINI key:
   argument validation rejects unknown model aliases/devices; `read_results`
   dedupes correctly against a fixture summary.csv; `inspect_failures` surfaces
   error rows; the retry counter forces degrade after max-retries (drive the
   loop with a scripted fake-LLM callable, not the real API); transcript JSONL
   lines are valid JSON; approval gate blocks a >1 GB acquisition when the
   approval callable returns False.
4. `README.md` — new "Agent mode" section: what the agent is (one paragraph
   mapping to the agent loop), the command, the safety model (whitelisted tools,
   approval gates, budget caps, PII-scanned transcript), and a sample transcript
   excerpt.
5. `RUNNING_GUIDE.md` — a Phase 6 section: agent quickstart with `--dry-run`
   first, then a real small goal, e.g.
   `python -m Code.agent "benchmark tiny on cpu with limit 5 using the mock engine and generate a report without pushing" --yes`.

## Verification (run all; report in your closing summary)

1. `pytest tests/ -q` — all green, including the new agent tests.
2. `python -m Code.agent --help` exits 0 and shows all flags.
3. Without `GEMINI_API_KEY` set: running with a goal exits 2 with a clear message.
4. `python -m Code.agent "run a quick mock benchmark of tiny on cpu and report" --dry-run --yes`
   (requires GEMINI_API_KEY): completes within max-steps, transcript JSONL is
   written and valid, the scripted failure is recovered from, `finish` produces
   a narrative, and `python Skills/check_no_pii.py path output/agent_transcript.jsonl`
   passes. If no API key is available in your environment, run the same flow
   with the scripted fake-LLM test driver instead and state that substitution.
5. `git status` — nothing from `output/`, `models/`, `data/` staged;
   `agent_transcript.jsonl` and `agent_progress.json` added to `.gitignore`
   (managed block) if not already ignored.
6. One commit per deliverable group, conventional messages, **no push**.
7. Closing summary: what was built, test results, any deviations with reasons,
   and a suggested 30-second video demo script (goal in → plan printed → tools
   firing → induced failure → recovery → finish narrative).
