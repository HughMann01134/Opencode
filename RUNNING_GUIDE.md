# Step-by-Step Guide: Running the ASR Benchmark Harness

This guide will walk you through setting up your environment and running the benchmark using both the mock engine (for quick verification) and the real `whisperx` engine.

**Path Note:** This guide uses the template paths `<project_root>` and `<venv_path>` (historically `/mnt/d/Opencode/` and `/tmp/opencode/.venv/`). Please substitute your own project root and virtual environment paths as appropriate for your machine.

---

#### **Phase 1: Environment Setup (One-Time)**

1.  **Prerequisites Check:**
    *   Ensure **Python 3.9+** is installed.
    *   Ensure **`ffmpeg`** is installed on your system (e.g., `sudo apt-get update && sudo apt-get install -y ffmpeg` on Ubuntu/Debian).

2.  **Create and Activate Virtual Environment:**
    Set up your virtual environment. For example:

    ```bash
    # Navigate to your project root
    cd <project_root>

    # If the virtual environment does not exist, create it:
    python3 -m venv <venv_path>

    # You can activate it:
    source <venv_path>/bin/activate
    ```

3.  **Install Project Dependencies:**
    Install all required Python packages into your virtual environment.

    ```bash
    cd <project_root>
    <venv_path>/bin/pip install -r requirements.txt
    ```

4.  **Install Project in Editable Mode:**
    This ensures that Python correctly recognizes the `Code/` and `Skills/` directories as packages.

    ```bash
    cd <project_root>
    <venv_path>/bin/pip install -e .
    ```

---

#### **Phase 2: Running with the Mock Engine (Quick Verification)**

Use the mock engine to quickly verify that the harness orchestration, data loading, and reporting mechanisms are working correctly, without needing to download large models or datasets.

1.  **Execute Mock Benchmark:**
    This command runs the `tiny` model (mocked) on the CPU, processing only 1 utterance per split.

    ```bash
    cd <project_root>
    PYTHONPATH=<project_root> <venv_path>/bin/python -m Code.main \
        --device cpu \
        --limit 1 \
        --engine-type mock \
        --models-to-benchmark tiny \
        --no-resume
    ```
    *   **Note on Output Rotation:** Because `--no-resume` is specified, any existing `output/details.csv` and `output/summary.csv` will be automatically rotated to `<name>.bak-<UTCtimestamp>.csv` so you start with a fresh, clean set of metrics.
    *   **Expected Output:** You will see messages about loading the mock engine, processing utterances, and a summary report with `Corpus WER: 0.0000` and `Corpus CER: 0.0000`.

---

#### **Phase 3: Asset Acquisition (Required for Real Engine)**

If you haven't already, you need to download the `faster-whisper` models and LibriSpeech datasets.

1.  **Set Hugging Face Token (Optional but Recommended):**
    If you encounter download issues or rate limits, set your Hugging Face API token.

    ```bash
    export HF_TOKEN="YOUR_HUGGING_FACE_API_TOKEN"
    ```

2.  **Run the Acquisition Script:**
    This command downloads all models and datasets.

    ```bash
    cd <project_root>
    PYTHONPATH=<project_root> <venv_path>/bin/python <project_root>/Skills/acquire_assets.py all
    ```

---

#### **Phase 4: Running with the Real `whisperx` Engine**

After assets are acquired, you can run benchmarks with the actual `whisperx` engine.

1.  **Run on CPU (Limited):**
    This runs the `tiny` model on the CPU, processing 2 utterances. This will perform actual ASR transcription.

    ```bash
    cd <project_root>
    PYTHONPATH=<project_root> <venv_path>/bin/python -m Code.main \
        --device cpu \
        --limit 2 \
        --engine-type whisperx \
        --models-to-benchmark tiny \
        --no-resume
    ```

2.  **Run on Auto-Detected Device:**
    *(Warning: This multi-model GPU configuration is **not yet validated on the target hardware**)*

    ```bash
    cd <project_root>
    PYTHONPATH=<project_root> <venv_path>/bin/python -m Code.main \
        --device auto \
        --limit 5 \
        --engine-type whisperx \
        --models-to-benchmark tiny medium.en \
        --no-resume
    ```

---

#### **Phase 5: Output Schema and Checking Results**

The outputs are written to the `output/` directory as `details.csv` and `summary.csv`.

##### **`output/details.csv` Schema**
- `model`, `arch`: The benchmarked model alias and its family.
- `engine`: The transcription engine used (`mock` or `whisperx`).
- `compute_type`, `beam_size`, `device`: Transcription hyperparameters and hardware.
- `dataset`, `split`: Dataset name (`LibriSpeech`) and split name (`test-clean` or `test-other`).
- `utt_id`, `audio_s`, `proc_s`, `rtf`: Utterance ID, duration, process time, and Real-Time Factor.
- `wer`, `cer`: Utterance-level error rates.
- `hypothesis`, `reference`, `error`: Normalized output text, exact reference, and any error message if transcription failed.

##### **`output/summary.csv` Schema**
- `timestamp`: Chronological ISO 8601 UTC timestamp of the pass.
- `model`, `arch`, `engine`, `compute_type`, `beam_size`, `device`, `batch_size`, `dataset`, `split`: Pass hyperparameters.
- `n_ok`: Count of successful utterances.
- `n_failed`: Count of failed utterances (failed utterances count as empty hypothesis in overall WER/CER).
- `n_utts`: Total attempted utterances (`n_ok + n_failed`).
- `total_audio_s`, `load_s`, `total_proc_s`, `rtf`: Audio/model timing statistics computed over successful transcriptions only.
- `wer`, `cer`: True corpus-level aggregated error rates over all attempted utterances.

1.  **View Raw Results:**
    ```bash
    cat <project_root>/output/details.csv
    ```

2.  **View Summary Results:**
    ```bash
    cat <project_root>/output/summary.csv
    ```

3.  **Generate a Markdown Report:**
    Prints a formatted Markdown report based on `summary.csv`. By default, it dedupes and shows only the latest run per configuration. Pass `--all-runs` to see full history.

    ```bash
    cd <project_root>
    PYTHONPATH=<project_root> <venv_path>/bin/python <project_root>/Skills/publish_report.py report
    ```

---

#### **Phase 6: Agent Mode**

The project includes an autonomous orchestrator agent that plans and executes benchmarking goals in natural language.

1.  **Safety Guardrails:**
    *   **Whitelisted Tools:** The agent cannot execute arbitrary shell commands or code.
    *   **Human-in-the-Loop:** Approvals are required for downloading assets > 1 GB and pushing reports to remote Git unless pre-approved.
    *   **Budget Caps:** Hard limits on max turns (default 20 steps) and recovery attempts (default 2 retries per unique tool intent).

2.  **Run with Dry-Run (Demonstration):**
    Simulates successes and failure recovery without API costs or downloads:

    ```bash
    python3 -m Code.agent "benchmark tiny on cpu with limit 5 using the mock engine and generate a report without pushing" --dry-run --yes
    ```

3.  **Run with Live API Key:**
    Requires `GEMINI_API_KEY` to be set in your environment:

    ```bash
    export GEMINI_API_KEY="your_api_key_here"
    python3 -m Code.agent "benchmark tiny on cpu with limit 5 using the mock engine and generate a report without pushing" --yes
    ```
