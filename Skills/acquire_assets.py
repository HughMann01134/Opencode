

import argparse
import hashlib
import tarfile

import urllib.request
import time
import subprocess
from pathlib import Path
from typing import Literal, get_args

# Define types for clarity and validation
ModelAlias = Literal["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3",
                     "tiny.en", "base.en", "small.en", "medium.en",
                     "distil-small.en", "distil-medium.en", "distil-large-v2", "distil-large-v3"]

DatasetSplit = Literal["test-clean", "test-other"]

MODEL_CATALOG: dict[ModelAlias, dict] = {
    "tiny": {"repo": "Systran/faster-whisper-tiny", "family": "Multilingual"},
    "base": {"repo": "Systran/faster-whisper-base", "family": "Multilingual"},
    "small": {"repo": "Systran/faster-whisper-small", "family": "Multilingual"},
    "medium": {"repo": "Systran/faster-whisper-medium", "family": "Multilingual"},
    "large-v1": {"repo": "Systran/faster-whisper-large-v1", "family": "Multilingual"},
    "large-v2": {"repo": "Systran/faster-whisper-large-v2", "family": "Multilingual"},
    "large-v3": {"repo": "Systran/faster-whisper-large-v3", "family": "Multilingual"},
    "tiny.en": {"repo": "Systran/faster-whisper-tiny.en", "family": "English-only"},
    "base.en": {"repo": "Systran/faster-whisper-base.en", "family": "English-only"},
    "small.en": {"repo": "Systran/faster-whisper-small.en", "family": "English-only"},
    "medium.en": {"repo": "Systran/faster-whisper-medium.en", "family": "English-only"},
    "distil-small.en": {"repo": "Systran/faster-distil-whisper-small.en", "family": "Distil"},
    "distil-medium.en": {"repo": "Systran/faster-distil-whisper-medium.en", "family": "Distil"},
    "distil-large-v2": {"repo": "Systran/faster-distil-whisper-large-v2", "family": "Distil"},
    "distil-large-v3": {"repo": "Systran/faster-distil-whisper-large-v3", "family": "Distil"},
}

DATASET_CATALOG: dict[DatasetSplit, dict] = {
    "test-clean": {
        "archive": "test-clean.tar.gz",
        "url": "https://openslr.trmal.net/resources/12/test-clean.tar.gz",
        "md5": "32fa31d27d2e1cad72775fee3f4849a9",
        "size_mb": 346
    },
    "test-other": {
        "archive": "test-other.tar.gz",
        "url": "https://openslr.trmal.net/resources/12/test-other.tar.gz",
        "md5": "fb5a50374b501bb3bac4815ee91d3135",
        "size_mb": 328
    },
}

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent # /mnt/d/Opencode
DEFAULT_MODELS_DIR = DEFAULT_PROJECT_ROOT / "models"
DEFAULT_DATA_ROOT = DEFAULT_PROJECT_ROOT / "data"

# --- Helper Functions ---

def _install_hf_cli(upgrade: bool = False):
    """Ensures huggingface_hub is installed and its CLI is available."""
    print("Ensuring huggingface_hub CLI is installed...")
    try:
        import huggingface_hub
        print(f"huggingface_hub {huggingface_hub.__version__} is installed.")
    except ImportError:
        print("huggingface_hub not found. Please ensure it's in your pyproject.toml and run 'uv sync'.")
        return

    # Verify 'hf' command presence
    try:
        subprocess.run(["hf", "--version"], check=True, capture_output=True)
        print("hf CLI is available.")
    except FileNotFoundError:
        print("hf CLI not found on PATH. Falling back to Python API for downloads.")
    except Exception as e:
        print(f"Error verifying hf CLI: {e}")

