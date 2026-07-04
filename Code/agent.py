"""ASR Benchmark Orchestrator Agent.

Implements the perceive -> plan -> act -> observe -> iterate loop on top of the
ASR benchmarking harness. The agent interacts with whitelisted tools under
strict safety bounds and budget caps.
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable

# Use unified google-genai SDK
from google import genai
from google.genai import types

# Existing repo modules
from Code.config import MODEL_CONFIG
from Skills.manage_device import plan_device_passes, gpu_available
from Skills.gemini_escalation import check_if_stuck, assemble_escalation_payload, escalate_to_gemini

# Model size estimates in GB (derived from Hugging Face Repository sizes)
MODEL_SIZES_GB = {
    "tiny": 0.08, "tiny.en": 0.08,
    "base": 0.15, "base.en": 0.15,
    "small": 0.46, "small.en": 0.46,
    "distil-small.en": 0.35,
    "medium": 1.5, "medium.en": 1.5,
    "distil-medium.en": 0.8,
    "large-v1": 3.0, "large-v2": 3.0, "large-v3": 3.0,
    "distil-large-v2": 1.5, "distil-large-v3": 1.5
}

SYSTEM_PROMPT = """You are an autonomous ASR benchmark agent. Your goal: {goal}

You have whitelisted tools to perceive, plan, act, and observe.
You MUST follow a loop: Plan -> Act (Tool Call) -> Observe -> Iterate.
Before taking your first action, you MUST output a text plan explaining your approach.
Always check `list_assets()` before acquiring models/datasets.
Always check `detect_hardware()` before specifying a `--device`.

Failure Protocol:
If a tool returns ok=False, you will see an error tail. You must:
1. Retry with changed arguments, OR
2. Take a remedial action (e.g., download missing models), OR
3. If max-retries for a tool are exhausted, finish with partial results.

Known issues:
- If ffmpeg is missing (`No such file or directory: 'ffmpeg'`), do NOT retry. Call `finish()` instructing the human to install ffmpeg (the agent has no shell tool).
- If a model directory is absent, call `list_assets`, `acquire_models` for the missing alias, then retry once.
- If CUDA out-of-memory occurs, retry with `--device cpu` or drop the model and note it in `finish`.
- If an illegal device/compute combo occurs, do not retry the exact same args.

