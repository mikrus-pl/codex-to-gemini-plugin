#!/usr/bin/env python3
"""Deterministic Gemini CLI wrapper for Codex plugin workflows."""

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

DEFAULT_MODEL = "gemini-3.1-pro-preview"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_ONE_SHOT = True
DEFAULT_APPROVAL_MODE = "plan"
DEFAULT_HEALTHCHECK_TIMEOUT_SECONDS = 30
DEFAULT_PROGRESS_HEARTBEAT_SECONDS = 20
HEALTHCHECK_AUTH_PROMPT = "Reply with exactly: AUTH_OK"

MODEL_ALIASES = {
    "gemini3.1pro": DEFAULT_MODEL,
    "gemini3.1propreview": DEFAULT_MODEL,
    "gemini31pro": DEFAULT_MODEL,
    "gemini31propreview": DEFAULT_MODEL,
    "gemini3pro": DEFAULT_MODEL,
    "gemini3propreview": DEFAULT_MODEL,
}

CRITICAL_STDERR_PATTERNS = (
    "path not in workspace",
    "error executing tool",
)
GEMINI_TMP_ROOT = Path.home() / ".gemini" / "tmp"


def normalize_model_name(model: str) -> str:
    candidate = model.strip()
    if not candidate:
        return DEFAULT_MODEL
    alias_key = re.sub(r"[^a-z0-9.]+", "", candidate.lower())
    return MODEL_ALIASES.get(alias_key, candidate)


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
        paths.append(path)
    return paths


def escape_at_path(path: str) -> str:
    return path.replace(" ", "\\ ")


def validate_paths_exist(paths: Sequence[Path], *, expected: str) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for path in paths:
        resolved = path.resolve()
        if expected == "file" and not resolved.is_file():
            missing.append(str(resolved))
        if expected == "dir" and not resolved.is_dir():
            missing.append(str(resolved))
    return len(missing) == 0, missing


def is_path_within(path: Path, root: Path) -> bool:
    normalized_path = path.resolve(strict=False)
    normalized_root = root.resolve(strict=False)
    try:
        normalized_path.relative_to(normalized_root)
        return True
    except ValueError:
        return False


def allowed_context_roots(*, cwd: Path) -> list[Path]:
    project_tmp = (GEMINI_TMP_ROOT / cwd.name).resolve(strict=False)
    return [cwd.resolve(), project_tmp]


def find_external_paths(paths: Sequence[Path], *, roots: Sequence[Path]) -> list[Path]:
    external: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if any(is_path_within(resolved, root) for root in roots):
            continue
        external.append(resolved)
    return external


def unique_materialized_path(destination: Path) -> Path:
    if not destination.exists():
        return destination
    counter = 1
    candidate = destination
    while candidate.exists():
        candidate = destination.with_name(f"{destination.name}-{counter}")
        counter += 1
    return candidate


def materialize_external_paths(
    paths: Sequence[Path],
    *,
    roots: Sequence[Path],
    destination_root: Path,
    expected: str,
) -> tuple[list[Path], list[dict[str, str]]]:
    rewritten: list[Path] = []
    copies: list[dict[str, str]] = []
    destination_root.mkdir(parents=True, exist_ok=True)

    for path in paths:
        resolved = path.resolve()
        if any(is_path_within(resolved, root) for root in roots):
            rewritten.append(resolved)
            continue

        base_name = resolved.name or "context"
        destination = unique_materialized_path(destination_root / base_name)
        if expected == "file":
            shutil.copy2(resolved, destination)
        else:
            shutil.copytree(resolved, destination)
        rewritten_destination = destination.resolve()
        rewritten.append(rewritten_destination)
        copies.append(
            {
                "source": str(resolved),
                "materialized": str(rewritten_destination),
            }
        )

    return rewritten, copies


def detect_critical_stderr(stderr: str) -> str | None:
    lower = stderr.lower()
    for pattern in CRITICAL_STDERR_PATTERNS:
        if pattern in lower:
            return pattern
    return None