def _download_url_with_resume(url: str, destination_path: Path):
    """Downloads a file with resume capabilities."""
    if destination_path.exists():
        print(f"  {destination_path.name} already exists. Resuming download...")
    
    temp_path = destination_path.with_suffix(".part")
    file_size = 0
    headers = {}
    if temp_path.exists():
        file_size = temp_path.stat().st_size
        headers["Range"] = f"bytes={file_size}-"
        mode = "ab"
    else:
        mode = "wb"
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            total_size = int(response.info().get("Content-Length", 0)) + file_size
            
            with open(temp_path, mode) as f:
                downloaded = file_size
                block_size = 8192
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    f.write(buffer)
                    downloaded += len(buffer)
                    # Simple progress indicator
                    if total_size > 0:
                        progress = downloaded / total_size * 100
                        print(f"\r  Downloading {destination_path.name}: {progress:.1f}% ({downloaded}/{total_size} bytes)", end="", flush=True)
            print() # New line after progress
        
        temp_path.rename(destination_path)
        print(f"  Downloaded {destination_path.name}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        raise

def _check_md5(file_path: Path, expected_md5: str) -> bool:
    """Computes MD5 hash of a file and compares it to the expected value."""
    print(f"  Verifying MD5 for {file_path.name}...")
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    actual_md5 = hash_md5.hexdigest()
    if actual_md5 == expected_md5:
        print(f"  MD5 check passed for {file_path.name}.")
        return True
    else:
        print(f"  MD5 mismatch for {file_path.name}. Expected {expected_md5}, got {actual_md5}.")
        return False

def _extract_archive(archive_path: Path, extract_to: Path):
    """Extracts a tar.gz archive."""
    print(f"  Extracting {archive_path.name} to {extract_to}...")
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=extract_to)
        print(f"  Extracted {archive_path.name}.")
    except Exception as e:
        print(f"Error extracting {archive_path.name}: {e}")
        raise

# --- Main Commands ---

def cmd_hf(args):
    """Installs or upgrades the huggingface_hub CLI."""
    _install_hf_cli(args.upgrade)

