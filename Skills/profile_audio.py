from pathlib import Path
import soundfile as sf  # type: ignore


def get_audio_duration(path: Path) -> float:
    """Reads soundfile header to retrieve duration in seconds, avoiding full file decode."""
    try:
        return sf.info(str(path)).duration
    except Exception as e:
        raise IOError(f"Failed to read audio file header for {path}: {e}")
