
import argparse
import csv
from datetime import datetime
from pathlib import Path
import subprocess
import os
import re
import sys
import shutil # Import shutil

DEFAULT_PROJECT_ROOT = Path("/mnt/d/Opencode/")
DEFAULT_REPORTS_DIR = DEFAULT_PROJECT_ROOT / "reports"

# --- Helper Functions ---

def _run_command(cmd: list[str], cwd: Path, error_message: str, check: bool = True):
    """Runs a shell command and optionally raises an error if it fails."""
    try:
        result = subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{error_message}: {e.stderr.strip()}") from e
    except FileNotFoundError:
        raise RuntimeError(f"Command not found: {cmd[0]}. Please ensure Git is installed and on your PATH.")

def _generate_markdown_report(summary_path: Path) -> str:
    """Generates a Markdown report from the summary.csv content."""
    report_lines = ["# ASR Benchmark Report\n", f"Generated on: {datetime.utcnow().isoformat()} (UTC)\n"]

    if not summary_path.exists():
        report_lines.append("## No Summary Data Available\n")
        report_lines.append("Run the ASR benchmark first to generate `summary.csv`.")
        return "\n".join(report_lines)

    report_lines.append("## Summary Metrics\n")
    report_lines.append("| Model | Device/Compute | Dataset | Utterances | Total Audio (s) | Load (s) | Proc (s) | RTF | WER | CER |\n")
    report_lines.append("|---|---|---|---|---|---|---|---|---|---|\n")

    with open(summary_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            report_lines.append(f"| {row['model']} | {row['device']}/{row['compute_type']} | {row['dataset']} | {row['n_utts']} | {float(row['total_audio_s']):.2f} | {float(row['load_s']):.2f} | {float(row['total_proc_s']):.2f} | {float(row['rtf']):.2f} | {float(row['wer']):.4f} | {float(row['cer']):.4f} |\n")
    
    # Add details about the environment/models if desired (could be from config.py)
    report_lines.append("\n--- Notes ---\n")
    report_lines.append("RTF (Real-Time Factor) = Processing Time / Audio Duration. Lower is better.\n")
    report_lines.append("WER (Word Error Rate) and CER (Character Error Rate) are corpus-level metrics. Lower is better.\n")

    return "".join(report_lines)

def _commit_and_push_report(project_root: Path, report_path: Path, index_path: Path, branch: str | None = None, no_push: bool = False):
    """Commits the report and pushes it to the repository."""
    print("Committing and pushing report...")

    current_branch = _run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], project_root, "Failed to get current branch")
    
    worktree_path: Path | None = None

    try:
        if branch and branch != current_branch:
            print(f"  Creating/switching to temporary worktree for branch '{branch}'...")
            worktree_path = project_root / ".git_worktrees" / branch
            if not worktree_path.exists():
                _run_command(["git", "worktree", "add", str(worktree_path), branch, "--orphan"], project_root, f"Failed to create worktree for {branch}")
            else:
                _run_command(["git", "worktree", "checkout", branch], worktree_path, f"Failed to checkout worktree branch {branch}")
            
            # Copy report files to worktree
            shutil.copy(report_path, worktree_path / report_path.name)
            shutil.copy(index_path, worktree_path / index_path.name)
            commit_cwd = worktree_path
        else:
            commit_cwd = project_root

        _run_command(["git", "add", str(report_path.name)], commit_cwd, "Failed to add report file", check=False)
        _run_command(["git", "add", str(index_path.name)], commit_cwd, "Failed to add index file", check=False)
        
        commit_message = f"Docs: ASR Benchmark Report {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        _run_command(["git", "commit", "-m", commit_message], commit_cwd, "Failed to commit report", check=False)
        
        if not no_push:
            print(f"  Pushing to remote origin/{branch or current_branch}...")
            _run_command(["git", "push", "origin", branch or current_branch], commit_cwd, "Failed to push report")
            print("  Report pushed successfully.")
        else:
            print("  Skipping push as --no-push was specified.")

    finally:
        if worktree_path and worktree_path.exists():
            print(f"  Removing temporary worktree {worktree_path}...")
            _run_command(["git", "worktree", "remove", str(worktree_path)], project_root, "Failed to remove worktree", check=False)
            _run_command(["git", "worktree", "prune"], project_root, "Failed to prune worktrees", check=False)

