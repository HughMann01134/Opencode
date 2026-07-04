# ASR Benchmark Harness — Remediation Plan

You are Claude Code, working in the root of a clone of `HughMann01134/Opencode` — an ASR
benchmark harness (specified in `asr_benchmark_master_blueprint.md`) that evaluates
Systran `faster-whisper` models against LibriSpeech `test-clean`/`test-other` using
WhisperX, producing WER/CER/RTF metrics in `output/details.csv` and `output/summary.csv`.

An external code review identified the issues below. Your job is to fix all of them.
The harness's core transcription and scoring paths have been verified correct against
real data — do not rewrite them; make the targeted changes specified here.

---

## Ground rules

1. Work through the tasks **in order** — Tasks 1–3 all touch the same CSV schema and
   `Code/writer.py`, so do them together as one coherent schema change, then verify once.
2. Make **one git commit per task** (Tasks 1–3 may share one commit since they share a
   schema change), with messages like `fix: track dataset split per utterance (Task 1)`.
   **Do not push.** Leave the branch local for human review.
3. Before committing, run the PII gate: `python Skills/check_no_pii.py tracked` must pass.
4. Never commit anything under `models/`, `data/`, or `output/`, and never modify
   `asr_benchmark_master_blueprint.md` or `uv.lock`.
5. After each task, run the verification steps listed for it. After all tasks, run the
   Final Verification section.
6. Environment: a venv may already exist (historically at `/tmp/opencode/.venv`). If not,
   create one, then `pip install -r requirements.txt` and `pip install -e .` from the
   repo root. Detect the actual interpreter path rather than assuming; the LibriSpeech
   data and models may or may not be present locally — **all verification below is
   designed to work with the mock engine and unit tests only**, no downloads required.
7. If a fake-audio test fixture is needed, generate a short FLAC with `soundfile`
   (e.g. 0.2 s of zeros at 16 kHz) in a pytest `tmp_path` — do not fetch real data.

---

## CRITICAL SHARED CONSTRAINT — the CSV schema is duplicated in four places

`Code/writer.py` hardcodes the column list in **four** independent locations:
`_init_headers()` (both header lists), `write_detail_row()` (fields list),
`write_summary_row()` (fields list), and — easy to miss — `parse_existing_runs()`
contains `if len(list(csv.reader([decoded]))[0]) == 15:` — a **magic number equal to the
current details column count**. Any task that adds a column MUST update all four places.

Refactor first: define module-level constants `DETAIL_FIELDS: list[str]` and
`SUMMARY_FIELDS: list[str]` at the top of `Code/writer.py`, use them everywhere,
and replace the magic `15` with `len(DETAIL_FIELDS)`.

**Legacy-file handling:** because Tasks 1–3 change the schema, old CSVs become
incompatible. In `ResilientCSVWriter.__init__`, if `details.csv` or `summary.csv`
exists with a header that does not match the current field list, rename it to
`<name>.legacy-<UTCtimestamp>.csv`, print a warning, and start a fresh file. Do not
attempt to migrate old rows.

---

## Task 1 — Track and report the dataset split (test-clean vs test-other)

**Problem.** `Code/datasets.py` pools both splits into one list; the `Utterance`
NamedTuple has no split field; every CSV row records `dataset: LibriSpeech`. The
entire purpose of LibriSpeech shipping two test sets — comparing accuracy on clean
vs. noisy speech — is currently impossible. Bonus inconsistency: `main.py`'s
`--limit` help text already says "per model/split", but the implementation applies
the limit to the pooled list, so a small `--limit` can sample only one split.

**Changes.**
- `Code/datasets.py`: add `split: str` to `Utterance`. Apply `limit` **per split**
  (deterministic `random.Random(seed)` shuffle within each split, then truncate),
  matching the existing `--limit` help text.
- `Code/main.py`: add a `split` column to each detail row (keep `dataset` =
  `LibriSpeech` as-is). Restructure the per-pass loop to keep **one
  `CorpusMetricAccumulator` and one set of counters per split** (a
  `dict[str, ...]` keyed by split is fine), and write **one summary row per split**
  at the end of each pass. Add `split` to the summary schema too.
