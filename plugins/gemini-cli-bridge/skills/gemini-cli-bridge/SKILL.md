---
name: gemini-cli-bridge
description: Delegate project-scale one-shot analysis tasks to Gemini CLI in headless mode. Use when the user wants large-context review of many related files to uncover technical, security, and business risks.
---

# Gemini CLI Bridge

## Overview

This skill provides a strict and auditable bridge from Codex to Gemini CLI.
It is designed for production-sensitive workflows where model choice must stay explicit.
It also supports one-shot consultations with large, explicit file context.
It enforces read-only approval mode (`--approval-mode=plan`) so Gemini cannot modify
project files during analysis runs.

Recommended use:

- Pass all directly related backend, frontend, migration, and design or policy files.
- Ask for a single final analysis that includes technical defects, vulnerabilities,
  business impact, and mitigation priorities.

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
mkdir -p "$PWD/.tmp"

cat > "$PWD/.tmp/gemini_prompt.txt" <<'PROMPT'
Review end-to-end risks in this change and propose concrete fixes.
PROMPT

python3 scripts/run_gemini.py \
  --model gemini-3.1-pro-preview \
  --prompt-file "$PWD/.tmp/gemini_prompt.txt" \
  --context-file ./backend/src/service.py \
  --context-file ./frontend/src/App.tsx \
  --context-dir ./migrations \
  --progress-logs \
  --progress-heartbeat-seconds 15 \
  --output-format json \
  --cwd .
```

## Required workflow

1. Preflight:
   - Run `python3 scripts/run_gemini.py --healthcheck`.
   - Healthcheck validates both CLI availability and non-interactive auth readiness.
   - If healthcheck fails, stop and provide fix steps.
2. Clarify scope:
   - Define exactly what Gemini should do and what output format is expected.
   - Keep prompt deterministic (inputs, constraints, deliverable, acceptance criteria).
   - Keep prompt one-shot: Gemini should return a complete answer in one response.
3. Build context set:
   - Select concrete files needed for reasoning (it is acceptable to pass many full files).
   - Prefer explicit files with `--context-file`; use `--context-dir` for cohesive modules.
   - Keep `--context-file` and `--context-dir` inside `--cwd` or `~/.gemini/tmp/<project>`.
   - If external context is unavoidable, explicitly use `--materialize-external-context`.
   - Do not pass secrets or unrelated files.
   - Prefer complete files over snippets so Gemini can reason across full code and flow boundaries.
4. Execute:
   - For short prompts, prefer `--prompt`.
   - For long/multiline prompts, prefer `--prompt-file` stored under `$PWD/.tmp/`.
   - Run wrapper with `--output-format json` and explicit context flags.
   - Keep progress logs enabled (default) so terminal shows wrapper phases and heartbeat while Gemini is running.
   - Keep Gemini prompt handoff positional (do not use deprecated Gemini `--prompt` flag).
   - Keep `--model` explicit.
   - Keep `--approval-mode=plan` to block editing tools.
5. Validate:
   - Require `ok: true` and `exit_code: 0` in wrapper output.
   - Treat `GEMINI_TOOL_ERROR` as hard failure (for example `Path not in workspace`).
   - Parse `gemini.response` when present, otherwise use `stdout`.
   - Treat technical findings as hypotheses until critically verified against the codebase.
   - If a technical finding is confirmed, fix it or explicitly document why it is deferred.
6. Summarize:
   - Report what Gemini returned.
   - Highlight confidence and unresolved risks before applying changes.
   - Clearly separate technical findings from business-flow findings.
   - Present business findings as a prioritized list with clear impact and urgency.

## Runtime diagnostics

- Wrapper prints runtime diagnostics to `stderr` by default:
  - `START` and `PREFLIGHT` phases
  - `EXECUTE` start line with model/cwd/timeout
  - `RUNNING` heartbeat every `--progress-heartbeat-seconds`
  - `COMPLETE` or `TIMEOUT`
- Keep `--progress-logs` enabled unless you intentionally need silent terminal output.
- If terminal appears "stuck", require at least one heartbeat line before deciding the run is blocked.

### Common failure signatures and actions

- `AUTH_REQUIRED`:
  - Business impact: delegation path unavailable; no audit/review can be delivered.
  - Action: run interactive `gemini` login for same OS user or configure headless creds.
- `INVALID_CONTEXT_PATH`:
  - Business impact: request executes without required evidence, risking wrong conclusions.
  - Action: move context into `$PWD/.tmp` or use `--materialize-external-context`.
- `GEMINI_TOOL_ERROR` with `Path not in workspace`:
  - Business impact: Gemini did not read all intended files; result is non-auditable.
  - Action: same as above; rerun only after context paths are workspace-safe.
- `TIMEOUT`:
  - Business impact: blocked delivery and incomplete analysis.
  - Action: increase `--timeout-seconds`, narrow context scope, or split task into smaller batches.

## Guardrails

- Never silently switch models.
- Never suppress wrapper errors.
- Never ignore `AUTH_REQUIRED`; resolve headless auth first.
- Never claim Gemini output is verified unless local checks were executed.
- If fallback is requested by Gemini CLI due limits/capacity, ask user permission first.
- Never use deprecated Gemini CLI prompt flags; keep prompt positional.
- Never send ambiguous prompts in one-shot mode.
- Never include files outside task scope without explicit reason.
- Never place context files in `/tmp` for wrapper execution; use `$PWD/.tmp` instead.
- Never present unverified technical findings as facts.
- Never report business-flow issues without prioritization and explicit impact language.
- Never run in any approval mode other than `plan` for this plugin.

## Business impact guidance

- Model fallback without approval can change output quality and cause silent regressions in
  architecture, migration, or code-change recommendations.
- Missing healthcheck means delegation function is down; communicate that as a blocked
  execution path, not a partial success.
- Excessive unrelated context increases latency/cost and can lower answer precision.
