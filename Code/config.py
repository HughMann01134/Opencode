
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, get_args

# Define types for clarity and validation
ModelAlias = Literal["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3",
                     "tiny.en", "base.en", "small.en", "medium.en",
                     "distil-small.en", "distil-medium.en", "distil-large-v2", "distil-large-v3"]

@dataclass(frozen=True)
class ModelConfig:
    alias: ModelAlias
    repo_id: str
    family: str
    local_path: Path # Will be set after acquisition

# Centralized model catalog derived from Skills/acquire_assets.py for consistency
MODEL_CATALOG_RAW: dict[ModelAlias, dict] = {
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

# Construct the actual MODEL_CONFIG dictionary with ModelConfig dataclasses
MODEL_CONFIG: dict[ModelAlias, ModelConfig] = {}
for alias, data in MODEL_CATALOG_RAW.items():
    # Assuming models are stored in a 'models/' directory at project root
    # This path will be validated/corrected during actual engine loading
    model_dir_name = data["repo"].split('/')[-1]
    local_model_path = Path(__file__).parent.parent / "models" / model_dir_name
    MODEL_CONFIG[alias] = ModelConfig(
        alias=alias,
        repo_id=data["repo"],
        family=data["family"],
        local_path=local_model_path,
    )

@dataclass
class BenchmarkConfig:
    # General project root and asset directories
    project_root: Path = Path(__file__).parent.parent.resolve()
    models_dir: Path = field(init=False)
    data_root: Path = field(init=False)

    # Dataset configuration
    dataset_name: str = "LibriSpeech"
    dataset_splits: list[Literal["test-clean", "test-other"]] = field(default_factory=lambda: ["test-clean", "test-other"])
    
    # Model configuration - list of aliases to benchmark
    models_to_benchmark: list[ModelAlias] = field(default_factory=lambda: [
        "tiny", "base", "small", "medium", "large-v3", # Core multilingual
        "tiny.en", "base.en", "small.en", "medium.en", # Core English-only
    ])

    # Benchmarking parameters
    engine_type: Literal["mock", "whisperx"] = "mock" # "mock" or "whisperx"
    device: str = "auto" # "auto", "cuda", "cpu", "both"
    compute_type: str | None = None # float16, int8, int16, float32 - auto-selected by manage_device
    batch_size: int = 1
    beam_size: int = 5
    limit: int | None = None # Limit the number of utterances to process
    seed: int = 42 # Random seed for deterministic sub-sampling
    
    # Resiliency and reporting
    resume_from_last_run: bool = True
    output_dir: Path = field(init=False)
    report_name: str = "benchmark_report"

    def __post_init__(self):
        self.models_dir = self.project_root / "models"
        self.data_root = self.project_root / "data"
        self.output_dir = self.project_root / "output" # For details.csv and summary.csv

        # Basic validation for models_to_benchmark
        for model_alias in self.models_to_benchmark:
            if model_alias not in get_args(ModelAlias):
                raise ValueError(f"Invalid model alias in models_to_benchmark: {model_alias}")

# Instantiate default configuration
# It can be overridden by CLI arguments in main.py
DEFAULT_BENCHMARK_CONFIG = BenchmarkConfig()
