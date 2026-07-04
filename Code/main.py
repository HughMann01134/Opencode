# Corrected Code/main.py content
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import torch
import gc

from Code.config import BenchmarkConfig, DEFAULT_BENCHMARK_CONFIG, MODEL_CONFIG, ModelAlias
from Code.datasets import load_librispeech
from Code.mock_engine import TranscriptionEngine, MockWhisperXEngine
from Code.engines import WhisperXEngine
from Code.writer import ResilientCSVWriter
from Skills.manage_device import plan_device_passes
from Skills.compute_wer_cer import CorpusMetricAccumulator
from Skills.normalize_text import normalize_text


def build_engine_factory(
    engine_type: Literal["mock", "whisperx"] = "mock"
) -> Callable[[ModelAlias, str, str, int], TranscriptionEngine]:
    """Returns a factory function for creating TranscriptionEngine instances."""
    def factory(model_alias: ModelAlias, device: str, compute_type: str, beam_size: int) -> TranscriptionEngine:
        model_config = MODEL_CONFIG.get(model_alias)
        if not model_config:
            raise ValueError(f"Unknown model alias: {model_alias}")
        
        if engine_type == "mock":
            return MockWhisperXEngine(model_config.alias, device, compute_type, beam_size)
        elif engine_type == "whisperx":
            return WhisperXEngine(model_config.alias, device, compute_type, beam_size)
        else:
            raise ValueError(f"Unknown engine type: {engine_type}")
    return factory


