---
name: gemini-cli-bridge
description: Delegate selected tasks to Gemini CLI in headless mode. Use when the user explicitly asks for a Gemini second opinion, parallel analysis, or execution with Gemini 3.1 Pro from Codex.
---

# Gemini CLI Bridge

## Overview

This skill provides a strict and auditable bridge from Codex to Gemini CLI.
It is designed for production-sensitive workflows where model choice must stay explicit.
It also supports one-shot consultations with large, explicit file context.

Default model:

- `gemini-3.1-pro-preview`

Model aliases normalized to that default:

- `gemini 3.1pro`
- `gemini-3.1-pro`
- `gemini3.1pro`

No automatic fallback is allowed in this workflow. If the requested model is unavailable,
stop and ask the user whether fallback to another model is acceptable.

## Script entrypoint

Use the bundled wrapper script relative to this skill:

```bash
python3 scripts/run_gemini.py --healthcheck
```

If you are not executing from the skill directory, resolve the script path first and run it
via absolute path.

For execution:

```bash
python3 scripts/run_gemini.py \
  --model gemini-3.1-pro-preview \
  --prompt-file /tmp/gemini_prompt.txt \
  --context-file ./backend/src/service.py \
  --context-file ./frontend/src/App.tsx \
  --context-dir ./migrations \
  --output-format json \
  --cwd .
```

## Required workflow

1. Preflight:
   - Run `python3 scripts/run_gemini.py --healthcheck`.
   - If healthcheck fails, stop and provide fix steps.
2. Clarify scope:
   - Define exactly what Gemini should do and what output format is expected.
   - Keep prompt deterministic (inputs, constraints, deliverable, acceptance criteria).
   - Keep prompt one-shot: Gemini should return a complete answer in one response.
3. Build context set:
   - Select concrete files needed for reasoning (it is acceptable to pass many full files).
   - Prefer explicit files with `--context-file`; use `--context-dir` for cohesive modules.
   - Do not pass secrets or unrelated files.
4. Execute:
   - Build prompt file and run wrapper with `--output-format json` and context flags.
   - Keep `--model` explicit.
5. Validate:
   - Require `ok: true` and `exit_code: 0` in wrapper output.
   - Parse `gemini.response` when present, otherwise use `stdout`.
6. Summarize:
   - Report what Gemini returned.
   - Highlight confidence and unresolved risks before applying changes.

## Guardrails

- Never silently switch models.
- Never suppress wrapper errors.
- Never claim Gemini output is verified unless local checks were executed.
- If fallback is requested by Gemini CLI due limits/capacity, ask user permission first.
- Never send ambiguous prompts in one-shot mode.
- Never include files outside task scope without explicit reason.

## Business impact guidance

- Model fallback without approval can change output quality and cause silent regressions in
  architecture, migration, or code-change recommendations.
- Missing healthcheck means delegation function is down; communicate that as a blocked
  execution path, not a partial success.
- Excessive unrelated context increases latency/cost and can lower answer precision.
