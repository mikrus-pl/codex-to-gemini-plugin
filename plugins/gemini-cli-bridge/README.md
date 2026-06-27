# Gemini CLI Bridge Plugin

`gemini-cli-bridge` is a Codex plugin that delegates one-shot, large-context analysis tasks to Gemini CLI in headless mode.

## What it provides

- plugin manifest at `.codex-plugin/plugin.json`
- skill `gemini-cli-bridge` for controlled delegation workflows
- slash command `/gemini-run`
- Python wrapper `skills/gemini-cli-bridge/scripts/run_gemini.py` for deterministic execution

## Why this design

- default model is explicit: `gemini-3.1-pro-preview`
- no automatic model fallback
- structured JSON output for traceability
- healthcheck before delegation (binary + non-interactive auth)
- one-shot prompt framing for deterministic consultation
- positional prompt handoff to Gemini CLI (avoids deprecated `--prompt` flag)
- explicit multi-file context injection via `--context-file` and `--context-dir`
- enforced read-only tool mode via `--approval-mode=plan` (no edit tools)

## Recommended usage

Use this plugin when you need a deep project audit in one response:

- pass all related full files (backend, frontend, migrations, docs, business rules)
- ask Gemini for one final report with technical defects and architecture gaps
- ask Gemini for one final report with security vulnerabilities and exploit surfaces
- ask Gemini for one final report with business-flow weaknesses and delivery or regression risks
- ask Gemini for one final report with prioritized mitigations

## Prerequisites

- Gemini CLI installed and available in `PATH` (`gemini --version`)
- Gemini CLI authentication already configured
- Python 3.10+

## Local verification

```bash
python3 skills/gemini-cli-bridge/scripts/run_gemini.py --healthcheck
```

The healthcheck now verifies both:
- Gemini CLI binary availability/version
- headless authentication readiness (non-interactive run)

```bash
mkdir -p "$PWD/.tmp"

cat > "$PWD/.tmp/gemini_bridge_prompt.txt" <<'PROMPT'
Review risks in the pending migration and propose rollout plan.
PROMPT
```

```bash
python3 skills/gemini-cli-bridge/scripts/run_gemini.py \
  --prompt-file "$PWD/.tmp/gemini_bridge_prompt.txt" \
  --approval-mode plan \
  --progress-logs \
  --progress-heartbeat-seconds 15 \
  --context-file ./backend/schema.sql \
  --context-file ./backend/migrations/20260408_add_column.sql \
  --context-file ./backend/services/order_service.py \
  --context-dir ./docs/architecture \
  --output-format json
```

The wrapper injects these paths into Gemini context with `@path` references and keeps
the request in one-shot mode by default.

Context path policy:

- `--context-file` and `--context-dir` must resolve inside `--cwd` or `~/.gemini/tmp/<project>`.
- If external paths are required, run with `--materialize-external-context` so the wrapper copies
  them into `$PWD/.tmp/gemini-context` first.
- `Path not in workspace` or `Error executing tool` in stderr is treated as hard failure.

Runtime observability:

- Wrapper prints progress logs to stderr by default (`START`, `PREFLIGHT`, `EXECUTE`, periodic `RUNNING`, final `COMPLETE` or `TIMEOUT`).
- Use `--no-progress-logs` only when a fully silent terminal is required.
- If terminal appears blocked and no heartbeat appears, treat the run as operationally unhealthy and restart with diagnostics enabled.

## Repository wiring

- marketplace entry: `/.agents/plugins/marketplace.json`
- plugin path: `/plugins/gemini-cli-bridge`

This repository ships one local marketplace plugin entry for `gemini-cli-bridge`.
