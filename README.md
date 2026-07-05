# ASR Benchmark Harness

## Overview

The ASR Benchmark Harness is a robust Python-based tool designed to evaluate the accuracy and performance of Automatic Speech Recognition (ASR) models, specifically focusing on Systran's `faster-whisper` implementations (which leverage OpenAI Whisper checkpoints with CTranslate2 for efficient inference).

This harness allows for:
*   **Comprehensive Evaluation:** Measures Word Error Rate (WER), Character Error Rate (CER), and Real-Time Factor (RTF) against the LibriSpeech `test-clean` and `test-other`.
*   **Device Management:** Automatically detects and manages GPU (CUDA) and CPU passes, allowing for a dual-device performance sweep in a single run.
*   **Resilient Logging:** Implements transactional, CSV logging for detailed and summarized results, protecting against data loss during unexpected interruptions.
*   **PII/Secret Scanning:** Integrates a pre-commit hook and report gating to prevent sensitive information from being accidentally committed or published.
*   **Modular Design:** Composed of core Python `Code` modules and reusable `Skills` for various tasks like audio profiling, text normalization, and GitHub integration.

## Features

*   **Model Compatibility:** Built for `faster-whisper` models, supporting various multilingual and English-only architectures.
*   **Dataset Support:** Processes LibriSpeech `test-clean` and `test-other` datasets.
*   **Performance Metrics:** Calculates WER, CER, RTF, load times, and processing times.
*   **Configurable Benchmarking:** Allows selection of models, devices, batch sizes, and dataset splits via command-line arguments.
*   **Security:** Enforces PII and secret scanning before commits and report publishing.

## Setup and Installation

### Prerequisites

Before you begin, ensure you have the following installed:

*   **Git:** For version control and cloning repositories (though this project was copied, Git commands are used for committing reports).
*   **Python 3.9+:** The project is developed and tested with Python 3.12.
*   **`ffmpeg`:** Required by `whisperx` for audio decoding. Install it using your system's package manager (e.g., `sudo apt-get update && sudo apt-get install -y ffmpeg` on Debian/Ubuntu).

### Step-by-Step Installation

1.  **Create and Activate a Virtual Environment:**
    Due to specific environment permissions during development, the virtual environment was created in `/tmp/opencode/.venv`. If your environment allows, you can create it directly in your project root (`/mnt/d/Opencode/.venv`).

    ```bash
    # Create the virtual environment (if not already present)
    python3 -m venv /tmp/opencode/.venv

    # Activate the virtual environment (or use full path as below)
    # source /tmp/opencode/.venv/bin/activate
    ```

2.  **Install Project Dependencies:**
    Install all required Python packages into the virtual environment using `pip`.

    ```bash
    /tmp/opencode/.venv/bin/pip install -r /mnt/d/Opencode/requirements.txt
    ```

3.  **Install Project in Editable Mode:**
    This ensures that Python recognizes the `Code/` and `Skills/` directories as packages.

    ```bash
    /tmp/opencode/.venv/bin/pip install -e /mnt/d/Opencode
    ```

## Asset Acquisition (Models & Data)

To download all necessary `faster-whisper` models and LibriSpeech datasets:

1.  **Set Hugging Face Token (Optional but Recommended):**
    If you encounter rate limits or plan to access private models, set your Hugging Face API token as an environment variable.

    ```bash
    export HF_TOKEN="YOUR_HUGGING_FACE_API_TOKEN"
    ```

2.  **Run the Acquisition Script:**
    This command downloads all models, LibriSpeech `test-clean` and `test-other` datasets, verifies their integrity, and runs a basic smoke test. This process can take a significant amount of time and disk space.

    ```bash
    PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/acquire_assets.py all
    ```

    You can list available assets or preview downloads:
    ```bash
    PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/acquire_assets.py list
    PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/acquire_assets.py models --preset all --dry-run
    ```

## Running the Benchmark

The main entry point for the benchmark is `Code/main.py`. You can run it with various arguments.

**Important:** Always run commands from the project root (`/mnt/d/Opencode`) and set `PYTHONPATH` to ensure modules are found correctly.

### Basic Usage with Mock Engine

Run a quick benchmark using the mock engine for testing the harness itself (zero-download required):

```bash
PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python -m Code.main \
    --device cpu \
    --limit 5 \
    --engine-type mock \
    --models-to-benchmark tiny
```

