# Research: Claude Code `oh-my-claudecode` marketplace error

Date: 2026-03-19

## User-visible symptom

- Claude Code shows: `Plugin 'oh-my-claudecode' not found in marketplace 'oh-my-claudecode'`
- UI also reports: `Plugin may not exist in marketplace 'oh-my-claudecode'`

## Repository-local findings

- This repository only contains `.claude/settings.local.json`.
- `.claude/settings.local.json` currently enables project MCP servers only and does not define plugin marketplaces or enabled plugins.
- Therefore the reported plugin error is not caused by a project-local config in this repo.

## User-scope Claude Code findings

### `/home/jjb/.claude/settings.json`

- `extraKnownMarketplaces` contains an entry keyed as `oh-my-claudecode` pointing to GitHub repo `yeachan-heo/oh-my-claudecode`.
- There is no matching `enabledPlugins` entry for `oh-my-claudecode@oh-my-claudecode` or `oh-my-claudecode@omc`.

### `/home/jjb/.claude/plugins/known_marketplaces.json`

- Registered marketplaces include:
  - `claude-plugins-official`
  - `claude-code-plugins`
  - `superpowers-marketplace`
  - `claude-hud`
- There is no registered `oh-my-claudecode` marketplace entry.
- There is no registered `omc` marketplace entry in this file either, despite marketplace folders existing on disk.

### Marketplace manifests on disk

- `/home/jjb/.claude/plugins/marketplaces/oh-my-claudecode/.claude-plugin/marketplace.json`
- `/home/jjb/.claude/plugins/marketplaces/omc/.claude-plugin/marketplace.json`

Both files declare the marketplace name as:

```json
{
  "name": "omc"
}
```

This is the key mismatch.

## External documentation findings

- Claude Code docs require plugin installs to use `plugin-name@marketplace-name`.
- Marketplace name comes from `.claude-plugin/marketplace.json` field `name`.
- Example from docs: marketplace file name `my-plugins` requires install command `/plugin install quality-review-plugin@my-plugins`.
- The oh-my-claudecode upstream docs say:
  - `/plugin marketplace add https://github.com/Yeachan-Heo/oh-my-claudecode`
  - `/plugin install oh-my-claudecode`
- The same upstream README later references `/plugin marketplace update omc`, which matches the actual marketplace manifest name.

## Root cause

- The upstream plugin repository is branded `oh-my-claudecode`, but its actual marketplace identifier is `omc`.
- User config currently stores the marketplace under key `oh-my-claudecode`, while the installed marketplace manifest identifies itself as `omc`.
- Claude Code then tries to resolve plugin `oh-my-claudecode` inside marketplace `oh-my-claudecode`, but the marketplace catalog actually names itself `omc`, producing the error.

## Safe fix direction

- Update user-scope marketplace configuration to use `omc` as the marketplace key.
- Ensure plugin installation, if enabled, references `oh-my-claudecode@omc`.
- Reload or refresh Claude Code plugin metadata after the config change.

## Constraints

- The required fix is outside the current workspace, in `/home/jjb/.claude/...`.
- Per security policy, those files cannot be modified without explicit user approval.