def cmd_models(args):
    """Downloads specified ASR models from Hugging Face."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub not found. Please ensure your environment is set up and all dependencies are installed.")
        print("You may need to run 'uv sync' and then 'python Skills/acquire_assets.py hf'.")
        return

    models_to_download: list[ModelAlias] = []
    if args.preset:
        if args.preset == "all":
            models_to_download = list(get_args(ModelAlias))
        elif args.preset == "core":
            models_to_download = ["tiny", "base", "small", "medium", "large-v3"]
        elif args.preset == "multilingual":
            models_to_download = ["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3"]
        elif args.preset == "english":
            models_to_download = ["tiny.en", "base.en", "small.en", "medium.en"]
        elif args.preset == "distil":
            models_to_download = ["distil-small.en", "distil-medium.en", "distil-large-v2", "distil-large-v3"]
        else:
            raise ValueError(f"Unknown preset: {args.preset}")
    elif args.models:
        for model_alias in args.models:
            if model_alias not in get_args(ModelAlias):
                raise ValueError(f"Unknown model alias: {model_alias}")
            models_to_download.append(model_alias)
    else:
        raise ValueError("Either --preset or --models must be specified for 'models' command.")

    args.models_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading models to {args.models_dir} (dry-run: {args.dry_run})...")

    for alias in models_to_download:
        repo_id = MODEL_CATALOG[alias]["repo"]
        model_output_path = args.models_dir / repo_id.split('/')[-1]

        if model_output_path.exists():
            print(f"  Model '{alias}' already exists at {model_output_path}. Skipping.")
            continue

        if args.dry_run:
            print(f"  [Dry Run] Would download '{repo_id}' to '{model_output_path}'")
            continue

        print(f"Downloading model: {alias} ({repo_id})...")
        try:
            snapshot_download(repo_id=repo_id, local_dir=model_output_path, local_dir_use_symlinks=False)
            print(f"  Successfully downloaded '{alias}' to {model_output_path}")
        except Exception as e:
            print(f"Error downloading model {alias} ({repo_id}): {e}")
            raise

def cmd_datasets(args):
    """Downloads and extracts LibriSpeech datasets."""
    datasets_to_download: list[DatasetSplit] = []
    if args.which:
        for split in args.which:
            if split not in get_args(DatasetSplit):
                raise ValueError(f"Unknown dataset split: {split}")
            datasets_to_download.append(split)
    else:
        # Default to both if nothing specified
        datasets_to_download = list(get_args(DatasetSplit))

    librispeech_root = args.data_root / "LibriSpeech"
    librispeech_root.mkdir(parents=True, exist_ok=True)
    print(f"Downloading datasets to {args.data_root}...")

    for split in datasets_to_download:
        data_info = DATASET_CATALOG[split]
        archive_name = data_info["archive"]
        download_url = data_info["url"]
        expected_md5 = data_info["md5"]
        
        archive_path = args.data_root / archive_name
        extract_path = librispeech_root / split # e.g., data/LibriSpeech/test-clean

        if extract_path.exists() and any(extract_path.iterdir()):
            print(f"  Dataset '{split}' already extracted to {extract_path}. Skipping.")
            continue

        if not archive_path.exists() or not _check_md5(archive_path, expected_md5):
            print(f"Downloading {archive_name} from {download_url}...")
            _download_url_with_resume(download_url, archive_path)
            if not _check_md5(archive_path, expected_md5):
                raise ValueError(f"MD5 verification failed after downloading {archive_name}.")
        else:
            print(f"  Archive {archive_name} already present and verified.")
        
        _extract_archive(archive_path, librispeech_root)
        # Clean up archive after extraction
        # print(f"  Removing archive {archive_path}...")
        # archive_path.unlink(missing_ok=True)


def cmd_smoke(args):
    """Performs a smoke test on downloaded models."""
    try:
        import faster_whisper
        import jiwer
        import torch
        from Skills.manage_device import determine_compute_type, gpu_available
    except ImportError:
        print("Required libraries (faster_whisper, jiwer, torch, Skills.manage_device) not found.")
        print("Please ensure your environment is set up and all dependencies are installed.")
        print("You may need to run 'uv sync' and then 'python Skills/acquire_assets.py hf'.")
        return

    models_to_smoke_test: list[ModelAlias] = []
    if args.models:
        for model_alias in args.models:
            if model_alias not in get_args(ModelAlias):
                raise ValueError(f"Unknown model alias: {model_alias}")
            models_to_smoke_test.append(model_alias)
    else:
        raise ValueError("At least one model must be specified for 'smoke' command using --models.")

    # Prepare a dummy audio and reference for smoke test
    # In a real scenario, this would come from the dataset
    # For now, create a dummy audio file
    dummy_audio_path = DEFAULT_PROJECT_ROOT / "temp_dummy_audio.flac"
    if not dummy_audio_path.exists():
        # Create a simple silence audio file for testing
        import soundfile as sf
        import numpy as np
        samplerate = 16000
        duration = 1 # second
        data = np.zeros(int(samplerate * duration), dtype=np.int16)
        sf.write(str(dummy_audio_path), data, samplerate)
        print(f"Created dummy audio file: {dummy_audio_path}")

    dummy_reference_text = "HELLO WORLD"
    
    passes: list[tuple[str, str]] = []
    req_device = args.device.lower()
    if req_device == "cpu":
        passes.append(("cpu", determine_compute_type("cpu", None)))
    elif req_device == "cuda":
        if not gpu_available():
            raise RuntimeError("Explicit CUDA requested, but no GPU is visible.")
        passes.append(("cuda", determine_compute_type("cuda", None)))
    elif req_device in ("auto", "both"):
        if gpu_available():
            passes.append(("cuda", determine_compute_type("cuda", None)))
        passes.append(("cpu", determine_compute_type("cpu", None)))
    else:
        raise ValueError(f"Unknown device request {args.device!r} (use auto, both, cuda, or cpu).")


    print(f"Running smoke tests (device passes: {' -> '.join(f'{d}/{c}' for d, c in passes)})...")

    for alias in models_to_smoke_test:
        repo_id = MODEL_CATALOG[alias]["repo"]
        model_path = args.models_dir / repo_id.split('/')[-1]
        
        if not model_path.exists():
            print(f"  Model '{alias}' not found at {model_path}. Skipping smoke test for this model.")
            continue

        for device, compute_type in passes:
            print(f"--- Smoke Test for {alias} on {device}/{compute_type} ---")
            model = None
            try:
                t0 = time.perf_counter()
                model = faster_whisper.WhisperModel(
                    str(model_path), 
                    device=device, 
                    compute_type=compute_type,
                    download_root=str(args.models_dir) # Ensure faster_whisper looks in our designated dir
                )
                load_s = time.perf_counter() - t0
                print(f"  Model loaded in {load_s:.2f} seconds.")

                t1 = time.perf_counter()
                segments, info = model.transcribe(
                    str(dummy_audio_path),
                    beam_size=5,
                    language="en" if ".en" in alias else None
                )
                hypothesis_segments = [seg.text for seg in segments]
                hypothesis = " ".join(hypothesis_segments).strip()
                proc_s = time.perf_counter() - t1
                
                audio_duration = 1.0 # Our dummy audio is 1 second
                rtf = proc_s / audio_duration if audio_duration > 0 else 0.0

                w_metrics = jiwer.process_words(dummy_reference_text, hypothesis)
                wer = w_metrics.wer * 100

                print(f"  Hypothesis: '{hypothesis}'")
                print(f"  Reference: '{dummy_reference_text}'")
                print(f"  Load Time: {load_s:.2f} s")
                print(f"  Processing Time: {proc_s:.2f} s")
                print(f"  RTF: {rtf:.2f}")
                print(f"  WER: {wer:.2f}%")

            except Exception as e:
                print(f"  Smoke test FAILED for {alias} on {device}/{compute_type}: {e}")
            finally:
                if model and hasattr(model, '_model'): # faster_whisper doesn't have an explicit unload, but we can try to free memory
                    del model
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                print("-" * 50)
    
    if dummy_audio_path.exists():
        dummy_audio_path.unlink()
        print(f"Removed dummy audio file: {dummy_audio_path}")


def cmd_all(args):
    """Runs all acquisition steps: hf, models (all preset), datasets, and smoke test (all models)."""
    print("Running 'hf' command...")
    cmd_hf(argparse.Namespace(upgrade=True))

    print("Running 'models --preset all' command...")
    # Create a dummy args object for models command
    models_args = argparse.Namespace(
        project_root=args.project_root,
        models_dir=args.models_dir,
        dry_run=False, # Always perform download for 'all'
        preset="all",
        models=None,
    )
    cmd_models(models_args)

    print("Running 'datasets' command...")
    datasets_args = argparse.Namespace(
        project_root=args.project_root,
        data_root=args.data_root,
        which=None, # Downloads both test-clean and test-other
    )
    cmd_datasets(datasets_args)

    print("Running 'smoke --models all' command...")
    smoke_models_to_test = list(get_args(ModelAlias))
    smoke_args = argparse.Namespace(
        project_root=args.project_root,
        models_dir=args.models_dir,
        device=args.device, # Use the device passed to 'all'
        models=smoke_models_to_test,
    )
    cmd_smoke(smoke_args)

def cmd_list(args):
    """Lists available models and datasets."""
    print("--- Available ASR Models ---")
    for alias, info in MODEL_CATALOG.items():
        print(f"  Alias: {alias:<15} Repo: {info['repo']:<40} Family: {info['family']}")
    
    print("--- Available Datasets ---")
    for split, info in DATASET_CATALOG.items():
        print(f"  Split: {split:<10} Archive: {info['archive']:<20} Size: {info['size_mb']:>4} MB")

# --- Argument Parsing ---

def main():
    parser = argparse.ArgumentParser(description="ASR Benchmark Assets Acquisition Skill")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT,
                        help=f"Project root directory (default: {DEFAULT_PROJECT_ROOT})")
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR,
                        help=f"Directory to store downloaded models (default: {DEFAULT_MODELS_DIR})")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT,
                        help=f"Directory to store downloaded data (default: {DEFAULT_DATA_ROOT})")
    parser.add_argument("--device", type=str, default="auto",
                        help="Device to use for smoke test (auto, both, cuda, cpu)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # hf command
    hf_parser = subparsers.add_parser("hf", help="Install/upgrade Hugging Face CLI")
    hf_parser.add_argument("--upgrade", action="store_true", help="Upgrade huggingface_hub package")
    hf_parser.set_defaults(func=cmd_hf)

    # models command
    models_parser = subparsers.add_parser("models", help="Download ASR models")
    models_group = models_parser.add_mutually_exclusive_group(required=True)
    models_group.add_argument("--preset", type=str, choices=["all", "core", "multilingual", "english", "distil"],
                              help="Download a preset collection of models")
    models_group.add_argument("--models", nargs="+", type=str, choices=get_args(ModelAlias),
                              help="Specific models to download by alias")
    models_parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded without actually downloading")
    models_parser.set_defaults(func=cmd_models)

    # datasets command
    datasets_parser = subparsers.add_parser("datasets", help="Download LibriSpeech datasets")
    datasets_parser.add_argument("--which", nargs="+", type=str, choices=get_args(DatasetSplit),
                                 help="Specific dataset splits to download (default: both)")
    datasets_parser.set_defaults(func=cmd_datasets)

    # smoke command
    smoke_parser = subparsers.add_parser("smoke", help="Run smoke test on downloaded models")
    smoke_parser.add_argument("--models", nargs="+", type=str, choices=get_args(ModelAlias), required=True,
                              help="Specific models to smoke test by alias")
    # smoke_parser.add_argument("--device", type=str, default="auto", # Already defined at top-level
    #                           help="Device to use (auto, both, cuda, cpu)")
    smoke_parser.set_defaults(func=cmd_smoke)

    # all command
    all_parser = subparsers.add_parser("all", help="Run all acquisition steps")
    all_parser.set_defaults(func=cmd_all)

    # list command
    list_parser = subparsers.add_parser("list", help="List available models and datasets")
    list_parser.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
