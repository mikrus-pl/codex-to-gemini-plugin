# Codex to Antigravity CLI Plugin

Codex plugin for one-shot, large-context project analysis through Google Antigravity CLI.

## One-command migration

### Existing Gemini CLI Bridge users

```bash
git pull
python3 scripts/install_global_plugin.py
```

### Fresh installation

```bash
git clone https://github.com/mikrus-pl/codex-to-gemini-plugin.git
cd codex-to-gemini-plugin
python3 scripts/install_global_plugin.py
```

On macOS, you can instead double-click `install-antigravity-plugin-global.command`.

The migrator automatically:

1. checks Codex CLI, Python, Antigravity CLI, the exact model, and authentication;
2. offers to install or update `agy` from Google's official installer when needed;
3. keeps the legacy plugin active while staging the new plugin;
4. installs `antigravity-cli-bridge` through `codex plugin add`;
5. runs a real authenticated healthcheck against the installed copy;
6. removes `gemini-cli-bridge` only after the new plugin passes;
7. atomically finalizes the personal marketplace;
8. moves the legacy source into `.migration-backups` instead of deleting it;
9. rolls back marketplace, source, and Codex installation state on failure.

Only two user actions cannot be safely automated:

- completing Google OAuth or Google Cloud onboarding when Antigravity requests it;
- restarting Codex and opening a new task so the new skill is loaded.

For non-interactive environments where Antigravity is already authenticated:

```bash
python3 scripts/install_global_plugin.py --yes --no-launch-auth
```

See [MIGRATION.md](MIGRATION.md) for the complete state machine, rollback behavior, flags, and troubleshooting.

## What changed

Google transitioned the consumer terminal experience from Gemini CLI to Antigravity CLI. For Google AI Pro, Ultra, and free-tier users, Gemini CLI stopped serving requests on June 18, 2026. Gemini CLI remains supported for some enterprise and paid API-key paths, but this project now targets the successor consumer CLI.

| Previous contract | Current contract |
|---|---|
| `gemini-cli-bridge` | `antigravity-cli-bridge` |
| `gemini` | `agy` |
| `/gemini-run` | `/antigravity-run` |
| `run_gemini.py` | `run_antigravity.py` |
| positional Gemini prompt | `agy --print` |
| `--approval-mode plan` | `--mode plan --sandbox` |
| CLI-provided JSON | wrapper-owned JSON around plain text |
| `--include-directories` | repeatable `--add-dir` |

No Gemini CLI runtime fallback or model fallback is included. Mixing both backends under one plugin identity would hide behavior differences and make production reviews non-reproducible.

## Runtime guarantees

- Antigravity CLI `1.1.2` or newer;
- default model fixed to `Gemini 3.1 Pro (High)`;
- exact model availability checked before every delegation;
- non-interactive `--print` execution;
- forced `--mode plan --sandbox`;
- external context granted only through explicit `--add-dir`;
- generated prompts above 128 KiB rejected;
- hard failure on missing context, auth, model, empty output, tool errors, or timeout;
- wrapper-owned JSON with prompt hash, redacted command, context paths, and duration.

Antigravity plan mode can still create its own planning artifacts under `~/.gemini/antigravity-cli/brain`. Runtime verification confirmed it did not modify project files.

## Repository layout

| Path | Purpose |
|---|---|
| `plugins/antigravity-cli-bridge/.codex-plugin/plugin.json` | Codex plugin manifest |
| `plugins/antigravity-cli-bridge/skills/antigravity-cli-bridge/SKILL.md` | Delegation workflow and guardrails |
| `plugins/antigravity-cli-bridge/commands/antigravity-run.md` | `/antigravity-run` command |
| `plugins/antigravity-cli-bridge/skills/antigravity-cli-bridge/scripts/run_antigravity.py` | Auditable `agy` wrapper |
| `scripts/install_global_plugin.py` | Fresh installer and transactional legacy migrator |
| `.agents/plugins/marketplace.json` | Repository-local marketplace |

## Requirements

- macOS or Linux;
- Python 3.9 or newer;
- Codex CLI with plugin support;
- a Google account or Google Cloud project eligible for Antigravity.

If `agy` is missing, the interactive migrator offers to use Google's official installer. It never downloads or executes the installer without confirmation unless `--yes` was explicitly supplied.

## Development verification

```bash
python3 -m unittest discover \
  -s plugins/antigravity-cli-bridge/tests \
  -p "test_*.py"
```

```bash
python3 plugins/antigravity-cli-bridge/skills/antigravity-cli-bridge/scripts/run_antigravity.py --healthcheck
```

The test suite covers fresh installation, legacy migration, marketplace transitions, hard model failure, runtime healthcheck, and rollback when legacy removal fails.

## Publishing checklist

A local commit is not downloadable by other users. To publish a migration-ready version:

1. run the development verification above;
2. commit all renamed, added, and deleted files together;
3. push the commit to the remote repository;
4. confirm the GitHub Actions CI matrix passes;
5. create a tagged GitHub release so users can pin a known version;
6. smoke-test the documented command from a fresh clone.

Do not publish only the new plugin directory. The marketplace, migrator, launcher, documentation, and old-plugin deletions form one atomic release.

## Remaining upstream risks

- Authentication differs from Gemini CLI; AI Studio API-key workflows do not map 1:1.
- Antigravity print mode returns plain text, so consumers must read `response` from wrapper JSON.
- Antigravity is distributed as a binary; integration confidence depends on documented flags and runtime tests.
- Agentic execution may consume more quota than a single-model Gemini CLI request.
- Proprietary production code is processed under the selected Google account and data settings.
- An open report against `agy 1.0.3` describes invented file and commit access after prompt truncation. This project requires `1.1.2`, rejects prompts above 128 KiB, and verifies real workspace access, but delegated findings must still be checked locally.

## Author and license

- Michał S. Wasażnik
- [heuron.pl](https://www.heuron.pl)
- [aicanvas.space](https://www.aicanvas.space)
- MIT License

## Official sources

- [Antigravity CLI repository and installation](https://github.com/google-antigravity/antigravity-cli)
- [Antigravity CLI overview](https://antigravity.google/docs/cli-overview)
- [Gemini CLI migration guide](https://antigravity.google/docs/gcli-migration)
- [Google transition announcement](https://developers.googleblog.com/en/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- [Open upstream print-mode truncation report](https://github.com/google-antigravity/antigravity-cli/issues/224)
