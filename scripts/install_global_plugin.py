#!/usr/bin/env python3
"""One-command migration from Gemini CLI Bridge to Antigravity CLI Bridge."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


PLUGIN_NAME = "antigravity-cli-bridge"
LEGACY_PLUGIN_NAME = "gemini-cli-bridge"
DEFAULT_MARKETPLACE_NAME = "personal-local"
MARKETPLACE_DISPLAY_NAME = "Personal Local Plugins"
ANTIGRAVITY_INSTALLER_URL = "https://antigravity.google/cli/install.sh"
MINIMUM_PYTHON_VERSION = (3, 9)


class MigrationError(RuntimeError):
    """Raised when migration cannot safely continue."""


@dataclass
class MigrationState:
    original_marketplace: bytes | None = None
    marketplace_changed: bool = False
    target_activated: bool = False
    target_existed: bool = False
    target_backup: Path | None = None
    new_was_installed: bool = False
    new_install_attempted: bool = False
    old_was_installed: bool = False
    old_removed: bool = False
    legacy_archive: Path | None = None


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install Antigravity CLI Bridge and safely migrate an existing "
            "Gemini CLI Bridge installation."
        )
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Approve installation or update of the official Antigravity CLI.",
    )
    parser.add_argument(
        "--keep-legacy-source",
        action="store_true",
        help="Keep the inactive legacy plugin source in place instead of archiving it.",
    )
    parser.add_argument(
        "--no-launch-auth",
        action="store_true",
        help="Do not launch interactive Antigravity onboarding when auth is required.",
    )
    return parser.parse_args(argv)


def load_marketplace(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "name": DEFAULT_MARKETPLACE_NAME,
            "interface": {"displayName": MARKETPLACE_DISPLAY_NAME},
            "plugins": [],
        }
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise MigrationError("Marketplace JSON root must be an object.")
    if "plugins" not in payload or not isinstance(payload["plugins"], list):
        raise MigrationError("Marketplace JSON must contain a 'plugins' array.")
    return payload


def marketplace_name(payload: dict[str, Any]) -> str:
    value = payload.get("name")
    if not isinstance(value, str) or not value.strip():
        raise MigrationError("Marketplace must have a non-empty string 'name'.")
    return value.strip()


def plugin_entry(plugin_name: str) -> dict[str, Any]:
    return {
        "name": plugin_name,
        "source": {
            "source": "local",
            "path": f"./.codex/plugins/{plugin_name}",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Coding",
    }


def ensure_marketplace_metadata(payload: dict[str, Any]) -> None:
    payload.setdefault("name", DEFAULT_MARKETPLACE_NAME)
    interface = payload.setdefault("interface", {})
    if not isinstance(interface, dict):
        raise MigrationError("Marketplace 'interface' must be an object.")
    interface.setdefault("displayName", MARKETPLACE_DISPLAY_NAME)
    plugins = payload.setdefault("plugins", [])
    if not isinstance(plugins, list):
        raise MigrationError("Marketplace 'plugins' must be an array.")


def build_transitional_marketplace(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the new plugin while preserving the legacy entry during validation."""
    transitional = copy.deepcopy(payload)
    ensure_marketplace_metadata(transitional)
    replacement = plugin_entry(PLUGIN_NAME)
    rewritten: list[Any] = []
    replacement_written = False
    for current in transitional["plugins"]:
        current_name = current.get("name") if isinstance(current, dict) else None
        if current_name == PLUGIN_NAME:
            if not replacement_written:
                rewritten.append(replacement)
                replacement_written = True
            continue
        rewritten.append(current)
    if not replacement_written:
        rewritten.append(replacement)
    transitional["plugins"] = rewritten
    return transitional


