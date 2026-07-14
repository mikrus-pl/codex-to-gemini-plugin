# Antigravity CLI Bridge Plugin

`antigravity-cli-bridge` delegates one-shot, large-context analysis from Codex to Google's Antigravity CLI.

## Runtime contract

- binary: `agy`
- minimum supported version: `1.1.2`
- default model: `Gemini 3.1 Pro (High)`
- headless mode: `--print`
- read-only workflow: `--mode plan`
- terminal isolation: `--sandbox`
- extra context roots: repeatable `--add-dir`
- result: wrapper-owned JSON containing Antigravity's plain-text `response`

The wrapper never selects another model automatically. A missing binary, unavailable model, failed authentication, unreadable context path, empty response, tool error, or timeout is a hard failure.
Generated prompts above 128 KiB are also rejected to avoid Antigravity's reported large-prompt truncation failure mode; pass code through context paths instead of embedding it in the task prompt.

## Why the wrapper owns JSON

Antigravity CLI print mode returns plain text and does not expose Gemini CLI's `--output-format=json` contract. The wrapper therefore records the requested model, execution mode, sandbox state, context paths, redacted command, prompt hash, duration, response, and exit status in its own JSON envelope.

## Prerequisites

1. Install Antigravity CLI from the official installer:

   ```bash
   curl -fsSL https://antigravity.google/cli/install.sh | bash
   ```

2. Confirm `agy --version` reports `1.1.2` or newer.
3. Run `agy` interactively once and complete Google OAuth or Google Cloud onboarding.
4. Use Python 3.9 or newer.

## Healthcheck

```bash
python3 skills/antigravity-cli-bridge/scripts/run_antigravity.py --healthcheck
```

The healthcheck verifies the binary, minimum version, exact model availability, and a real non-interactive authenticated request.

## Example

```bash
mkdir -p "$PWD/.tmp"

cat > "$PWD/.tmp/antigravity_bridge_prompt.txt" <<'PROMPT'
Review the pending migration end to end and propose a safe rollout plan.
PROMPT
```

```bash
python3 skills/antigravity-cli-bridge/scripts/run_antigravity.py \
  --prompt-file "$PWD/.tmp/antigravity_bridge_prompt.txt" \
  --model "Gemini 3.1 Pro (High)" \
  --context-file ./backend/schema.sql \
  --context-file ./backend/services/order_service.py \
  --context-dir ./backend/migrations \
  --cwd .
```

Context outside `--cwd` is made visible through an explicit Antigravity `--add-dir` argument. The wrapper lists every requested path in the prompt and tells Antigravity to fail rather than return a partial review when a path cannot be read.

## Breaking migration from Gemini CLI Bridge

This plugin intentionally does not ship compatibility shims:

- plugin ID changed from `gemini-cli-bridge` to `antigravity-cli-bridge`
- skill changed from `gemini-cli-bridge` to `antigravity-cli-bridge`
- slash command changed from `/gemini-run` to `/antigravity-run`
- wrapper changed from `run_gemini.py` to `run_antigravity.py`
- Gemini-only flags such as `--approval-mode` and `--output-format` were removed

Keeping both contracts behind one name would hide backend differences and make audits non-reproducible.
