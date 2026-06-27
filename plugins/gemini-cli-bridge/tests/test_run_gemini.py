import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "gemini-cli-bridge"
    / "scripts"
    / "run_gemini.py"
)

SPEC = importlib.util.spec_from_file_location("run_gemini", SCRIPT_PATH)
run_gemini = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(run_gemini)


class RunGeminiTests(unittest.TestCase):
    def test_normalize_model_alias(self):
        self.assertEqual(
            run_gemini.normalize_model_name("gemini 3.1pro"),
            run_gemini.DEFAULT_MODEL,
        )
        self.assertEqual(
            run_gemini.normalize_model_name("gemini-3.1-pro"),
            run_gemini.DEFAULT_MODEL,
        )
        self.assertEqual(
            run_gemini.normalize_model_name("gemini-2.5-pro"),
            "gemini-2.5-pro",
        )

    def test_build_command_contains_required_flags(self):
        command = run_gemini.build_command(
            gemini_binary="gemini",
            model=run_gemini.DEFAULT_MODEL,
            output_format="json",
            approval_mode=run_gemini.DEFAULT_APPROVAL_MODE,
            include_directories=["../lib", "../docs"],
            prompt="Summarize project",
        )
        self.assertEqual(command[0], "gemini")
        self.assertIn("--model", command)
        self.assertIn(run_gemini.DEFAULT_MODEL, command)
        self.assertIn("--output-format", command)
        self.assertIn("--approval-mode", command)
        self.assertIn("plan", command)
        self.assertNotIn("--prompt", command)
        self.assertIn("--include-directories", command)
        self.assertEqual(command[-1], "Summarize project")

    def test_compose_prompt_includes_context_and_one_shot(self):
        prompt = run_gemini.compose_prompt(
            user_prompt="Review architecture tradeoffs.",
            context_files=[Path("/tmp/a.py"), Path("/tmp/with space.ts")],
            context_dirs=[Path("/tmp/src")],
            one_shot=True,
        )
        self.assertIn("a.py", prompt)
        self.assertIn("with\\ space.ts", prompt)
        self.assertIn("/src", prompt)
        self.assertIn("ONE-SHOT MODE", prompt)
        self.assertIn("Do not modify any files. Analysis only.", prompt)
        self.assertIn("Task:", prompt)

    def test_find_external_paths_returns_only_outside_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            allowed_root = root / "workspace"
            allowed_root.mkdir()
            inside = allowed_root / "inside.txt"
            outside = root / "outside.txt"
            inside.write_text("inside", encoding="utf-8")
            outside.write_text("outside", encoding="utf-8")

            external = run_gemini.find_external_paths(
                [inside, outside],
                roots=[allowed_root],
            )

            self.assertEqual(external, [outside.resolve()])

    @mock.patch("shutil.which", return_value=None)
    def test_healthcheck_binary_missing(self, _mock_which):
        payload, code = run_gemini.perform_healthcheck("gemini", run_gemini.DEFAULT_MODEL)
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 127)
        self.assertEqual(payload["error"]["type"], "BINARY_NOT_FOUND")

    @mock.patch("shutil.which", return_value="/usr/local/bin/gemini")
    @mock.patch("subprocess.run")
    def test_healthcheck_auth_required(self, mock_run, _mock_which):
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["gemini", "--version"],
                returncode=0,
                stdout="gemini-cli 1.0.0\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["gemini"],
                returncode=41,
                stdout="",
                stderr="Manual authorization is required",
            ),
        ]
        payload, code = run_gemini.perform_healthcheck("gemini", run_gemini.DEFAULT_MODEL)
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 41)
        self.assertEqual(payload["error"]["type"], "AUTH_REQUIRED")

    @mock.patch("shutil.which", return_value="/usr/local/bin/gemini")
    @mock.patch("subprocess.run")
    def test_healthcheck_success(self, mock_run, _mock_which):
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["gemini", "--version"],
                returncode=0,
                stdout="gemini-cli 1.0.0\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["gemini"],
                returncode=0,
                stdout='{"response":"AUTH_OK"}',
                stderr="",
            ),
        ]
        payload, code = run_gemini.perform_healthcheck("gemini", run_gemini.DEFAULT_MODEL)
        self.assertTrue(payload["ok"])
        self.assertEqual(code, 0)
        self.assertIn("auth_check", payload)
        self.assertTrue(payload["auth_check"]["ok"])

    @mock.patch("shutil.which", return_value="/usr/local/bin/gemini")
    @mock.patch("subprocess.Popen")
    def test_execute_gemini_timeout(self, mock_popen, _mock_which):
        mock_process = mock.Mock()
        mock_process.returncode = None
        mock_process.communicate.return_value = ("", "")
        mock_popen.return_value = mock_process

        payload, code = run_gemini.execute_gemini(
            gemini_binary="gemini",
            model=run_gemini.DEFAULT_MODEL,
            output_format="json",
            approval_mode=run_gemini.DEFAULT_APPROVAL_MODE,
            prompt="Run task",
            context_files=[],
            context_dirs=[],
            include_directories=[],
            cwd=Path("."),
            timeout_seconds=0,
            progress_logs=False,
            progress_heartbeat_seconds=5,
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 124)
        self.assertEqual(payload["error"]["type"], "TIMEOUT")
        mock_process.kill.assert_called_once()

    @mock.patch("shutil.which", return_value="/usr/local/bin/gemini")
    @mock.patch("subprocess.Popen")
    def test_execute_gemini_detects_tool_error_in_stderr(self, mock_popen, _mock_which):
        mock_process = mock.Mock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (
            '{"response":"ok"}',
            "Error executing tool: Path not in workspace",
        )
        mock_popen.return_value = mock_process

        payload, code = run_gemini.execute_gemini(
            gemini_binary="gemini",
            model=run_gemini.DEFAULT_MODEL,
            output_format="json",
            approval_mode=run_gemini.DEFAULT_APPROVAL_MODE,
            prompt="Run task",
            context_files=[],
            context_dirs=[],
            include_directories=[],
            cwd=Path("."),
            timeout_seconds=10,
            progress_logs=False,
            progress_heartbeat_seconds=5,
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(code, 65)
        self.assertEqual(payload["error"]["type"], "GEMINI_TOOL_ERROR")


if __name__ == "__main__":
    unittest.main()
