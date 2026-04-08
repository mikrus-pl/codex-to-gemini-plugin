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
- healthcheck before delegation
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

```bash
cat > /tmp/gemini_bridge_prompt.txt <<'PROMPT'
Review risks in the pending migration and propose rollout plan.
PROMPT
```

```bash
python3 skills/gemini-cli-bridge/scripts/run_gemini.py \
  --prompt-file /tmp/gemini_bridge_prompt.txt \
  --approval-mode plan \
  --context-file ./backend/schema.sql \
  --context-file ./backend/migrations/20260408_add_column.sql \
  --context-file ./backend/services/order_service.py \
  --context-dir ./docs/architecture \
  --output-format json
```

The wrapper injects these paths into Gemini context with `@path` references and keeps
the request in one-shot mode by default.

## Repository wiring

- marketplace entry: `/.agents/plugins/marketplace.json`
- plugin path: `/plugins/gemini-cli-bridge`

This repository ships one local marketplace plugin entry for `gemini-cli-bridge`.
