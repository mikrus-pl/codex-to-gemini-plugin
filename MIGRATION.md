# Migrating to Antigravity CLI Bridge

This guide covers both upgrades from `gemini-cli-bridge` and fresh installations.

## Recommended command

```bash
python3 scripts/install_global_plugin.py
```

The command is interactive only when Antigravity must be installed, updated, or authenticated.

## Migration state machine

The migrator follows a two-phase cutover:

1. Preflight Codex CLI, `agy`, minimum version, exact model, and authentication.
2. Snapshot the personal marketplace and current Codex plugin inventory.
3. Stage the new source with a rollback backup.
4. Publish a transitional marketplace containing both old and new plugins.
5. Install the new plugin with `codex plugin add`.
6. Run the installed plugin's real Antigravity healthcheck.
7. Remove the old plugin from Codex only after healthcheck success.
8. Replace the transitional marketplace with the final new-only entry.
9. Move the old source to `~/.codex/plugins/.migration-backups/`.
10. Verify that the new plugin is installed and the old one is not.

The legacy plugin remains operational until step 7.

## Rollback

If migration fails after filesystem changes begin, the migrator attempts to:

1. restore the archived legacy source;
2. uninstall a newly added Antigravity plugin;
3. restore the previous Antigravity plugin source if it was an upgrade;
4. restore the exact original marketplace bytes;
5. reinstall the previously installed plugin entries.

Rollback problems are reported individually. They are never suppressed.

## Flags

### Approve official Antigravity installation or update

```bash
python3 scripts/install_global_plugin.py --yes
```

`--yes` authorizes downloading Google's official installer when `agy` is missing and running `agy update` when the installed version is too old. It does not bypass OAuth.

### Pre-authenticated automation

```bash
python3 scripts/install_global_plugin.py --yes --no-launch-auth
```

Use this only when the same OS account is already authenticated. Authentication failure remains a hard error.

### Keep the old source path

```bash
python3 scripts/install_global_plugin.py --keep-legacy-source
```

The old plugin is still removed from Codex and marketplace, but its source directory is left untouched. The default moves it to a timestamped backup.

## Expected success result

After migration:

- `codex plugin list --json` contains `antigravity-cli-bridge@<personal-marketplace>`;
- it does not contain `gemini-cli-bridge@<personal-marketplace>`;
- `~/.agents/plugins/marketplace.json` contains only the new entry;
- the installed wrapper healthcheck returns `ok: true`;
- the old source is stored under `.migration-backups` unless explicitly retained.

Restart Codex and open a new task before using `/antigravity-run`.

## Troubleshooting

### Codex CLI not found

Install or repair Codex CLI first. The migrator will not mutate plugin state without the CLI that owns installation and cache state.

### `BINARY_NOT_FOUND`

Run the migrator interactively and approve the official Antigravity installer, or install `agy` from:

```text
https://antigravity.google/cli/install.sh
```

### `VERSION_UNSUPPORTED`

Approve `agy update` or update Antigravity manually, then rerun migration.

### `AUTH_REQUIRED`

Run `agy`, complete Google OAuth or Google Cloud onboarding, exit Antigravity, and rerun migration.

### `MODEL_UNAVAILABLE`

The migrator stops. It does not select another model. Confirm account eligibility and available Antigravity models.

### Marketplace is a symlink

The migrator refuses to replace symlinked marketplace or plugin paths because atomic replacement would break the link. Migrate that custom setup manually.

### Migration failed

Read both the primary error and any `Rollback problems` section. Do not delete `.backup`, `.staging`, or `.migration-backups` directories until the active Codex plugin state has been verified.
