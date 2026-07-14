import argparse
import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "install_global_plugin.py"
)
SPEC = importlib.util.spec_from_file_location("install_global_plugin", SCRIPT_PATH)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = installer
SPEC.loader.exec_module(installer)


class InstallGlobalPluginTests(unittest.TestCase):
    def test_transitional_marketplace_keeps_legacy_and_adds_new(self):
        payload = {
            "name": "personal-local",
            "plugins": [
                {"name": "before"},
                {"name": installer.LEGACY_PLUGIN_NAME, "legacy": True},
            ],
        }

        transitional = installer.build_transitional_marketplace(payload)

        self.assertEqual(
            [entry["name"] for entry in transitional["plugins"]],
            ["before", installer.LEGACY_PLUGIN_NAME, installer.PLUGIN_NAME],
        )
        self.assertEqual(
            [entry["name"] for entry in payload["plugins"]],
            ["before", installer.LEGACY_PLUGIN_NAME],
        )

    def test_final_marketplace_replaces_legacy_and_deduplicates_new(self):
        payload = {
            "name": "personal-local",
            "plugins": [
                {"name": "before"},
                {"name": installer.LEGACY_PLUGIN_NAME},
                {"name": installer.PLUGIN_NAME, "stale": True},
                {"name": "after"},
            ],
        }

        final = installer.build_final_marketplace(payload)

        self.assertEqual(
            [entry["name"] for entry in final["plugins"]],
            ["before", installer.PLUGIN_NAME, "after"],
        )
        self.assertEqual(
            final["plugins"][1]["source"]["path"],
            "./.codex/plugins/antigravity-cli-bridge",
        )

    def test_atomic_write_json_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_path = root / "real-marketplace.json"
            link_path = root / "marketplace.json"
            real_path.write_text('{"preserve": true}\n', encoding="utf-8")
            link_path.symlink_to(real_path)

            with self.assertRaisesRegex(installer.MigrationError, "symlinked file"):
                installer.atomic_write_json(link_path, {"new": True})

            self.assertEqual(
                json.loads(real_path.read_text(encoding="utf-8")),
                {"preserve": True},
            )

    def _write_fake_binaries(self, root: Path) -> Path:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        agy = bin_dir / "agy"
        agy.write_text(
            textwrap.dedent(
                """\
                #!/bin/sh
                if [ "$1" = "--version" ]; then
                  echo "1.1.2"
                  exit 0
                fi
                if [ "$1" = "models" ]; then
                  echo "Gemini 3.1 Pro (High)"
                  exit 0
                fi
                case " $* " in
                  *" --print "*) echo "AUTH_OK"; exit 0 ;;
                esac
                exit 0
                """
            ),
            encoding="utf-8",
        )
        agy.chmod(0o755)

        codex = bin_dir / "codex"
        codex.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                state_path = Path.home() / "codex-state.json"
                state = json.loads(state_path.read_text()) if state_path.exists() else []
                args = sys.argv[1:]
                if args[:3] == ["plugin", "list", "--json"]:
                    print(json.dumps({"installed": [
                        {"pluginId": item, "installed": True} for item in state
                    ]}))
                    raise SystemExit(0)
                if len(args) >= 4 and args[0] == "plugin" and args[1] in {"add", "remove"}:
                    action = args[1]
                    selector = args[2]
                    fail_remove = os.environ.get("FAKE_CODEX_FAIL_REMOVE")
                    if action == "remove" and selector == fail_remove:
                        print(json.dumps({"ok": False, "error": "injected remove failure"}))
                        print("injected remove failure", file=sys.stderr)
                        raise SystemExit(9)
                    if action == "add" and selector not in state:
                        state.append(selector)
                    if action == "remove" and selector in state:
                        state.remove(selector)
                    state_path.write_text(json.dumps(state))
                    print(json.dumps({"ok": True, "pluginId": selector}))
                    raise SystemExit(0)
                print(json.dumps({"error": "unsupported", "args": args}), file=sys.stderr)
                raise SystemExit(2)
                """
            ),
            encoding="utf-8",
        )
        codex.chmod(0o755)
        return bin_dir

    def _migration_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            yes=False,
            keep_legacy_source=False,
            no_launch_auth=True,
        )

    def _legacy_marketplace(self) -> dict:
        return {
            "name": "personal-local",
            "interface": {"displayName": "Personal Local Plugins"},
            "plugins": [installer.plugin_entry(installer.LEGACY_PLUGIN_NAME)],
        }

    def test_full_migration_installs_new_then_retires_legacy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            home.mkdir()
            bin_dir = self._write_fake_binaries(root)
            marketplace = home / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text(
                json.dumps(self._legacy_marketplace()), encoding="utf-8"
            )
            legacy_source = home / ".codex" / "plugins" / installer.LEGACY_PLUGIN_NAME
            legacy_source.mkdir(parents=True)
            (legacy_source / "marker.txt").write_text("legacy", encoding="utf-8")
            old_selector = f"{installer.LEGACY_PLUGIN_NAME}@personal-local"
            (home / "codex-state.json").write_text(
                json.dumps([old_selector]), encoding="utf-8"
            )

            environment = {
                "HOME": str(home),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                code = installer.run_migration(self._migration_args())

            self.assertEqual(code, 0)
            installed = json.loads((home / "codex-state.json").read_text())
            self.assertEqual(installed, [f"{installer.PLUGIN_NAME}@personal-local"])
            final_marketplace = json.loads(marketplace.read_text())
            self.assertEqual(
                [entry["name"] for entry in final_marketplace["plugins"]],
                [installer.PLUGIN_NAME],
            )
            self.assertFalse(legacy_source.exists())
            archives = list(
                (home / ".codex" / "plugins" / ".migration-backups").glob(
                    f"{installer.LEGACY_PLUGIN_NAME}-*"
                )
            )
            self.assertEqual(len(archives), 1)
            self.assertEqual((archives[0] / "marker.txt").read_text(), "legacy")

    def test_fresh_install_completes_without_legacy_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            home.mkdir()
            bin_dir = self._write_fake_binaries(root)
            environment = {
                "HOME": str(home),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            }

            with mock.patch.dict(os.environ, environment, clear=False):
                code = installer.run_migration(self._migration_args())

            self.assertEqual(code, 0)
            installed = json.loads((home / "codex-state.json").read_text())
            self.assertEqual(installed, [f"{installer.PLUGIN_NAME}@personal-local"])
            marketplace = json.loads(
                (home / ".agents" / "plugins" / "marketplace.json").read_text()
            )
            self.assertEqual(
                [entry["name"] for entry in marketplace["plugins"]],
                [installer.PLUGIN_NAME],
            )

    def test_failed_legacy_removal_rolls_back_to_working_old_plugin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            home.mkdir()
            bin_dir = self._write_fake_binaries(root)
            marketplace = home / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            original_marketplace = self._legacy_marketplace()
            marketplace.write_text(json.dumps(original_marketplace), encoding="utf-8")
            legacy_source = home / ".codex" / "plugins" / installer.LEGACY_PLUGIN_NAME
            legacy_source.mkdir(parents=True)
            old_selector = f"{installer.LEGACY_PLUGIN_NAME}@personal-local"
            (home / "codex-state.json").write_text(
                json.dumps([old_selector]), encoding="utf-8"
            )
            environment = {
                "HOME": str(home),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "FAKE_CODEX_FAIL_REMOVE": old_selector,
            }

            with mock.patch.dict(os.environ, environment, clear=False):
                with self.assertRaisesRegex(installer.MigrationError, "rollback"):
                    installer.run_migration(self._migration_args())

            installed = json.loads((home / "codex-state.json").read_text())
            self.assertEqual(installed, [old_selector])
            self.assertEqual(json.loads(marketplace.read_text()), original_marketplace)
            self.assertTrue(legacy_source.exists())
            self.assertFalse(
                (home / ".codex" / "plugins" / installer.PLUGIN_NAME).exists()
            )


if __name__ == "__main__":
    unittest.main()