def build_final_marketplace(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the new plugin and remove all legacy/new duplicates after validation."""
    final = copy.deepcopy(payload)
    ensure_marketplace_metadata(final)
    replacement = plugin_entry(PLUGIN_NAME)
    rewritten: list[Any] = []
    replacement_written = False
    for current in final["plugins"]:
        current_name = current.get("name") if isinstance(current, dict) else None
        if current_name not in {PLUGIN_NAME, LEGACY_PLUGIN_NAME}:
            rewritten.append(current)
            continue
        if not replacement_written:
            rewritten.append(replacement)
            replacement_written = True
    if not replacement_written:
        rewritten.append(replacement)
    final["plugins"] = rewritten
    return final


def atomic_write_bytes(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise MigrationError(f"Refusing to replace symlinked file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    content = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, content)


def restore_marketplace(path: Path, original: bytes | None) -> None:
    if original is None:
        if path.exists() and not path.is_symlink():
            path.unlink()
        return
    atomic_write_bytes(path, original)


def stage_plugin(source: Path, target: Path) -> Path:
    staging = target.with_name(f".{target.name}.{os.getpid()}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(
        source,
        staging,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".DS_Store", ".ruff_cache"
        ),
    )
    return staging


def activate_staged_plugin(staging: Path, target: Path) -> tuple[bool, Path | None]:
    if target.is_symlink():
        raise MigrationError(
            f"Refusing to replace symlinked plugin directory: {target}"
        )
    backup = target.with_name(f".{target.name}.{os.getpid()}.backup")
    if backup.exists():
        shutil.rmtree(backup)

    target_existed = target.exists()
    if target_existed:
        target.rename(backup)
    try:
        staging.rename(target)
    except Exception:
        if target_existed and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    return target_existed, backup if target_existed else None


def restore_plugin_target(
    target: Path,
    *,
    target_existed: bool,
    backup: Path | None,
) -> None:
    if target.exists():
        shutil.rmtree(target)
    if target_existed:
        if backup is None or not backup.exists():
            raise MigrationError("Plugin rollback backup is missing.")
        backup.rename(target)


def run_command(
    command: Sequence[str],
    *,
    capture: bool = True,
    check: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=capture,
        text=True,
        check=check,
        timeout=timeout,
    )


def parse_json_output(process: subprocess.CompletedProcess[str], operation: str) -> Any:
    if process.returncode != 0:
        raise MigrationError(
            f"{operation} failed with exit code {process.returncode}: "
            f"{process.stderr.strip() or process.stdout.strip()}"
        )
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise MigrationError(f"{operation} returned invalid JSON.") from exc


def installed_plugin_ids(codex_binary: str) -> set[str]:
    process = run_command([codex_binary, "plugin", "list", "--json"], timeout=30)
    payload = parse_json_output(process, "Codex plugin inventory")
    installed = payload.get("installed") if isinstance(payload, dict) else None
    if not isinstance(installed, list):
        raise MigrationError("Codex plugin inventory has no 'installed' array.")
    identifiers: set[str] = set()
    for item in installed:
        if not isinstance(item, dict) or item.get("installed") is not True:
            continue
        plugin_id = item.get("pluginId")
        if isinstance(plugin_id, str):
            identifiers.add(plugin_id)
    return identifiers


def codex_plugin_change(codex_binary: str, action: str, selector: str) -> None:
    process = run_command(
        [codex_binary, "plugin", action, selector, "--json"],
        timeout=60,
    )
    parse_json_output(process, f"codex plugin {action} {selector}")


def wrapper_healthcheck(wrapper: Path) -> dict[str, Any]:
    try:
        process = run_command(
            [sys.executable, str(wrapper), "--healthcheck", "--no-progress-logs"],
            timeout=75,
        )
    except subprocess.TimeoutExpired as exc:
        raise MigrationError("Antigravity healthcheck timed out.") from exc
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise MigrationError("Antigravity healthcheck returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise MigrationError("Antigravity healthcheck returned an invalid payload.")
    return payload


def healthcheck_error_type(payload: dict[str, Any]) -> str | None:
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    value = error.get("type")
    return value if isinstance(value, str) else None


def healthcheck_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return json.dumps(payload, indent=2)


def ask_confirmation(message: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    answer = input(f"{message} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def install_official_antigravity() -> None:
    print(f"Downloading the official installer from {ANTIGRAVITY_INSTALLER_URL}")
    request = urllib.request.Request(
        ANTIGRAVITY_INSTALLER_URL,
        headers={"User-Agent": "codex-antigravity-bridge-migrator/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            installer = response.read()
    except OSError as exc:
        raise MigrationError(
            f"Unable to download Antigravity installer: {exc}"
        ) from exc
    if not installer.startswith(b"#!"):
        raise MigrationError("Downloaded Antigravity installer is not a shell script.")
    with tempfile.TemporaryDirectory() as temp_dir:
        installer_path = Path(temp_dir) / "install-antigravity.sh"
        installer_path.write_bytes(installer)
        process = run_command(["/bin/bash", str(installer_path)], capture=False)
    if process.returncode != 0:
        raise MigrationError(
            f"Official Antigravity installer failed with exit code {process.returncode}."
        )


def refresh_antigravity_path() -> None:
    local_bin = Path.home() / ".local" / "bin"
    candidate = local_bin / "agy"
    if not candidate.is_file():
        return
    current_parts = os.environ.get("PATH", "").split(os.pathsep)
    if str(local_bin) not in current_parts:
        os.environ["PATH"] = str(local_bin) + os.pathsep + os.environ.get("PATH", "")


def update_antigravity(agy_binary: str) -> None:
    process = run_command([agy_binary, "update"], capture=False)
    if process.returncode != 0:
        raise MigrationError(
            f"Antigravity update failed with exit code {process.returncode}."
        )


def ensure_antigravity_ready(
    source_wrapper: Path,
    *,
    assume_yes: bool,
    launch_auth: bool,
) -> dict[str, Any]:
    payload = wrapper_healthcheck(source_wrapper)
    error_type = healthcheck_error_type(payload)

    if error_type == "BINARY_NOT_FOUND":
        approved = ask_confirmation(
            "Antigravity CLI is missing. Install it from Google's official installer now?",
            assume_yes=assume_yes,
        )
        if not approved:
            raise MigrationError(
                "Antigravity CLI is required. Re-run interactively or pass --yes."
            )
        install_official_antigravity()
        refresh_antigravity_path()
        payload = wrapper_healthcheck(source_wrapper)
        error_type = healthcheck_error_type(payload)

    if error_type == "VERSION_UNSUPPORTED":
        agy_binary = shutil.which("agy")
        if not agy_binary:
            raise MigrationError("Antigravity CLI path disappeared during preflight.")
        approved = ask_confirmation(
            "Antigravity CLI is outdated. Run `agy update` now?",
            assume_yes=assume_yes,
        )
        if not approved:
            raise MigrationError(
                "Antigravity CLI must be updated. Re-run interactively or pass --yes."
            )
        update_antigravity(agy_binary)
        payload = wrapper_healthcheck(source_wrapper)
        error_type = healthcheck_error_type(payload)

    if error_type == "AUTH_REQUIRED" and launch_auth:
        if not sys.stdin.isatty():
            raise MigrationError(
                "Antigravity authentication requires an interactive terminal. Run `agy`, "
                "complete onboarding, and rerun the migrator."
            )
        agy_binary = shutil.which("agy")
        if not agy_binary:
            raise MigrationError(
                "Antigravity CLI path disappeared during auth preflight."
            )
        print(
            "Antigravity authentication is required. Complete onboarding, then exit agy."
        )
        process = run_command([agy_binary], capture=False)
        if process.returncode != 0:
            raise MigrationError(
                f"Antigravity onboarding exited with code {process.returncode}."
            )
        payload = wrapper_healthcheck(source_wrapper)
        error_type = healthcheck_error_type(payload)

    if payload.get("ok") is not True:
        raise MigrationError(
            f"Antigravity preflight failed ({error_type or 'UNKNOWN'}): "
            f"{healthcheck_message(payload)}"
        )
    return payload


def unique_archive_path(root: Path, name: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = root / f"{name}-{timestamp}"
    candidate = base
    counter = 1
    while candidate.exists():
        candidate = root / f"{base.name}-{counter}"
        counter += 1
    return candidate


def archive_legacy_source(legacy_path: Path) -> Path | None:
    if not legacy_path.exists():
        return None
    if legacy_path.is_symlink():
        raise MigrationError(
            f"Refusing to archive symlinked legacy source: {legacy_path}"
        )
    archive_root = legacy_path.parent / ".migration-backups"
    archive_root.mkdir(parents=True, exist_ok=True)
    destination = unique_archive_path(archive_root, legacy_path.name)
    legacy_path.rename(destination)
    return destination


def rollback(
    *,
    state: MigrationState,
    marketplace_path: Path,
    target_plugin_dir: Path,
    legacy_plugin_dir: Path,
    codex_binary: str,
    new_selector: str,
    old_selector: str,
) -> list[str]:
    failures: list[str] = []
    try:
        if state.legacy_archive and state.legacy_archive.exists():
            if legacy_plugin_dir.exists():
                raise MigrationError(
                    f"Cannot restore legacy source because path exists: {legacy_plugin_dir}"
                )
            state.legacy_archive.rename(legacy_plugin_dir)
    except Exception as exc:
        failures.append(f"legacy source restore: {exc}")

    try:
        if state.new_install_attempted and not state.new_was_installed:
            installed = installed_plugin_ids(codex_binary)
            if new_selector in installed:
                codex_plugin_change(codex_binary, "remove", new_selector)
    except Exception as exc:
        failures.append(f"new plugin uninstall: {exc}")

    try:
        if state.target_activated:
            restore_plugin_target(
                target_plugin_dir,
                target_existed=state.target_existed,
                backup=state.target_backup,
            )
    except Exception as exc:
        failures.append(f"new plugin source restore: {exc}")

    try:
        if state.marketplace_changed:
            restore_marketplace(marketplace_path, state.original_marketplace)
    except Exception as exc:
        failures.append(f"marketplace restore: {exc}")

    try:
        if state.new_was_installed and state.target_activated:
            codex_plugin_change(codex_binary, "add", new_selector)
    except Exception as exc:
        failures.append(f"previous new plugin reinstall: {exc}")

    try:
        if state.old_was_installed and state.old_removed:
            codex_plugin_change(codex_binary, "add", old_selector)
    except Exception as exc:
        failures.append(f"legacy plugin reinstall: {exc}")
    return failures


def run_migration(args: argparse.Namespace) -> int:
    if sys.version_info < MINIMUM_PYTHON_VERSION:
        required = ".".join(str(part) for part in MINIMUM_PYTHON_VERSION)
        raise MigrationError(f"Python {required} or newer is required.")

    repo_root = Path(__file__).resolve().parents[1]
    source_plugin_dir = repo_root / "plugins" / PLUGIN_NAME
    source_manifest = source_plugin_dir / ".codex-plugin" / "plugin.json"
    source_wrapper = (
        source_plugin_dir / "skills" / PLUGIN_NAME / "scripts" / "run_antigravity.py"
    )
    if not source_manifest.is_file() or not source_wrapper.is_file():
        raise MigrationError("Repository plugin source is incomplete.")

    codex_binary = shutil.which("codex")
    if not codex_binary:
        raise MigrationError("Codex CLI was not found in PATH.")

    print("[1/6] Checking Antigravity CLI, model, and authentication...")
    antigravity = ensure_antigravity_ready(
        source_wrapper,
        assume_yes=args.yes,
        launch_auth=not args.no_launch_auth,
    )
    print(
        f"      ready: agy {antigravity.get('version')} / "
        f"{antigravity.get('model_default')}"
    )

    home = Path.home()
    target_plugin_dir = home / ".codex" / "plugins" / PLUGIN_NAME
    legacy_plugin_dir = home / ".codex" / "plugins" / LEGACY_PLUGIN_NAME
    marketplace_path = home / ".agents" / "plugins" / "marketplace.json"
    target_plugin_dir.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)

    state = MigrationState(
        original_marketplace=(
            marketplace_path.read_bytes() if marketplace_path.exists() else None
        )
    )
    staging: Path | None = None
    old_selector = ""
    new_selector = ""

    try:
        original_payload = load_marketplace(marketplace_path)
        selected_marketplace = marketplace_name(original_payload)
        old_selector = f"{LEGACY_PLUGIN_NAME}@{selected_marketplace}"
        new_selector = f"{PLUGIN_NAME}@{selected_marketplace}"
        installed_before = installed_plugin_ids(codex_binary)
        state.old_was_installed = old_selector in installed_before
        state.new_was_installed = new_selector in installed_before

        print("[2/6] Staging new plugin and transitional marketplace...")
        staging = stage_plugin(source_plugin_dir, target_plugin_dir)
        state.target_existed, state.target_backup = activate_staged_plugin(
            staging, target_plugin_dir
        )
        state.target_activated = True
        staging = None
        transitional = build_transitional_marketplace(original_payload)
        atomic_write_json(marketplace_path, transitional)
        state.marketplace_changed = True

        print("[3/6] Installing Antigravity CLI Bridge in Codex...")
        state.new_install_attempted = True
        codex_plugin_change(codex_binary, "add", new_selector)

        print("[4/6] Running installed-plugin healthcheck...")
        installed_wrapper = (
            target_plugin_dir
            / "skills"
            / PLUGIN_NAME
            / "scripts"
            / "run_antigravity.py"
        )
        installed_healthcheck = wrapper_healthcheck(installed_wrapper)
        if installed_healthcheck.get("ok") is not True:
            raise MigrationError(
                "Installed plugin healthcheck failed: "
                f"{healthcheck_message(installed_healthcheck)}"
            )

        print("[5/6] Retiring legacy Gemini CLI Bridge...")
        if state.old_was_installed:
            codex_plugin_change(codex_binary, "remove", old_selector)
            state.old_removed = True
        final_marketplace = build_final_marketplace(transitional)
        atomic_write_json(marketplace_path, final_marketplace)
        if not args.keep_legacy_source:
            state.legacy_archive = archive_legacy_source(legacy_plugin_dir)

        print("[6/6] Verifying final Codex plugin state...")
        installed_after = installed_plugin_ids(codex_binary)
        if new_selector not in installed_after:
            raise MigrationError("New Antigravity plugin is not installed in Codex.")
        if old_selector in installed_after:
            raise MigrationError("Legacy Gemini plugin is still installed in Codex.")

    except Exception as exc:
        if staging and staging.exists():
            shutil.rmtree(staging)
        rollback_failures = rollback(
            state=state,
            marketplace_path=marketplace_path,
            target_plugin_dir=target_plugin_dir,
            legacy_plugin_dir=legacy_plugin_dir,
            codex_binary=codex_binary,
            new_selector=new_selector,
            old_selector=old_selector,
        )
        message = f"Migration failed and rollback was attempted: {exc}"
        if rollback_failures:
            message += "\nRollback problems:\n- " + "\n- ".join(rollback_failures)
        raise MigrationError(message) from exc

    if state.target_backup and state.target_backup.exists():
        shutil.rmtree(state.target_backup)

    print("")
    print("Migration completed successfully.")
    print(f"- installed: {new_selector}")
    print(f"- runtime: agy {antigravity.get('version')}")
    print(f"- marketplace: {marketplace_path}")
    if state.old_was_installed:
        print(f"- removed from Codex: {old_selector}")
    if state.legacy_archive:
        print(f"- legacy source backup: {state.legacy_archive}")
    elif legacy_plugin_dir.exists():
        print(f"- legacy source retained: {legacy_plugin_dir}")
    print("")
    print("Restart Codex and start a new task to load the new skill and command.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        return run_migration(args)
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
