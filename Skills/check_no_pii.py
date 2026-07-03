# Corrected Skills/check_no_pii.py content
import argparse
import re
import os
import sys
from pathlib import Path
import subprocess

DEFAULT_PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# --- PII and Secret Patterns ---
# Compiled regex patterns for detection
PII_PATTERNS = {
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "PHONE": re.compile(r"\b(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})(?: *x(\d+))?\b"), # Covers various formats
    "SSN": re.compile(r"\b(?!000|666)[0-8][0-9]{2}-(?!00)[0-9]{2}-(?!0000)[0-9]{4}\b"),
    "IPV4": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"), # Simple IPv4, can be extended
    "HOMEDIR_PATH": re.compile(r"/home/[a-zA-Z0-9_-]+/"),
}

SECRET_PATTERNS = {
    "AWS_KEY": re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"), # AWS Access Key ID (20 chars) and Secret Access Key (40 chars)
    "GITHUB_PAT": re.compile(r"ghp_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{82,}"), # GitHub Personal Access Token (classic & fine-grained)
    "GOOGLE_API_KEY": re.compile(r"AIza[0-9A-Za-z-_]{35}"), # Google API Key
    "HUGGINGFACE_TOKEN": re.compile(r"hf_[0-9A-Za-z]{36,}"), # Hugging Face Token
    "OPENAI_API_KEY": re.compile(r"sk-[0-9A-Za-z]{32,}"), # OpenAI API Key
    "SLACK_TOKEN": re.compile(r"xoxb-[0-9]{12}-[0-9]{12}-[0-9a-zA-Z]{24}"), # Slack Bot Token
    "GENERIC_CRED": re.compile(r"(password|secret|api_key|token)\s*=\s*(?:['\"](.+?)['\"])"), # Generic key=value pairs
}

# Combined patterns with severity
ALL_PATTERNS = {
    **{k: {"pattern": v, "severity": "medium", "redact": True} for k, v in PII_PATTERNS.items()},
    **{k: {"pattern": v, "severity": "high", "redact": True} for k, v in SECRET_PATTERNS.items()},
}

# Project-specific tunings (e.g., LibriSpeech utterance IDs)
# Add regexes here if they are common false positives but match PII_PATTERNS
# e.g., r"\b\d{4}-\d{5}-\d{4}\b" for LibriSpeech utterance IDs that might look like credit cards
FALSE_POSITIVES = [
    re.compile(r"\b\d{4}-\d{5}-\d{4}\b"), # LibriSpeech utterance ID example
]

# --- Allowlist Management ---

def _load_allowlist(project_root: Path) -> list[re.Pattern]:
    """Loads regex patterns from .pii-allow file and inline # pii-allow comments."""
    allowlist_patterns = []
    pii_allow_path = project_root / ".pii-allow"
    if pii_allow_path.exists():
        with open(pii_allow_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        if line.startswith("re:"):
                            allowlist_patterns.append(re.compile(line[3:]))
                        else:
                            allowlist_patterns.append(re.compile(re.escape(line))) # Exact match for plain strings
                    except re.error as e:
                        print(f"Warning: Invalid regex in .pii-allow: {line} - {e}", file=sys.stderr)
    return allowlist_patterns

def _is_allowed(content: str, line_number: int, allowlist: list[re.Pattern], pii_allow_tokens: list[str]) -> bool:
    """Checks if a detected string is present in the allowlist or has an inline token."""
    # Check inline # pii-allow tokens on the same line
    for token in pii_allow_tokens:
        if token.lower() in content.lower(): # Simple substring match for tokens
            return True
    
    # Check against allowlist regexes
    for pattern in allowlist:
        if pattern.search(content):
            return True
    return False

# --- Scanner Logic ---

def scan_file(file_path: Path, allowlist_patterns: list[re.Pattern], strict: bool = False) -> bool:
    """Scans a single file for PII and secrets, redacts findings, and returns True if issues found."""
    has_issues = False
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"Warning: Could not decode {file_path} as UTF-8. Skipping content scan.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error reading {file_path}: {e}. Skipping content scan.", file=sys.stderr)
        return False

    lines = content.splitlines()
    for i, line in enumerate(lines):
        redacted_line = line
        pii_allow_tokens = re.findall(r"#\s*pii-allow:([a-zA-Z0-9,_-]+)", line, re.IGNORECASE)
        
        for pattern_name, pattern_info in ALL_PATTERNS.items():
            pattern = pattern_info["pattern"]
            severity = pattern_info["severity"]
            redact = pattern_info["redact"]

            if severity == "low" and not strict:
                continue
            
            for match in pattern.finditer(line):
                found_text = match.group(0)
                
                # Apply false positive filters
                if any(fp_pattern.search(found_text) for fp_pattern in FALSE_POSITIVES):
                    continue

                if not _is_allowed(found_text, i + 1, allowlist_patterns, pii_allow_tokens):
                    has_issues = True
                    issue_description = f"[{severity.upper()}] PII/Secret detected ({pattern_name})"
                    if redact:
                        redacted_match = "*" * len(found_text) # Simple redaction
                        # Special handling for generic_cred to redact only the value
                        if pattern_name == "GENERIC_CRED" and match.lastindex == 2:
                            full_match_start, full_match_end = match.span(0)
                            value_start, value_end = match.span(2) # Group 2 is the value
                            redacted_value = "*" * (value_end - value_start)
                            redacted_line = redacted_line[:value_start] + redacted_value + redacted_line[value_end:]
                        else:
                            redacted_line = redacted_line.replace(found_text, redacted_match)
                    
                    print(f"❌ {file_path}:{i+1}: {issue_description} in line: {redacted_line.strip()}", file=sys.stderr)
        
        # If line has an issue and not fully redacted, display original (truncated) if not already done
        # This part needs careful handling to avoid re-printing or partial redaction issues
        # For now, the redacted_line will be printed as part of the match detection.

    return has_issues

