#!/usr/bin/env python3
"""Deterministic Antigravity CLI wrapper for Codex analysis workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


DEFAULT_MODEL = "Gemini 3.1 Pro (High)"
MINIMUM_ANTIGRAVITY_VERSION = (1, 1, 2)
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_ONE_SHOT = True
DEFAULT_EXECUTION_MODE = "plan"
DEFAULT_HEALTHCHECK_TIMEOUT_SECONDS = 45
DEFAULT_PROGRESS_HEARTBEAT_SECONDS = 20
MAX_PROMPT_BYTES = 128 * 1024
HEALTHCHECK_AUTH_PROMPT = "Reply with exactly: AUTH_OK"

MODEL_ALIASES = {
    "gemini3.1pro": DEFAULT_MODEL,
    "gemini3.1prohigh": DEFAULT_MODEL,
    "gemini31pro": DEFAULT_MODEL,
    "gemini31prohigh": DEFAULT_MODEL,
    "gemini3pro": DEFAULT_MODEL,
    "gemini3prohigh": DEFAULT_MODEL,
}

AUTH_ERROR_PATTERNS = (
    "authorization is required",
    "authentication required",
    "not authenticated",
    "not signed in",
    "please sign in",
)

CRITICAL_STDERR_PATTERNS = (
    "outside workspace",
    "permission denied",
    "failed to read",
    "error executing tool",
)


def normalize_model_name(model: str) -> str:
    candidate = model.strip()
    if not candidate:
        return DEFAULT_MODEL
    alias_key = re.sub(r"[^a-z0-9.]+", "", candidate.lower())
    return MODEL_ALIASES.get(alias_key, candidate)


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(?:^|\s)v?(\d+)\.(\d+)\.(\d+)(?:\s|$)", value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def prompt_size_bytes(prompt: str) -> int:
    return len(prompt.encode("utf-8"))


def parse_comma_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_path_list(values: Sequence[str | Path], *, base_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        paths.append(path.resolve())
    return paths


def validate_paths_exist(
    paths: Sequence[Path], *, expected: str
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for path in paths:
        if expected == "file" and not path.is_file():
            missing.append(str(path))
        if expected == "dir" and not path.is_dir():
            missing.append(str(path))
    return not missing, missing


def is_path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def unique_paths(paths: Sequence[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def workspace_directories_for_context(
    *,
    cwd: Path,
    context_files: Sequence[Path],
    context_dirs: Sequence[Path],
    explicit_directories: Sequence[Path],
) -> list[Path]:
    directories = list(explicit_directories)
    directories.extend(
        path.parent for path in context_files if not is_path_within(path, cwd)
    )
    directories.extend(path for path in context_dirs if not is_path_within(path, cwd))
    return unique_paths(directories)


def compose_prompt(
    *,
    user_prompt: str,
    context_files: Sequence[Path],
    context_dirs: Sequence[Path],
    one_shot: bool,
) -> str:
    context_refs = [str(path) for path in [*context_files, *context_dirs]]
    prompt_blocks: list[str] = []

    if context_refs:
        prompt_blocks.append(
            "Read every explicitly referenced file and directory before answering. "
            "If any path cannot be read, stop and report that path; do not produce a partial review:\n"
            + "\n".join(f"- {path}" for path in context_refs)
        )

    if one_shot:
        prompt_blocks.append(
            "ONE-SHOT ANALYSIS MODE:\n"
            "- Return a complete final answer in one response.\n"
            "- Do not ask follow-up questions.\n"
            "- Do not modify project files or execute commands that change state.\n"
            "- If assumptions are required, list them explicitly.\n"
            "- Separate verified findings from hypotheses.\n"
            "- Highlight technical, security, and business-flow risks."
        )

    prompt_blocks.append(f"Task:\n{user_prompt}")
    return "\n\n".join(prompt_blocks)


def read_prompt(prompt: str | None, prompt_file: Path | None) -> str:
    if prompt and prompt_file:
        raise ValueError("Provide either --prompt or --prompt-file, not both.")
    if prompt_file:
        try:
            prompt_text = prompt_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Unable to read prompt file: {prompt_file}") from exc
        if not prompt_text.strip():
            raise ValueError("Prompt file is empty.")
        return prompt_text
    if prompt and prompt.strip():
        return prompt
    raise ValueError("Missing prompt. Provide --prompt or --prompt-file.")


def build_command(
    *,
    antigravity_binary: str,
    model: str,
    execution_mode: str,
    add_directories: Sequence[Path],
    prompt: str,
    print_timeout_seconds: int,
) -> list[str]:
    command = [
        antigravity_binary,
        "--print",
        prompt,
        "--model",
        model,
        "--mode",
        execution_mode,
        "--sandbox",
        "--print-timeout",
        f"{print_timeout_seconds}s",
    ]
    for directory in add_directories:
        command.extend(["--add-dir", str(directory)])
    return command


def command_for_logs(command: Sequence[str]) -> list[str]:
    redacted = list(command)
    try:
        prompt_index = redacted.index("--print") + 1
    except ValueError:
        return redacted
    if prompt_index < len(redacted):
        redacted[prompt_index] = "<prompt>"
    return redacted


def json_output(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def log_progress(enabled: bool, phase: str, message: str) -> None:
    if not enabled:
        return
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    sys.stderr.write(f"[antigravity-bridge][{timestamp}][{phase}] {message}\n")
    sys.stderr.flush()


def error_payload(
    error_type: str,
    message: str,
    *,
    exit_code: int,
    details: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    payload: dict[str, Any] = {
        "ok": False,
        "provider": "antigravity-cli",
        "error": {"type": error_type, "message": message},
        "exit_code": exit_code,
    }
    if details:
        payload["error"]["details"] = details
    return payload, exit_code


def detect_auth_error(stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    return any(pattern in combined for pattern in AUTH_ERROR_PATTERNS)


def detect_critical_stderr(stderr: str) -> str | None:
    lower = stderr.lower()
    for pattern in CRITICAL_STDERR_PATTERNS:
        if pattern in lower:
            return pattern
    return None


def run_checked(
    command: Sequence[str],
    *,
    timeout: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env={**dict(os.environ), "NO_COLOR": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def perform_cli_preflight(
    antigravity_binary: str,
    model: str,
) -> tuple[dict[str, Any], int]:
    binary_path = shutil.which(antigravity_binary)
    if not binary_path:
        return error_payload(
            "BINARY_NOT_FOUND",
            f"Antigravity CLI binary '{antigravity_binary}' was not found in PATH.",
            exit_code=127,
            details={"binary": antigravity_binary},
        )

    try:
        version_proc = run_checked([antigravity_binary, "--version"], timeout=15)
        models_proc = run_checked([antigravity_binary, "models"], timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return error_payload(
            "HEALTHCHECK_FAILED",
            "Unable to query Antigravity CLI version or models.",
            exit_code=70,
            details={"reason": str(exc), "binary": antigravity_binary},
        )

    if version_proc.returncode != 0:
        return error_payload(
            "VERSION_CHECK_FAILED",
            "Antigravity CLI version check failed.",
            exit_code=version_proc.returncode,
            details={
                "stdout": version_proc.stdout.strip(),
                "stderr": version_proc.stderr.strip(),
            },
        )

    installed_version = parse_version(version_proc.stdout)
    if installed_version is None or installed_version < MINIMUM_ANTIGRAVITY_VERSION:
        minimum = ".".join(str(part) for part in MINIMUM_ANTIGRAVITY_VERSION)
        return error_payload(
            "VERSION_UNSUPPORTED",
            f"Antigravity CLI {minimum} or newer is required.",
            exit_code=69,
            details={
                "installed_version": version_proc.stdout.strip(),
                "minimum_version": minimum,
            },
        )

    available_models = [
        line.strip() for line in models_proc.stdout.splitlines() if line.strip()
    ]
    if models_proc.returncode != 0 or model not in available_models:
        return error_payload(
            "MODEL_UNAVAILABLE",
            f"Required Antigravity model is unavailable: {model}",
            exit_code=models_proc.returncode or 69,
            details={
                "requested_model": model,
                "available_models": available_models,
                "stderr": models_proc.stderr.strip(),
            },
        )

    payload = {
        "ok": True,
        "provider": "antigravity-cli",
        "binary": antigravity_binary,
        "binary_path": binary_path,
        "version": ".".join(str(part) for part in installed_version),
        "requested_model": model,
        "available_models": available_models,
        "exit_code": 0,
    }
    return payload, 0


def perform_healthcheck(
    antigravity_binary: str,
    model: str,
    *,
    progress_logs: bool = False,
) -> tuple[dict[str, Any], int]:
    log_progress(progress_logs, "HEALTHCHECK", "Starting Antigravity CLI healthcheck.")
    preflight, preflight_code = perform_cli_preflight(antigravity_binary, model)
    if preflight_code != 0:
        return preflight, preflight_code

    auth_command = build_command(
        antigravity_binary=antigravity_binary,
        model=model,
        execution_mode=DEFAULT_EXECUTION_MODE,
        add_directories=[],
        prompt=HEALTHCHECK_AUTH_PROMPT,
        print_timeout_seconds=DEFAULT_HEALTHCHECK_TIMEOUT_SECONDS,
    )
    try:
        auth_proc = run_checked(
            auth_command, timeout=DEFAULT_HEALTHCHECK_TIMEOUT_SECONDS + 5
        )
    except subprocess.TimeoutExpired:
        return error_payload(
            "HEALTHCHECK_AUTH_TIMEOUT",
            "Antigravity authentication check timed out in print mode.",
            exit_code=124,
            details={"command": command_for_logs(auth_command)},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return error_payload(
            "HEALTHCHECK_AUTH_FAILED",
            "Unable to execute the Antigravity authentication check.",
            exit_code=70,
            details={"reason": str(exc), "command": command_for_logs(auth_command)},
        )

    if auth_proc.returncode != 0:
        error_type = (
            "AUTH_REQUIRED"
            if detect_auth_error(auth_proc.stdout, auth_proc.stderr)
            else "HEALTHCHECK_AUTH_FAILED"
        )
        return error_payload(
            error_type,
            "Antigravity CLI is not ready for authenticated non-interactive execution.",
            exit_code=auth_proc.returncode,
            details={
                "stdout_preview": auth_proc.stdout[:500],
                "stderr_preview": auth_proc.stderr[:500],
                "recommendation": "Run `agy` interactively and complete Google OAuth or Google Cloud onboarding.",
                "command": command_for_logs(auth_command),
            },
        )

    if auth_proc.stdout.strip() != "AUTH_OK":
        return error_payload(
            "HEALTHCHECK_UNEXPECTED_RESPONSE",
            "Antigravity CLI returned an unexpected healthcheck response.",
            exit_code=65,
            details={"stdout_preview": auth_proc.stdout[:500]},
        )

    payload = {
        **preflight,
        "model_default": model,
        "execution_mode": DEFAULT_EXECUTION_MODE,
        "sandbox": True,
        "auth_check": {"ok": True, "exit_code": 0},
        "exit_code": 0,
    }
    log_progress(progress_logs, "HEALTHCHECK", "Healthcheck finished successfully.")
    return payload, 0


def execute_antigravity(
    *,
    antigravity_binary: str,
    model: str,
    execution_mode: str,
    prompt: str,
    context_files: Sequence[Path],
    context_dirs: Sequence[Path],
    add_directories: Sequence[Path],
    cwd: Path,
    timeout_seconds: int,
    progress_logs: bool,
    progress_heartbeat_seconds: int,
) -> tuple[dict[str, Any], int]:
    if not shutil.which(antigravity_binary):
        return error_payload(
            "BINARY_NOT_FOUND",
            f"Antigravity CLI binary '{antigravity_binary}' was not found in PATH.",
            exit_code=127,
        )

    command = build_command(
        antigravity_binary=antigravity_binary,
        model=model,
        execution_mode=execution_mode,
        add_directories=add_directories,
        prompt=prompt,
        print_timeout_seconds=timeout_seconds,
    )
    log_progress(
        progress_logs,
        "EXECUTE",
        f"Starting Antigravity CLI (model={model}, mode={execution_mode}, cwd={cwd}).",
    )

    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env={**dict(os.environ), "NO_COLOR": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return error_payload(
            "EXECUTION_ERROR",
            "Antigravity CLI execution failed before completion.",
            exit_code=70,
            details={"reason": str(exc), "command": command_for_logs(command)},
        )

    started_at = time.monotonic()
    heartbeat_seconds = max(1, progress_heartbeat_seconds)
    while True:
        elapsed = time.monotonic() - started_at
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            process.kill()
            stdout, stderr = process.communicate()
            return error_payload(
                "TIMEOUT",
                "Antigravity CLI timed out before returning a result.",
                exit_code=124,
                details={
                    "timeout_seconds": timeout_seconds,
                    "partial_stdout": (stdout or "").strip(),
                    "partial_stderr": (stderr or "").strip(),
                    "command": command_for_logs(command),
                },
            )
        try:
            stdout, stderr = process.communicate(
                timeout=min(remaining, heartbeat_seconds)
            )
            break
        except subprocess.TimeoutExpired:
            log_progress(
                progress_logs,
                "RUNNING",
                f"Antigravity CLI still running ({int(time.monotonic() - started_at)}s elapsed).",
            )

    duration_seconds = round(time.monotonic() - started_at, 3)
    log_progress(
        progress_logs,
        "COMPLETE",
        f"Antigravity CLI finished in {duration_seconds}s with exit code {process.returncode}.",
    )

    if process.returncode != 0:
        error_type = (
            "AUTH_REQUIRED" if detect_auth_error(stdout, stderr) else "PROCESS_ERROR"
        )
        return error_payload(
            error_type,
            "Antigravity CLI returned a non-zero exit code.",
            exit_code=process.returncode,
            details={
                "stdout_preview": stdout[:1000],
                "stderr_preview": stderr[:1000],
                "command": command_for_logs(command),
            },
        )

    stderr_pattern = detect_critical_stderr(stderr or "")
    if stderr_pattern:
        return error_payload(
            "ANTIGRAVITY_TOOL_ERROR",
            "Antigravity CLI reported a tool-level error.",
            exit_code=65,
            details={
                "matched_pattern": stderr_pattern,
                "stdout_preview": stdout[:1000],
                "stderr_preview": stderr[:1000],
                "command": command_for_logs(command),
            },
        )

    if not stdout.strip():
        return error_payload(
            "EMPTY_RESPONSE",
            "Antigravity CLI completed without a response.",
            exit_code=65,
            details={
                "stderr_preview": stderr[:1000],
                "command": command_for_logs(command),
            },
        )

    payload: dict[str, Any] = {
        "ok": True,
        "provider": "antigravity-cli",
        "exit_code": 0,
        "binary": antigravity_binary,
        "model": model,
        "execution_mode": execution_mode,
        "sandbox": True,
        "cwd": str(cwd),
        "context_files": [str(path) for path in context_files],
        "context_dirs": [str(path) for path in context_dirs],
        "workspace_directories": [str(path) for path in add_directories],
        "command": command_for_logs(command),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "duration_seconds": duration_seconds,
        "response": stdout.strip(),
        "stderr": stderr,
    }
    return payload, 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Antigravity CLI in sandboxed plan mode with strict model control."
    )
    parser.add_argument(
        "--antigravity-binary",
        default="agy",
        help="Antigravity CLI executable name or full path.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Exact Antigravity model name. Defaults to {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--execution-mode",
        choices=["plan"],
        default=DEFAULT_EXECUTION_MODE,
        help="Fixed to plan so delegated analysis cannot edit project files.",
    )
    parser.add_argument("--prompt", help="Prompt text to send to Antigravity CLI.")
    parser.add_argument(
        "--prompt-file", type=Path, help="UTF-8 file containing prompt text."
    )
    parser.add_argument(
        "--add-directory",
        action="append",
        default=[],
        help="Additional trusted Antigravity workspace directory (repeatable).",
    )
    parser.add_argument(
        "--add-directories",
        help="Comma-separated trusted Antigravity workspace directories.",
    )
    parser.add_argument(
        "--cwd", type=Path, default=Path.cwd(), help="Primary workspace directory."
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Wrapper and Antigravity print-mode timeout in seconds.",
    )
    parser.add_argument(
        "--context-file",
        action="append",
        default=[],
        help="File Antigravity must read before answering (repeatable).",
    )
    parser.add_argument("--context-files", help="Comma-separated context files.")
    parser.add_argument(
        "--context-dir",
        action="append",
        default=[],
        help="Directory Antigravity must inspect before answering (repeatable).",
    )
    parser.add_argument("--context-dirs", help="Comma-separated context directories.")
    parser.add_argument(
        "--healthcheck", action="store_true", help="Check binary, model, and auth."
    )
    parser.add_argument(
        "--progress-logs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print wrapper progress and heartbeat logs to stderr.",
    )
    parser.add_argument(
        "--progress-heartbeat-seconds",
        type=int,
        default=DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
        help="Heartbeat interval while Antigravity is running.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    model = normalize_model_name(args.model)

    if args.timeout_seconds <= 0 or args.progress_heartbeat_seconds <= 0:
        payload, code = error_payload(
            "INVALID_ARGUMENT",
            "Timeout and heartbeat values must be positive integers.",
            exit_code=2,
        )
        json_output(payload)
        return code

    cwd = args.cwd.expanduser().resolve()
    if not cwd.is_dir():
        payload, code = error_payload(
            "INVALID_ARGUMENT",
            f"Working directory does not exist or is not a directory: {cwd}",
            exit_code=2,
        )
        json_output(payload)
        return code

    log_progress(args.progress_logs, "START", f"Wrapper started (cwd={cwd}).")
    if args.healthcheck:
        payload, code = perform_healthcheck(
            args.antigravity_binary,
            model,
            progress_logs=args.progress_logs,
        )
        json_output(payload)
        return code

    try:
        prompt = read_prompt(args.prompt, args.prompt_file)
    except ValueError as exc:
        payload, code = error_payload("INVALID_ARGUMENT", str(exc), exit_code=2)
        json_output(payload)
        return code

    context_files = parse_path_list(
        [*args.context_file, *parse_comma_list(args.context_files)],
        base_dir=cwd,
    )
    context_dirs = parse_path_list(
        [*args.context_dir, *parse_comma_list(args.context_dirs)],
        base_dir=cwd,
    )
    explicit_directories = parse_path_list(
        [*args.add_directory, *parse_comma_list(args.add_directories)],
        base_dir=cwd,
    )

    files_ok, missing_files = validate_paths_exist(context_files, expected="file")
    dirs_ok, missing_dirs = validate_paths_exist(context_dirs, expected="dir")
    explicit_ok, missing_explicit = validate_paths_exist(
        explicit_directories, expected="dir"
    )
    if not files_ok or not dirs_ok or not explicit_ok:
        payload, code = error_payload(
            "INVALID_CONTEXT_PATH",
            "One or more context or workspace paths do not exist.",
            exit_code=2,
            details={
                "missing_files": missing_files,
                "missing_dirs": missing_dirs,
                "missing_workspace_dirs": missing_explicit,
            },
        )
        json_output(payload)
        return code

    add_directories = workspace_directories_for_context(
        cwd=cwd,
        context_files=context_files,
        context_dirs=context_dirs,
        explicit_directories=explicit_directories,
    )
    prompt_with_context = compose_prompt(
        user_prompt=prompt,
        context_files=context_files,
        context_dirs=context_dirs,
        one_shot=DEFAULT_ONE_SHOT,
    )
    prompt_bytes = prompt_size_bytes(prompt_with_context)
    if prompt_bytes > MAX_PROMPT_BYTES:
        payload, code = error_payload(
            "PROMPT_TOO_LARGE",
            "Refusing to send an oversized prompt that Antigravity may truncate.",
            exit_code=2,
            details={
                "prompt_bytes": prompt_bytes,
                "maximum_bytes": MAX_PROMPT_BYTES,
                "recommendation": (
                    "Keep instructions concise and pass source evidence through "
                    "--context-file or --context-dir."
                ),
            },
        )
        json_output(payload)
        return code
    runtime_preflight, preflight_code = perform_cli_preflight(
        args.antigravity_binary,
        model,
    )
    if preflight_code != 0:
        json_output(runtime_preflight)
        return preflight_code
    payload, code = execute_antigravity(
        antigravity_binary=args.antigravity_binary,
        model=model,
        execution_mode=args.execution_mode,
        prompt=prompt_with_context,
        context_files=context_files,
        context_dirs=context_dirs,
        add_directories=add_directories,
        cwd=cwd,
        timeout_seconds=args.timeout_seconds,
        progress_logs=args.progress_logs,
        progress_heartbeat_seconds=args.progress_heartbeat_seconds,
    )
    payload["runtime_preflight"] = runtime_preflight
    json_output(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