### Running with Real `whisperx` Engine

To run with the actual `whisperx` models (after asset acquisition):

```bash
# Run on CPU with a small limit
PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python -m Code.main \
    --device cpu \
    --limit 10 \
    --engine-type whisperx \
    --models-to-benchmark tiny base medium

# Run on GPU (if available) then CPU, with a larger dataset
# Replace "cuda" with "auto" or "both" to enable dual-device sweep
PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python -m Code.main \
    --device auto \
    --engine-type whisperx \
    --models-to-benchmark large-v3 medium.en
```

### Command-Line Arguments

*   `--models-to-benchmark <alias> [<alias> ...]`: Specify model aliases (e.g., `tiny`, `base.en`).
*   `--device <type>`: `auto` (default, GPU then CPU if available, else CPU), `cpu`, `cuda`, `both`.
*   `--limit <int>`: Limit the number of utterances to process for quick runs.
*   `--engine-type <type>`: `mock` (default) or `whisperx`.
*   `--no-resume`: Start a fresh run, ignoring previous `details.csv` entries.
*   `--output-dir <path>`: Directory for `details.csv` and `summary.csv` (default: `/mnt/d/Opencode/output`).

### Output Files

Benchmark results are stored in the `output/` directory:
*   `output/details.csv`: Per-utterance raw results (hypothesis, reference, WER, CER, timing).
*   `output/summary.csv`: Aggregated results per model, device, and dataset.

## Reporting and Publishing

The `Skills/publish_report.py` script helps generate and publish Markdown reports.

### Generate a Local Markdown Report

To generate a Markdown report from `output/summary.csv` and print it to the console (without committing):

```bash
PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/publish_report.py report
```

### Publish a Report (Commit Locally)

To generate a report, run it through the PII scanner, and commit it to your local Git repository (without pushing to a remote):

```bash
PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/publish_report.py publish --no-push
```

This will create `reports/report_<TIMESTAMP>.md` and update `reports/INDEX.md`.

## Git Setup and PII Protection

The `Skills/setup_github.py` and `Skills/check_no_pii.py` scripts manage Git setup and enforce PII/secret scanning.

### Initial Git Setup (if not already done)

The `init` command sets up Git identity, remote, `.gitignore`, and the PII pre-commit hook.
**Note:** You would replace `<YOUR_GITHUB_REPO_URL>`, `<YOUR_NAME>`, and `<YOUR_EMAIL>` with your actual details. For authentication, `--method ssh` assumes your SSH keys are set up.

```bash
PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/setup_github.py init \
    --remote https://github.com/your-user/your-repo.git \
    --name "Your Name" \
    --email "your.email@example.com" \
    --method ssh
```

### Diagnose Git Setup

Check the current Git configuration and PII hook status:

```bash
PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/setup_github.py doctor
```

### PII/Secret Scanning

The `check_no_pii.py` script runs as a pre-commit hook (installed by `setup_github.py`) and is integrated into the `publish` command. You can also run it manually:

```bash
# Scan all tracked files (e.g., before an initial commit)
PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/check_no_pii.py tracked

# Scan specific paths
PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/check_no_pii.py path /mnt/d/Opencode/some_doc.md
```

### `.pii-allow` File

To handle false positives or acceptable PII, create a `.pii-allow` file in the project root. This file can contain literal strings or `re:`-prefixed regex patterns to be ignored by the scanner.

Example `/mnt/d/Opencode/.pii-allow`:
```
# .pii-allow file for asr-benchmark-harness

# Allow email used as placeholder
re:.*@example\.com

# Allow specific git@github.com string in setup_github.py output
re:git@github\.com

# Allow placeholder home directory paths from blueprint
re:/home/[a-zA-Z0-9_-]+/FirstProgram/

# Allow LibriSpeech utterance IDs which might resemble credit card numbers
re:\b\d{4}-\d{5}-\d{4}\b

# Allow IPv4-like version numbers and URLs in uv.lock
re:^version = "\\*+"
re:https://files\\.pythonhosted\\.org/packages/.*/nvidia_cublas_cu12-\\*+-py3-none-manylinux_2_27_x86_64\\.whl
# ... (other similar uv.lock patterns)
```

### Inline `# pii-allow:` Comments

