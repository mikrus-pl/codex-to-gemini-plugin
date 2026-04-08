---
description: Delegate a task from Codex to Gemini CLI using the strict Gemini 3.1 Pro bridge wrapper.
---

# Gemini Run

Delegate work to Gemini CLI and return structured output to Codex.

## Preflight

1. Ensure command argument contains the user task. If empty, ask for the task.
2. Resolve wrapper path:

```bash
if [ -f "plugins/gemini-cli-bridge/skills/gemini-cli-bridge/scripts/run_gemini.py" ]; then
  SCRIPT_PATH="plugins/gemini-cli-bridge/skills/gemini-cli-bridge/scripts/run_gemini.py"
elif [ -f "skills/gemini-cli-bridge/scripts/run_gemini.py" ]; then
  SCRIPT_PATH="skills/gemini-cli-bridge/scripts/run_gemini.py"
else
  echo "Gemini bridge wrapper not found."
  exit 1
fi
```

3. Run wrapper healthcheck:
   - `python3 "$SCRIPT_PATH" --healthcheck`
4. If healthcheck fails, stop and return actionable remediation.

## Plan

1. Build a deterministic prompt from `$ARGUMENTS`.
2. Run Gemini CLI via wrapper in JSON mode.
3. Validate wrapper response and summarize Gemini output.

No destructive operations are performed by this command.

## Commands

```bash
cat > /tmp/gemini_bridge_prompt.txt <<PROMPT
$ARGUMENTS
PROMPT
```

```bash
CONTEXT_ARGS=(
  --context-file ./path/to/file1
  --context-file ./path/to/file2
  --context-dir ./path/to/module_dir
)
```

```bash
python3 "$SCRIPT_PATH" \
  --model gemini-3.1-pro-preview \
  --prompt-file /tmp/gemini_bridge_prompt.txt \
  "${CONTEXT_ARGS[@]}" \
  --output-format json \
  --cwd .
```

## Verification

1. Require JSON output from wrapper.
2. Require `ok=true` and `exit_code=0`.
3. If wrapper returns non-zero, stop and surface the exact error type and message.

## Summary

Return:

- delegated model
- Gemini result summary
- known risks or confidence limits

## Next Steps

- If user approves, apply Gemini recommendations in repository changes.
- If model is unavailable, ask whether fallback model is permitted.
