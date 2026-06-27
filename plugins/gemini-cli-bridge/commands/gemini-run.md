---
description: Delegate a task from Codex to Gemini CLI using the strict Gemini 3.1 Pro bridge wrapper.
---

# Gemini Run

Delegate work to Gemini CLI and return structured output to Codex.
This command is best for one-shot project analysis with many related full files.

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
   - `AUTH_REQUIRED` means Gemini is not authenticated for non-interactive/headless execution.
5. Keep approval mode read-only (`plan`) so Gemini cannot invoke editing tools.

## Plan

1. Build a deterministic prompt from `$ARGUMENTS`.
2. Attach all related files and module directories as explicit context.
3. Run Gemini CLI via wrapper in JSON mode.
4. Validate wrapper response and summarize Gemini output.

No destructive operations are performed by this command.

## Commands

```bash
mkdir -p "$PWD/.tmp"

cat > "$PWD/.tmp/gemini_bridge_prompt.txt" <<PROMPT
$ARGUMENTS
PROMPT
```

```bash
CONTEXT_ARGS=(
  --context-file ./backend/src/service_a.py
  --context-file ./backend/src/service_b.py
  --context-file ./frontend/src/app.tsx
  --context-file ./docs/business-rules.md
  --context-dir ./backend/migrations
)
```

```bash
python3 "$SCRIPT_PATH" \
  --model gemini-3.1-pro-preview \
  --approval-mode plan \
  --prompt-file "$PWD/.tmp/gemini_bridge_prompt.txt" \
  --progress-logs \
  --progress-heartbeat-seconds 15 \
  "${CONTEXT_ARGS[@]}" \
  --output-format json \
  --cwd .
```

## Verification

1. Require JSON output from wrapper.
2. Require `ok=true` and `exit_code=0`.
3. Treat `INVALID_CONTEXT_PATH` and `GEMINI_TOOL_ERROR` as hard failures.
4. If wrapper returns non-zero, stop and surface the exact error type and message.
5. Require visible progress logs in stderr (`START`, `PREFLIGHT`, `EXECUTE`, heartbeat `RUNNING`, `COMPLETE`/`TIMEOUT`).

## Troubleshooting

1. If command appears frozen:
   - Confirm heartbeat lines appear every ~15s.
   - If no heartbeat appears, treat wrapper invocation as broken and rerun with `--progress-logs`.
2. If `INVALID_CONTEXT_PATH` or `Path not in workspace` appears:
   - Move context files from `/tmp` to `$PWD/.tmp` or rerun with `--materialize-external-context`.
3. If `AUTH_REQUIRED` appears:
   - Re-authenticate Gemini for non-interactive use in the same OS account.

## Summary

Return:

- delegated model
- technical risk summary
- business-flow risk summary
- known confidence limits

## Next Steps

- If user approves, apply Gemini recommendations in repository changes.
- If model is unavailable, ask whether fallback model is permitted.
