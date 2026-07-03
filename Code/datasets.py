
import random
from pathlib import Path
from typing import NamedTuple, Iterator, Sequence, Literal

# Define a named tuple for an utterance to hold its data
class Utterance(NamedTuple):
    id: str
    audio_path: Path
    text: str
    duration: float  # In seconds

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
        # Correct path for where the actual split data (e.g., test-clean) is located
        # given that the overall data_root already points to /mnt/d/Opencode/data
        split_path = data_root / "LibriSpeech" / "LibriSpeech" / split
        if not split_path.exists():
            print(f"Warning: Dataset split path not found: {split_path}. Skipping.")
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
                    # Example: 19-198-0000.flac for 19-198-0000.trans.txt (trans_file contains only text for utterance ids)
                    audio_path = trans_file.parent / f"{utt_id}.flac"
                    if not audio_path.exists():
                        # Fallback for paths like LibriSpeech/train-clean-100/19/198/19-198-0000.flac
                        # The transcription file itself is often at a higher level, so we need to rebuild the path.
                        # Reconstruct the audio file path based on LibriSpeech common structure:
                        # data_root/LibriSpeech/<split>/<speaker_id>/<chapter_id>/<utterance_id>.flac
                        # utt_id is typically <speaker_id>-<chapter_id>-<sequence_id>
                        try:
                            speaker_id, chapter_id, _ = utt_id.split('-')
                            audio_path = data_root / "LibriSpeech" / split / speaker_id / chapter_id / f"{utt_id}.flac"
                        except ValueError:
                            pass # Keep original audio_path if utt_id format is unexpected

                    if not audio_path.exists():
                        # If still not found, print a warning and skip
                        print(f"Warning: Audio file not found for {utt_id} at {audio_path}. Skipping.")
                        continue

                    # We need the duration. Instead of re-implementing, we can use the skill.
                    # For this module, we'll assume a mechanism to get duration will be available
                    # (e.g., an external profiler utility or a pre-computed manifest).
                    # For now, we'll use a placeholder or rely on a helper from Skills.
                    # Since Skills.profile_audio is available, we will use it.
                    try:
                        from Skills.profile_audio import get_audio_duration
                        duration = get_audio_duration(audio_path)
                    except Exception as e:
                        print(f"Error getting duration for {audio_path}: {e}. Skipping.")
                        continue

                    all_utterances.append(Utterance(id=utt_id, audio_path=audio_path, text=text, duration=duration))

    if limit and len(all_utterances) > limit:
        random.Random(seed).shuffle(all_utterances) # Deterministic shuffle
        all_utterances = all_utterances[:limit]

    yield from all_utterances