- Resume key: extend from
  `(model, dataset, utt_id, device, compute_type)` to include `split` (and `engine`
  from Task 3). Update both the key construction in `main.py` and the tuple built in
  `writer.parse_existing_runs()`.

**Verify.** With no real data present, unit tests (Task 9) cover this. If
`data/LibriSpeech/` exists locally, additionally run the mock command in Final
Verification and confirm the summary contains one row per split.

---

## Task 2 — Failed utterances must count in corpus metrics

**Problem.** In `Code/main.py`, the per-utterance `except` branch writes a detail
row with `wer=1.0` but never touches `corpus_accumulator` or the pass counters. A
run where most utterances fail would report a summary WER computed only over the
successes, with no failure count anywhere. (This actually happened: two
ffmpeg-missing failures in the historical `details.csv` left no trace in any summary.)

**Changes.**
- In the `except` branch, score the failure into the accumulator as an **empty
  hypothesis**: `corpus_accumulator.add_utterance(normalize_text(utt.text), "")`
  (the accumulator already handles empty hypotheses as full deletions — do not
  change `Skills/compute_wer_cer.py`).
- Add summary columns `n_ok` and `n_failed`. Semantics: `n_utts` = total attempted
  (`n_ok + n_failed`); `wer`/`cer` = corpus metrics over **all attempted** utterances
  (failures as deletions); `total_audio_s`, `total_proc_s`, and `rtf` computed over
  **successful** transcriptions only (failed utterances have no meaningful timing).
- Update `Skills/publish_report.py`'s table to include the failure count (a single
  `OK/Fail` or `n_ok`/`n_failed` column pair).

**Verify.** Unit test in Task 9 (`test_metrics`): three good utterances plus one
failure scored as empty hypothesis must yield the manually computed corpus WER.

---

## Task 3 — Add an `engine` column; mock results must never masquerade as real

**Problem.** Neither CSV records whether a row came from the mock engine or real
WhisperX. In the committed reports, mock rows (load 0.10 s, RTF exactly 0.1) sit
beside a real WhisperX row in the same table, indistinguishable. Worse, because the
resume key omits engine, **a mock run marks utterances as "done" and a subsequent
`--engine-type whisperx --resume` run would skip them**, silently producing a
benchmark of nothing.

**Changes.**
- Thread `engine_type` into `run_benchmark` (it currently exists only inside the
  factory closure — add it as a parameter or a `BenchmarkConfig` field).
- Add `engine` (`mock` | `whisperx`) to both `DETAIL_FIELDS` and `SUMMARY_FIELDS`
  and to every written row.
- Include `engine` in the resume key (construction in `main.py` and parsing in
  `writer.parse_existing_runs()`).
- `Skills/publish_report.py`: add an Engine column to the report table, and either
  render mock rows in a separate "Mock (harness verification)" section or suffix
  them clearly — a reader must not be able to mistake mock numbers for benchmark
  results.

**Verify.** Unit test: `parse_existing_runs` on a fixture CSV containing a mock row
and a whisperx row for the same utterance returns two distinct keys.

---

## Task 4 — Report/run hygiene: timestamps, dedupe, output rotation, stale reports

**Problem.** `summary.csv` is append-only and `_generate_markdown_report` drops the
timestamp column, so reports accumulate stale rows from every historical run with no
way to tell them apart. The repo contains two near-duplicate committed reports
generated four minutes apart. Additionally, `--no-resume` ignores prior keys but
still appends to the same CSVs, creating duplicate detail rows.

**Changes.**
- `Skills/publish_report.py::_generate_markdown_report`: include the timestamp in
  the table, and **by default show only the latest row per
  `(model, engine, device, compute_type, split)`** (latest by timestamp). Add an
  `--all-runs` flag to both `report` and `publish` subcommands to show full history.
- `Code/main.py`: when `--no-resume` is passed, rotate any existing
  `output/details.csv` and `output/summary.csv` to `<name>.bak-<UTCtimestamp>.csv`
  before the run starts, so "no resume" genuinely means a fresh output set.
