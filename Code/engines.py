
import time # Import time module
import gc
import torch
import whisperx
from pathlib import Path
from Code.mock_engine import TranscriptionEngine # Re-use the base class
from Code.config import MODEL_CONFIG, ModelAlias
from Skills.manage_device import determine_compute_type # For safety checks


class WhisperXEngine(TranscriptionEngine):
    """Real WhisperX ASR engine wrapper for benchmarking."""

    def __init__(self, model_alias: ModelAlias, device: str, compute_type: str, beam_size: int):
        print(f"Initializing WhisperXEngine for {model_alias} on {device}/{compute_type}")
        self.model_alias = model_alias
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.model = None
        self.audio_model = None  # For WhisperX's internal audio processing
        self.metadata = MODEL_CONFIG[model_alias] # Get model metadata
        self.load_seconds = 0.0

        # Pre-validate compute_type to match blueprint safety rules
        # This will raise ValueError if an invalid combination is requested.
        determine_compute_type(device, compute_type) 

    def load(self) -> float:
        if self.model is not None:
            return self.load_seconds # Already loaded

        t0 = time.perf_counter() # Use time.perf_counter for high-resolution timing

        # Load the model from the local path
        # whisperx.load_model expects model_path, device, compute_type
        self.model = whisperx.load_model(
            str(self.metadata.local_path),
            self.device,
            compute_type=self.compute_type,
            language="en" if ".en" in self.model_alias else None # Auto-detect language
        )
        
        # WhisperX also has a separate audio processing model (usually common for all models)
        # For now, we will load a base one. A more robust implementation might make this configurable
        # or load it once globally if it's truly device-agnostic.
        # This assumes the base audio model doesn't need special compute_type handling per device
        # For benchmarking, we should perhaps also time this separately or ensure it's part of 'load'
        # Since it's usually small, let's include in load time.


        self.load_seconds = time.perf_counter() - t0
        return self.load_seconds

    def transcribe(self, audio_path: Path, reference_text: str = "") -> tuple[str, float, float]:
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        t0 = time.perf_counter()
        
        # Load audio using whisperx's utility
        audio = whisperx.load_audio(str(audio_path))

        # Transcribe audio
        result = self.model.transcribe(audio, batch_size=1) # batch_size=1 for per-utterance
        
        # Extract text
        combined_text = " ".join([seg["text"] for seg in result["segments"]]).strip()
        
        proc_s = time.perf_counter() - t0

        # We need original audio duration to calculate RTF accurately
        # This will come from the Utterance object in Code.datasets.py
        # For now, return a placeholder for audio_s (will be overridden by caller)
        audio_s = 0.0 # Placeholder, will be replaced by actual duration from dataset

        return combined_text, audio_s, proc_s

    def unload(self) -> None:
        if self.model is not None:
            del self.model
            self.model = None
        # self.audio_model is no longer explicitly managed here if it's not loaded via load_audio_model
        
        # Force garbage collection and empty CUDA cache if applicable
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"Engine for {self.model_alias} unloaded. Memory reclaimed.")

    def settings(self) -> str:
        return f"whisperx {self.model_alias} ({self.device}/{self.compute_type}, beam_size {self.beam_size})"
