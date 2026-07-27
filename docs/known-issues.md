# Known issues (v0.9)

An honest, short list of what's rough or deferred in this release. None
are data-loss or security issues — each is cosmetic, has a workaround,
or is an explicit scope decision.

## Rough edges (with workarounds)

| Area | Issue | Workaround |
|------|-------|-----------|
| Graph | A page deleted on disk can linger in the graph until the next rebuild. | Run `/rescan` (slash command or button) to force a cold rebuild. |
| Plots | Plot specs live in `.workbench/plots/`, not as `wiki/plots/<slug>.md` pages. | They work as-is; promoting them to CE-native pages is a post-v1 design call. |
| Packs | With many pack tabs open the tab strip scrolls; there's no overflow dropdown yet. | Scroll the strip horizontally. |
| Codex provider | Codex's tool permissions are workspace-wide — it has no per-call approval card (the upstream CLI lacks a PreToolUse hook). | Use Claude Code or Grok Build, which do surface per-tool approval cards. |

## Platform support

macOS is the exercised path (a launchd service). The Windows (Scheduled
Task) and Linux (systemd `--user`) service paths in `service.py` are
implemented but not yet tested — treat them as beta.

## Comms streams

The password-tier adapters (IMAP, Telegram, Discord, GitHub, iMessage,
RSS) verify credentials at add time and are tested end-to-end. The OAuth
adapters (Gmail, Microsoft 365, Slack) need your own app registration and
a browser round-trip; that path is wired but less exercised.

## Intentionally out of scope for v1

- **Multi-user / multi-machine / hosted** deployment — Switch Bay is
  single-user and localhost-only by design.
- **A plugin marketplace** — skills and MCP servers are added locally
  (authored or entered by hand), never from a catalog.
