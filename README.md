# Codex to Gemini CLI Plugin

This repository contains a local Codex plugin that delegates selected tasks to Gemini CLI.

## Delivered artifact

- plugin id: `gemini-cli-bridge`
- plugin root: `plugins/gemini-cli-bridge`
- marketplace file: `.agents/plugins/marketplace.json`

## Scope

- Codex plugin manifest and marketplace entry
- skill for safe delegation workflow
- slash command for quick invocation
- deterministic wrapper around `gemini` CLI
- one-shot consultation mode with explicit multi-file context injection
- unit tests for wrapper core behavior

## Run tests

```bash
python3 -m unittest discover -s plugins/gemini-cli-bridge/tests -p "test_*.py"
```

## Quick healthcheck

```bash
python3 plugins/gemini-cli-bridge/skills/gemini-cli-bridge/scripts/run_gemini.py --healthcheck
```

## macOS global install helpers

Double-click in Finder:

- `install-gemini-plugin-global.command`  
  Copies plugin to `~/.codex/plugins/gemini-cli-bridge` and updates
  `~/.agents/plugins/marketplace.json`.
- `open-codex-folders.command`  
  Opens `~/.codex` and `~/.agents/plugins` in Finder.

If plugin directory is not visible in CLI, enable plugins feature and restart Codex:

```bash
codex features enable plugins
```
