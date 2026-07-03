# ASR Benchmark Harness — Master Implementation Blueprint & Spec

This document is a complete, self-contained, production-grade engineering specification and execution plan for an **Automatic Speech Recognition (ASR) Benchmark Harness**. It integrates all architectural layouts, custom "Skills," cost-controlled human-in-the-loop escalation gates, offline mocking frameworks, crash-resiliency mechanisms, and setup instructions.

---

## 1. Goal & Target Environment

Evaluate **multiple automatic speech recognition (ASR) models** against the LibriSpeech `test-clean` and `test-other` corpora. The tool must compute per-utterance and aggregate **accuracy** (WER/CER) and **performance** (RTF, load time, processing time), displaying a formatted console report and logging details/summaries to disk in CSV files.

The models under test are the **Systran `faster-whisper`** weights — OpenAI Whisper checkpoints re-implemented with **CTranslate2** for fast inference. These are the exact CT2 artifacts that WhisperX (and `faster-whisper`) load under the hood, so "WhisperX model" and "faster-whisper model" here refer to the same on-disk weights. They are downloaded locally so the harness runs **fully offline** once set up. See [`Skills/acquire_assets.py`](#6-acquisition-skill-skillsacquire_assetspy) for the one-command downloader/verifier/smoke-tester.

### Models Under Test (Systran `faster-whisper` collection)
The full collection is the 15 repositories below, mirrored from <https://huggingface.co/collections/Systran/faster-whisper>. The acquisition skill exposes each via a short alias and offers presets (`all`, `core`, `multilingual`, `english`, `distil`).

| Alias | Hugging Face repo | Family |
|-------|-------------------|--------|
| `tiny` | `Systran/faster-whisper-tiny` | Multilingual |
| `base` | `Systran/faster-whisper-base` | Multilingual |
| `small` | `Systran/faster-whisper-small` | Multilingual |
| `medium` | `Systran/faster-whisper-medium` | Multilingual |
| `large-v1` | `Systran/faster-whisper-large-v1` | Multilingual |
| `large-v2` | `Systran/faster-whisper-large-v2` | Multilingual |
| `large-v3` | `Systran/faster-whisper-large-v3` | Multilingual |
| `tiny.en` | `Systran/faster-whisper-tiny.en` | English-only |
| `base.en` | `Systran/faster-whisper-base.en` | English-only |
| `small.en` | `Systran/faster-whisper-small.en` | English-only |
| `medium.en` | `Systran/faster-whisper-medium.en` | English-only |
| `distil-small.en` | `Systran/faster-distil-whisper-small.en` | Distil |
| `distil-medium.en` | `Systran/faster-distil-whisper-medium.en` | Distil |
| `distil-large-v2` | `Systran/faster-distil-whisper-large-v2` | Distil |
| `distil-large-v3` | `Systran/faster-distil-whisper-large-v3` | Distil |

> **Offline wiring:** after download, point each entry in `Code/config.py` at its **local path** under `models/` (e.g. `models/faster-whisper-large-v3`). `faster-whisper`/WhisperX accept a directory path as the model identifier, which keeps benchmark runs network-free and reproducible.

### ⚠️ Target Hardware & Quantization Logic
The program auto-detects device availability and enforces strict, safe quantization settings matching the target hardware. Device selection drives a **dual-device sweep**:

| `--device` | What runs | Order |
|-----------|-----------|-------|
| `auto` (default) / `both` | GPU pass **then** CPU pass when a GPU is detected; CPU only when none is | GPU first, then CPU |
| `cuda` | GPU pass only (errors if no GPU is visible) | — |
| `cpu` | CPU pass only, **even when a GPU is attached** (device forced to `cpu`; the external card need not be disconnected) | — |

Running every model on the GPU and then again on the CPU in a single invocation yields performance figures for both scenarios — laptop **with** the external video card attached, and laptop **without** it — written as separate, device-tagged rows in `summary.csv`. The mandatory compute_type for each pass:

| Device | compute_type | Hardware Details | Notes |
|--------|--------------|------------------|-------|
| `cuda` | `float16` | NVIDIA RTX 5060 Ti 16 GB (Blackwell, sm_120) | **CRITICAL:** `int8` quantization **crashes** on sm_120 with `CUBLAS_STATUS_NOT_SUPPORTED`. Use `float16`. |
| `cpu` | `int8` (default), `int16`, or `float32` | Any general CPU machine | **CRITICAL:** `float16` is **GPU-only** in CTranslate2 and fails on CPU. |

Any illegal combinations (e.g., `int8` on CUDA or `float16` on CPU) must be intercepted immediately at launch, raising clear errors instead of failing mid-execution. The sweep is implemented by `Skills/manage_device.plan_device_passes()` (§5.C.4); the orchestrator loops over its passes and calls `engine.unload()` between them to free GPU memory before the CPU pass begins.

---

## 2. Environment Setup

To ensure safety and isolate dependencies, everything must run inside a Python virtual environment.

### Step-by-Step Environment Bootstrapping:
```bash
# 1. Ensure uv is installed (pip install uv) and run uv sync
uv sync

# This will create a .venv and install all core packages listed in pyproject.toml
# (including standard PyTorch, metric, and offline audio drivers)
```

> **Notes:**
> - `huggingface_hub` provides the modern **`hf`** command-line tool (the former `huggingface-cli`, now deprecated) used to pull the Systran models. `Skills/acquire_assets.py` will install/upgrade it automatically if it is missing, so this line is a convenience, not a hard prerequisite.
> - `faster-whisper` is listed explicitly for clarity even though `whisperx` already depends on it; the acquisition skill's smoke test loads models through it directly.
> - Optional download speed-up: `pip install "huggingface_hub[hf_xet]"` enables Xet-accelerated transfers for the larger `large-v*` weights.

---

## 3. High-Resilience & Progress State Contracts

### A. Agentic Development Progress (`agent_progress.json`)
To protect against sudden power loss during the development loop, the automated developer (local LLM) maintains a progress JSON file in the root workspace. The agent updates this file upon completing each phase.

```json
{
  "current_stage": "Stage 3: Core Metric Accumulator Skill",
  "last_updated": "2026-06-26T20:50:00Z",
  "overall_status": "in_progress",
  "stages": {
    "Stage 1: Basic Scaffolding": "completed",
    "Stage 2: Basic Utility Skills": "completed",
    "Stage 3: Core Metric Accumulator Skill": "in_progress",
    "Stage 4: Code Scaffolding & Config": "pending",
    "Stage 5: Resilient Writer & Mock Engine": "pending",
    "Stage 6: Loop Orchestration & Simulation": "pending",
    "Stage 7: Real ASR Engine Integration": "pending"
  },
  "completed_skills": [
    "profile_audio.py",
    "normalize_text.py",
    "manage_device.py",
    "gemini_escalation.py"
  ],
  "completed_code_modules": [],
  "tests_passed": {
    "unit_tests_skills": false,
    "dry_run_simulation": false,
    "resiliency_recovery": false
  },
  "metadata": {
    "consecutive_failures": 0
  }
}
```

### B. Run-Level Crash Resilience (Line-Buffered Flush)
To protect against system crashes mid-benchmark, the CSV loggers must operate as a transactional write-ahead logger:
1. **No Buffering:** Set `buffering=1` (line-buffered) in `open()` or call `csv_file.flush()` immediately followed by `os.fsync(csv_file.fileno())` after every written utterance row. This guarantees the OS commits the entry to physical disk immediately.
2. **Double-Verification (Resume Logic):** At startup with `--resume` active (default), the engine parses `details.csv`. It extracts all finished keys `(model, dataset, utt_id)`. Any matching records are filtered out of the active queue.
3. **Truncation Cleanup:** Before resuming, the parser checks if the last line of `details.csv` is malformed/incomplete. If so, it safely truncates the file back to the last complete row, preventing parser errors.

---

## 4. Proposed Modular File Directory Structure

```
/home/hughmann/FirstProgram/
├── agent_progress.json             # Global progress monitor (resiliency)
├── validate_workspace.py           # AST syntax checking script
├── requirements.txt                # Dependency definitions
├── asr_benchmark_master_blueprint.md # This blueprint document
│
├── Specs/
│   ├── asr_benchmark_harness_spec.md # Original specification
│   └── api_cheat_sheet.md          # Jiwer 3.0+ and WhisperX schema API guide
│
├── Skills/                         # Standalone, reusable mathematical/hardware modules
│   ├── profile_audio.py            # FLAC audio duration profiling
│   ├── normalize_text.py           # Text cleaner (Whisper normalizer with Fallback)
│   ├── compute_wer_cer.py          # Math accumulator (true corpus-level WER/CER)
│   ├── manage_device.py            # Device routing and Blackwell safety enforcer
│   ├── gemini_escalation.py        # Stuck-state detector & cost-controlled Gemini escalation
│   ├── acquire_assets.py           # Installs hf CLI; downloads+verifies models & LibriSpeech; smoke-tests
│   ├── setup_github.py             # One-time Git/GitHub setup: identity, remote, auth, .gitignore, PII hook
│   ├── check_no_pii.py             # PII/secret scanner & pre-commit gate (blocks leaks to Git/docs)
│   └── publish_report.py           # Generates a Markdown report from summary.csv; PII-gated commit + push
│
├── reports/                        # Generated benchmark reports (committed by publish_report.py)
│   ├── INDEX.md                    # Running list of all reports
│   └── report_<UTC>.md             # One timestamped report per run
│
├── .gitignore                      # Managed by setup_github.py (excludes models/, data/, secrets, ...)
├── .pii-allow                      # Optional allowlist for known-safe scanner matches
│
├── Code/                           # Core benchmark harness package
│   ├── __init__.py
│   ├── config.py                   # Model configuration & dataclasses
│   ├── datasets.py                 # Seeded LibriSpeech dataset loading & subsetting
│   ├── engines.py                  # Core TranscriptionEngine ABC & WhisperX wrapper
│   ├── mock_engine.py              # Offline mock transcription simulator
│   ├── writer.py                   # High-resiliency, disk-synced CSV writer
│   └── main.py                     # CLI loop orchestrator and console reporter
│
└── tests/                          # Automated Unit & Integration Tests
    ├── run_unit_tests.py           # Core test runner
    ├── test_skills.py              # Verifies math aggregates, device guards, and text filters
    └── test_resiliency.py          # Verifies recovery from simulated power-cut interruptions

# ── Generated assets (created by Skills/acquire_assets.py; git-ignore these) ──
models/                             # Local CTranslate2 faster-whisper weights
├── faster-whisper-tiny/
├── faster-whisper-base/
├── ...                             # one folder per downloaded Systran repo
└── faster-whisper-large-v3/        #   each holds model.bin, config.json, tokenizer.json, ...

data/                               # LibriSpeech corpora (and transient archives)
└── LibriSpeech/
    ├── test-clean/                 # extracted; datasets.py rglob's *.trans.txt here
    └── test-other/
```

> `models/` and `data/` are large, reproducible, and must never be committed. `Skills/setup_github.py` writes a managed `.gitignore` block that excludes them (plus virtualenvs, `details.csv`, the Gemini prompt, and secret/credential files). Generated **reports** under `reports/` *are* committed — see §5.C.9.

---

## 5. Code Implementations & Reference Guides

### A. Third-Party API Reference Sheet (`Specs/api_cheat_sheet.md`)
```markdown
# API Reference Cheat Sheet

### 1. Jiwer (Version 3.0+)
Always use metric objects returned by process functions instead of deprecated wrappers.
```python
import jiwer
# Words scoring
w_metrics = jiwer.process_words("reference text", "hypothesis text")
substitutions = w_metrics.substitutions
deletions = w_metrics.deletions
insertions = w_metrics.insertions
hits = w_metrics.hits
wer_value = w_metrics.wer

# Characters scoring
c_metrics = jiwer.process_characters("reference text", "hypothesis text")
cer_value = c_metrics.cer
```

### 2. WhisperX Output Schema
`model.transcribe` returns a dictionary. Extract text segments correctly:
```python
result = model.transcribe(audio_arr, batch_size=batch_size)
combined_text = " ".join([seg["text"] for seg in result["segments"]]).strip()
```
```

### B. Workspace Linter (`validate_workspace.py`)
```python
import ast
import sys
from pathlib import Path

def validate_files():
    has_errors = False
    for path in Path(".").rglob("*.py"):
        if ".venv" in path.parts or "venv" in path.parts:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            print(f"✅ {path}: Syntactically Correct")
        except SyntaxError as e:
            print(f"❌ {path}: Syntax Error: {e.msg} on line {e.lineno}")
            has_errors = True
    if has_errors:
        sys.exit(1)
    print("🎉 Workspace is clean of syntax errors!")

if __name__ == "__main__":
    validate_files()
```

### C. Skills Directory

#### 1. Audio Profiler (`Skills/profile_audio.py`)
```python
from pathlib import Path
import soundfile as sf

def get_audio_duration(path: Path) -> float:
    """Reads soundfile header to retrieve duration in seconds, avoiding full file decode."""
    try:
        return sf.info(str(path)).duration
    except Exception as e:
        raise IOError(f"Failed to read audio file header for {path}: {e}")
```

#### 2. Text Normalizer (`Skills/normalize_text.py`)
```python
import jiwer

try:
    from whisper.normalizers import EnglishTextNormalizer
    _normalizer = EnglishTextNormalizer()
    def normalize_text(text: str) -> str:
        return _normalizer(text)
except ImportError:
    _fallback_pipeline = jiwer.Compose([
        jiwer.ToLowerCase(),
        jiwer.RemovePunctuation(),
        jiwer.RemoveMultipleSpaces(),
        jiwer.Strip(),
    ])
    def normalize_text(text: str) -> str:
        return _fallback_pipeline(text)
```

#### 3. Core Math Accumulator (`Skills/compute_wer_cer.py`)
This calculates true **corpus-level aggregates** (edits divided by total reference lengths).
```python
import jiwer

class CorpusMetricAccumulator:
    """Accumulates edits across all utterances to calculate true corpus-level WER/CER."""
    def __init__(self):
        # Word-level edit counters
        self.word_subs = self.word_dels = self.word_ins = self.word_hits = 0
        # Character-level edit counters
        self.char_subs = self.char_dels = self.char_ins = self.char_hits = 0
    
    def add_utterance(self, reference: str, hypothesis: str) -> tuple[float, float]:
        """
        Scores an utterance, updates global counts, and returns per-sentence (wer, cer).
        Handles empty hypotheses gracefully (forces deletions).
        """
        # Word-level metrics
        w_err = jiwer.process_words(reference, hypothesis)
        self.word_subs += w_err.substitutions
        self.word_dels += w_err.deletions
        self.word_ins += w_err.insertions
        self.word_hits += w_err.hits      
         
        # Character-level metrics
        c_err = jiwer.process_characters(reference, hypothesis)
        self.char_subs += c_err.substitutions
        self.char_dels += c_err.deletions
        self.char_ins += c_err.insertions
        self.char_hits += c_err.hits
         
        return w_err.wer, c_err.cer    
    
    @property
    def corpus_wer(self) -> float:
        total_ref_words = self.word_subs + self.word_dels + self.word_hits
        if total_ref_words == 0:
            return 0.0
        return (self.word_subs + self.word_dels + self.word_ins) / total_ref_words   
    
    @property
    def corpus_cer(self) -> float:
        total_ref_chars = self.char_subs + self.char_dels + self.char_hits
        if total_ref_chars == 0:
            return 0.0
        return (self.char_subs + self.char_dels + self.char_ins) / total_ref_chars
```

#### 4. Hardware Manager (`Skills/manage_device.py`)
```python
import torch

def detect_device(requested_device: str = "auto") -> str:
    """Resolves auto to cuda (if GPU available) or cpu. Validates explicit cuda requests."""
    if requested_device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    
    if requested_device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("Explicit CUDA requested, but PyTorch cannot find an active GPU.")
        return "cuda"
    
    return "cpu"

def determine_compute_type(device: str, requested_type: str | None) -> str:
    """Determines best quantization type or validates explicitly requested types."""
    if requested_type is None:
        return "float16" if device == "cuda" else "int8"
    
    if device == "cuda" and requested_type == "int8":
        raise ValueError("Invalid configuration: int8 quantization on sm_120 causes cuBLAS crashes. Use float16 on GPU.")
    if device == "cpu" and requested_type == "float16":
        raise ValueError("Invalid configuration: float16 is GPU-only under CTranslate2. Use int8, int16, or float32.")
        
    return requested_type

def gpu_available() -> bool:
    """True only if PyTorch can see a usable CUDA GPU."""
    try:
        return torch.cuda.is_available() and torch.cuda.device_count() > 0
    except Exception:
        return False

def plan_device_passes(requested_device: str = "auto") -> list[tuple[str, str]]:
    """Resolve a device request into an ORDERED list of (device, compute_type)
    passes to benchmark.

        auto / both : GPU pass FIRST (if a GPU is detected) then a CPU pass, so
                      performance is captured both with the external card
                      attached and on CPU alone. CPU-only when no GPU exists.
        cuda        : GPU pass only (raises if no GPU is visible).
        cpu         : CPU pass only, even when a GPU is attached — the device is
                      forced to "cpu", so the external card does NOT need to be
                      physically disconnected to collect CPU-only numbers.

    compute_type is fixed by the safety rules above (cuda->float16, cpu->int8).
    """
    req = requested_device.lower()
    if req == "cpu":
        return [("cpu", determine_compute_type("cpu", None))]
    if req == "cuda":
        detect_device("cuda")  # raises RuntimeError if no GPU is visible
        return [("cuda", determine_compute_type("cuda", None))]
    if req in ("auto", "both"):
        passes: list[tuple[str, str]] = []
        if gpu_available():
            passes.append(("cuda", determine_compute_type("cuda", None)))
        passes.append(("cpu", determine_compute_type("cpu", None)))
        return passes
    raise ValueError(f"Unknown device request {requested_device!r} "
                     "(use auto, both, cuda, or cpu).")
```

> **Dual-device sweep.** `plan_device_passes` is what makes the harness benchmark the GPU *then* the CPU automatically. Because CTranslate2 honours an explicit `device="cpu"`, the CPU pass runs correctly whether or not the external GPU is attached — the card never has to be unplugged. Each pass is tagged with its own `device`/`compute_type`, so `summary.csv` ends up with one set of rows per scenario.

#### 5. Cost-Gated Stuck Escalation Portal (`Skills/gemini_escalation.py`)
```python
import os
import json
from pathlib import Path

PROGRESS_PATH = Path("/home/hughmann/FirstProgram/agent_progress.json")
REQUEST_PATH = Path("/home/hughmann/FirstProgram/gemini_query_prompt.md")

def check_if_stuck(consecutive_failure_threshold: int = 3) -> bool:
    """Checks agent_progress.json to determine if the local LLM is looping."""
    if not PROGRESS_PATH.exists():
        return False
        
    try:
        progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        failures = progress.get("metadata", {}).get("consecutive_failures", 0)
        return failures >= consecutive_failure_threshold
    except Exception:
        return False

def assemble_escalation_payload(stuck_module: str, error_message: str, code_snippet: str) -> str:
    prompt = f"""### SYSTEM ESCALATION: DEVELOPER ASSISTANCE REQUEST
The automated coding agent has encountered a persistent error during implementation.

**Failing Module:** `{stuck_module}`
**Error Output / Stack Trace:**
```text
{error_message}
```

**Current Implementation Code:**
```python
{code_snippet}
```

**Task Spec Context:**
Review the ASR Spec rules regarding `{stuck_module}`. 

**Instruction:**
Identify the exact bug causing this failure and provide a corrected, complete implementation of the code snippet above. Keep your response brief and direct.
"""
    return prompt

def escalate_to_gemini(prompt: str) -> str | None:
    print("\\n" + "="*60)
    print("⚠️  STUCK ALERT: The local agent has encountered repeating failures.")
    print("Proposed Question for Gemini:")
    print("-" * 60)
    print(prompt)
    print("-" * 60)
    
    REQUEST_PATH.write_text(prompt, encoding="utf-8")
    print(f"📝 Prompt saved to: {REQUEST_PATH}")
    
    user_input = input("\\nDo you approve sending this query to Gemini API? (y/n): ").strip().lower()
    
    if user_input != 'y':
        print("❌ Request cancelled by user. You can manually copy the prompt from gemini_query_prompt.md.")
        return None

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("⚠️  GEMINI_API_KEY environment variable not found.")
        print("Please resolve manually using the prompt saved in gemini_query_prompt.md, then paste the solution.")
        return None

    try:
        print("🚀 Sending approved request to Gemini...")
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        
        print("\\n✅ Response Received from Gemini:")
        print(response.text)
        return response.text
    except Exception as e:
        print(f"❌ Error communicating with Gemini API: {e}")
        return None
```

#### 6. Acquisition Skill (`Skills/acquire_assets.py`)
A single, resumable command-line Skill that prepares every external asset the harness needs. It is intentionally standard-library-only for the dataset/CLI work (so it runs before the heavy stack is installed) and imports `faster_whisper`/`jiwer` lazily for the smoke test.

**Four responsibilities**
1. **Install the `hf` CLI** — ensures `huggingface_hub` (which ships the modern `hf` command) is present in the active venv, upgrading on request. Falls back to the Python download API if the `hf` console-script isn't on `PATH`.
2. **Download the models** — pulls the Systran `faster-whisper` repos into `models/<repo-name>/` via `snapshot_download` (resumable through the HF cache). Supports presets and explicit aliases.
3. **Download the corpora** — fetches LibriSpeech `test-clean`/`test-other` from OpenSLR, **verifies MD5**, and safely extracts to `data/LibriSpeech/` (resumable via HTTP Range; mirror-failover).
4. **Smoke-test** — loads each downloaded model with `faster-whisper`, transcribes one `test-clean` utterance, and prints `load_s / proc_s / RTF / WER%`. It applies the **same Blackwell safety rules** as `manage_device.py` (CUDA→`float16`, CPU→`int8`), reusing that module if importable. By default (`--device auto`/`both`) it runs every model on the **GPU first, then the CPU** when a GPU is present (CPU only otherwise), so you get a quick attached-card vs CPU-only comparison; `--device cpu` forces CPU only without unplugging the card, and `--device cuda` does GPU only.

**Quick start**
```bash
# Everything, in order: hf → all 15 models → both corpora → smoke test
python Skills/acquire_assets.py all

# Inspect the catalogue / preview downloads without touching the network
python Skills/acquire_assets.py list
python Skills/acquire_assets.py models --preset all --dry-run

# Granular steps
python Skills/acquire_assets.py hf --upgrade
python Skills/acquire_assets.py models --preset core          # tiny,base,small,medium,large-v3
python Skills/acquire_assets.py models --models large-v3 distil-large-v3
python Skills/acquire_assets.py datasets --which test-clean   # one split only
python Skills/acquire_assets.py smoke --models large-v3       # GPU then CPU (auto)
python Skills/acquire_assets.py smoke --models large-v3 --device cpu   # CPU only, card stays attached
python Skills/acquire_assets.py smoke --models large-v3 --device cuda  # GPU only
```
All sub-commands accept `--project-root` (default: CWD), `--models-dir`, and `--data-root` *after* the sub-command. Model presets: `all` (15), `core` (5), `multilingual` (7), `english` (4), `distil` (4).

**Dataset sources & integrity** (verified against OpenSLR SLR12 — primary mirror `openslr.trmal.net`, with `www.openslr.org`, `openslr.elda.org`, and the CN mirror as automatic failovers):

| Split | Archive | Size | MD5 |
|-------|---------|------|-----|
| `test-clean` | `test-clean.tar.gz` | 346 MB | `32fa31d27d2e1cad72775fee3f4849a9` |
| `test-other` | `test-other.tar.gz` | 328 MB | `fb5a50374b501bb3bac4815ee91d3135` |

> ⚠️ **Note on the source URLs:** both download links were originally pasted as `test-clean.tar.gz`. The correct second link is `https://openslr.trmal.net/resources/12/test-other.tar.gz` — that is what this skill uses, and the MD5 above (`fb5a5037…`, *not* the test-clean hash) is what it verifies.

The skill is safe to `Ctrl-C` at any point: model pulls resume from the HF cache, dataset downloads resume from the partial `.part` file, and already-extracted splits / already-present models are skipped on re-run.

#### 7. GitHub Setup Skill (`Skills/setup_github.py`)

A one-time, idempotent setup skill that wires the project to GitHub so results can be published. Standard-library-only; no `PyGithub` dependency.

**Responsibilities** — verifies `git`; sets the commit identity; initialises the repo (branch `main`); writes the **managed `.gitignore`** block; sets the `origin` remote; configures **authentication**; installs the PII pre-commit hook; and verifies connectivity with `git ls-remote`.

**Authentication** is auto-detected (override with `--method`):
- `gh` — uses the GitHub CLI credential helper (`gh auth setup-git`). Recommended.
- `ssh` — verifies an SSH key and `git@github.com` access.
- `token` — stores a PAT through the OS keychain helper. The token is read from `GITHUB_TOKEN`/`GH_TOKEN` or a hidden prompt and fed to `git credential approve` over **stdin**; it is *never* placed in the remote URL, in argv, or in `.git/config`. With no keychain helper it falls back to the in-memory `cache` helper (1 h) unless `--persist-plaintext` is given.

```bash
# Full setup in one go
python Skills/setup_github.py init \
    --remote https://github.com/<you>/asr-benchmark.git \
    --name "Your Name" --email you@example.com

python Skills/setup_github.py doctor          # diagnose current state
python Skills/setup_github.py gitignore       # (re)write the managed block
python Skills/setup_github.py auth --method gh
python Skills/setup_github.py hook            # install the PII pre-commit hook
python Skills/setup_github.py verify          # test the origin connection
```

#### 8. PII / Secret Guard (`Skills/check_no_pii.py`)

Confirms that **no Personally Identifiable Information (PII) and no secrets** reach Git or shipped documentation. Runs three ways: as a **git pre-commit hook** (installed by this skill or `setup_github.py`), as the **gate** called by `publish_report.py`, and **standalone** to audit any file or directory.

**Detects** — emails, phone numbers, US SSNs, Luhn-validated credit-card numbers, IPv4 addresses, and `/home/<user>/`-style path leaks (PII); plus private keys, AWS keys, GitHub PATs (classic/fine-grained/OAuth), **Google/Gemini API keys**, **Hugging Face tokens**, OpenAI keys, Slack tokens, and quoted `password=/secret=/api_key=` assignments. Findings are **redacted** in all output, so the scanner never re-prints the secret it just found.

> Two project-specific tunings: LibriSpeech utterance IDs like `1089-134686-0000` are explicitly **not** mistaken for credit cards (card matches with separators must follow standard 4-4-4-4 / Amex groupings), and the Gemini `AIza…` key shape used by `gemini_escalation.py` is a first-class detector.

**Allowlisting false positives** — a repo-root `.pii-allow` file (literal substrings, or `re:`-prefixed regexes), or an inline `# pii-allow` token on the offending line.

```bash
python Skills/check_no_pii.py staged          # what's staged (hook mode)
python Skills/check_no_pii.py tracked          # every tracked file
python Skills/check_no_pii.py path reports/ docs/   # arbitrary docs
python Skills/check_no_pii.py --install-hook   # wire up the pre-commit hook
python Skills/check_no_pii.py staged --strict  # also fail on low-severity
```

Exit code is **0** when clean and **1** when blocking findings remain (medium severity and above by default), so it doubles as a commit/CI gate. Emergency bypass: `git commit --no-verify`.

#### 9. Report Publisher (`Skills/publish_report.py`)

Turns `summary.csv` into a clean, timestamped **Markdown report**, gates it through the PII scanner, and commits + pushes it. Each run writes its **own** `reports/report_<UTC>.md` (a separate commit) and updates `reports/INDEX.md`, so the repo keeps a full benchmark history.

**Pipeline:** `summary.csv → reports/report_<UTC>.md → PII gate → git commit + push`. If the gate finds anything, **publishing is aborted** (override only with the explicit, discouraged `--no-gate`). The hostname and user are omitted from reports by default to avoid leaking identity.

**Where reports land:**
- Default — committed to the **current branch** under `reports/` (also includes `summary.csv`).
- `--branch <name>` — committed to a **separate branch** via a throwaway `git worktree`, leaving the working tree and current branch untouched. Add `--orphan` for an independent history (only the report files are tracked).

```bash
python Skills/publish_report.py report                 # preview Markdown only (no git)
python Skills/publish_report.py publish                 # gate → commit → push (current branch)
python Skills/publish_report.py publish --no-push       # commit locally only
python Skills/publish_report.py publish --branch reports # keep reports on their own branch
```

> The publisher runs its own PII gate *before* committing, which is what guarantees report safety. The pre-commit hook is a second line of defence; in a `--orphan` worktree it self-skips (the scanner file isn't checked out there) and the gate still covers the content.

### D. Code Directory (Skeletons to Implement)

#### 1. Core Transcription Abstract class & Mock Simulator (`Code/mock_engine.py`)
```python
import time
from pathlib import Path

class TranscriptionEngine:
    def load(self) -> float: raise NotImplementedError()
    def transcribe(self, audio_path: Path, reference_text: str = "") -> tuple[str, float, float]: raise NotImplementedError()
    def unload(self) -> None: raise NotImplementedError()
    def settings(self) -> str: raise NotImplementedError()

class MockWhisperXEngine(TranscriptionEngine):
    """Offline mock engine that runs on CPU instantly. Returns mock text matching reference length."""
    def __init__(self, arch: str, device: str, compute_type: str = "int8", beam_size: int = 5):
        self.arch = arch
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.is_loaded = False

    def load(self) -> float:
        t = time.perf_counter()
        time.sleep(0.1)  # Simulate fast loading
        self.is_loaded = True
        return time.perf_counter() - t

    def transcribe(self, audio_path: Path, reference_text: str = "MOCK REF") -> tuple[str, float, float]:
        import soundfile as sf
        audio_len = sf.info(str(audio_path)).duration
        proc_time = audio_len * 0.10  # Simulate processing at 10x real-time
        time.sleep(0.01)  # Brief sleep for testing speed
        return reference_text.upper(), audio_len, proc_time

    def unload(self) -> None:
        self.is_loaded = False

    def settings(self) -> str:
        return f"{self.device}/{self.compute_type} (mocked), beam_size {self.beam_size}"
```

#### 2. Resilient Writer (`Code/writer.py`)
```python
import os
import csv
from pathlib import Path

class ResilientCSVWriter:
    """
    Handles transactional, write-ahead, line-buffered writing to details.csv and summary.csv.
    Enforces immediate physical storage commit to prevent cached data loss on power cuts.
    """
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.details_path = self.output_dir / "details.csv"
        self.summary_path = self.output_dir / "summary.csv"
        self._init_headers()

    def _init_headers(self):
        # Header definitions matching spec §10
        det_head = ["model", "arch", "compute_type", "beam_size", "device", "dataset", "utt_id", "audio_s", "proc_s", "rtf", "wer", "cer", "hypothesis", "reference", "error"]
        sum_head = ["timestamp", "model", "arch", "compute_type", "beam_size", "device", "batch_size", "dataset", "n_utts", "total_audio_s", "load_s", "total_proc_s", "rtf", "wer", "cer"]
        
        if not self.details_path.exists():
            with open(self.details_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(det_head)
        if not self.summary_path.exists():
            with open(self.summary_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(sum_head)

    def write_detail_row(self, row: dict):
        """Writes one row and immediately flushes + syncs it to the physical disk."""
        fields = ["model", "arch", "compute_type", "beam_size", "device", "dataset", "utt_id", "audio_s", "proc_s", "rtf", "wer", "cer", "hypothesis", "reference", "error"]
        with open(self.details_path, "a", newline="", encoding="utf-8", buffering=1) as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writerow(row)
            # Guarantee physical write to disk
            f.flush()
            os.fsync(f.fileno())

    def write_summary_row(self, row: dict):
        """Writes summary record and immediate physical disk commit."""
        fields = ["timestamp", "model", "arch", "compute_type", "beam_size", "device", "batch_size", "dataset", "n_utts", "total_audio_s", "load_s", "total_proc_s", "rtf", "wer", "cer"]
        with open(self.summary_path, "a", newline="", encoding="utf-8", buffering=1) as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())

    def parse_existing_runs(self) -> set[tuple[str, str, str, str, str]]:
        """
        Reads details.csv to retrieve already finished keys
        (model, dataset, utt_id, device, compute_type) to skip redundant
        calculations. Including device + compute_type is essential for the
        GPU-then-CPU sweep: the same utterance is benchmarked once per device,
        so a 3-tuple key would make the CPU pass skip everything the GPU pass
        already wrote.
        Safely ignores the last line if it is corrupt/half-written, truncating the file back to safety.
        """
        completed_keys = set()
        if not self.details_path.exists():
            return completed_keys

        # Check and handle half-written lines
        lines = self.details_path.read_bytes().splitlines()
        if not lines:
            return completed_keys

        valid_lines = []
        for line in lines:
            try:
                decoded = line.decode("utf-8")
                # Ensure it is a valid CSV line with the exact expected comma count
                if len(list(csv.reader([decoded]))[0]) == 15:
                    valid_lines.append(line)
            except Exception:
                continue

        # If we detected half-written corrupt rows, rewrite the file safely
        if len(valid_lines) < len(lines):
            print(f"⚠️  Detected {len(lines) - len(valid_lines)} corrupt or half-written row(s). Recovering and truncating details.csv...")
            self.details_path.write_bytes(b"\n".join(valid_lines) + b"\n")

        # Parse completed runs
        with open(self.details_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("error") == "" or row.get("error") is None:
                    completed_keys.add((row["model"], row["dataset"], row["utt_id"],
                                        row["device"], row["compute_type"]))
        return completed_keys
```

#### 3. Device-Sweep Orchestrator (`Code/main.py`)

`main.py` resolves the requested device into passes with `plan_device_passes()` and runs them **in order** — GPU first, then CPU — reusing the resilient writer and the device-aware resume key. Each pass loads the model on its own device and unloads it (freeing GPU memory) before the next pass starts, so the CPU pass runs cleanly with the external card still attached.

```python
from Skills.manage_device import plan_device_passes

def run_benchmark(args, dataset, writer, build_engine):
    passes = plan_device_passes(args.device)          # e.g. [("cuda","float16"), ("cpu","int8")]
    print("Device passes:", " → ".join(f"{d}/{c}" for d, c in passes))
    done = writer.parse_existing_runs()               # 5-tuple keys incl. device + compute_type

    for device, compute_type in passes:
        scenario = "external GPU attached" if device == "cuda" else "CPU only (card may stay plugged in)"
        print(f"\n=== Pass: {device}/{compute_type}  ({scenario}) ===")
        engine = build_engine(args.model, device=device,
                              compute_type=compute_type, beam_size=args.beam_size)
        try:
            n = total_audio = total_proc = 0.0
            t_load = engine.load_seconds                # captured during build_engine
            for utt in dataset:
                key = (args.model, args.dataset, utt.id, device, compute_type)
                if key in done:                         # resume: skip per-device, not globally
                    continue
                result = engine.transcribe(utt.audio)   # -> hypothesis + timing
                writer.write_detail_row({
                    "model": args.model, "device": device, "compute_type": compute_type,
                    "dataset": args.dataset, "utt_id": utt.id, ...,
                })
                n += 1; total_audio += utt.duration; total_proc += result.proc_s
            writer.write_summary_row({
                "model": args.model, "device": device, "compute_type": compute_type,
                "dataset": args.dataset, "n_utts": n, "total_audio_s": total_audio,
                "load_s": t_load, "total_proc_s": total_proc,
                "rtf": (total_proc / total_audio) if total_audio else "", ...,
            })
        finally:
            engine.unload()        # del model; gc.collect(); torch.cuda.empty_cache() under guards
```

The result: a single `python -m Code.main` invocation produces one summary row per `(model, dataset, device)`. When no GPU is present, `plan_device_passes` returns just the CPU pass, so the same code runs unchanged on a CPU-only machine. `Skills/publish_report.py` already groups its table by `device`/`compute_type`, so the generated report shows the attached-GPU and CPU-only results next to each other.

---

## 6. Execution Stages Checklist for the Local LLM Session

When you initialize your new session, feed this plan to your LLM and instruct it to execute the steps one by one.

### ➔ Phase 1: Dependency Setup & Verification
1. Create the `venv` virtual environment and run the pip installation command specified in Section 2.
2. Confirm the environment is fully active.

### ➔ Phase 1B: Asset Acquisition (Models + Corpora)
1. Run `python Skills/acquire_assets.py list` to confirm the catalogue, then `... models --preset all --dry-run` to preview the 15 downloads.
2. Download the models and corpora: `python Skills/acquire_assets.py all` (or run the `hf`, `models`, and `datasets` sub-commands individually). This installs the `hf` CLI if needed, fetches the Systran `faster-whisper` weights into `models/`, and downloads + MD5-verifies + extracts `test-clean`/`test-other` into `data/LibriSpeech/`.
3. Confirm the smoke test prints a sane `WER%`/`RTF` per model (it runs automatically at the end of `all`, or via `... smoke`). On the RTX 5060 Ti this must use `compute_type=float16` — the skill enforces this and will reject `int8` on `sm_120`.
4. Note: this phase is **not** required for the Phase 4 mock run (which is zero-download); it is the prerequisite for the real Phase 5 GPU benchmark.

### ➔ Phase 2: Core Skills Setup (Skills Modules)
1. Complete `profile_audio.py` and `normalize_text.py`.
2. Complete `manage_device.py`. Ensure illegal quantization patterns throw detailed `ValueError` exceptions immediately on CPU/GPU conflicts, and implement `plan_device_passes()` (the GPU-then-CPU sweep planner).
3. Complete `compute_wer_cer.py` and ensure the mathematically correct corpus aggregation runs cleanly.
4. Run unit tests (`pytest tests/test_corpus_metrics.py`) to mathematically verify that corpus-level WER/CER is calculated instead of line averages.

### ➔ Phase 3: Dataset Loading & Setup Options (`Code/config.py` & `Code/datasets.py`)
1. Create `Code/config.py` options including Display Model lists.
2. Build the LibriSpeech directory parser in `Code/datasets.py` (`load_librispeech` using `Path.rglob("*.trans.txt")`). Include the deterministic seeded sub-sampling routine (`random.Random(seed)`).

### ➔ Phase 4: Mock Execution & Integration Tests (Zero-Download Verification)
1. Set up `Code/mock_engine.py` and connect it to `Code/writer.py`.
2. Build `Code/main.py` core orchestrator. It must loop over `plan_device_passes(args.device)` (GPU pass then CPU pass) and use the device-aware 5-tuple resume key so each device is benchmarked independently.
3. Run a complete offline simulation using `python -m Code.main --device cpu --limit 5` with the Mock Engine to verify that console reports output cleanly, and `details.csv` / `summary.csv` write perfectly. Also run `--device both --limit 5` to confirm the mock produces a CPU row (and, on a GPU box, a CUDA row first).
4. **Resiliency Test:** Interrupt the dry-run, restart it, and assert that the resume functionality reads the previous lines, ignores half-written lines, and successfully skips already transcribed utterances **per device** (the CPU pass must not be skipped because the GPU pass finished those utterances).

### ➔ Phase 5: Production GPU Deployment (`Code/engines.py`)
1. Implement the real `WhisperXEngine` inside `Code/engines.py`. Load each model from its **local path** under `models/` (downloaded in Phase 1B) so runs stay offline, e.g. `whisperx.load_model("models/faster-whisper-large-v3", device, compute_type=compute_type)` where `(device, compute_type)` comes from the current pass.
2. Integrate memory-reclaim mechanics (`unload()`: delete references, run `gc.collect()`, and execute `torch.cuda.empty_cache()` inside safety guards). This runs between the GPU and CPU passes so the CPU pass starts with GPU memory freed.
3. Switch the mock engine to the live system and run `python -m Code.main` (default `--device auto`) against the `data/LibriSpeech/` corpora. With the external card attached this benchmarks **GPU then CPU automatically**, writing both attached-GPU and CPU-only metrics; on a machine with no GPU it collects CPU-only metrics with the identical command. Use `--device cpu` to force a CPU-only run without unplugging the card, or `--device cuda` for GPU only.

### ➔ Phase 6: Reporting & Safe Publishing (`Skills/setup_github.py`, `check_no_pii.py`, `publish_report.py`)
1. **One-time setup:** run `python Skills/setup_github.py init --remote <url> --name "…" --email "…"`. This sets identity, writes the managed `.gitignore`, configures auth (`gh`/`ssh`/`token`), and installs the PII pre-commit hook. Confirm with `setup_github.py doctor` and `verify`.
2. **Audit before first push:** run `python Skills/check_no_pii.py tracked` (and `path` over any loose docs) to confirm no PII/secrets are already present. Add intentional exceptions to `.pii-allow`. Remember `details.csv` and `gemini_query_prompt.md` are git-ignored by design.
3. **Publish each run:** after a benchmark completes, run `python Skills/publish_report.py publish` to generate `reports/report_<UTC>.md`, gate it, and push. Use `--branch reports` to keep reports on their own branch, or `--no-push` to stage commits for review first.
4. The pre-commit hook independently blocks any future commit that would leak PII/secrets, so the protection holds even for manual `git commit`s outside this skill.