You must ALWAYS conclude by calling `finish(summary: str)`. The summary must be a 3-6 sentence honest narrative of results, RTF tradeoffs, and failures.
Do NOT invent tool names or arguments."""


class AgentContext:
    dry_run: bool = False
    yes_flag: bool = False
    project_root: Path = Path(__file__).resolve().parent.parent
    max_steps: int = 20
    max_retries: int = 2
    tool_timeout: int = 3600
    model_name: str = "gemini-2.5-flash"
    goal: str = ""
    steps_count: int = 0
    calls_count: int = 0
    consecutive_failures: int = 0
    benchmark_calls_count: int = 0
    tool_intent_retries: dict[str, int] = {}
    approval_callable: Callable[[str], bool] = lambda self, msg: input(msg).strip().lower() == 'y'

_ctx = AgentContext()


# --- Progress and Audit Helpers ---

def update_progress(stage: str, consecutive_failures: int):
    """Saves the progress JSON contract."""
    progress_path = _ctx.project_root / "agent_progress.json"
    data = {
        "current_stage": stage,
        "metadata": {
            "consecutive_failures": consecutive_failures
        }
    }
    try:
        progress_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Error writing progress file: {e}", file=sys.stderr)


def append_transcript(event_type: str, details: dict):
    """Appends an event to the JSONL audit transcript."""
    transcript_path = _ctx.project_root / "output" / "agent_transcript.jsonl"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "details": details
    }
    try:
        with open(transcript_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print(f"Error writing transcript: {e}", file=sys.stderr)


# --- Whitelisted Tool Registry ---

def detect_hardware() -> dict:
    """Detects available hardware (devices) and planned passes.
    
    Returns:
        A dict with 'ok' status, human summary, and hardware details.
    """
    _ctx.calls_count += 1
    if _ctx.dry_run:
        res = {
            "ok": True,
            "summary": "Detected hardware (Dry-run stub).",
            "data": {
                "gpu_available": False,
                "gpu_name": None,
                "passes": [["cpu", "int8"]]
            }
        }
        append_transcript("tool_call", {"tool": "detect_hardware", "args": {}, "result": res})
        return res

    try:
        gpu_ok = gpu_available()
        # Find GPU name if present
        import torch
        gpu_name = torch.cuda.get_device_name(0) if (gpu_ok and torch.cuda.is_available()) else None
        
        # Determine planned passes
        try:
            passes = plan_device_passes("auto")
        except Exception:
            passes = [("cpu", "int8")]

        res = {
            "ok": True,
            "summary": f"Hardware detected: GPU={gpu_ok} ({gpu_name}), planned passes: {passes}.",
            "data": {
                "gpu_available": gpu_ok,
                "gpu_name": gpu_name,
                "passes": passes
            }
        }
        append_transcript("tool_call", {"tool": "detect_hardware", "args": {}, "result": res})
        return res
    except Exception as e:
        res = {"ok": False, "summary": f"Hardware detection failed: {e}", "data": {"tail": str(e)}}
        append_transcript("tool_call", {"tool": "detect_hardware", "args": {}, "result": res})
        return res


def list_assets() -> dict:
    """Lists downloaded model aliases and extracted dataset splits.
    
    Returns:
        A dict with downloaded models and extracted splits.
    """
    _ctx.calls_count += 1
    if _ctx.dry_run:
        # Write canned summary so read_results doesn't error
        res = {
            "ok": True,
            "summary": "Assets listed (Dry-run stub).",
            "data": {
                "downloaded_models": ["tiny"],
                "extracted_splits": ["test-clean"]
            }
        }
        append_transcript("tool_call", {"tool": "list_assets", "args": {}, "result": res})
        return res

    try:
        downloaded_models = []
        for alias, config in MODEL_CONFIG.items():
            local_path = config.local_path
            if local_path.exists() and (local_path / "model.bin").exists():
                downloaded_models.append(alias)
                
        extracted_splits = []
        librispeech_root = _ctx.project_root / "data" / "LibriSpeech"
        if librispeech_root.exists():
            for split in ["test-clean", "test-other"]:
                split_dir = librispeech_root / split
                if split_dir.exists() and any(split_dir.iterdir()):
                    extracted_splits.append(split)

        res = {
            "ok": True,
            "summary": f"Listed assets: found {len(downloaded_models)} models, {len(extracted_splits)} dataset splits.",
            "data": {
                "downloaded_models": downloaded_models,
                "extracted_splits": extracted_splits
            }
        }
        append_transcript("tool_call", {"tool": "list_assets", "args": {}, "result": res})
        return res
    except Exception as e:
        return {"ok": False, "summary": f"Failed listing assets: {e}", "data": {}}


def acquire_models(aliases: list[str]) -> dict:
    """Downloads model assets. Requires human approval if estimated size > 1 GB.
    
    Args:
        aliases: List of model aliases to acquire (e.g. ['tiny', 'medium.en']).
    """
    _ctx.calls_count += 1
    for alias in aliases:
        if alias not in MODEL_CONFIG:
            return {"ok": False, "summary": f"Unknown model alias: {alias}", "data": {}}

    # Estimate download size for missing models
    total_size_gb = 0.0
    for alias in aliases:
        local_path = MODEL_CONFIG[alias].local_path
        if not (local_path.exists() and (local_path / "model.bin").exists()):
            total_size_gb += MODEL_SIZES_GB.get(alias, 0.5)

    if total_size_gb > 1.0:
        if not _ctx.yes_flag:
            msg = f"\n⚠️ APPROVAL GATE: The requested model download size is estimated at {total_size_gb:.2f} GB, which exceeds the 1 GB safety limit.\nDo you approve this download? (y/n): "
            if not _ctx.approval_callable(msg):
                res = {
                    "ok": False,
                    "summary": f"Acquisition of models {aliases} blocked: size {total_size_gb:.2f} GB rejected.",
                    "data": {"size_gb": total_size_gb}
                }
                append_transcript("tool_call", {"tool": "acquire_models", "args": {"aliases": aliases}, "result": res})
                return res

    if _ctx.dry_run:
        res = {"ok": True, "summary": f"Mock acquired models: {aliases}", "data": {}}
        append_transcript("tool_call", {"tool": "acquire_models", "args": {"aliases": aliases}, "result": res})
        return res

    cmd = [sys.executable, "Skills/acquire_assets.py", "models", "--models"] + aliases
    try:
        result = subprocess.run(cmd, cwd=_ctx.project_root, capture_output=True, text=True, timeout=_ctx.tool_timeout)
        if result.returncode == 0:
            res = {"ok": True, "summary": f"Successfully acquired models: {aliases}", "data": {}}
        else:
            res = {
                "ok": False,
                "summary": "Failed acquiring models.",
                "data": {"tail": (result.stderr + "\n" + result.stdout)[-2000:]}
            }
        append_transcript("tool_call", {"tool": "acquire_models", "args": {"aliases": aliases}, "result": res})
        return res
    except Exception as e:
        res = {"ok": False, "summary": f"Acquisition error: {e}", "data": {"tail": str(e)}}
        append_transcript("tool_call", {"tool": "acquire_models", "args": {"aliases": aliases}, "result": res})
        return res


def acquire_datasets(splits: list[str]) -> dict:
    """Downloads and extracts specified dataset splits.
    
    Args:
        splits: List of dataset splits to acquire (from 'test-clean', 'test-other').
    """
    _ctx.calls_count += 1
    for s in splits:
        if s not in ["test-clean", "test-other"]:
            return {"ok": False, "summary": f"Invalid dataset split: {s}", "data": {}}

    if _ctx.dry_run:
        res = {"ok": True, "summary": f"Mock acquired datasets: {splits}", "data": {}}
        append_transcript("tool_call", {"tool": "acquire_datasets", "args": {"splits": splits}, "result": res})
        return res

    cmd = [sys.executable, "Skills/acquire_assets.py", "datasets", "--which"] + splits
    try:
        result = subprocess.run(cmd, cwd=_ctx.project_root, capture_output=True, text=True, timeout=_ctx.tool_timeout)
        if result.returncode == 0:
            res = {"ok": True, "summary": f"Successfully acquired datasets: {splits}", "data": {}}
        else:
            res = {
                "ok": False,
                "summary": "Failed acquiring datasets.",
                "data": {"tail": (result.stderr + "\n" + result.stdout)[-2000:]}
            }
        append_transcript("tool_call", {"tool": "acquire_datasets", "args": {"splits": splits}, "result": res})
        return res
    except Exception as e:
        res = {"ok": False, "summary": f"Dataset acquisition error: {e}", "data": {"tail": str(e)}}
        append_transcript("tool_call", {"tool": "acquire_datasets", "args": {"splits": splits}, "result": res})
        return res


def run_benchmark(models: list[str], device: str, limit: int, engine: str) -> dict:
    """Runs the benchmark harness for specified models, device, and engine.
    
    Args:
        models: List of model aliases to run (e.g. ['tiny']).
        device: Device choice ('auto', 'both', 'cuda', 'cpu').
        limit: Max utterances per split/model (use -1 for no limit, or a small number like 5 for quick runs).
        engine: Engine type ('mock' or 'whisperx').
    """
    _ctx.calls_count += 1
    for m in models:
        if m not in MODEL_CONFIG:
            return {"ok": False, "summary": f"Invalid model alias: {m}", "data": {}}
    if device not in ["auto", "both", "cuda", "cpu"]:
        return {"ok": False, "summary": f"Invalid device choice: {device}", "data": {}}
    if engine not in ["mock", "whisperx"]:
        return {"ok": False, "summary": f"Invalid engine choice: {engine}", "data": {}}

    if _ctx.dry_run:
        _ctx.benchmark_calls_count += 1
        if _ctx.benchmark_calls_count == 1:
            res = {
                "ok": False,
                "summary": "CUDA out-of-memory during load (scripted dry-run failure).",
                "data": {
                    "tail": "torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.50 GiB (GPU 0; 8.00 GiB total capacity; 6.20 GiB already allocated)"
                }
            }
            append_transcript("tool_call", {"tool": "run_benchmark", "args": {"models": models, "device": device, "limit": limit, "engine": engine}, "result": res})
            return res

        # Check for local data
        librispeech_root = _ctx.project_root / "data" / "LibriSpeech"
        has_local_data = False
        if librispeech_root.exists():
            for _ in librispeech_root.rglob("*.flac"):
                has_local_data = True
                break

        if has_local_data:
            # Route to real mock engine
            cmd = [sys.executable, "-m", "Code.main", "--models-to-benchmark"] + models + [
                "--device", device,
                "--engine-type", "mock"
            ]
            if limit > 0:
                cmd += ["--limit", str(limit)]
            # If Goal requests fresh/no-resume
            if any(kw in _ctx.goal.lower() for kw in ["fresh", "no-resume", "no resume"]):
                cmd += ["--no-resume"]

            try:
                result = subprocess.run(cmd, cwd=_ctx.project_root, capture_output=True, text=True, timeout=_ctx.tool_timeout)
                if result.returncode == 0:
                    res = {"ok": True, "summary": "Benchmark run successfully completed (mock engine).", "data": {}}
                else:
                    res = {"ok": False, "summary": "Benchmark run failed.", "data": {"tail": (result.stderr + "\n" + result.stdout)[-2000:]}}
                append_transcript("tool_call", {"tool": "run_benchmark", "args": {"models": models, "device": device, "limit": limit, "engine": engine}, "result": res})
                return res
            except Exception as e:
                res = {"ok": False, "summary": f"Benchmark error: {e}", "data": {"tail": str(e)}}
                append_transcript("tool_call", {"tool": "run_benchmark", "args": {"models": models, "device": device, "limit": limit, "engine": engine}, "result": res})
                return res
        else:
            # Write canned rows to CSVs so agent can read them
            from Code.writer import ResilientCSVWriter
            writer = ResilientCSVWriter(_ctx.project_root / "output")
            for m in models:
                for split in ["test-clean", "test-other"]:
                    writer.write_detail_row({
                        "model": m, "arch": MODEL_CONFIG[m].family, "engine": engine,
                        "compute_type": "int8" if device == "cpu" else "float16",
                        "beam_size": 5, "device": "cpu" if device == "cpu" else "cuda",
                        "dataset": "LibriSpeech", "split": split, "utt_id": f"dummy-{m}-1",
                        "audio_s": 10.0, "proc_s": 2.0, "rtf": 0.2, "wer": 0.0, "cer": 0.0,
                        "hypothesis": "hello world", "reference": "hello world", "error": ""
                    })
                    writer.write_summary_row({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "model": m, "arch": MODEL_CONFIG[m].family, "engine": engine,
                        "compute_type": "int8" if device == "cpu" else "float16",
                        "beam_size": 5, "device": "cpu" if device == "cpu" else "cuda",
                        "batch_size": 1, "dataset": "LibriSpeech", "split": split,
                        "n_ok": 1, "n_failed": 0, "n_utts": 1, "total_audio_s": 10.0, "load_s": 0.5,
                        "total_proc_s": 2.0, "rtf": 0.2, "wer": 0.0, "cer": 0.0
                    })
            res = {"ok": True, "summary": f"Mock benchmark completed for {models} (Canned successfully).", "data": {}}
            append_transcript("tool_call", {"tool": "run_benchmark", "args": {"models": models, "device": device, "limit": limit, "engine": engine}, "result": res})
            return res

    cmd = [sys.executable, "-m", "Code.main", "--models-to-benchmark"] + models + [
        "--device", device,
        "--engine-type", engine
    ]
    if limit > 0:
        cmd += ["--limit", str(limit)]
    if any(kw in _ctx.goal.lower() for kw in ["fresh", "no-resume", "no resume"]):
        cmd += ["--no-resume"]

    try:
        result = subprocess.run(cmd, cwd=_ctx.project_root, capture_output=True, text=True, timeout=_ctx.tool_timeout)
        if result.returncode == 0:
            res = {"ok": True, "summary": f"Successfully completed benchmark for {models}.", "data": {}}
        else:
            lines = (result.stderr + "\n" + result.stdout).splitlines()
            tail = "\n".join(lines[-40:])
            res = {
                "ok": False,
                "summary": "Benchmark run failed.",
                "data": {"tail": tail}
            }
        append_transcript("tool_call", {"tool": "run_benchmark", "args": {"models": models, "device": device, "limit": limit, "engine": engine}, "result": res})
        return res
    except Exception as e:
        res = {"ok": False, "summary": f"Failed running benchmark: {e}", "data": {"tail": str(e)}}
        append_transcript("tool_call", {"tool": "run_benchmark", "args": {"models": models, "device": device, "limit": limit, "engine": engine}, "result": res})
        return res


def read_results(latest_only: bool = True) -> dict:
    """Reads summary of benchmark results from summary.csv.
    
    Args:
        latest_only: Whether to deduplicate results to show only the latest per configuration.
    """
    _ctx.calls_count += 1
    summary_path = _ctx.project_root / "output" / "summary.csv"
    if not summary_path.exists():
        res = {"ok": False, "summary": "No summary.csv results file exists yet.", "data": {}}
        append_transcript("tool_call", {"tool": "read_results", "args": {"latest_only": latest_only}, "result": res})
        return res

    try:
        import csv
        with open(summary_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if latest_only:
            latest_runs = {}
            for row in rows:
                key = (
                    row.get("model", ""), row.get("engine", ""), row.get("device", ""),
                    row.get("compute_type", ""), row.get("split", "")
                )
                try:
                    dt = datetime.fromisoformat(row.get("timestamp", ""))
                except Exception:
                    dt = datetime.min.replace(tzinfo=timezone.utc)
                if key not in latest_runs or dt > latest_runs[key][0]:
                    latest_runs[key] = (dt, row)
            display_rows = [val[1] for val in latest_runs.values()]
        else:
            display_rows = rows

        # Truncate row counts if huge
        recent_rows = display_rows[-50:]
        res = {
            "ok": True,
            "summary": f"Read results. Found {len(display_rows)} rows in summary.",
            "data": {"rows": recent_rows}
        }
        append_transcript("tool_call", {"tool": "read_results", "args": {"latest_only": latest_only}, "result": res})
        return res
    except Exception as e:
        res = {"ok": False, "summary": f"Failed reading results: {e}", "data": {"tail": str(e)}}
        append_transcript("tool_call", {"tool": "read_results", "args": {"latest_only": latest_only}, "result": res})
        return res


def inspect_failures(n: int = 5) -> dict:
    """Reads details of recent failed transcriptions from details.csv.
    
    Args:
        n: Maximum number of failure rows to return.
    """
    _ctx.calls_count += 1
    details_path = _ctx.project_root / "output" / "details.csv"
    if not details_path.exists():
        res = {"ok": True, "summary": "No failures recorded (details.csv absent).", "data": {"failures": []}}
        append_transcript("tool_call", {"tool": "inspect_failures", "args": {"n": n}, "result": res})
        return res

    try:
        import csv
        failures = []
        with open(details_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                err = row.get("error", "").strip()
                if err:
                    failures.append({
                        "model": row.get("model", ""),
                        "utt_id": row.get("utt_id", ""),
                        "split": row.get("split", ""),
                        "error": err
                    })
        recent_failures = failures[-n:]
        res = {
            "ok": True,
            "summary": f"Inspected failures. Returning {len(recent_failures)} of {len(failures)} failures.",
            "data": {"failures": recent_failures}
        }
        append_transcript("tool_call", {"tool": "inspect_failures", "args": {"n": n}, "result": res})
        return res
    except Exception as e:
        res = {"ok": False, "summary": f"Failed inspecting failures: {e}", "data": {"tail": str(e)}}
        append_transcript("tool_call", {"tool": "inspect_failures", "args": {"n": n}, "result": res})
        return res


def publish_report(no_push: bool = True) -> dict:
    """Generates and publishes the benchmark report to Git.
    
    Args:
        no_push: Whether to commit locally but skip pushing to remote.
    """
    _ctx.calls_count += 1
    if not no_push:
        if not _ctx.yes_flag:
            msg = "\n⚠️ APPROVAL GATE: You are attempting to publish with PUSH enabled.\nDo you approve pushing this report to the remote origin? (y/n): "
            if not _ctx.approval_callable(msg):
                res = {"ok": False, "summary": "Publish report with push rejected.", "data": {}}
                append_transcript("tool_call", {"tool": "publish_report", "args": {"no_push": no_push}, "result": res})
                return res

    if _ctx.dry_run:
        res = {"ok": True, "summary": "Mock publish report completed successfully.", "data": {}}
        append_transcript("tool_call", {"tool": "publish_report", "args": {"no_push": no_push}, "result": res})
        return res

    cmd = [sys.executable, "Skills/publish_report.py", "--project-root", str(_ctx.project_root), "publish"]
    if no_push:
        cmd += ["--no-push"]

    try:
        result = subprocess.run(cmd, cwd=_ctx.project_root, capture_output=True, text=True, timeout=_ctx.tool_timeout)
        if result.returncode == 0:
            res = {"ok": True, "summary": "Report successfully published.", "data": {"stdout": result.stdout[-2000:]}}
        else:
            res = {
                "ok": False,
                "summary": f"Failed publishing report (exit {result.returncode}).",
                "data": {"tail": (result.stderr + "\n" + result.stdout)[-2000:]}
            }
        append_transcript("tool_call", {"tool": "publish_report", "args": {"no_push": no_push}, "result": res})
        return res
    except Exception as e:
        res = {"ok": False, "summary": f"Failed publishing report script: {e}", "data": {"tail": str(e)}}
        append_transcript("tool_call", {"tool": "publish_report", "args": {"no_push": no_push}, "result": res})
        return res


def finish(summary: str) -> dict:
    """Concludes the agent session and presents the final summary narrative.
    
    Args:
        summary: A 3-6 sentence results narrative summarizing findings, trade-offs, and solutions.
    """
    _ctx.calls_count += 1
    res = {"ok": True, "summary": "Finished.", "data": {"summary": summary}}
    append_transcript("finish", {"summary": summary})
    return res


# Dispatcher map
DISPATCHER = {
    "detect_hardware": detect_hardware,
    "list_assets": list_assets,
    "acquire_models": acquire_models,
    "acquire_datasets": acquire_datasets,
    "run_benchmark": run_benchmark,
    "read_results": read_results,
    "inspect_failures": inspect_failures,
    "publish_report": publish_report,
    "finish": finish
}


# --- Agent Core Execution ---

def execute_agent_loop(goal: str):
    """Orchestrates the main perceive-plan-act loop."""
    print("=" * 80)
    print(f"🚀 AGENT SESSION STARTED: {datetime.now(timezone.utc).isoformat()} UTC")
    print(f"Goal: {goal}")
    print(f"Dry-run: {_ctx.dry_run} | Pre-approve: {_ctx.yes_flag} | Model: {_ctx.model_name}")
    print("=" * 80)

    # Missing GEMINI_API_KEY check exits 2 before client instantiation
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        print("Please resolve manually and run again.", file=sys.stderr)
        sys.exit(2)

    # Initialize Client
    client = genai.Client(api_key=api_key)

    # Configure tools list & manual control config
    tools_list = list(DISPATCHER.values())
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.format(goal=goal),
        tools=tools_list,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    )

    contents = [types.Content(role="user", parts=[types.Part.from_text(text=goal)])]
    update_progress("running", 0)

    last_failing_tool = ""
    last_failing_args = {}
    last_failing_tail = ""

    # Primary Loop
    while _ctx.steps_count < _ctx.max_steps:
        _ctx.steps_count += 1
        print(f"\n[Step {_ctx.steps_count}/{_ctx.max_steps}] Thinking...")

        # Escalation Trigger
        if check_if_stuck():
            print("⚠️ STUCK ALERT: Consecutive failures threshold met. Requesting Gemini system advice...")
            payload = assemble_escalation_payload(
                stuck_module=last_failing_tool,
                error_message=last_failing_tail,
                attempted_args=json.dumps(last_failing_args)
            )
            advice = escalate_to_gemini(payload)
            if advice:
                # Inject escalation advice directly as observation into context
                advice_part = types.Part.from_text(text=f"escalation_advice: {advice}")
                contents.append(types.Content(role="user", parts=[advice_part]))
                # Reset consecutive failure counter inside agent_progress.json so we don't repeat loop endlessly
                update_progress("running", 0)
                _ctx.consecutive_failures = 0

        # LLM Turn
        try:
            response = client.models.generate_content(
                model=_ctx.model_name,
                contents=contents,
                config=config
            )
        except Exception as e:
            err_str = str(e).lower()
            if any(term in err_str for term in ["not found", "404", "not_found"]):
                print(f"❌ API Error: Model '{_ctx.model_name}' was not found by the Gemini API.", file=sys.stderr)
                print("Available model flags / options: 'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-1.5-flash', 'gemini-1.5-pro'.", file=sys.stderr)
                sys.exit(2)
            else:
                print(f"❌ Gemini API Error: {e}", file=sys.stderr)
                sys.exit(1)

        # Print reasoning or content
        if response.text:
            print(f"Agent Thought:\n{response.text.strip()}")

        # Append assistant turn
        contents.append(response.candidates[0].content)

        # Handle tool execution
        if response.function_calls:
            tool_parts = []
            finished_session = False
            for call in response.function_calls:
                name = call.name
                args = call.args if call.args else {}
                
                print(f"🔧 Tool selected: {name}({args})")
                
                # Check retry budget constraint per tool+intent
                intent_key = f"{name}:{json.dumps(args, sort_keys=True)}"
                if _ctx.tool_intent_retries.get(intent_key, 0) >= _ctx.max_retries:
                    result = {
                        "ok": False,
                        "summary": f"Call blocked: exceeded retry limit of {_ctx.max_retries} for this exact execution intent.",
                        "data": {"tail": f"Tool intent retries of {_ctx.max_retries} exhausted. You must degrade your goal parameter(s) or calls, try an alternate parameter combination, or finish."}
                    }
                else:
                    func = DISPATCHER.get(name)
                    if func:
                        # Execute the whitelisted function
                        try:
                            result = func(**args)
                        except Exception as ex:
                            result = {"ok": False, "summary": f"Unhandled tool runtime exception: {ex}", "data": {"tail": str(ex)}}
                    else:
                        result = {"ok": False, "summary": f"Tool '{name}' is not in the whitelisted registry.", "data": {}}

                print(f"Result: {result.get('summary')}")
                
                # Update retry counters
                if not result.get("ok"):
                    _ctx.tool_intent_retries[intent_key] = _ctx.tool_intent_retries.get(intent_key, 0) + 1
                    _ctx.consecutive_failures += 1
                    
                    last_failing_tool = name
                    last_failing_args = args
                    last_failing_tail = result.get("data", {}).get("tail", result.get("summary", ""))
                else:
                    _ctx.consecutive_failures = 0

                update_progress("running", _ctx.consecutive_failures)

                part = types.Part.from_function_response(
                    name=name,
                    response=result
                )
                tool_parts.append(part)

                if name == "finish":
                    finished_session = True

            # Append tool observations
            contents.append(types.Content(role="tool", parts=tool_parts))
            
            if finished_session:
                update_progress("completed", 0)
                print("\n" + "=" * 80)
                print("🏁 AGENT RUN COMPLETED SUCCESSFULLY.")
                print(f"Final summary results narrative:\n{response.text or ''}")
                print(f"Audit log stored to: {_ctx.project_root}/output/agent_transcript.jsonl")
                print("=" * 80)
                sys.exit(0)
        else:
            # If model spoke without function call, make sure it knows it needs to select a tool or finish
            if not response.text:
                print("⚠️ Warning: Model returned an empty response.")

    # Max steps exhaustion
    update_progress("failed", _ctx.consecutive_failures)
    print("\n❌ Error: Agent loop execution exhausted budget of --max-steps before calling finish().", file=sys.stderr)
    print("Writing partial results summary.", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="ASR Benchmark Orchestrator Agent",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("goal", type=str, help="Natural language goal for the agent.")
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum LLM steps/turns.")
    parser.add_argument("--max-retries", type=int, default=2, help="Maximum retries per failed tool call.")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash", help="Gemini model name.")
    parser.add_argument("--yes", action="store_true", help="Pre-approve large downloads (>1GB) and report pushes.")
    parser.add_argument("--tool-timeout", type=int, default=3600, help="Subprocess tool timeout in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Run agent in demonstration dry-run mode.")
    
    args = parser.parse_args()

    # Populate context state
    _ctx.goal = args.goal
    _ctx.max_steps = args.max_steps
    _ctx.max_retries = args.max_retries
    _ctx.model_name = args.model
    _ctx.yes_flag = args.yes
    _ctx.tool_timeout = args.tool_timeout
    _ctx.dry_run = args.dry_run

    execute_agent_loop(args.goal)


if __name__ == "__main__":
    main()
