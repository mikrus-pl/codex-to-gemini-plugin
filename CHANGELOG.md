# Changelog

## Unreleased

### Breaking

- Replaced `gemini-cli-bridge` with `antigravity-cli-bridge`.
- Replaced `/gemini-run` with `/antigravity-run`.
- Replaced Gemini CLI flags and output parsing with Antigravity `agy --print`, plan mode, sandbox mode, repeatable workspaces, and wrapper-owned JSON.

### Added

- One-command fresh installation and transactional legacy migration.
- Automatic Codex plugin install/remove operations.
- Two-phase cutover that validates the new plugin before retiring the old one.
- Rollback of marketplace, plugin source, and Codex installation state.
- Optional official Antigravity installation/update with explicit approval.
- Interactive authentication handoff and installed-copy healthcheck.
- Timestamped archive of legacy plugin source.
- Fresh-install, migration, and rollback integration tests.

### Security

- Forced Antigravity plan and sandbox modes.
- Exact model validation with no fallback.
- Refusal to replace symlinked marketplace and plugin paths.
- Prompt-size limit for the reported Antigravity truncation failure class.
