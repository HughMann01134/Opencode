import pytest
from pathlib import Path
import soundfile as sf
import numpy as np
from Code.datasets import load_librispeech

def _create_synthetic_dataset(root: Path, double_nested: bool = False):
    # Single-nested: root / "LibriSpeech" / split / speaker / chapter
    # Double-nested: root / "LibriSpeech" / "LibriSpeech" / split / speaker / chapter
    base = root / "LibriSpeech"
    if double_nested:
        base = base / "LibriSpeech"
        
    for split in ["test-clean", "test-other"]:
        split_dir = base / split / "19" / "198"
        split_dir.mkdir(parents=True, exist_ok=True)
        
        # Create flac audio files
        for i in range(5):
            utt_id = f"19-198-{i:04d}"
            audio_path = split_dir / f"{utt_id}.flac"
            # Create a tiny flac of zeros (e.g. 0.2s of zeros at 16kHz)
            sf.write(audio_path, np.zeros(3200, dtype="float32"), 16000)
            
        # Create .trans.txt file
        trans_file = split_dir / "19-198.trans.txt"
        trans_file.write_text(
            "\n".join(f"19-198-{i:04d} UTTERANCE TEXT NUMBER {i}" for i in range(5)) + "\n",
            encoding="utf-8"
        )

def test_datasets_single_nested(tmp_path):
    # Set up single-nested tree
    _create_synthetic_dataset(tmp_path, double_nested=False)
    
    # Load and verify
    utterances = list(load_librispeech(tmp_path, ["test-clean", "test-other"]))
    assert len(utterances) == 10  # 5 clean + 5 other
    for utt in utterances:
        assert utt.split in ["test-clean", "test-other"]
        assert utt.duration == pytest.approx(0.2)

def test_datasets_double_nested(tmp_path):
    # Set up double-nested tree
    _create_synthetic_dataset(tmp_path, double_nested=True)
    
    # Load and verify
    utterances = list(load_librispeech(tmp_path, ["test-clean", "test-other"]))
    assert len(utterances) == 10
    for utt in utterances:
        assert utt.split in ["test-clean", "test-other"]

def test_datasets_limit_and_seed(tmp_path):
    _create_synthetic_dataset(tmp_path, double_nested=False)

    # limit = 2 per split (total 4)
    utts_seed42_a = list(load_librispeech(tmp_path, ["test-clean", "test-other"], limit=2, seed=42))
    assert len(utts_seed42_a) == 4

    utts_seed42_b = list(load_librispeech(tmp_path, ["test-clean", "test-other"], limit=2, seed=42))
    # same seed => same selection
    assert [u.id for u in utts_seed42_a] == [u.id for u in utts_seed42_b]

    # different seed => likely different selection
    utts_seed100 = list(load_librispeech(tmp_path, ["test-clean", "test-other"], limit=2, seed=100))
    assert len(utts_seed100) == 4

def test_datasets_missing_audio(tmp_path):
    # Create a structure but delete one audio file
    _create_synthetic_for_missing(tmp_path)
    
    # 2 items in test-clean, but one is missing audio
    utterances = list(load_librispeech(tmp_path, ["test-clean"]))
    assert len(utterances) == 1
    assert utterances[0].id == "19-198-0000"

def _create_synthetic_for_missing(root: Path):
    split_dir = root / "LibriSpeech" / "test-clean" / "19" / "198"
    split_dir.mkdir(parents=True, exist_ok=True)
    
    # Create only one flac audio file for 0000, 0001 is missing
    sf.write(split_dir / "19-198-0000.flac", np.zeros(3200, dtype="float32"), 16000)
    
    trans_file = split_dir / "19-198.trans.txt"
    trans_file.write_text(
        "19-198-0000 UTTERANCE ZERO\n"
        "19-198-0001 UTTERANCE ONE\n",
        encoding="utf-8"
    )
