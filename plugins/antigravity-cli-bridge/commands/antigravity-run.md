---
description: Delegate a one-shot project analysis to Antigravity CLI in sandboxed plan mode.
---

# Antigravity Run

Delegate `$ARGUMENTS` to Antigravity CLI as an analysis-only second opinion.

## Preflight

1. If `$ARGUMENTS` is empty, ask the user for the analysis task.
2. Resolve the wrapper:

```bash
if [ -f "plugins/antigravity-cli-bridge/skills/antigravity-cli-bridge/scripts/run_antigravity.py" ]; then
  SCRIPT_PATH="plugins/antigravity-cli-bridge/skills/antigravity-cli-bridge/scripts/run_antigravity.py"
elif [ -f "skills/antigravity-cli-bridge/scripts/run_antigravity.py" ]; then
  SCRIPT_PATH="skills/antigravity-cli-bridge/scripts/run_antigravity.py"
else
  echo "Antigravity bridge wrapper not found."
  exit 1
fi
```

3. Run `python3 "$SCRIPT_PATH" --healthcheck`.
4. Stop on any healthcheck failure. Never change models automatically.

## Context selection

Select the concrete files and cohesive directories required to verify the task end to end. Include backend, frontend, migrations, tests, documentation, and business rules when relevant. Do not include secrets or unrelated files.

## Execute

```bash
mkdir -p "$PWD/.tmp"

cat > "$PWD/.tmp/antigravity_bridge_prompt.txt" <<PROMPT
$ARGUMENTS
PROMPT
```

Build context arguments for the real task, for example:

```bash
CONTEXT_ARGS=(
  --context-file ./backend/src/service_a.py
  --context-file ./frontend/src/app.tsx
  --context-file ./docs/business-rules.md
  --context-dir ./backend/migrations
)
```

```bash
python3 "$SCRIPT_PATH" \
  --model "Gemini 3.1 Pro (High)" \
  --execution-mode plan \
  --prompt-file "$PWD/.tmp/antigravity_bridge_prompt.txt" \
  "${CONTEXT_ARGS[@]}" \
  --progress-logs \
  --progress-heartbeat-seconds 15 \
  --cwd .
```

The wrapper always invokes `agy --print` with `--mode plan --sandbox`. Never use `--dangerously-skip-permissions` or `accept-edits`.

## Verification

1. Require wrapper JSON with `ok=true` and `exit_code=0`.
2. Require the requested model, `execution_mode=plan`, and `sandbox=true`.
3. Read Antigravity's answer from `response`.
4. Treat `INVALID_CONTEXT_PATH`, `ANTIGRAVITY_TOOL_ERROR`, `EMPTY_RESPONSE`, and `TIMEOUT` as hard failures.
5. Verify technical claims locally before presenting them as facts or applying changes.

## Result

Return:

- delegated model and inspected context
- verified technical findings
- unverified hypotheses
- prioritized security and business-flow risks
- confidence limits and missing evidence

Only implement recommendations after separate Codex verification.