You can also whitelist specific findings inline on the same line as the finding by appending a comment.
- **Format:** `# pii-allow:<exact_finding_text>`
- **Semantics:** The token after the colon must **exactly equal** the matched finding text (case-insensitive full-string comparison). Substrings are not supported.
- **Length Constraint:** Tokens shorter than 6 characters are ignored with a warning.

Example:
```python
my_api_key = "AIzaSyD-abcde12345"  # pii-allow:AIzaSyD-abcde12345
```

## How this project was built

This project was built using an advanced agentic software engineering workflow:
1. **Implementation Blueprint:** An exhaustive [asr_benchmark_master_blueprint.md](asr_benchmark_master_blueprint.md) was authored with Claude.
2. **First-Pass Implementation:** The system was built by Gemini 2.5 Flash driving the OpenCode interactive agent (documented in [.opencode/handoff.md](.opencode/handoff.md)).
3. **Agentic Code Review:** The initial implementation was comprehensively reviewed by a Gemini 2.5 Pro subagent ([.opencode/gemini-review.md](.opencode/gemini-review.md)).
4. **Remediation & Final Polish:** This final remediation pass was executed by Claude Code from an external review, addressing schema, failures, dataset structure, testing, and report/run hygiene.

## Current results

First real-inference benchmark matrix, executed 2026-07-04 on a fresh clone
(n=10 utterances per split, seed 42, WhisperX engine):

| Model | Device/Compute | Split | RTF | WER | CER |
|---|---|---|---|---|---|
| tiny | cpu/int8 | test-clean | 0.27 | 0.0705 | 0.0270 |
| tiny | cpu/int8 | test-other | 0.25 | 0.1767 | 0.0940 |
| tiny | cuda/float16 | test-clean | 0.09 | 0.0705 | 0.0270 |
| tiny | cuda/float16 | test-other | 0.08 | 0.1638 | 0.0882 |
| medium.en | cuda/float16 | test-clean | 0.21 | 0.0617 | 0.0410 |
| medium.en | cuda/float16 | test-other | 0.19 | 0.0991 | 0.0441 |

Highlights: `tiny` reproduces published Whisper-tiny LibriSpeech figures
(~7% clean / ~17% other), validating the measurement pipeline end to end;
`medium.en` cuts word errors on noisy speech by ~40% relative; the GPU pass
(first executed on an RTX 5060 Ti, float16) runs tiny ~3× faster than CPU;
and int8 quantization is accuracy-free on clean speech but costs ~1.3 WER
points on noisy speech.

*Caveats:* small sample (10 utterances/split); `medium.en` clean-split WER
sits above published figures (sample variance plus WhisperX's VAD-chunked
pipeline vs. the standard eval protocol); the full 15-model, full-corpus
sweep remains future work.

---

## Agent Mode

The project features a thin, fully autonomous **Agent layer** that interprets natural-language goals (e.g. *"Benchmark tiny and medium.en on whatever hardware I have and publish a report"*), formulates execution plans, calls whitelisted tools, and handles recovery (OOM fallback, asset acquisition) in a tight perceive-plan-act loop.

### Safety Model & Constraints
- **Whitelisted Tool Registry:** Zero arbitrary shell or code execution capability is granted to the LLM.
- **Human-in-the-Loop Gates:** Asset downloads > 1 GB and remote Git pushes are gated with an interactive prompt. Bypassed only via `--yes`.
- **Budget Caps:** Caps of `--max-steps` (default 20 turns) and `--max-retries` (default 2 failed attempts per intent) protect against runaway loops.
- **Full Auditability:** Every turn is logged as JSON lines in `output/agent_transcript.jsonl` with automatic PII and secret checking.

### Quickstart Command
```bash
python3 -m Code.agent "run a quick mock benchmark of tiny on cpu and report" --dry-run --yes
```

### Sample Transcript Excerpt
```json
{"timestamp": "2026-07-04T17:47:48.000Z", "event_type": "tool_call", "details": {"tool": "detect_hardware", "args": {}, "result": {"ok": true, "summary": "Detected hardware (Dry-run stub)."}}}
{"timestamp": "2026-07-04T17:47:48.100Z", "event_type": "tool_call", "details": {"tool": "run_benchmark", "args": {"models": ["tiny"], "device": "cpu", "limit": 5, "engine": "mock"}}}
{"timestamp": "2026-07-04T17:47:48.500Z", "event_type": "finish", "details": {"summary": "Completed successfully under dry-run bounds."}}
```