def run_benchmark(
    config: BenchmarkConfig,
    engine_factory: Callable[[ModelAlias, str, str, int], TranscriptionEngine],
):
    """Orchestrates the ASR benchmarking process.

    Args:
        config: The BenchmarkConfig instance with all settings.
        engine_factory: A factory function to create TranscriptionEngine instances.
    """
    writer = ResilientCSVWriter(config.output_dir)
    
    # Get all utterances, applying limit and seeding for reproducibility
    all_utterances = list(load_librispeech(
        config.data_root,
        config.dataset_splits,
        limit=config.limit,
        seed=config.seed,
    ))
    print(f"Loaded {len(all_utterances)} utterances from {config.dataset_splits}.")

    if config.resume_from_last_run:
        done_keys = writer.parse_existing_runs()
        print(f"Found {len(done_keys)} completed utterances from previous runs for resume.")
    else:
        done_keys = set()

    for model_alias in config.models_to_benchmark:
        print("\n" + '='*80)
        print(f"Benchmarking Model: {model_alias}")
        print('='*80)

        # Determine device passes (e.g., [("cuda","float16"), ("cpu","int8")])
        try:
            passes = plan_device_passes(config.device)
            print(f"Device passes planned: {' -> '.join(f'{d}/{c}' for d, c in passes)}")
        except RuntimeError as e:
            print(f"Skipping model {model_alias} due to device planning error: {e}")
            continue
        except ValueError as e:
            print(f"Skipping model {model_alias} due to invalid device configuration: {e}")
            continue

        for device, compute_type in passes:
            scenario = "external GPU attached" if device == "cuda" else "CPU only (card may stay plugged in)"
            print(f"\n--- Pass: {device}/{compute_type} ({scenario}) ---")
            
            engine = None
            current_pass_load_s = 0.0
            
            # Group stats and accumulators by split name
            split_stats = {}

            try:
                # Build and load engine
                engine = engine_factory(model_alias, device, compute_type, config.beam_size)
                print(f"Loading engine for {model_alias} ({device}/{compute_type})...")
                current_pass_load_s = engine.load()
                print(f"Engine loaded in {current_pass_load_s:.2f} seconds. Settings: {engine.settings()}")

                for utt in all_utterances:
                    # Key structure: (model_alias, dataset_name, utt_id, device, compute_type, split, engine_type)
                    key = (
                        model_alias,
                        config.dataset_name,
                        utt.id,
                        device,
                        compute_type,
                        utt.split,
                        config.engine_type
                    )
                    if key in done_keys:
                        # print(f"  Skipping already processed utterance: {utt.id}")
                        continue
                    
                    # Initialize stats for this split if not present
                    if utt.split not in split_stats:
                        split_stats[utt.split] = {
                            "n_ok": 0,
                            "n_failed": 0,
                            "total_audio_s": 0.0,
                            "total_proc_s": 0.0,
                            "accumulator": CorpusMetricAccumulator()
                        }
                    
                    stats = split_stats[utt.split]
                    
                    # Transcribe and collect metrics
                    try:
                        hypothesis, _, proc_s = engine.transcribe(utt.audio_path, utt.text)
                        audio_s = utt.duration # Use actual audio duration
                        
                        # Normalize texts for WER/CER calculation
                        normalized_ref = normalize_text(utt.text)
                        normalized_hyp = normalize_text(hypothesis)

                        wer_utt, cer_utt = stats["accumulator"].add_utterance(normalized_ref, normalized_hyp)

                        writer.write_detail_row({
                            "model": model_alias,
                            "arch": MODEL_CONFIG[model_alias].family,
                            "engine": config.engine_type,
                            "compute_type": compute_type,
                            "beam_size": config.beam_size,
                            "device": device,
                            "dataset": config.dataset_name,
                            "split": utt.split,
                            "utt_id": utt.id,
                            "audio_s": audio_s,
                            "proc_s": proc_s,
                            "rtf": proc_s / audio_s if audio_s else 0.0,
                            "wer": wer_utt,
                            "cer": cer_utt,
                            "hypothesis": hypothesis,
                            "reference": utt.text,
                            "error": "", # No error for successful transcription
                        })
                        stats["n_ok"] += 1
                        stats["total_audio_s"] += audio_s
                        stats["total_proc_s"] += proc_s

                    except Exception as e:
                        print(f"Error processing utterance {utt.id}: {e}")
                        # Score failure into the accumulator as an empty hypothesis
                        normalized_ref = normalize_text(utt.text)
                        wer_utt, cer_utt = stats["accumulator"].add_utterance(normalized_ref, "")

                        writer.write_detail_row({
                            "model": model_alias,
                            "arch": MODEL_CONFIG[model_alias].family,
                            "engine": config.engine_type,
                            "compute_type": compute_type,
                            "beam_size": config.beam_size,
                            "device": device,
                            "dataset": config.dataset_name,
                            "split": utt.split,
                            "utt_id": utt.id,
                            "audio_s": utt.duration,
                            "proc_s": 0.0,
                            "rtf": 0.0,
                            "wer": wer_utt,
                            "cer": cer_utt,
                            "hypothesis": "",
                            "reference": utt.text,
                            "error": str(e),
                        })
                        stats["n_failed"] += 1

                # Write summary row for each split in the current pass
                for split_name, stats in split_stats.items():
                    n_utts = stats["n_ok"] + stats["n_failed"]
                    if n_utts > 0:
                        writer.write_summary_row({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "model": model_alias,
                            "arch": MODEL_CONFIG[model_alias].family,
                            "engine": config.engine_type,
                            "compute_type": compute_type,
                            "beam_size": config.beam_size,
                            "device": device,
                            "batch_size": config.batch_size,
                            "dataset": config.dataset_name,
                            "split": split_name,
                            "n_ok": stats["n_ok"],
                            "n_failed": stats["n_failed"],
                            "n_utts": n_utts,
                            "total_audio_s": stats["total_audio_s"],
                            "load_s": current_pass_load_s,
                            "total_proc_s": stats["total_proc_s"],
                            "rtf": (stats["total_proc_s"] / stats["total_audio_s"]) if stats["total_audio_s"] else 0.0,
                            "wer": stats["accumulator"].corpus_wer,
                            "cer": stats["accumulator"].corpus_cer,
                        })
                        print(f"Summary for {model_alias} ({device}/{compute_type}) split {split_name}:")
                        print(f"  Total Utterances: {n_utts} (OK: {stats['n_ok']}, Failed: {stats['n_failed']})")
                        print(f"  Total Audio: {stats['total_audio_s']:.2f} s")
                        print(f"  Total Proc: {stats['total_proc_s']:.2f} s")
                        print(f"  RTF: {(stats['total_proc_s'] / stats['total_audio_s'] if stats['total_audio_s'] else 0.0):.2f}")
                        print(f"  Corpus WER: {stats['accumulator'].corpus_wer:.4f}")
                        print(f"  Corpus CER: {stats['accumulator'].corpus_cer:.4f}")

            except Exception as e:
                print(f"Critical error during pass for {model_alias} ({device}/{compute_type}): {e}")
            finally:
                if engine:
                    print(f"Unloading engine for {model_alias} ({device}/{compute_type})...")
                    engine.unload()
                    # Force garbage collection and empty CUDA cache if applicable
                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(
        description="ASR Benchmark Harness",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--models-to-benchmark", nargs='+', type=str, 
                        choices=list(MODEL_CONFIG.keys()),
                        default=DEFAULT_BENCHMARK_CONFIG.models_to_benchmark,
                        help="List of model aliases to benchmark.")
    parser.add_argument("--device", type=str, choices=["auto", "both", "cuda", "cpu"],
                        default=DEFAULT_BENCHMARK_CONFIG.device,
                        help="Device to use for benchmarking.")
    parser.add_argument("--batch-size", type=int, 
                        default=DEFAULT_BENCHMARK_CONFIG.batch_size,
                        help="Batch size for transcription.")
    parser.add_argument("--beam-size", type=int, 
                        default=DEFAULT_BENCHMARK_CONFIG.beam_size,
                        help="Beam size for transcription.")
    parser.add_argument("--dataset-splits", nargs='+', type=str, 
                        choices=["test-clean", "test-other"],
                        default=DEFAULT_BENCHMARK_CONFIG.dataset_splits,
                        help="Dataset splits to use.")
    parser.add_argument("--limit", type=int, 
                        help="Limit the number of utterances to process per model/split (for quick runs).")
    parser.add_argument("--no-resume", action="store_false", dest="resume_from_last_run",
                        help="Do not resume from previous runs, start fresh.")
    parser.add_argument("--output-dir", type=Path, 
                        default=DEFAULT_BENCHMARK_CONFIG.output_dir,
                        help="Directory to store output CSVs.")
    parser.add_argument("--engine-type", type=str, choices=["mock", "whisperx"], default="mock",
                        help="Type of transcription engine to use.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for dataset subsampling.")

    args = parser.parse_args()

    # Update default config with CLI arguments
    config = DEFAULT_BENCHMARK_CONFIG
    config.models_to_benchmark = args.models_to_benchmark
    config.device = args.device
    config.batch_size = args.batch_size
    config.beam_size = args.beam_size
    config.dataset_splits = args.dataset_splits
    if args.limit is not None:
        config.limit = args.limit
    config.resume_from_last_run = args.resume_from_last_run
    config.output_dir = args.output_dir
    config.seed = args.seed
    config.engine_type = args.engine_type # Set config.engine_type

    print(f"Starting ASR Benchmark Harness (Engine: {args.engine_type})...")
    print(f"Configuration: {config}")
    print(f"Project Root: {config.project_root}")
    print(f"Models Directory: {config.models_dir}")
    print(f"Data Root: {config.data_root}")
    print(f"Output Directory: {config.output_dir}")

    # Ensure output directory exists
    config.output_dir.mkdir(parents=True, exist_ok=True)

    if not config.resume_from_last_run:
        # Rotate existing output files to prevent appending duplicates on no-resume
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        for name in ["details", "summary"]:
            path = config.output_dir / f"{name}.csv"
            if path.exists():
                backup_path = config.output_dir / f"{name}.bak-{timestamp}.csv"
                print(f"⚠️  --no-resume specified. Rotating existing {path.name} to {backup_path.name}")
                path.rename(backup_path)

    engine_factory = build_engine_factory(args.engine_type)
    run_benchmark(config, engine_factory)

    print("ASR Benchmark Harness finished.")


if __name__ == "__main__":
    # Set PYTHONPATH to include project root for module discovery
    project_root = Path(__file__).parent.parent.resolve()
    if str(project_root) not in os.environ.get('PYTHONPATH', '').split(os.pathsep):
        os.environ['PYTHONPATH'] = f"{project_root}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"

    main()
