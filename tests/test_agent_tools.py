import json
import csv
import pytest
import tempfile
from pathlib import Path

from Code.agent import (
    _ctx,
    list_assets,
    acquire_models,
    run_benchmark,
    read_results,
    inspect_failures,
    update_progress,
    append_transcript,
    execute_agent_loop
)
from Skills.gemini_escalation import check_if_stuck, assemble_escalation_payload


@pytest.fixture(autouse=True)
def setup_agent_context():
    """Reset agent context before and after each test."""
    # Store original values
    orig_dry_run = _ctx.dry_run
    orig_yes_flag = _ctx.yes_flag
    orig_project_root = _ctx.project_root
    orig_max_retries = _ctx.max_retries
    orig_max_steps = _ctx.max_steps
    orig_tool_intent_retries = _ctx.tool_intent_retries.copy()
    orig_consecutive_failures = _ctx.consecutive_failures
    orig_benchmark_calls_count = _ctx.benchmark_calls_count
    orig_approval = _ctx.approval_callable

    yield

    # Restore original values
    _ctx.dry_run = orig_dry_run
    _ctx.yes_flag = orig_yes_flag
    _ctx.project_root = orig_project_root
    _ctx.max_retries = orig_max_retries
    _ctx.max_steps = orig_max_steps
    _ctx.tool_intent_retries = orig_tool_intent_retries
    _ctx.consecutive_failures = orig_consecutive_failures
    _ctx.benchmark_calls_count = orig_benchmark_calls_count
    _ctx.approval_callable = orig_approval


def test_argument_validation():
    """Verify tool registry functions reject invalid configurations."""
    _ctx.dry_run = True

    # run_benchmark: invalid model alias
    res = run_benchmark(models=["not-a-real-model"], device="cpu", limit=1, engine="mock")
    assert res["ok"] is False
    assert "Invalid model alias" in res["summary"]

    # run_benchmark: invalid device
    res = run_benchmark(models=["tiny"], device="invalid-device", limit=1, engine="mock")
    assert res["ok"] is False
    assert "Invalid device choice" in res["summary"]

    # run_benchmark: invalid engine
    res = run_benchmark(models=["tiny"], device="cpu", limit=1, engine="invalid")
    assert res["ok"] is False
    assert "Invalid engine choice" in res["summary"]


def list_assets_test():
    # Helper to check listing assets
    pass


def test_list_assets_dry_run():
    _ctx.dry_run = True
    res = list_assets()
    assert res["ok"] is True
    assert "tiny" in res["data"]["downloaded_models"]


def acquire_models_approval_gate():
    """Verify approval gate logic and return value."""
    pass


def test_model_acquisition_approval_gate():
    """Verify approval gate blocks model downloads > 1 GB if user says no."""
    _ctx.dry_run = True
    _ctx.yes_flag = False

    # Mock approval callable to return False (user rejects)
    _ctx.approval_callable = lambda msg: False

    # 'large-v3' is ~3.0 GB, so it should trigger the gate and get blocked
    res = acquire_models(["large-v3"])
    assert res["ok"] is False
    assert "blocked" in res["summary"]
    assert res["data"]["size_gb"] == 3.0

    # If --yes is set, it should bypass the gate
    _ctx.yes_flag = True
    res = acquire_models(["large-v3"])
    assert res["ok"] is True
    assert "Mock acquired models" in res["summary"]


