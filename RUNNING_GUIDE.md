# Step-by-Step Guide: Running the ASR Benchmark Harness

This guide will walk you through setting up your environment and running the benchmark using both the mock engine (for quick verification) and the real `whisperx` engine.

**Important:** Always execute commands from your project's root directory (`/mnt/d/Opencode/`) and ensure your virtual environment is active or Python is called with its full path.

---

#### **Phase 1: Environment Setup (One-Time)**

1.  **Prerequisites Check:**
    *   Ensure **Python 3.9+** is installed.
    *   Ensure **`ffmpeg`** is installed on your system (e.g., `sudo apt-get update && sudo apt-get install -y ffmpeg` on Ubuntu/Debian).

2.  **Create and Activate Virtual Environment:**
    If you followed the previous steps, your virtual environment is at `/tmp/opencode/.venv`. To ensure all commands use this environment:

    ```bash
    # Navigate to your project root
    cd /mnt/d/Opencode/

    # If the virtual environment does not exist, create it:
    python3 -m venv /tmp/opencode/.venv

    # You can activate it (optional, but good practice for interactive work):
    # source /tmp/opencode/.venv/bin/activate

    # Or, as we've been doing, use the full path to the Python executable for all commands.
    # We will primarily use the full path in this guide for consistency.
    ```

3.  **Install Project Dependencies:**
    Install all required Python packages into your virtual environment.

    ```bash
    cd /mnt/d/Opencode/
    /tmp/opencode/.venv/bin/pip install -r requirements.txt
    ```

4.  **Install Project in Editable Mode:**
    This ensures that Python correctly recognizes the `Code/` and `Skills/` directories as packages.

    ```bash
    cd /mnt/d/Opencode/
    /tmp/opencode/.venv/bin/pip install -e .
    ```

---

#### **Phase 2: Running with the Mock Engine (Quick Verification)**

Use the mock engine to quickly verify that the harness orchestration, data loading, and reporting mechanisms are working correctly, without needing to download large models or datasets.

1.  **Execute Mock Benchmark:**
    This command runs the `tiny` model (mocked) on the CPU, processing only 2 utterances.

    ```bash
    cd /mnt/d/Opencode/
    PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python -m Code.main \
        --device cpu \
        --limit 2 \
        --engine-type mock \
        --models-to-benchmark tiny \
        --no-resume
    ```
    *   **Expected Output:** You will see messages about loading the mock engine, processing utterances, and a summary report with `Corpus WER: 0.0000` and `Corpus CER: 0.0000` (since the mock engine returns a perfect transcription).

---

#### **Phase 3: Asset Acquisition (Required for Real Engine)**

If you haven't already, you need to download the `faster-whisper` models and LibriSpeech datasets. This can take a significant amount of time and bandwidth.

1.  **Set Hugging Face Token (Optional but Recommended):**
    If you encounter download issues or rate limits, set your Hugging Face API token.

    ```bash
    export HF_TOKEN="YOUR_HUGGING_FACE_API_TOKEN"
    ```

2.  **Run the Acquisition Script:**
    This command downloads all models and datasets. It is resumable, so if it stops, you can rerun it.

    ```bash
    cd /mnt/d/Opencode/
    PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/acquire_assets.py all
    ```
    *   **Expected Output:** Messages about downloading models and datasets. This will take a long time.

---

#### **Phase 4: Running with the Real `whisperx` Engine**

After assets are acquired, you can run benchmarks with the actual `whisperx` engine.

1.  **Run on CPU (Limited):**
    This runs the `tiny` model on the CPU, processing 2 utterances. This will perform actual ASR transcription.

    ```bash
    cd /mnt/d/Opencode/
    PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python -m Code.main \
        --device cpu \
        --limit 2 \
        --engine-type whisperx \
        --models-to-benchmark tiny \
        --no-resume
    ```
    *   **Expected Output:** You will see messages about loading the `whisperx` engine, language detection, and actual WER/CER figures in the summary. This will be slower than the mock engine.

2.  **Run on Auto-Detected Device (GPU then CPU if available, or CPU only):**
    This command runs the `tiny` and `medium.en` models. If a GPU is detected, it will run on the GPU first, then on the CPU. Otherwise, it will run only on the CPU.

    ```bash
    cd /mnt/d/Opencode/
    PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python -m Code.main \
        --device auto \
        --limit 5 \
        --engine-type whisperx \
        --models-to-benchmark tiny medium.en \
        --no-resume
    ```
    *   **Expected Output:** Similar to the CPU run, but you might see two "passes" (one for GPU, one for CPU) if a GPU is available.

---

#### **Phase 5: Checking Results and Reporting**

1.  **View Raw Results (`details.csv`):**
    ```bash
    cat /mnt/d/Opencode/output/details.csv
    ```

2.  **View Summary Results (`summary.csv`):**
    ```bash
    cat /mnt/d/Opencode/output/summary.csv
    ```

3.  **Generate a Markdown Report:**
    This will generate a formatted Markdown report based on `summary.csv` and print it to your console.

    ```bash
    cd /mnt/d/Opencode/
    PYTHONPATH=/mnt/d/Opencode /tmp/opencode/.venv/bin/python /mnt/d/Opencode/Skills/publish_report.py report
    ```
