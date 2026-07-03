# ASR Benchmark Harness Review

## Session Observations
- **General Reliability:** The developer consistently followed the blueprint, implemented modules, and provided comprehensive documentation. Most of the session was driven by clear incremental commits.
- **Common Missteps:**
  - *Print Formatting Errors*: Several `print` statements used double braces (`{{...}}`) in f‑strings (e.g., in ``main.py``) causing literal `{compute_type}` to appear instead of the actual value. This does not affect functionality but confuses logs.
  - *Unnecessary Complexity*: Some helper functions were re‑implemented instead of using straightforward alternatives (e.g., ``determine_compute_type`` is called redundantly in both the engine constructor and `plan_device_passes`).
- **Successful Fixes:** The model catalog construction correctly maps aliases to repo IDs. All tests passed once the bug in `load_librispeech` was addressed by confirming that audio paths are resolved correctly.

## Code Quality
- **Pythonic Implementation:** Use of dataclasses for configuration and type hints throughout reflects modern practices.
- **Minor Inefficiencies:** The `MockWhisperXEngine.transcribe` imports ``soundfile`` inside the method. Importing at module level is preferred for clarity and to avoid repeated import overhead.
- **Naming Coherence:** Function names follow snake_case; however, some variable names like ``metadata.local_path`` are slightly ambiguous (could be called ``model_dir``).

## Test Coverage
- Only unit tests for the WER/CER accumulator exist. No integration or dataset loading tests are present.
- Missing Edge Cases:
  - Empty dataset splits or non‑existent directories.
  - Subsetting logic when ``limit`` is set to zero.
  - Mock engine’s handling of empty reference strings.

## Security & Robustness
- **Input Validation:** Functions such as `load_librispeech` silently skip missing files and emit warnings instead of raising. This is acceptable for non‑critical data but may mask problems.
- **PII Scanner:** The scanner uses regex patterns with a global allowlist loaded from `.pii-allow`. A potential regression could happen if a file path contains an accidental inline comment `# pii-allow`, which the current logic treats as an inline token, masking real PII. This should be explicitly documented.

## Specific Issues & Suggested Fixes
1. **File:** `Code/main.py` (≈lines 80‑95)
   - Problem: Failing to interpolate ``compute_type`` in log messages due to double braces.
   - Fix: Replace ``{{compute_type}}`` with `{compute_type}` and ensure f‑string is used correctly.

2. **File:** `Code/main.py` (≈lines 95‑97)
   - Problem: Same formatting issue in the engine loading log string.
   - Fix: Remove double braces or use an f‑string that includes ``compute_type``.

3. **File:** `Skills/check_no_pii.py`
   - Problem: The project root is hard‑coded as `/mnt/d/Opencode/`. This may break when the repository is moved.
   - Fix: Compute `DEFAULT_PROJECT_ROOT` dynamically using ``Path(__file__).parents[2]`` or allow overriding via environment variable.

4. **File:** `Code/mock_engine.py`
   - Problem: Importing ``soundfile`` inside ``transcribe`` causes repeated imports.
   - Fix: Move the import to module level.

5. **File:** `Skills/check_no_pii.py`
   - Problem: Inline comment pattern ``# pii-allow:…`` captures any occurrence; a false positive may hide real PII.
   - Fix: Require a strict token format, e.g., `#<pii-allow>…</pii-allow>` or prefix with an explicit marker.

## What Devstral Did Well
Devstral consistently delivered a fully working ASR benchmark harness that aligns closely with the provided blueprint. The code is modular, well‑documented, and demonstrates careful handling of dataset extraction, device management, model cataloging, and error reporting. The implementation of PII scanning and report publishing further shows an awareness of operational security.

## Verdict
**NEEDS MINOR FIXES**

### Prioritised Fix List
1. Correct the f‑string formatting in `Code/main.py` to display actual compute type values during logging.
2. Compute project root dynamically in `Skills/check_no_pii.py` instead of hard‑coding.
3. Relocate imports inside `MockWhisperXEngine.transcribe` to module level and consider replacing with a lightweight fallback if ``soundfile`` is missing.
4. Add unit/integration tests for dataset loading, mock engine handling of empty references, and limit edge cases.
5. Adjust inline PII‑allow token parsing to prevent accidental masking of real credentials.

---
Full review written to .opencode/gemini-review.md