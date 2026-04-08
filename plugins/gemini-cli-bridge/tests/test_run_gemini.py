import importlib.util
import subprocess
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

    @mock.patch("shutil.which", return_value=None)
    def test_healthcheck_binary_missing(self, _mock_which):
        payload, code = run_gemini.perform_healthcheck("gemini", run_gemini.DEFAULT_MODEL)
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 127)
        self.assertEqual(payload["error"]["type"], "BINARY_NOT_FOUND")

    @mock.patch("shutil.which", return_value="/usr/local/bin/gemini")
    @mock.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["gemini"], timeout=10),
    )
    def test_execute_gemini_timeout(self, _mock_run, _mock_which):
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
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(code, 124)
        self.assertEqual(payload["error"]["type"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