# --- Commands ---

def cmd_report(args):
    """Generates and prints a Markdown report (does not commit)."""
    print("Generating Markdown report...")
    summary_path = args.project_root / "output" / "summary.csv"
    report_content = _generate_markdown_report(summary_path)
    print("\n" + report_content)

def cmd_publish(args):
    """Generates a Markdown report, gates it, commits, and pushes it."""
    print("Publishing ASR benchmark report...")
    summary_path = args.project_root / "output" / "summary.csv"
    report_content = _generate_markdown_report(summary_path)

    # PII Gate
    check_pii_script_path = (DEFAULT_PROJECT_ROOT / "Skills" / "check_no_pii.py").resolve()
    temp_report_path = args.project_root / "temp_report_for_pii_scan.md"
    temp_report_path.write_text(report_content, encoding="utf-8")

    if not args.no_gate:
        print("  Running PII/Secret scan on report...")
        try:
            subprocess.run([
                sys.executable, # Use the current Python interpreter from venv
                str(check_pii_script_path),
                "path",
                str(temp_report_path)
            ], cwd=args.project_root, check=True, capture_output=False) # Capture_output=False so it prints directly
            print("  ✅ PII/Secret scan passed.")
        except subprocess.CalledProcessError:
            print("⛔ PII/Secret scan FAILED. Aborting report publication.", file=sys.stderr)
            if temp_report_path.exists():
                temp_report_path.unlink()
            sys.exit(1)
        except FileNotFoundError:
            print(f"Warning: PII scanner script not found at {check_pii_script_path}. Skipping PII scan.", file=sys.stderr)

    report_file_name = f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = DEFAULT_REPORTS_DIR / report_file_name
    index_path = DEFAULT_REPORTS_DIR / "INDEX.md"

    DEFAULT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_content, encoding="utf-8")

    # Update INDEX.md
    index_content = ""
    if index_path.exists():
        index_content = index_path.read_text()
    
    # Add new report link to the top of INDEX.md (after potential existing header)
    new_entry = f"- [{report_file_name}]({report_file_name})\n"
    if "# ASR Benchmark Reports" in index_content:
        index_content = re.sub(r"(# ASR Benchmark Reports\n)", r"\1" + new_entry, index_content, count=1)
    else:
        index_content = "# ASR Benchmark Reports\n\n" + new_entry + index_content
    
    index_path.write_text(index_content, encoding="utf-8")

    # Commit and push
    _commit_and_push_report(args.project_root, report_path, index_path, args.branch, args.no_push)

    if temp_report_path.exists():
        temp_report_path.unlink()

    print(f"Report published to {report_path} and indexed in {index_path}.")

# --- Argument Parsing ---

def main():
    parser = argparse.ArgumentParser(description="ASR Benchmark Report Publishing Skill")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT,
                        help=f"Project root directory (default: {DEFAULT_PROJECT_ROOT})")
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR,
                        help=f"Directory to store generated reports (default: {DEFAULT_REPORTS_DIR})")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # report command
    report_parser = subparsers.add_parser("report", help="Generate and print a Markdown report")
    report_parser.set_defaults(func=cmd_report)

    # publish command
    publish_parser = subparsers.add_parser("publish", help="Generate, gate, commit, and push a Markdown report")
    publish_parser.add_argument("--branch", type=str, help="Branch to commit the report to (creates worktree if different from current)")
    publish_parser.add_argument("--no-push", action="store_true", help="Do not push the commit to remote")
    publish_parser.add_argument("--no-gate", action="store_true", help="Skip the PII/Secret scan (DANGEROUS!)")
    publish_parser.set_defaults(func=cmd_publish)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
