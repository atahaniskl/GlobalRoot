"""
Bash Tool — Secure command execution (Path Sandbox)
"""
import os
import re
import shlex
import subprocess
from pathlib import Path

from config import (
    BANNED_COMMANDS, DANGEROUS_PATTERNS,
    ALLOWED_DIRS, BASH_TIMEOUT, BASH_MAX_OUTPUT,
)


def _is_within_dir(path: str, base_dir: str) -> bool:
    """Robust containment check that avoids startswith path-bypass issues."""
    try:
        path_norm = os.path.normcase(os.path.realpath(path))
        base_norm = os.path.normcase(os.path.realpath(os.path.expanduser(base_dir)))
        return os.path.commonpath([path_norm, base_norm]) == base_norm
    except Exception:
        return False


def validate_command(command: str) -> tuple[bool, str]:
    """
    Runs the command through security filters.
    Returns: (is_valid, message)
    """
    command_lower = command.lower()

    for banned in BANNED_COMMANDS:
        banned_lower = banned.lower()
        if len(banned_lower) <= 2 or " " not in banned_lower:
            if re.search(r'\b' + re.escape(banned_lower) + r'\b', command_lower):
                return False, f"❌ SECURITY: '{banned}' command is banned!"

    for pattern in DANGEROUS_PATTERNS:
        if pattern in command_lower:
            return False, f"❌ SECURITY: Dangerous pattern detected: '{pattern}'"

    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()

    def _is_abs_path_arg(arg: str) -> bool:
        return (
            arg.startswith("/")
            or arg.startswith("~")
            or bool(re.match(r"^[a-zA-Z]:[\\/]", arg))
            or arg.startswith("\\\\")
        )

    for arg in parts[1:]:
        if _is_abs_path_arg(arg):
            real_path = os.path.realpath(os.path.expanduser(arg))
            if not any(_is_within_dir(real_path, allowed) for allowed in ALLOWED_DIRS):
                home = str(Path.home())
                if not _is_within_dir(real_path, home) and not _is_within_dir(real_path, "/tmp"):
                    return False, f"❌ SECURITY: '{arg}' is not in allowed directories!"

    return True, "✅"


def bash(command: str) -> str:
    """
    Run a secure bash command.
    - Banned/Dangerous blocked
    - Starts the process; waits for BASH_TIMEOUT (10-15s).
    - If it doesn't finish, leaves it running in the background and returns output so far.
    - Long outputs are middle-truncated (First 50 lines... Last 50 lines) to save LLM tokens.
    """
    valid, msg = validate_command(command)
    if not valid:
        return msg

    try:
        # Start command asynchronously
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(Path.home()),
            start_new_session=True # Detach so it survives Python execution
        )

        try:
            # Wait for it to finish within timeout
            stdout, _ = process.communicate(timeout=BASH_TIMEOUT)
            is_background = False
        except subprocess.TimeoutExpired:
            # If it times out, DO NOT KILL IT. Leave it running in the background!
            is_background = True
            stdout = f"\n[The command did not finish within {BASH_TIMEOUT}s. It has been moved to the BACKGROUND and is still executing (PID: {process.pid}).]\n"

        # Output Pagination (Middle Truncation)
        lines = stdout.splitlines()
        if len(lines) > 120:
            top_lines = lines[:50]
            bottom_lines = lines[-50:]
            skipped_count = len(lines) - 100
            
            truncated_stdout = "\n".join(top_lines)
            truncated_stdout += f"\n\n... [ {skipped_count} lines skipped because output was too long. Showing top 50 and bottom 50 lines ] ...\n\n"
            truncated_stdout += "\n".join(bottom_lines)
        else:
            truncated_stdout = stdout

        if is_background:
            return f"⏳ Background Process Info:\n{truncated_stdout}"
        
        if process.returncode == 0:
            return f"✅ Command successful:\n{truncated_stdout}"
        else:
            return f"⚠️ Command returned error (exit code: {process.returncode}):\n{truncated_stdout}"

    except Exception as e:
        return f"❌ ERROR: {type(e).__name__}: {str(e)}"
