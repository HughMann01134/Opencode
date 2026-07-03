
import argparse
import subprocess
import os
from pathlib import Path
import re

DEFAULT_PROJECT_ROOT = Path("/mnt/d/Opencode/")

# --- Helper Functions ---

def _run_command(cmd: list[str], cwd: Path, error_message: str):
    """Runs a shell command and raises an error if it fails."""
    try:
        result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{error_message}: {e.stderr.strip()}") from e
    except FileNotFoundError:
        raise RuntimeError(f"Command not found: {cmd[0]}. Please ensure Git is installed and on your PATH.")

def _set_git_config(project_root: Path, key: str, value: str):
    """Sets a Git configuration value locally."""
    _run_command(["git", "config", "--local", key, value], project_root,
                 f"Failed to set Git config {key}={value}")
    print(f"  Set Git config: {key} = {value}")

def _check_git_config(project_root: Path, key: str) -> str:
    """Checks a Git configuration value locally."""
    try:
        return _run_command(["git", "config", "--local", key], project_root,
                            f"Failed to get Git config {key}")
    except RuntimeError:
        return ""

def _initialize_git_repo(project_root: Path, branch: str = "main"):
    """Initializes a Git repository if it doesn't exist and sets the default branch."""
    if not (project_root / ".git").exists():
        print("  Initializing new Git repository...")
        _run_command(["git", "init", "-b", branch], project_root, "Failed to initialize Git repo")
        print(f"  Git repository initialized with branch '{branch}'.")
    else:
        print("  Git repository already exists.")

def _set_remote(project_root: Path, remote_url: str, remote_name: str = "origin"):
    """Sets or updates the Git remote origin."""
    # Check if remote already exists
    remotes = _run_command(["git", "remote"], project_root, "Failed to list Git remotes")
    if remote_name in remotes.splitlines():
        existing_url = _run_command(["git", "config", "--local", f"remote.{remote_name}.url"], project_root, "")
        if existing_url != remote_url:
            print(f"  Updating remote '{remote_name}' URL from {existing_url} to {remote_url}...")
            _run_command(["git", "remote", "set-url", remote_name, remote_url], project_root, "Failed to set remote URL")
            print(f"  Remote '{remote_name}' updated.")
        else:
            print(f"  Remote '{remote_name}' already set to {remote_url}.")
    else:
        print(f"  Adding remote '{remote_name}' with URL {remote_url}...")
        _run_command(["git", "remote", "add", remote_name, remote_url], project_root, "Failed to add remote")
        print(f"  Remote '{remote_name}' added.")

def _configure_auth(project_root: Path, method: str, token: str | None = None):
    """Configures Git authentication method."""
    print(f"Configuring Git authentication using method: {method}...")
    if method == "gh":
        print("  Using GitHub CLI for credential helper.")
        _run_command(["gh", "auth", "setup-git"], project_root, "Failed to setup gh CLI credential helper")
    elif method == "ssh":
        print("  Assuming SSH key is already configured and git@github.com access is working.")
        # No specific git command needed, just a check for user awareness
    elif method == "token":
        resolved_token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if resolved_token is None:
            raise ValueError("GitHub PAT token required for 'token' authentication method. Set via --token argument or GITHUB_TOKEN/GH_TOKEN environment variable.")
        print("  Storing GitHub PAT using OS keychain helper (or in-memory cache). THIS IS A SIMULATION.")
        # In a real scenario, this would involve piping resolved_token to `git credential approve`
        print("  (Simulated) PAT stored securely.")
    else:
        raise ValueError(f"Unknown authentication method: {method}")

def _install_pii_pre_commit_hook(project_root: Path):
    """Installs the PII pre-commit hook."""
    print("Installing PII pre-commit hook...")
    hook_path = project_root / ".git" / "hooks" / "pre-commit"
    check_pii_script_path = DEFAULT_PROJECT_ROOT / "Skills" / "check_no_pii.py"

    hook_content = f"""#!/bin/bash
# PII Pre-commit Hook managed by asr-benchmark-harness setup_github.py

PYTHONPATH="{os.environ.get('PYTHONPATH', '')}" /tmp/opencode/.venv/bin/python "{check_pii_script_path}" staged

if [ $? -ne 0 ]; then
  echo "\n⛔ PII/Secret scan failed. Aborting commit.\n"
  exit 1
fi
"""
    hook_path.write_text(hook_content)
    os.chmod(hook_path, 0o755) # Make executable
    print("  PII pre-commit hook installed.")

def _write_gitignore(project_root: Path):
    """Writes or updates the managed .gitignore block."""
    print("Writing/updating .gitignore...")
    gitignore_path = project_root / ".gitignore"

    gitignore_content = """
# Managed by asr-benchmark-harness setup_github.py. DO NOT EDIT THIS BLOCK.
# --- ASR BENCHMARK IGNORE START ---
.venv/
/output/
/models/
/data/
gemini_query_prompt.md
details.csv
summary.csv
# --- ASR BENCHMARK IGNORE END ---
"""
    
    current_content = ""
    if gitignore_path.exists():
        current_content = gitignore_path.read_text()
    
    # Remove existing block if present
    current_content = re.sub(r"# --- ASR BENCHMARK IGNORE START ---\n.*?# --- ASR BENCHMARK IGNORE END ---\n", "", current_content, flags=re.DOTALL)
    
    new_content = current_content.strip() + "\n" + gitignore_content
    gitignore_path.write_text(new_content.strip() + "\n")
    print("  .gitignore updated.")