- Repo cleanup: delete `reports/report_20260703_034838.md` (superseded duplicate of
  `report_20260703_035247.md`); fix `reports/INDEX.md` to list only the remaining
  report, newest first, with consistent formatting (no stray blank lines between
  entries).

**Verify.** Generate a report against a fixture `summary.csv` containing duplicate
combos with different timestamps; confirm only the latest appears by default and all
appear with `--all-runs`.

---

## Task 5 — `datasets.py` path handling and import hoist

**Problem.** The split scanner hardcodes a **double-nested** layout
(`data / "LibriSpeech" / "LibriSpeech" / split`) while its own missing-audio
fallback reconstructs a **single-nested** path (`data / "LibriSpeech" / split / ...`)
— whichever layout a user's extraction produced, one of the two code paths is wrong.
Also, `from Skills.profile_audio import get_audio_duration` sits **inside the
per-utterance loop**.

**Changes.**
- Detect the layout once per split: probe `data_root/"LibriSpeech"/split` first,
  then `data_root/"LibriSpeech"/"LibriSpeech"/split`; use whichever exists and make
  the audio-path fallback use the **same** detected split root. Keep the existing
  warning-and-skip behavior for genuinely missing files.
- Move the `profile_audio` import to module top.

**Verify.** Task 9's `test_datasets` builds both layouts in `tmp_path` and asserts
both load.

---

## Task 6 — `datetime.utcnow()` deprecation

Replace every `datetime.utcnow()` with `datetime.now(timezone.utc)` (add the
`timezone` import). Grep the whole repo; known sites are `Code/main.py` and
`Skills/publish_report.py` (both `.isoformat()` and `.strftime(...)` call sites —
`strftime` output is unaffected by the change). Confirm `pytest` runs with **zero**
deprecation warnings from project code afterward.

---

## Task 7 — Finish the dynamic-project-root fix (and the hardcoded hook interpreter)

**Problem.** A prior review pass fixed the hardcoded project root only in
`Skills/check_no_pii.py`. These still hardcode `DEFAULT_PROJECT_ROOT =
Path("/mnt/d/Opencode/")`: `Skills/setup_github.py`, `Skills/publish_report.py`,
`Skills/gemini_escalation.py`, `Skills/acquire_assets.py`. Additionally,
`setup_github.py` line ~90 bakes a hardcoded interpreter
(`/tmp/opencode/.venv/bin/python`) into the generated pre-commit hook, which breaks
the PII gate on any other machine.

**Changes.**
- In all four files: `DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent`
  (matching `check_no_pii.py`). Keep the existing `--project-root` CLI overrides.
- In both hook-generating functions (`setup_github.py::_install_pii_pre_commit_hook`
  and the equivalent in `check_no_pii.py::cmd_install_hook`), embed `sys.executable`
  of the installing interpreter instead of the hardcoded venv path.

---

## Task 8 — Tighten the inline `# pii-allow:` token semantics

**Problem.** In `Skills/check_no_pii.py::_is_allowed`, an inline token is honored
via loose **substring** matching against the finding
(`token.lower() in content.lower()`). A short token like `# pii-allow:a` on a line
would whitelist nearly any secret containing the letter "a" on that line.

**Changes.**
- Require the inline token to **exactly equal** the matched finding text
  (case-insensitive full-string comparison), and ignore tokens shorter than
  6 characters with a printed warning.
- Document the inline-token format and its exact-match semantics in the module
  docstring and in the README's PII section.

**Verify.** Unit test: a line containing a fake secret plus `# pii-allow:a` must
still be flagged; the same line with `# pii-allow:<the exact matched string>` must pass.

---

## Task 9 — Test coverage the blueprint specified but was never built

Only `tests/test_corpus_metrics.py` exists. Add the following, all runnable
**offline, CPU-only, no models/data downloads** (monkeypatch
`torch.cuda.is_available` where needed; never import `whisperx` in tests):

