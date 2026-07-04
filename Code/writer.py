import os
import csv
from pathlib import Path
from datetime import datetime, timezone

DETAIL_FIELDS: list[str] = [
    "model",
    "arch",
    "engine",
    "compute_type",
    "beam_size",
    "device",
    "dataset",
    "split",
    "utt_id",
    "audio_s",
    "proc_s",
    "rtf",
    "wer",
    "cer",
    "hypothesis",
    "reference",
    "error",
]

SUMMARY_FIELDS: list[str] = [
    "timestamp",
    "model",
    "arch",
    "engine",
    "compute_type",
    "beam_size",
    "device",
    "batch_size",
    "dataset",
    "split",
    "n_ok",
    "n_failed",
    "n_utts",
    "total_audio_s",
    "load_s",
    "total_proc_s",
    "rtf",
    "wer",
    "cer",
]


class ResilientCSVWriter:
    """
    Handles transactional, write-ahead, line-buffered writing to details.csv and summary.csv.
    Enforces immediate physical storage commit to prevent cached data loss on power cuts.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.details_path = self.output_dir / "details.csv"
        self.summary_path = self.output_dir / "summary.csv"
        self._check_legacy_headers()
        self._init_headers()

    def _check_legacy_headers(self):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        for path, expected_fields in [
            (self.details_path, DETAIL_FIELDS),
            (self.summary_path, SUMMARY_FIELDS),
        ]:
            if path.exists():
                try:
                    with open(path, "r", newline="", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        header = next(reader, None)
                    if header and header != expected_fields:
                        legacy_path = path.with_name(
                            f"{path.stem}.legacy-{timestamp}.csv"
                        )
                        print(
                            f"⚠️  Legacy header detected in {path.name}. Renaming to {legacy_path.name}"
                        )
                        path.rename(legacy_path)
                except Exception as e:
                    print(f"Error checking header for {path.name}: {e}")

    def _init_headers(self):
        if not self.details_path.exists():
            with open(self.details_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(DETAIL_FIELDS)
        if not self.summary_path.exists():
            with open(self.summary_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(SUMMARY_FIELDS)

    def write_detail_row(self, row: dict):
        """Writes one row and immediately flushes + syncs it to the physical disk."""
        with open(
            self.details_path, "a", newline="", encoding="utf-8", buffering=1
        ) as f:
            writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
            writer.writerow(row)
            # Guarantee physical write to disk
            f.flush()
            os.fsync(f.fileno())

    def write_summary_row(self, row: dict):
        """Writes summary record and immediate physical disk commit."""
        with open(
            self.summary_path, "a", newline="", encoding="utf-8", buffering=1
        ) as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
            writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())

    def parse_existing_runs(self) -> set[tuple[str, str, str, str, str, str, str]]:
        """
        Reads details.csv to retrieve already finished keys
        (model, dataset, utt_id, device, compute_type, split, engine) to skip redundant
        calculations. Including device + compute_type is essential for the
        GPU-then-CPU sweep.
        Safely ignores the last line if it is corrupt/half-written, truncating the file back to safety.
        """
        completed_keys: set[tuple[str, str, str, str, str, str, str]] = set()
        if not self.details_path.exists():
            return completed_keys

        # Check and handle half-written lines
        lines = self.details_path.read_bytes().splitlines()
        if not lines:
            return completed_keys

        valid_lines = []
        for line in lines:
            try:
                decoded = line.decode("utf-8")
                # Ensure it is a valid CSV line with the exact expected column count
                if len(list(csv.reader([decoded]))[0]) == len(DETAIL_FIELDS):
                    valid_lines.append(line)
            except Exception:
                continue

        # If we detected half-written corrupt rows, rewrite the file safely
        if len(valid_lines) < len(lines):
            print(
                f"⚠️  Detected {len(lines) - len(valid_lines)} corrupt or half-written row(s). Recovering and truncating details.csv..."
            )
            self.details_path.write_bytes(b"\n".join(valid_lines) + b"\n")

        # Parse completed runs
        with open(self.details_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("error") == "" or row.get("error") is None:
                    completed_keys.add(
                        (
                            row["model"],
                            row["dataset"],
                            row["utt_id"],
                            row["device"],
                            row["compute_type"],
                            row.get("split", "unknown"),
                            row.get("engine", "unknown"),
                        )
                    )
        return completed_keys