# --- Commands ---

def cmd_init(args):
    """Initializes Git repo, sets identity, remote, auth, .gitignore, and PII hook."""
    print("Running full Git/GitHub setup...")
    _initialize_git_repo(args.project_root, args.branch)
    _set_git_config(args.project_root, "user.name", args.name)
    _set_git_config(args.project_root, "user.email", args.email)
    _set_remote(args.project_root, args.remote)
    _configure_auth(args.project_root, args.method, args.token)
    _write_gitignore(args.project_root)
    _install_pii_pre_commit_hook(args.project_root)
    print("Full Git/GitHub setup complete. Run 'python Skills/setup_github.py verify' to confirm connection.")

def cmd_doctor(args):
    """Diagnoses current Git/GitHub setup state."""
    print("Diagnosing Git/GitHub setup...")
    if not (args.project_root / ".git").exists():
        print("❌ Not a Git repository.")
        return
    
    print("✅ Git repository initialized.")
    print(f"  User Name: {_check_git_config(args.project_root, 'user.name') or 'Not set'}")
    print(f"  User Email: {_check_git_config(args.project_root, 'user.email') or 'Not set'}")
    
    remotes = _run_command(["git", "remote"], args.project_root, "Failed to list remotes")
    if "origin" in remotes.splitlines():
        remote_url = _check_git_config(args.project_root, "remote.origin.url")
        print(f"  Remote 'origin' URL: {remote_url}")
    else:
        print("  ❌ Remote 'origin' not set.")

    # Check .gitignore for managed block
    gitignore_path = args.project_root / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if "# --- ASR BENCHMARK IGNORE START ---" in content and "# --- ASR BENCHMARK IGNORE END ---" in content:
            print("✅ Managed .gitignore block is present.")
        else:
            print("⚠️  Managed .gitignore block is missing or malformed.")
    else:
        print("⚠️  .gitignore file is missing.")

    # Check PII hook
    hook_path = args.project_root / ".git" / "hooks" / "pre-commit"
    if hook_path.exists() and "# PII Pre-commit Hook" in hook_path.read_text():
        print("✅ PII pre-commit hook is installed.")
    else:
        print("⚠️  PII pre-commit hook is missing or malformed.")

def cmd_gitignore(args):
    """Rewrites the managed .gitignore block."""
    _write_gitignore(args.project_root)

def cmd_auth(args):
    """Configures Git authentication."""
    _configure_auth(args.project_root, args.method, args.token)

def cmd_hook(args):
    """Installs the PII pre-commit hook."""
    _install_pii_pre_commit_hook(args.project_root)

def cmd_verify(args):
    """Verifies connectivity to the remote origin."""
    print("Verifying Git remote connection...")
    try:
        # Use git ls-remote to check connection without cloning
        _run_command(["git", "ls-remote", "--exit-code", "origin"], args.project_root, "Failed to verify remote connection")
        print("✅ Git remote connection to 'origin' successful.")
    except RuntimeError as e:
        print(f"❌ Git remote connection FAILED: {e}")

# --- Argument Parsing ---

def main():
    parser = argparse.ArgumentParser(description="ASR Benchmark GitHub Setup Skill")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT,
                        help=f"Project root directory (default: {DEFAULT_PROJECT_ROOT})")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize Git repo, set identity/remote/auth/hooks")
    init_parser.add_argument("--remote", type=str, required=True, help="GitHub remote URL (e.g., https://github.com/user/repo.git)")
    init_parser.add_argument("--name", type=str, required=True, help="Git user name")
    init_parser.add_argument("--email", type=str, required=True, help="Git user email")
    init_parser.add_argument("--branch", type=str, default="main", help="Initial branch name")
    init_parser.add_argument("--method", type=str, choices=["gh", "ssh", "token"], default="gh",
                             help="Authentication method for GitHub")
    init_parser.add_argument("--token", type=str, help="GitHub PAT for 'token' auth method (will not be stored in .git/config)")
    init_parser.set_defaults(func=cmd_init)

    # doctor command
    doctor_parser = subparsers.add_parser("doctor", help="Diagnose current Git/GitHub setup state")
    doctor_parser.set_defaults(func=cmd_doctor)

    # gitignore command
    gitignore_parser = subparsers.add_parser("gitignore", help="Rewrites the managed .gitignore block")
    gitignore_parser.set_defaults(func=cmd_gitignore)

    # auth command
    auth_parser = subparsers.add_parser("auth", help="Configures Git authentication")
    auth_parser.add_argument("--method", type=str, choices=["gh", "ssh", "token"], required=True,
                             help="Authentication method for GitHub")
    auth_parser.add_argument("--token", type=str, help="GitHub PAT for 'token' auth method")
    auth_parser.set_defaults(func=cmd_auth)

    # hook command
    hook_parser = subparsers.add_parser("hook", help="Installs the PII pre-commit hook")
    hook_parser.set_defaults(func=cmd_hook)

    # verify command
    verify_parser = subparsers.add_parser("verify", help="Verifies connectivity to the remote origin")
    verify_parser.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
