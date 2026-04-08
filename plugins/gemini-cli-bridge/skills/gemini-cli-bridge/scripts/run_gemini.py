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
from pathlib import Path
from typing import Any, Sequence

DEFAULT_MODEL = "gemini-3.1-pro-preview"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_ONE_SHOT = True
DEFAULT_APPROVAL_MODE = "plan"

MODEL_ALIASES = {
    "gemini3.1pro": DEFAULT_MODEL,
    "gemini3.1propreview": DEFAULT_MODEL,
    "gemini31pro": DEFAULT_MODEL,
    "gemini31propreview": DEFAULT_MODEL,
    "gemini3pro": DEFAULT_MODEL,
    "gemini3propreview": DEFAULT_MODEL,
}


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


def perform_healthcheck(gemini_binary: str, model: str) -> tuple[dict[str, Any], int]:
    binary_path = shutil.which(gemini_binary)
    if not binary_path:
        return error_payload(
            "BINARY_NOT_FOUND",
            f"Gemini CLI binary '{gemini_binary}' was not found in PATH.",
            exit_code=127,
            details={"binary": gemini_binary},
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

    payload = {
        "ok": version_proc.returncode == 0,
        "binary": gemini_binary,
        "binary_path": binary_path,
        "model_default": model,
        "version_stdout": version_proc.stdout.strip(),
        "version_stderr": version_proc.stderr.strip(),
        "exit_code": version_proc.returncode,
    }
    return payload, 0 if version_proc.returncode == 0 else version_proc.returncode


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

    try:
        process = subprocess.run(
            command,
            cwd=str(cwd),
            env={**env, "NO_COLOR": "1"},
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return error_payload(
            "TIMEOUT",
            "Gemini CLI timed out before returning a result.",
            exit_code=124,
            details={
                "timeout_seconds": timeout_seconds,
                "partial_stdout": (exc.stdout or "").strip(),
                "partial_stderr": (exc.stderr or "").strip(),
                "command": command_for_logs(command),
            },
        )
    except OSError as exc:
        return error_payload(
            "EXECUTION_ERROR",
            "Gemini CLI execution failed before completion.",
            exit_code=70,
            details={"reason": str(exc), "command": command_for_logs(command)},
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
        "stdout": process.stdout,
        "stderr": process.stderr,
    }

    if output_format == "json" and process.stdout.strip():
        try:
            payload["gemini"] = json.loads(process.stdout)
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
                    "stdout_preview": process.stdout[:500],
                    "stderr_preview": process.stderr[:500],
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

    if args.healthcheck:
        payload, code = perform_healthcheck(args.gemini_binary, model)
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
    )
    json_output(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
