import csv
from Code.writer import ResilientCSVWriter, DETAIL_FIELDS, SUMMARY_FIELDS

def test_resiliency_truncated_repair(tmp_path):
    # Set up a details.csv with valid rows plus one truncated final line
    details_file = tmp_path / "details.csv"
    
    # Valid row
    valid_row = {f: "val" for f in DETAIL_FIELDS}
    valid_row["wer"] = "0.0"
    valid_row["cer"] = "0.0"
    valid_row["error"] = ""
    valid_row["split"] = "test-clean"
    valid_row["engine"] = "mock"

    writer = ResilientCSVWriter(tmp_path)
    writer.write_detail_row(valid_row)

    # Let's manually append a truncated line (incomplete comma count)
    with open(details_file, "a", encoding="utf-8") as f:
        f.write("model,arch,incomplete_line\n")

    # Now parse existing runs - it should repair/truncate the file and ignore the corrupt line
    keys = writer.parse_existing_runs()
    assert len(keys) == 1

    # Read back file to verify it was truncated/repaired (has exactly 2 lines: header + 1 valid row)
    lines = details_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

def test_resiliency_exclude_error_rows(tmp_path):
    writer = ResilientCSVWriter(tmp_path)
    
    # Valid successful row
    row_ok = {f: "val" for f in DETAIL_FIELDS}
    row_ok["utt_id"] = "utt-ok"
    row_ok["error"] = ""
    row_ok["split"] = "test-clean"
    row_ok["engine"] = "mock"
    writer.write_detail_row(row_ok)

    # Failed row with non-empty error
    row_failed = {f: "val" for f in DETAIL_FIELDS}
    row_failed["utt_id"] = "utt-failed"
    row_failed["error"] = "RuntimeError"
    row_failed["split"] = "test-clean"
    row_failed["engine"] = "mock"
    writer.write_detail_row(row_failed)

    keys = writer.parse_existing_runs()
    # The failed row should be excluded from resume keys
    assert len(keys) == 1
    # Check that only the OK utterance is in keys
    # Key tuple structure: (model, dataset, utt_id, device, compute_type, split, engine)
    expected_key = ("val", "val", "utt-ok", "val", "val", "test-clean", "mock")
    assert expected_key in keys

def test_resiliency_distinct_keys(tmp_path):
    writer = ResilientCSVWriter(tmp_path)

    # Set up rows with identical utterance IDs but different device, engine, and split
    row1 = {f: "val" for f in DETAIL_FIELDS}
    row1["utt_id"] = "identical-utt"
    row1["device"] = "cpu"
    row1["engine"] = "mock"
    row1["split"] = "test-clean"
    row1["error"] = ""
    writer.write_detail_row(row1)

    row2 = {f: "val" for f in DETAIL_FIELDS}
    row2["utt_id"] = "identical-utt"
    row2["device"] = "cuda"
    row2["engine"] = "whisperx"
    row2["split"] = "test-other"
    row2["error"] = ""
    writer.write_detail_row(row2)

    keys = writer.parse_existing_runs()
    # Should yield two distinct resume keys
    assert len(keys) == 2

def test_resiliency_legacy_rotation(tmp_path):
    # Set up details.csv and summary.csv with obsolete headers
    details_file = tmp_path / "details.csv"
    summary_file = tmp_path / "summary.csv"

    details_file.write_text("old,obsolete,header\n", encoding="utf-8")
    summary_file.write_text("old,obsolete,summary\n", encoding="utf-8")

    # Instantiate writer - it should rotate the files to legacy versions and create fresh ones
    _ = ResilientCSVWriter(tmp_path)

    # Check that fresh files with correct headers are created
    with open(details_file, "r", encoding="utf-8") as f:
        header = next(csv.reader(f))
        assert header == DETAIL_FIELDS

    with open(summary_file, "r", encoding="utf-8") as f:
        header = next(csv.reader(f))
        assert header == SUMMARY_FIELDS

    # Check that legacy backups were created
    legacy_files = list(tmp_path.glob("*.legacy-*.csv"))
    assert len(legacy_files) == 2
