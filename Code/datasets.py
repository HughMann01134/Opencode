import random
from pathlib import Path
from typing import NamedTuple, Iterator, Sequence, Literal
from Skills.profile_audio import get_audio_duration

# Define a named tuple for an utterance to hold its data
class Utterance(NamedTuple):
    id: str
    audio_path: Path
    text: str
    duration: float  # In seconds
    split: str

def load_librispeech(
    data_root: Path,
    splits: Sequence[Literal["test-clean", "test-other"]],
    limit: int | None = None,
    seed: int = 42,
) -> Iterator[Utterance]:
    """Loads LibriSpeech dataset utterances from specified splits.

    Args:
        data_root: The root directory containing the LibriSpeech data (e.g., project_root/data).
        splits: A list of dataset splits to load (e.g., ["test-clean", "test-other"]).
        limit: Optional. If specified, limits the number of utterances returned.
        seed: Random seed for deterministic sub-sampling if a limit is applied.

    Yields:
        Utterance: A named tuple containing utterance ID, audio path, text, and duration.
    """
    all_utterances: list[Utterance] = []

    for split in splits:
        split_utterances: list[Utterance] = []
        
        # Detect the layout once per split: probe single-nested, then double-nested
        split_path = data_root / "LibriSpeech" / split
        if not split_path.exists():
            split_path = data_root / "LibriSpeech" / "LibriSpeech" / split

        if not split_path.exists():
            print(f"Warning: Dataset split path not found (tried both single and double nested layouts) in: {data_root / 'LibriSpeech' / split}. Skipping.")
            continue

        # Find all .trans.txt files
        transcription_files = list(split_path.rglob("*.trans.txt"))

        if not transcription_files:
            print(f"Warning: No *.trans.txt files found in {split_path}. Skipping.")
            continue

        for trans_file in transcription_files:
            with open(trans_file, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(" ", 1)
                    if len(parts) < 2:
                        continue
                    utt_id, text = parts[0], parts[1]
                    
                    # Construct audio path (assuming FLAC files in same dir as trans.txt)
                    audio_path = trans_file.parent / f"{utt_id}.flac"
                    if not audio_path.exists():
                        try:
                            speaker_id, chapter_id, _ = utt_id.split('-')
                            # Fallback using the same detected split root structure
                            audio_path = split_path / speaker_id / chapter_id / f"{utt_id}.flac"
                        except ValueError:
                            pass

                    if not audio_path.exists():
                        print(f"Warning: Audio file not found for {utt_id} at {audio_path}. Skipping.")
                        continue

                    try:
                        duration = get_audio_duration(audio_path)
                    except Exception as e:
                        print(f"Error getting duration for {audio_path}: {e}. Skipping.")
                        continue

                    split_utterances.append(Utterance(id=utt_id, audio_path=audio_path, text=text, duration=duration, split=split))

        if limit and len(split_utterances) > limit:
            random.Random(seed).shuffle(split_utterances) # Deterministic shuffle
            split_utterances = split_utterances[:limit]

        all_utterances.extend(split_utterances)

    yield from all_utterances