- `tests/test_skills.py` — `manage_device`: illegal combos (`int8`+cuda,
  `float16`+cpu) raise `ValueError`; `plan_device_passes` returns a CPU-only pass
  when CUDA is unavailable (monkeypatched) and GPU-then-CPU when available
  (monkeypatched). `normalize_text`: casing/punctuation collapse to equal strings.
- `tests/test_resiliency.py` — using `tmp_path` and `ResilientCSVWriter`: (a) a
  details.csv with valid rows plus one truncated final line is repaired and the
  truncated row excluded; (b) rows with a non-empty `error` are excluded from
  resume keys; (c) identical utterances under different `device` / `engine` /
  `split` values yield distinct keys; (d) legacy-header files are rotated to
  `.legacy-*.csv` and a fresh file started.
- `tests/test_datasets.py` — build a fake LibriSpeech tree in `tmp_path` (generate
  tiny FLACs with `soundfile`): split recorded on each `Utterance`; per-split
  `limit` honored; same seed ⇒ same selection; missing-audio rows skipped with a
  warning; **both** single- and double-nested layouts load (Task 5).
- Extend `tests/test_corpus_metrics.py` — one test combining successful utterances
  with a failure scored as empty hypothesis, asserting the manually computed
  corpus WER/CER (Task 2 semantics).

All tests green via `pytest tests/ -q`.

---

## Task 10 — Documentation honesty (README + RUNNING_GUIDE)

- `README.md`: add two sections.
  - **"How this project was built"** — the agentic workflow: implementation
    blueprint authored with Claude → built by Gemini 2.5 Flash driving OpenCode →
    reviewed by a Gemini 2.5 Pro subagent (`.opencode/gemini-review.md`) → this
    remediation pass executed by Claude Code from an external review. Link the
    committed artifacts (`asr_benchmark_master_blueprint.md`, `.opencode/handoff.md`,
    `.opencode/gemini-review.md`).
  - **"Current results"** — an honest scope statement: verified so far is the
    `tiny` model, CPU/int8, 2 LibriSpeech utterances (WER 0.0000 / CER 0.0000 with
    word-perfect transcriptions confirmed against references; real-run RTF
    ~0.61–0.87). State explicitly that the full 15-model, GPU-then-CPU,
    full-corpus sweep is implemented but **not yet executed**.
- `RUNNING_GUIDE.md`: update output-column documentation for the new schema
  (`split`, `engine`, `n_ok`/`n_failed`, timestamp in reports); note that
  `--no-resume` now rotates output CSVs; mark the Phase 4 step 2 example
  (`--device auto`, multi-model) as **not yet validated on the target hardware**;
  replace hardcoded `/mnt/d/Opencode` and `/tmp/opencode/.venv` with a note to
  substitute the reader's own project root and venv paths.

---

## Task 11 — Add a LICENSE

Add an MIT `LICENSE` file (year 2026, copyright holder `HughMann01134` — flag in
your final summary that the owner should confirm the name and may substitute a
different license). A public repo with no license is all-rights-reserved by
default, which defeats the purpose of publishing.

---

## Final verification (run all; report results in your summary)

1. `pytest tests/ -q` — all green, zero project deprecation warnings.
2. `python Skills/check_no_pii.py tracked` — passes.
3. If `data/LibriSpeech/` exists locally, run:
   `python -m Code.main --device cpu --limit 3 --engine-type mock --models-to-benchmark tiny --no-resume`
   and confirm: old CSVs rotated to `.bak-*`; new `details.csv`/`summary.csv` carry
   `split` and `engine` columns; one summary row per available split with
   `n_ok`/`n_failed`. If no data is present, state that this step was covered by
   unit tests instead.
4. `python Skills/publish_report.py report` (or against a fixture summary) —
   table shows Timestamp, Engine, Split, and failure counts; duplicates deduped by
   default.
5. `git log --oneline` shows one commit per task; nothing pushed; nothing from
   `output/`, `models/`, or `data/` staged.
6. Write a short closing summary: tasks completed, deviations (if any) with
   reasons, and any follow-ups for the owner (license name confirmation; the
   still-pending full GPU/multi-model benchmark run).
