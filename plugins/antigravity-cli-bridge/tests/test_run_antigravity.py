import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "antigravity-cli-bridge"
    / "scripts"
    / "run_antigravity.py"
)

SPEC = importlib.util.spec_from_file_location("run_antigravity", SCRIPT_PATH)
run_antigravity = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(run_antigravity)


class RunAntigravityTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(run_antigravity.parse_version("1.1.2\n"), (1, 1, 2))
        self.assertEqual(run_antigravity.parse_version("agy v2.0.1"), (2, 0, 1))
        self.assertIsNone(run_antigravity.parse_version("unknown"))

    def test_prompt_size_counts_utf8_bytes(self):
        self.assertEqual(run_antigravity.prompt_size_bytes("abc"), 3)
        self.assertEqual(run_antigravity.prompt_size_bytes("ż"), 2)

    def test_normalize_model_alias(self):
        self.assertEqual(
            run_antigravity.normalize_model_name("gemini 3.1 pro high"),
            run_antigravity.DEFAULT_MODEL,
        )
        self.assertEqual(
            run_antigravity.normalize_model_name("Gemini 3.1 Pro (High)"),
            run_antigravity.DEFAULT_MODEL,
        )
        self.assertEqual(
            run_antigravity.normalize_model_name("Claude Sonnet 4.6 (Thinking)"),
            "Claude Sonnet 4.6 (Thinking)",
        )

    def test_build_command_uses_print_plan_sandbox_and_add_dirs(self):
        command = run_antigravity.build_command(
            antigravity_binary="agy",
            model=run_antigravity.DEFAULT_MODEL,
            execution_mode=run_antigravity.DEFAULT_EXECUTION_MODE,
            add_directories=[Path("/repo/lib"), Path("/repo/docs")],
            prompt="Summarize project",
            print_timeout_seconds=60,
        )
        self.assertEqual(command[0], "agy")
        self.assertEqual(command[1:3], ["--print", "Summarize project"])
        self.assertIn("--model", command)
        self.assertIn(run_antigravity.DEFAULT_MODEL, command)
        self.assertIn("--mode", command)
        self.assertIn("plan", command)
        self.assertIn("--sandbox", command)
        self.assertEqual(command.count("--add-dir"), 2)
        self.assertNotIn("--approval-mode", command)
        self.assertNotIn("--output-format", command)

    def test_command_for_logs_redacts_prompt(self):
        command = ["agy", "--print", "secret prompt", "--mode", "plan"]
        self.assertEqual(
            run_antigravity.command_for_logs(command),
            ["agy", "--print", "<prompt>", "--mode", "plan"],
        )

    def test_compose_prompt_requires_complete_context(self):
        prompt = run_antigravity.compose_prompt(
            user_prompt="Review architecture tradeoffs.",
            context_files=[Path("/tmp/a.py"), Path("/tmp/with space.ts")],
            context_dirs=[Path("/tmp/src")],
            one_shot=True,
        )
        self.assertIn("/tmp/a.py", prompt)
        self.assertIn("/tmp/with space.ts", prompt)
        self.assertIn("/tmp/src", prompt)
        self.assertIn("stop and report that path", prompt)
        self.assertIn("ONE-SHOT ANALYSIS MODE", prompt)
        self.assertIn("Do not modify project files", prompt)

    def test_external_context_becomes_explicit_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cwd = root / "workspace"
            external = root / "external"
            cwd.mkdir()
            external.mkdir()
            inside_file = cwd / "inside.txt"
            outside_file = external / "outside.txt"
            inside_file.write_text("inside", encoding="utf-8")
            outside_file.write_text("outside", encoding="utf-8")

            directories = run_antigravity.workspace_directories_for_context(
                cwd=cwd,
                context_files=[inside_file, outside_file],
                context_dirs=[],
                explicit_directories=[],
            )

            self.assertEqual(directories, [external.resolve()])

    @mock.patch("shutil.which", return_value=None)
    def test_healthcheck_binary_missing(self, _mock_which):
        payload, code = run_antigravity.perform_healthcheck(
            "agy", run_antigravity.DEFAULT_MODEL
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 127)
        self.assertEqual(payload["error"]["type"], "BINARY_NOT_FOUND")

    @mock.patch("shutil.which", return_value="/usr/local/bin/agy")
    @mock.patch("subprocess.run")
    def test_healthcheck_version_unsupported(self, mock_run, _mock_which):
        mock_run.side_effect = [
            subprocess.CompletedProcess(["agy", "--version"], 0, "1.1.1\n", ""),
            subprocess.CompletedProcess(
                ["agy", "models"], 0, f"{run_antigravity.DEFAULT_MODEL}\n", ""
            ),
        ]
        payload, code = run_antigravity.perform_healthcheck(
            "agy", run_antigravity.DEFAULT_MODEL
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 69)
        self.assertEqual(payload["error"]["type"], "VERSION_UNSUPPORTED")

    @mock.patch("shutil.which", return_value="/usr/local/bin/agy")
    @mock.patch("subprocess.run")
    def test_healthcheck_model_unavailable(self, mock_run, _mock_which):
        mock_run.side_effect = [
            subprocess.CompletedProcess(["agy", "--version"], 0, "1.1.2\n", ""),
            subprocess.CompletedProcess(
                ["agy", "models"], 0, "Gemini 3.5 Flash (High)\n", ""
            ),
        ]
        payload, code = run_antigravity.perform_healthcheck(
            "agy", run_antigravity.DEFAULT_MODEL
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 69)
        self.assertEqual(payload["error"]["type"], "MODEL_UNAVAILABLE")

    @mock.patch("shutil.which", return_value="/usr/local/bin/agy")
    @mock.patch("subprocess.run")
    def test_healthcheck_auth_required(self, mock_run, _mock_which):
        mock_run.side_effect = [
            subprocess.CompletedProcess(["agy", "--version"], 0, "1.1.2\n", ""),
            subprocess.CompletedProcess(
                ["agy", "models"], 0, f"{run_antigravity.DEFAULT_MODEL}\n", ""
            ),
            subprocess.CompletedProcess(["agy", "--print"], 41, "", "Please sign in"),
        ]
        payload, code = run_antigravity.perform_healthcheck(
            "agy", run_antigravity.DEFAULT_MODEL
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 41)
        self.assertEqual(payload["error"]["type"], "AUTH_REQUIRED")

    @mock.patch("shutil.which", return_value="/usr/local/bin/agy")
    @mock.patch("subprocess.run")
    def test_healthcheck_success(self, mock_run, _mock_which):
        mock_run.side_effect = [
            subprocess.CompletedProcess(["agy", "--version"], 0, "1.1.2\n", ""),
            subprocess.CompletedProcess(
                ["agy", "models"], 0, f"{run_antigravity.DEFAULT_MODEL}\n", ""
            ),
            subprocess.CompletedProcess(["agy", "--print"], 0, "AUTH_OK\n", ""),
        ]
        payload, code = run_antigravity.perform_healthcheck(
            "agy", run_antigravity.DEFAULT_MODEL
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["version"], "1.1.2")
        self.assertTrue(payload["auth_check"]["ok"])

    @mock.patch("shutil.which", return_value="/usr/local/bin/agy")
    @mock.patch("subprocess.Popen")
    def test_execute_antigravity_timeout(self, mock_popen, _mock_which):
        mock_process = mock.Mock()
        mock_process.returncode = None
        mock_process.communicate.return_value = ("", "")
        mock_popen.return_value = mock_process

        payload, code = run_antigravity.execute_antigravity(
            antigravity_binary="agy",
            model=run_antigravity.DEFAULT_MODEL,
            execution_mode=run_antigravity.DEFAULT_EXECUTION_MODE,
            prompt="Run task",
            context_files=[],
            context_dirs=[],
            add_directories=[],
            cwd=Path("."),
            timeout_seconds=0,
            progress_logs=False,
            progress_heartbeat_seconds=5,
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 124)
        self.assertEqual(payload["error"]["type"], "TIMEOUT")
        mock_process.kill.assert_called_once()

    @mock.patch("shutil.which", return_value="/usr/local/bin/agy")
    @mock.patch("subprocess.Popen")
    def test_execute_antigravity_detects_tool_error(self, mock_popen, _mock_which):
        mock_process = mock.Mock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (
            "Partial answer",
            "Error executing tool: path is outside workspace",
        )
        mock_popen.return_value = mock_process

        payload, code = run_antigravity.execute_antigravity(
            antigravity_binary="agy",
            model=run_antigravity.DEFAULT_MODEL,
            execution_mode=run_antigravity.DEFAULT_EXECUTION_MODE,
            prompt="Run task",
            context_files=[],
            context_dirs=[],
            add_directories=[],
            cwd=Path("."),
            timeout_seconds=10,
            progress_logs=False,
            progress_heartbeat_seconds=5,
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 65)
        self.assertEqual(payload["error"]["type"], "ANTIGRAVITY_TOOL_ERROR")


if __name__ == "__main__":
    unittest.main()