def test_read_results_deduplication():
    """Verify read_results correctly deduplicates against a fixture summary.csv."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        _ctx.project_root = tmp_path
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        summary_file = output_dir / "summary.csv"
        
        # Write mock summary rows with duplicates
        fieldnames = [
            "timestamp", "model", "arch", "engine", "compute_type",
            "beam_size", "device", "batch_size", "dataset", "split",
            "n_ok", "n_failed", "n_utts", "total_audio_s", "load_s",
            "total_proc_s", "rtf", "wer", "cer"
        ]
        
        with open(summary_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            # Older run
            writer.writerow({
                "timestamp": "2026-07-04T12:00:00.000000+00:00",
                "model": "tiny", "arch": "Multilingual", "engine": "mock",
                "compute_type": "int8", "beam_size": "5", "device": "cpu",
                "batch_size": "1", "dataset": "LibriSpeech", "split": "test-clean",
                "n_ok": "1", "n_failed": "0", "n_utts": "1", "total_audio_s": "10.0",
                "load_s": "0.5", "total_proc_s": "2.0", "rtf": "0.2", "wer": "0.1000", "cer": "0.0500"
            })
            
            # Newer run
            writer.writerow({
                "timestamp": "2026-07-04T13:00:00.000000+00:00",
                "model": "tiny", "arch": "Multilingual", "engine": "mock",
                "compute_type": "int8", "beam_size": "5", "device": "cpu",
                "batch_size": "1", "dataset": "LibriSpeech", "split": clean_split_name(),
                "n_ok": "1", "n_failed": "0", "n_utts": "1", "total_audio_s": "10.0",
                "load_s": "0.5", "total_proc_s": "2.0", "rtf": "0.2", "wer": "0.0000", "cer": "0.0000"
            })

        # Read latest only
        res = read_results(latest_only=True)
        assert res["ok"] is True
        rows = res["data"]["rows"]
        assert len(rows) == 1
        assert rows[0]["timestamp"] == "2026-07-04T13:00:00.000000+00:00"
        assert rows[0]["wer"] == "0.0000"

        # Read all
        res_all = read_results(latest_only=False)
        assert len(res_all["data"]["rows"]) == 2


def clean_split_name():
    return "test-clean"


def test_inspect_failures_surfaces_errors():
    """Verify inspect_failures parses error rows correctly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        _ctx.project_root = tmp_path
        
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        details_file = output_dir / "details.csv"

        fieldnames = [
            "model", "arch", "engine", "compute_type", "beam_size",
            "device", "dataset", "split", "utt_id", "audio_s",
            "proc_s", "rtf", "wer", "cer", "hypothesis",
            "reference", "error"
        ]

        with open(details_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            # Success row
            writer.writerow({
                "model": "tiny", "arch": "Multilingual", "engine": "mock",
                "compute_type": "int8", "beam_size": "5", "device": "cpu",
                "dataset": "LibriSpeech", "split": "test-clean", "utt_id": "success-1",
                "audio_s": "10.0", "proc_s": "2.0", "rtf": "0.2", "wer": "0.0", "cer": "0.0",
                "hypothesis": "hello world", "reference": "hello world", "error": ""
            })
            # Failed row
            writer.writerow({
                "model": "tiny", "arch": "Multilingual", "engine": "mock",
                "compute_type": "int8", "beam_size": "5", "device": "cpu",
                "dataset": "LibriSpeech", "split": "test-clean", "utt_id": "fail-1",
                "audio_s": "10.0", "proc_s": "0.0", "rtf": "0.0", "wer": "1.0", "cer": "1.0",
                "hypothesis": "", "reference": "hello world", "error": "AssertionError: file empty"
            })

        res = inspect_failures(n=5)
        assert res["ok"] is True
        failures = res["data"]["failures"]
        assert len(failures) == 1
        assert failures[0]["utt_id"] == "fail-1"
        assert failures[0]["error"] == "AssertionError: file empty"


def test_transcript_validity():
    """Verify jsonl transcript is valid JSON."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        _ctx.project_root = tmp_path

        # Generate a transcript event
        append_transcript("test_event", {"some_key": "some_val"})

        transcript_file = tmp_path / "output" / "agent_transcript.jsonl"
        assert transcript_file.exists()

        lines = transcript_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        
        parsed = json.loads(lines[0])
        assert parsed["event_type"] == "test_event"
        assert parsed["details"]["some_key"] == "some_val"
        assert "timestamp" in parsed


# --- Mock classes for fake LLM turn driving ---

class MockFunctionCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class MockCandidateContent:
    def __init__(self, parts):
        self.parts = parts
        self.role = "model"


class MockCandidate:
    def __init__(self, content):
        self.content = content


class MockResponse:
    def __init__(self, function_calls=None, text=""):
        from google.genai import types
        self.function_calls = function_calls or []
        self.text = text
        p_list = []
        for fc in self.function_calls:
            p_list.append(types.Part(function_call=types.FunctionCall(name=fc.name, args=fc.args)))
        self.candidates = [MockCandidate(MockCandidateContent(p_list))]


def test_retry_degrade_constraint_loop(monkeypatch):
    """Verify retry budget forces degradation or finish using a fake-LLM driver."""
    from google import genai
    _ctx.dry_run = True
    _ctx.max_retries = 2
    _ctx.max_steps = 5

    class FakeModels:
        def __init__(self):
            self.calls = 0

        def generate_content(self, model, contents, config):
            self.calls += 1
            # Step 1: Model tries to benchmark tiny
            if self.calls == 1:
                return MockResponse(
                    function_calls=[
                        MockFunctionCall(name="run_benchmark", args={"models": ["tiny"], "device": "cpu", "limit": 5, "engine": "mock"})
                    ]
                )
            # Step 2: Model retries same intent (first retry)
            elif self.calls == 2:
                return MockResponse(
                    function_calls=[
                        MockFunctionCall(name="run_benchmark", args={"models": ["tiny"], "device": "cpu", "limit": 5, "engine": "mock"})
                    ]
                )
            # Step 3: Model tries same intent (second retry) - hits retry limit, gets blocked
            elif self.calls == 3:
                return MockResponse(
                    function_calls=[
                        MockFunctionCall(name="run_benchmark", args={"models": ["tiny"], "device": "cpu", "limit": 5, "engine": "mock"})
                    ]
                )
            # Step 4: Model sees failure and decides to finish
            else:
                return MockResponse(
                    function_calls=[
                        MockFunctionCall(name="finish", args={"summary": "Mock results narrative explaining fallback."})
                    ]
                )

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key")

    with pytest.raises(SystemExit) as exc_info:
        execute_agent_loop("test goal")
    assert exc_info.value.code == 0


def test_escalation_payload_and_progress_tracking():
    """Verify escalation prompt formatting and stuck checking state."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        _ctx.project_root = tmp_path

        # Initially not stuck
        assert check_if_stuck() is False

        # Set stuck metadata in agent_progress.json
        update_progress("running", 3)
        
        import Skills.gemini_escalation
        orig_progress_path = Skills.gemini_escalation.PROGRESS_PATH
        try:
            Skills.gemini_escalation.PROGRESS_PATH = tmp_path / "agent_progress.json"
            assert check_if_stuck() is True
        finally:
            Skills.gemini_escalation.PROGRESS_PATH = orig_progress_path

        # Verify escalation payload contents
        payload = assemble_escalation_payload(
            stuck_module="run_benchmark",
            error_message="OOM error",
            attempted_args='{"models": ["tiny"]}'
        )
        assert "run_benchmark" in payload
        assert "OOM error" in payload
        assert '{"models": ["tiny"]}' in payload
        assert "Attempted Arguments" in payload