# Define paths to exclude from PII scanning
EXCLUDED_PATHS = [
    DEFAULT_PROJECT_ROOT / "uv.lock",
    DEFAULT_PROJECT_ROOT / "asr_benchmark_master_blueprint.md",
    DEFAULT_PROJECT_ROOT / "Code" / "asr_benchmark_harness.egg-info", # Exclude .egg-info directory
]

def scan_paths(paths: list[Path], project_root: Path, strict: bool = False) -> bool:
    """Scans multiple paths (files or directories) for PII and secrets."""
    overall_issues = False
    allowlist_patterns = _load_allowlist(project_root)

    for path in paths:
        # Check if the current path or any of its parents are in the exclusion list
        if any(excluded_path == path or excluded_path in path.parents for excluded_path in EXCLUDED_PATHS):
            print(f"  Skipping excluded path: {path}")
            continue

        if path.is_file():
            if scan_file(path, allowlist_patterns, strict):
                overall_issues = True
        elif path.is_dir():
            for root, _, files in os.walk(path):
                for file in files:
                    full_path = Path(root) / file
                    # Check if the current file or any of its parents are in the exclusion list
                    if any(excluded_path == full_path or excluded_path in full_path.parents for excluded_path in EXCLUDED_PATHS):
                        print(f"  Skipping excluded file: {full_path}")
                        continue
                    if full_path.is_file():
                        if scan_file(full_path, allowlist_patterns, strict):
                            overall_issues = True
    return overall_issues

# --- Commands ---

def cmd_staged(args):
    """Scans staged Git files for PII/secrets."""
    print("Scanning staged files for PII/secrets...")
    try:
        # Get staged files
        staged_files_output = subprocess.run(["git", "diff", "--cached", "--name-only"], 
                                                cwd=args.project_root, check=True, capture_output=True, text=True).stdout.strip()
        staged_files = [args.project_root / f for f in staged_files_output.splitlines()]
        
        if not staged_files:
            print("No staged files to scan.")
            sys.exit(0)

        if scan_paths(staged_files, args.project_root, args.strict):
            print("⛔ PII/Secret findings in staged files. Commit aborted.", file=sys.stderr)
            sys.exit(1)
        else:
            print("✅ No PII/secret findings in staged files.")
            sys.exit(0)
    except Exception as e:
        print(f"Error scanning staged files: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_tracked(args):
    """Scans all tracked Git files for PII/secrets."""
    print("Scanning all tracked files for PII/secrets...")
    try:
        tracked_files_output = subprocess.run(["git", "ls-files"], 
                                               cwd=args.project_root, check=True, capture_output=True, text=True).stdout.strip()
        tracked_files = [args.project_root / f for f in tracked_files_output.splitlines()]
        
        if not tracked_files:
            print("No tracked files to scan.")
            sys.exit(0)

        if scan_paths(tracked_files, args.project_root, args.strict):
            print("⛔ PII/Secret findings in tracked files.", file=sys.stderr)
            sys.exit(1)
        else:
            print("✅ No PII/secret findings in tracked files.")
            sys.exit(0)
    except Exception as e:
        print(f"Error scanning tracked files: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_path(args):
    """Scans arbitrary files or directories for PII/secrets."""
    print(f"Scanning specified paths for PII/secrets: {args.paths}...")
    abs_paths = [Path(p).resolve() for p in args.paths]
    if scan_paths(abs_paths, args.project_root, args.strict):
        print("⛔ PII/Secret findings in specified paths.", file=sys.stderr)
        sys.exit(1)
    else:
        print("✅ No PII/secret findings in specified paths.")
        sys.exit(0)

def cmd_install_hook(args):
    """Installs the PII pre-commit hook."""
    print("Installing PII pre-commit hook...")
    hook_path = args.project_root / ".git" / "hooks" / "pre-commit"
    check_pii_script_path = (DEFAULT_PROJECT_ROOT / "Skills" / "check_no_pii.py").resolve()

    hook_content = f"""#!/bin/bash
# PII Pre-commit Hook managed by asr-benchmark-harness check_no_pii.py

PYTHONPATH="{os.environ.get('PYTHONPATH', '')}" /tmp/opencode/.venv/bin/python "{check_pii_script_path}" staged

if [ $? -ne 0 ]; then
  echo "\n⛔ PII/Secret scan failed. Aborting commit.\n"
  exit 1
fi
"""
    # Ensure .git/hooks directory exists
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(hook_content)
    os.chmod(hook_path, 0o755) # Make executable
    print("✅ PII pre-commit hook installed.")

# --- Argument Parsing ---

def main():
    parser = argparse.ArgumentParser(description="ASR Benchmark PII/Secret Scanner Skill")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT,
                        help=f"Project root directory (default: {DEFAULT_PROJECT_ROOT})")
    parser.add_argument("--strict", action="store_true",
                        help="Also fail on low-severity findings.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # staged command
    staged_parser = subparsers.add_parser("staged", help="Scan staged Git files")
    staged_parser.set_defaults(func=cmd_staged)

    # tracked command
    tracked_parser = subparsers.add_parser("tracked", help="Scan all tracked Git files")
    tracked_parser.set_defaults(func=cmd_tracked)

    # path command
    path_parser = subparsers.add_parser("path", help="Scan arbitrary files or directories")
    path_parser.add_argument("paths", nargs='+', type=Path, help="List of paths to scan")
    path_parser.set_defaults(func=cmd_path)

    # install-hook command
    install_hook_parser = subparsers.add_parser("install-hook", help="Install PII pre-commit hook")
    install_hook_parser.set_defaults(func=cmd_install_hook)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