def compose_prompt(
    *,
    user_prompt: str,
    context_files: Sequence[Path],
    context_dirs: Sequence[Path],
    one_shot: bool,
) -> str:
    context_refs: list[str] = []
    for path in [*context_files, *context_dirs]:
        context_refs.append(f"@{escape_at_path(str(path.resolve()))}")

    prompt_blocks: list[str] = []
    if context_refs:
        prompt_blocks.append(
            "Read all referenced files/directories fully before answering:\n"
            + "\n".join(context_refs)
        )

    if one_shot:
        prompt_blocks.append(
            "ONE-SHOT MODE:\n"
            "- Return a complete final answer in one response.\n"
            "- Do not ask follow-up questions.\n"
            "- Do not modify any files. Analysis only.\n"
            "- If assumptions are required, list them explicitly.\n"
            "- Highlight risks and unknowns clearly."
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
    gemini_binary: str,
    model: str,
    output_format: str,
    approval_mode: str,
    include_directories: Sequence[str],
    prompt: str,
) -> list[str]:
    command = [
        gemini_binary,
        "--model",
        model,
        "--output-format",
        output_format,
        "--approval-mode",
        approval_mode,
    ]
    if include_directories:
        command.extend(["--include-directories", ",".join(include_directories)])
    # Gemini CLI now recommends positional prompt input over deprecated --prompt.
    command.append(prompt)
    return command


def command_for_logs(command: Sequence[str]) -> list[str]:
    if not command:
        return []
    redacted = list(command)
    redacted[-1] = "<prompt>"
    return redacted


def json_output(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def log_progress(enabled: bool, phase: str, message: str) -> None:
    if not enabled:
        return
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    sys.stderr.write(f"[gemini-bridge][{timestamp}][{phase}] {message}\n")
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
        "error": {
            "type": error_type,
            "message": message,
        },
        "exit_code": exit_code,
    }
    if details:
        payload["error"]["details"] = details
    return payload, exit_code


