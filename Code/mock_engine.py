import time
from pathlib import Path
import abc
import soundfile as sf # Moved import to top


class TranscriptionEngine(abc.ABC):
    @abc.abstractmethod
    def load(self) -> float:
        raise NotImplementedError()

    @abc.abstractmethod
    def transcribe(
        self, audio_path: Path, reference_text: str = ""
    ) -> tuple[str, float, float]:
        raise NotImplementedError()

    @abc.abstractmethod
    def unload(self) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def settings(self) -> str:
        raise NotImplementedError()


class MockWhisperXEngine(TranscriptionEngine):
    """Offline mock engine that runs on CPU instantly. Returns mock text matching reference length."""

    def __init__(
        self, arch: str, device: str, compute_type: str = "int8", beam_size: int = 5
    ):
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

    def transcribe(
        self, audio_path: Path, reference_text: str = "MOCK REF"
    ) -> tuple[str, float, float]:


        audio_len = sf.info(str(audio_path)).duration
        proc_time = audio_len * 0.10  # Simulate processing at 10x real-time
        time.sleep(0.01)  # Brief sleep for testing speed
        return reference_text.upper(), audio_len, proc_time

    def unload(self) -> None:
        self.is_loaded = False

    def settings(self) -> str:
        return f"{self.device}/{self.compute_type} (mocked), beam_size {self.beam_size}"
