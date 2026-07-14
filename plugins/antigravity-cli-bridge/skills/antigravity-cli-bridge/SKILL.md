---
name: antigravity-cli-bridge
description: Delegate project-scale one-shot analysis tasks to Antigravity CLI in sandboxed plan mode. Use when the user wants a large-context review of related files to uncover technical, security, and business risks.
---

# Antigravity CLI Bridge

## Purpose

Use the bundled wrapper to run Antigravity CLI as a second-opinion analysis engine. The workflow is intentionally read-only for project files and is suitable for production-sensitive architecture, migration, security, and business-flow reviews.

Runtime contract:

- Antigravity CLI binary: `agy`
- minimum supported version: `1.1.2`
- default model: `Gemini 3.1 Pro (High)`
- one-shot execution: `--print`
- project protection: `--mode plan --sandbox`
- external context: explicit repeatable `--add-dir`
- wrapper result: JSON with Antigravity's plain-text response in `response`

Never silently switch models. If the exact requested model is unavailable, stop and ask the user before using another model.

## Entrypoint

From this skill directory:

```bash
python3 scripts/run_antigravity.py --healthcheck
```

For analysis:

```bash
mkdir -p "$PWD/.tmp"

cat > "$PWD/.tmp/antigravity_prompt.txt" <<'PROMPT'
Review this change end to end. Verify technical correctness, security, migrations,
frontend/backend consistency, business-flow protection, and rollout risk.
PROMPT

python3 scripts/run_antigravity.py \
  --model "Gemini 3.1 Pro (High)" \
  --prompt-file "$PWD/.tmp/antigravity_prompt.txt" \
  --context-file ./backend/src/service.py \
  --context-file ./frontend/src/App.tsx \
  --context-dir ./migrations \
  --cwd .
```

Resolve the script to an absolute path when executing outside the skill directory.

## Required workflow

1. Preflight:
   - Run `python3 scripts/run_antigravity.py --healthcheck`.
   - Require `ok: true`, the expected model, plan mode, sandbox mode, and successful auth.
   - Treat missing binary, outdated version, unavailable model, or auth failure as a blocked delegation function.
2. Define the task:
   - State inputs, constraints, output sections, and acceptance criteria.
   - Require one complete answer and tell Antigravity not to modify files or run state-changing commands.
3. Select context:
   - Include all directly related backend, frontend, migration, tests, docs, and business rules.
   - Prefer complete files over snippets.
   - Do not include secrets or unrelated files.
   - Use `--context-file` and `--context-dir`; do not hide evidence selection in a broad filesystem scan.
4. Execute:
   - Keep the default explicit model unless the user requested another exact model.
   - Keep progress logging enabled so long runs show heartbeat messages.
   - Never use `--dangerously-skip-permissions` or `accept-edits`.
5. Validate:
   - Require `ok: true` and `exit_code: 0`.
   - Read the result from `response`.
   - Reject empty responses and any `ANTIGRAVITY_TOOL_ERROR`.
   - Treat model findings as hypotheses until checked against the repository and runtime evidence.
6. Report:
   - Separate verified defects, unverified hypotheses, and business risks.
   - Prioritize by impact and urgency.
   - State any context Antigravity could not inspect.

## Failure handling

- `BINARY_NOT_FOUND` or `VERSION_UNSUPPORTED`: delegation is unavailable; install or update `agy`.
- `MODEL_UNAVAILABLE`: stop. Ask before changing the model.
- `AUTH_REQUIRED`: run `agy` interactively and complete Google OAuth or Google Cloud onboarding.
- `INVALID_CONTEXT_PATH`: fix the path; do not continue with incomplete evidence.
- `ANTIGRAVITY_TOOL_ERROR`: the analysis is incomplete and must not be presented as a finished audit.
- `TIMEOUT`: increase the timeout or narrow the requested scope; do not treat partial output as final.
- `PROMPT_TOO_LARGE`: keep instructions concise and pass evidence with context path flags.

## Guardrails

- Never silently fall back to Gemini CLI or another Antigravity model.
- Never use Antigravity edit modes in this plugin.
- Never use `--dangerously-skip-permissions`.
- Never suppress wrapper errors or stderr evidence.
- Never claim delegated findings are verified until local checks confirm them.
- Never apply Antigravity recommendations automatically; Codex must review and implement them separately.
- Never omit frontend/backend or migration implications from an end-to-end review.

## Business impact

- A silent model change makes architecture and migration reviews non-reproducible.
- Missing or unreadable context can produce false confidence and regress production flows.
- Edit-capable delegation can change production code outside the user's reviewed implementation path.
- Authentication or quota failure means the second-opinion function is down, not partially successful.