def perform_healthcheck(
    gemini_binary: str,
    model: str,
    *,
    progress_logs: bool = False,
) -> tuple[dict[str, Any], int]:
    log_progress(progress_logs, "HEALTHCHECK", "Starting wrapper healthcheck.")
    binary_path = shutil.which(gemini_binary)
    if not binary_path:
        return error_payload(
            "BINARY_NOT_FOUND",
            f"Gemini CLI binary '{gemini_binary}' was not found in PATH.",
            exit_code=127,
            details={"binary": gemini_binary},
        )
    log_progress(
        progress_logs,
        "HEALTHCHECK",
        f"Gemini binary found at {binary_path}. Checking version and auth.",
    )

    try:
        version_proc = subprocess.run(
            [gemini_binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return error_payload(
            "HEALTHCHECK_FAILED",
            "Unable to execute gemini --version.",
            exit_code=70,
            details={"reason": str(exc), "binary": gemini_binary},
        )

    if version_proc.returncode != 0:
        payload = {
            "ok": False,
            "binary": gemini_binary,
            "binary_path": binary_path,
            "model_default": model,
            "version_stdout": version_proc.stdout.strip(),
            "version_stderr": version_proc.stderr.strip(),
            "exit_code": version_proc.returncode,
        }
        return payload, version_proc.returncode
    log_progress(progress_logs, "HEALTHCHECK", "Version check passed.")

    auth_command = build_command(
        gemini_binary=gemini_binary,
        model=model,
        output_format="json",
        approval_mode=DEFAULT_APPROVAL_MODE,
        include_directories=[],
        prompt=HEALTHCHECK_AUTH_PROMPT,
    )
    try:
        auth_proc = subprocess.run(
            auth_command,
            capture_output=True,
            text=True,
            check=False,
            timeout=DEFAULT_HEALTHCHECK_TIMEOUT_SECONDS,
            env={**dict(os.environ), "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired:
        return error_payload(
            "HEALTHCHECK_AUTH_TIMEOUT",
            "Gemini auth healthcheck timed out in non-interactive mode.",
            exit_code=124,
            details={
                "timeout_seconds": DEFAULT_HEALTHCHECK_TIMEOUT_SECONDS,
                "command": command_for_logs(auth_command),
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return error_payload(
            "HEALTHCHECK_AUTH_FAILED",
            "Unable to execute Gemini auth healthcheck command.",
            exit_code=70,
            details={
                "reason": str(exc),
                "command": command_for_logs(auth_command),
            },
        )

    if auth_proc.returncode != 0:
        stderr = (auth_proc.stderr or "").strip()
        stdout = (auth_proc.stdout or "").strip()
        combined = f"{stderr}\n{stdout}".lower()
        if "manual authorization is required" in combined:
            return error_payload(
                "AUTH_REQUIRED",
                (
                    "Gemini CLI is not authorized for non-interactive/headless use "
                    "in this environment."
                ),
                exit_code=auth_proc.returncode,
                details={
                    "recommendation": (
                        "Run interactive `gemini` login for this OS user or set "
                        "headless credentials (e.g. GEMINI_API_KEY / Vertex ADC)."
                    ),
                    "stdout_preview": auth_proc.stdout[:500],
                    "stderr_preview": auth_proc.stderr[:500],
                    "command": command_for_logs(auth_command),
                },
            )

        return error_payload(
            "HEALTHCHECK_AUTH_FAILED",
            "Gemini auth healthcheck failed in non-interactive/headless mode.",
            exit_code=auth_proc.returncode,
            details={
                "stdout_preview": auth_proc.stdout[:500],
                "stderr_preview": auth_proc.stderr[:500],
                "command": command_for_logs(auth_command),
            },
        )
    log_progress(progress_logs, "HEALTHCHECK", "Headless auth check passed.")

    auth_stdout = (auth_proc.stdout or "").strip()
    if auth_stdout:
        try:
            json.loads(auth_stdout)
        except json.JSONDecodeError as exc:
            return error_payload(
                "HEALTHCHECK_AUTH_INVALID_JSON",
                "Gemini auth healthcheck returned non-JSON output.",
                exit_code=65,
                details={
                    "reason": str(exc),
                    "stdout_preview": auth_proc.stdout[:500],
                    "stderr_preview": auth_proc.stderr[:500],
                    "command": command_for_logs(auth_command),
                },
            )

    payload = {
        "ok": True,
        "binary": gemini_binary,
        "binary_path": binary_path,
        "model_default": model,
        "version_stdout": version_proc.stdout.strip(),
        "version_stderr": version_proc.stderr.strip(),
        "auth_check": {
            "ok": True,
            "exit_code": auth_proc.returncode,
            "command": command_for_logs(auth_command),
        },
        "exit_code": 0,
    }
    log_progress(progress_logs, "HEALTHCHECK", "Healthcheck finished successfully.")
    return payload, 0


def execute_gemini(
    *,
    gemini_binary: str,
    model: str,
    output_format: str,
    approval_mode: str,
    prompt: str,
    context_files: Sequence[Path],
    context_dirs: Sequence[Path],
    include_directories: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
    progress_logs: bool,
    progress_heartbeat_seconds: int,
) -> tuple[dict[str, Any], int]:
    if not shutil.which(gemini_binary):
        return error_payload(
            "BINARY_NOT_FOUND",
            f"Gemini CLI binary '{gemini_binary}' was not found in PATH.",
            exit_code=127,
            details={"binary": gemini_binary},
        )

    command = build_command(
        gemini_binary=gemini_binary,
        model=model,
        output_format=output_format,
        approval_mode=approval_mode,
        include_directories=include_directories,
        prompt=prompt,
    )

    env = dict(os.environ)
    heartbeat_seconds = max(1, progress_heartbeat_seconds)
    log_progress(
        progress_logs,
        "EXECUTE",
        (
            "Starting Gemini CLI process "
            f"(model={model}, format={output_format}, cwd={cwd})."
        ),
    )
    log_progress(
        progress_logs,
        "EXECUTE",
        (
            f"Context files={len(context_files)}, context dirs={len(context_dirs)}, "
            f"timeout={timeout_seconds}s."
        ),
    )

    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env={**env, "NO_COLOR": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return error_payload(
            "EXECUTION_ERROR",
            "Gemini CLI execution failed before completion.",
            exit_code=70,
            details={"reason": str(exc), "command": command_for_logs(command)},
        )

    started_at = time.monotonic()
    stdout = ""
    stderr = ""
    while True:
        elapsed = time.monotonic() - started_at
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            process.kill()
            stdout, stderr = process.communicate()
            log_progress(
                progress_logs,
                "TIMEOUT",
                f"Gemini CLI timed out after {int(elapsed)}s. Process killed.",
            )
            return error_payload(
                "TIMEOUT",
                "Gemini CLI timed out before returning a result.",
                exit_code=124,
                details={
                    "timeout_seconds": timeout_seconds,
                    "partial_stdout": (stdout or "").strip(),
                    "partial_stderr": (stderr or "").strip(),
                    "command": command_for_logs(command),
                },
            )
        try:
            stdout, stderr = process.communicate(timeout=min(remaining, heartbeat_seconds))
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started_at
            log_progress(
                progress_logs,
                "RUNNING",
                f"Gemini CLI still running ({int(elapsed)}s elapsed).",
            )

    elapsed_seconds = round(time.monotonic() - started_at, 3)
    log_progress(
        progress_logs,
        "COMPLETE",
        f"Gemini CLI finished in {elapsed_seconds}s with exit code {process.returncode}.",
    )

    payload: dict[str, Any] = {
        "ok": process.returncode == 0,
        "exit_code": process.returncode,
        "model": model,
        "output_format": output_format,
        "approval_mode": approval_mode,
        "cwd": str(cwd),
        "context_files": [str(path.resolve()) for path in context_files],
        "context_dirs": [str(path.resolve()) for path in context_dirs],
        "command": command_for_logs(command),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "duration_seconds": elapsed_seconds,
        "stdout": stdout,
        "stderr": stderr,
    }

    if output_format == "json" and stdout.strip():
        try:
            payload["gemini"] = json.loads(stdout)
            if isinstance(payload["gemini"], dict):
                response = payload["gemini"].get("response")
                if isinstance(response, str):
                    payload["response"] = response
        except json.JSONDecodeError as exc:
            return error_payload(
                "INVALID_JSON_OUTPUT",
                "Gemini CLI returned non-JSON output while --output-format=json was requested.",
                exit_code=65,
                details={
                    "reason": str(exc),
                    "stdout_preview": stdout[:500],
                    "stderr_preview": stderr[:500],
                    "command": command_for_logs(command),
                },
            )

    stderr_pattern = detect_critical_stderr(stderr or "")
    if stderr_pattern:
        wrapper_exit_code = process.returncode if process.returncode != 0 else 65
        return error_payload(
            "GEMINI_TOOL_ERROR",
            "Gemini CLI reported a tool-level error in stderr.",
            exit_code=wrapper_exit_code,
            details={
                "matched_pattern": stderr_pattern,
                "process_exit_code": process.returncode,
                "stdout_preview": stdout[:500],
                "stderr_preview": stderr[:1000],
                "command": command_for_logs(command),
            },
        )

    if process.returncode != 0:
        payload["error"] = {
            "type": "PROCESS_ERROR",
            "message": "Gemini CLI returned a non-zero exit code.",
        }
    return payload, process.returncode


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Gemini CLI in headless mode with strict model control."
    )
    parser.add_argument(
        "--gemini-binary",
        default="gemini",
        help="Gemini CLI executable name or full path.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            "Model identifier. Defaults to gemini-3.1-pro-preview. "
            "Alias 'gemini 3.1pro' is normalized to that value."
        ),
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "text", "stream-json"],
        default="json",
        help="Gemini output format flag.",
    )
    parser.add_argument(
        "--approval-mode",
        choices=["plan"],
        default=DEFAULT_APPROVAL_MODE,
        help=(
            "Tool approval mode. Fixed to plan (read-only) to block edit tools "
            "during headless analysis."
        ),
    )
    parser.add_argument(
        "--prompt",
        help="Prompt text to send to Gemini CLI.",
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        help="UTF-8 file containing prompt text.",
    )
    parser.add_argument(
        "--include-directory",
        action="append",
        default=[],
        help="Additional directory to include (repeatable).",
    )
    parser.add_argument(
        "--include-directories",
        help="Comma-separated list of additional directories to include.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Working directory for command execution.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Execution timeout in seconds.",
    )
    parser.add_argument(
        "--context-file",
        action="append",
        default=[],
        help=(
            "File path to inject into Gemini context using @path syntax. "
            "Repeatable."
        ),
    )
    parser.add_argument(
        "--context-files",
        help=(
            "Comma-separated file paths to inject into Gemini context using @path "
            "syntax."
        ),
    )
    parser.add_argument(
        "--context-dir",
        action="append",
        default=[],
        help=(
            "Directory path to inject recursively into Gemini context using @path "
            "syntax. Repeatable."
        ),
    )
    parser.add_argument(
        "--context-dirs",
        help=(
            "Comma-separated directory paths to inject recursively into Gemini "
            "context."
        ),
    )
    parser.add_argument(
        "--one-shot",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_ONE_SHOT,
        help="Enforce one-shot response behavior in the generated prompt.",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Validate binary availability and print version metadata.",
    )
    parser.add_argument(
        "--materialize-external-context",
        action="store_true",
        help=(
            "Copy context paths outside allowed roots into $cwd/.tmp/gemini-context "
            "before execution."
        ),
    )
    parser.add_argument(
        "--progress-logs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Print wrapper progress logs to stderr "
            "(use --no-progress-logs to disable)."
        ),
    )
    parser.add_argument(
        "--progress-heartbeat-seconds",
        type=int,
        default=DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
        help=(
            "Interval for runtime heartbeat logs while waiting for Gemini "
            "response."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    model = normalize_model_name(args.model)

    if args.timeout_seconds <= 0:
        payload, code = error_payload(
            "INVALID_ARGUMENT",
            "--timeout-seconds must be a positive integer.",
            exit_code=2,
        )
        json_output(payload)
        return code

    if args.progress_heartbeat_seconds <= 0:
        payload, code = error_payload(
            "INVALID_ARGUMENT",
            "--progress-heartbeat-seconds must be a positive integer.",
            exit_code=2,
        )
        json_output(payload)
        return code

    log_progress(
        args.progress_logs,
        "START",
        f"Wrapper started (cwd={args.cwd.expanduser().resolve()}).",
    )
    if args.healthcheck:
        payload, code = perform_healthcheck(
            args.gemini_binary,
            model,
            progress_logs=args.progress_logs,
        )
        json_output(payload)
        return code

    try:
        prompt = read_prompt(args.prompt, args.prompt_file)
    except ValueError as exc:
        payload, code = error_payload(
            "INVALID_ARGUMENT",
            str(exc),
            exit_code=2,
        )
        json_output(payload)
        return code

    context_base_dir = args.cwd.expanduser().resolve()
    context_files = parse_path_list(
        [*args.context_file, *parse_comma_list(args.context_files)],
        base_dir=context_base_dir,
    )
    context_dirs = parse_path_list(
        [*args.context_dir, *parse_comma_list(args.context_dirs)],
        base_dir=context_base_dir,
    )
    files_ok, missing_files = validate_paths_exist(context_files, expected="file")
    dirs_ok, missing_dirs = validate_paths_exist(context_dirs, expected="dir")
    if not files_ok or not dirs_ok:
        payload, code = error_payload(
            "INVALID_ARGUMENT",
            "One or more context paths do not exist.",
            exit_code=2,
            details={
                "missing_files": missing_files,
                "missing_dirs": missing_dirs,
            },
        )
        json_output(payload)
        return code
    log_progress(
        args.progress_logs,
        "PREFLIGHT",
        (
            f"Validated context inputs: files={len(context_files)}, "
            f"dirs={len(context_dirs)}."
        ),
    )

    roots = allowed_context_roots(cwd=context_base_dir)
    external_files = find_external_paths(context_files, roots=roots)
    external_dirs = find_external_paths(context_dirs, roots=roots)
    materialization_report: dict[str, Any] = {
        "enabled": args.materialize_external_context,
        "files": [],
        "dirs": [],
    }
    if external_files or external_dirs:
        if args.materialize_external_context:
            files_root = context_base_dir / ".tmp" / "gemini-context" / "files"
            dirs_root = context_base_dir / ".tmp" / "gemini-context" / "dirs"
            context_files, file_copies = materialize_external_paths(
                context_files,
                roots=roots,
                destination_root=files_root,
                expected="file",
            )
            context_dirs, dir_copies = materialize_external_paths(
                context_dirs,
                roots=roots,
                destination_root=dirs_root,
                expected="dir",
            )
            materialization_report["files"] = file_copies
            materialization_report["dirs"] = dir_copies
            log_progress(
                args.progress_logs,
                "PREFLIGHT",
                (
                    "Materialized external context into workspace: "
                    f"files={len(file_copies)}, dirs={len(dir_copies)}."
                ),
            )
        else:
            payload, code = error_payload(
                "INVALID_CONTEXT_PATH",
                "Context paths must stay inside allowed Gemini roots.",
                exit_code=2,
                details={
                    "invalid_files": [str(path) for path in external_files],
                    "invalid_dirs": [str(path) for path in external_dirs],
                    "allowed_roots": [str(root) for root in roots],
                    "recommendation": (
                        "Move context into the workspace or rerun with "
                        "--materialize-external-context."
                    ),
                },
            )
            json_output(payload)
            return code

    include_directories = [
        *args.include_directory,
        *parse_comma_list(args.include_directories),
    ]
    cwd = context_base_dir
    if not cwd.exists() or not cwd.is_dir():
        payload, code = error_payload(
            "INVALID_ARGUMENT",
            f"Working directory does not exist or is not a directory: {cwd}",
            exit_code=2,
        )
        json_output(payload)
        return code

    prompt_with_context = compose_prompt(
        user_prompt=prompt,
        context_files=context_files,
        context_dirs=context_dirs,
        one_shot=args.one_shot,
    )

    payload, code = execute_gemini(
        gemini_binary=args.gemini_binary,
        model=model,
        output_format=args.output_format,
        approval_mode=args.approval_mode,
        prompt=prompt_with_context,
        context_files=context_files,
        context_dirs=context_dirs,
        include_directories=include_directories,
        cwd=cwd,
        timeout_seconds=args.timeout_seconds,
        progress_logs=args.progress_logs,
        progress_heartbeat_seconds=args.progress_heartbeat_seconds,
    )
    if materialization_report["files"] or materialization_report["dirs"]:
        payload["context_materialization"] = materialization_report
    json_output(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
