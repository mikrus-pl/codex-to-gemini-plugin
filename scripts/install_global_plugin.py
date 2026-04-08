#!/usr/bin/env python3
"""Install the gemini-cli-bridge plugin into the user's global Codex directories."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any


PLUGIN_NAME = "gemini-cli-bridge"
MARKETPLACE_NAME = "personal-local"
MARKETPLACE_DISPLAY_NAME = "Personal Local Plugins"


def load_marketplace(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "name": MARKETPLACE_NAME,
            "interface": {"displayName": MARKETPLACE_DISPLAY_NAME},
            "plugins": [],
        }
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Marketplace JSON root must be an object.")
    if "plugins" not in payload or not isinstance(payload["plugins"], list):
        raise ValueError("Marketplace JSON must contain a 'plugins' array.")
    return payload


def upsert_plugin_entry(payload: dict[str, Any], plugin_name: str) -> None:
    payload.setdefault("name", MARKETPLACE_NAME)
    interface = payload.setdefault("interface", {})
    if isinstance(interface, dict):
        interface.setdefault("displayName", MARKETPLACE_DISPLAY_NAME)
    payload.setdefault("plugins", [])

    entry = {
        "name": plugin_name,
        "source": {
            "source": "local",
            # Personal marketplace resolves relative to HOME.
            "path": f"./.codex/plugins/{plugin_name}",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Coding",
    }

    plugins = payload["plugins"]
    for index, current in enumerate(plugins):
        if isinstance(current, dict) and current.get("name") == plugin_name:
            plugins[index] = entry
            break
    else:
        plugins.append(entry)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    source_plugin_dir = repo_root / "plugins" / PLUGIN_NAME
    if not source_plugin_dir.exists():
        print(f"ERROR: source plugin path not found: {source_plugin_dir}")
        return 1

    home = Path.home()
    target_plugin_dir = home / ".codex" / "plugins" / PLUGIN_NAME
    marketplace_path = home / ".agents" / "plugins" / "marketplace.json"

    target_plugin_dir.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)

    shutil.copytree(source_plugin_dir, target_plugin_dir, dirs_exist_ok=True)

    payload = load_marketplace(marketplace_path)
    upsert_plugin_entry(payload, PLUGIN_NAME)
    with marketplace_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    print("Global plugin source updated.")
    print(f"- plugin: {target_plugin_dir}")
    print(f"- marketplace: {marketplace_path}")
    print("")
    print("Next steps:")
    print("1. Restart Codex.")
    print("2. Run `codex`, then `/plugins`.")
    print(f"3. Choose marketplace '{MARKETPLACE_DISPLAY_NAME}' and install '{PLUGIN_NAME}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
