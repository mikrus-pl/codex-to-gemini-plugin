# Codex to Gemini CLI Plugin

Large-context Codex plugin that delegates one-shot project analysis to Gemini CLI.

## Author

- **Creator**: Michał S. Wasażnik
- **Websites**:
  - https://www.heuron.pl
  - https://www.aicanvas.space

## What this repository contains

- Plugin ID: `gemini-cli-bridge`
- Plugin source folder: `plugins/gemini-cli-bridge`
- Local repo marketplace file: `.agents/plugins/marketplace.json`

This plugin is designed for deep analysis by passing many full files to Gemini in one request.

## Codex plugin anatomy (beginner-friendly)

Think about Codex plugins as two layers:

1. **Plugin package**: what the plugin is and how it behaves.
2. **Marketplace catalog**: where Codex discovers installable plugins.

### Layer 1: Plugin package (`plugins/gemini-cli-bridge`)

| Path | What it is |
|---|---|
| `plugins/gemini-cli-bridge/.codex-plugin/plugin.json` | Main plugin manifest (name, author, UI metadata, capabilities). |
| `plugins/gemini-cli-bridge/skills/.../SKILL.md` | Behavior instructions used by Codex when plugin skill is invoked. |
| `plugins/gemini-cli-bridge/commands/gemini-run.md` | Slash command definition (`/gemini-run`). |
| `plugins/gemini-cli-bridge/skills/.../scripts/run_gemini.py` | Runtime wrapper that calls `gemini` CLI safely and deterministically. |
| `plugins/gemini-cli-bridge/assets/*` | Plugin icon and logo used by Codex UI. |
| `plugins/gemini-cli-bridge/tests/*` | Unit tests for the runtime wrapper. |

### Layer 2: Marketplace catalog

| Path | What it is |
|---|---|
| `.agents/plugins/marketplace.json` | Repo-local marketplace catalog used while developing in this repository. |
| `~/.agents/plugins/marketplace.json` | Your global marketplace catalog used by Codex on your machine. |

### Where Codex stores globally installed plugin source

| Path | What it is |
|---|---|
| `~/.codex/plugins/<plugin-name>` | Global plugin source folder. |
| `~/.codex/plugins/cache/...` | Internal plugin cache used by Codex after install. |

## Prerequisites

1. macOS with Terminal.
2. Codex CLI installed.
3. Gemini CLI installed and authenticated.
4. Git installed.

Optional but recommended:

```bash
codex features enable plugins
```

Then restart Codex.

## Clone this repository (step by step)

1. Open Terminal.
2. Move to a place where you keep projects:

```bash
cd ~/Code
```

3. Clone:

```bash
git clone https://github.com/mikrus-pl/codex-to-gemini-plugin.git
```

4. Enter repo:

```bash
cd codex-to-gemini-plugin
```

## Install globally - Manual method

This is the fully manual path, no helper script.

### 1) Create global Codex folders (if missing)

```bash
mkdir -p ~/.codex/plugins
mkdir -p ~/.agents/plugins
```

### 2) Copy plugin package to global plugin directory

From this repo root:

```bash
cp -R plugins/gemini-cli-bridge ~/.codex/plugins/
```

After this step, this file must exist:

`~/.codex/plugins/gemini-cli-bridge/.codex-plugin/plugin.json`

### 3) Add plugin entry to global marketplace

Edit or create:

`~/.agents/plugins/marketplace.json`

If file does not exist, create this exact content:

```json
{
  "name": "personal-local",
  "interface": {
    "displayName": "Personal Local Plugins"
  },
  "plugins": [
    {
      "name": "gemini-cli-bridge",
      "source": {
        "source": "local",
        "path": "./.codex/plugins/gemini-cli-bridge"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Coding"
    }
  ]
}
```

If file already exists, only add (or update) the `gemini-cli-bridge` entry in `plugins[]`.
Do not delete other plugins.

### 4) Restart Codex and install from UI

1. Restart Codex.
2. Run:

```bash
codex
```

3. In Codex, open:

`/plugins`

4. Choose marketplace `Personal Local Plugins`.
5. Install `gemini-cli-bridge`.

## Install globally - Script method (recommended)

From this repo root:

### Option A: Double-click in Finder

Double-click:

`install-gemini-plugin-global.command`

This will:

1. Copy plugin to `~/.codex/plugins/gemini-cli-bridge`.
2. Create or update `~/.agents/plugins/marketplace.json`.
3. Open the relevant folders in Finder.

### Option B: Run script from Terminal

```bash
/usr/bin/python3 scripts/install_global_plugin.py
```

After script completes:

1. Restart Codex.
2. Run `codex`.
3. Open `/plugins`.
4. Install `gemini-cli-bridge` from `Personal Local Plugins`.

## Open hidden Codex folders on macOS (helper)

Double-click:

`open-codex-folders.command`

It opens:

- `~/.codex`
- `~/.codex/plugins`
- `~/.agents/plugins`

## Verify plugin runtime quickly

```bash
python3 plugins/gemini-cli-bridge/skills/gemini-cli-bridge/scripts/run_gemini.py --healthcheck
```

## Run tests

```bash
python3 -m unittest discover -s plugins/gemini-cli-bridge/tests -p "test_*.py"
```
