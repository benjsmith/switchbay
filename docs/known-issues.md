# Known issues (v0.9.12)

An honest, short list of what's rough or deferred in this release. None
are data-loss or security issues — each is cosmetic, has a workaround,
or is an explicit scope decision.

Provider implementation state (first-class vs usable vs preview,
including Muse Code) lives in **[`providers.md`](providers.md)**. This
page only keeps the one-line workarounds.

## Rough edges (with workarounds)

| Area | Issue | Workaround |
|------|-------|-----------|
| Graph | A page deleted on disk can linger in the graph until the next rebuild. | Run `/rescan` (slash command or button) to force a cold rebuild. |
| Plots | Plot specs still live in `.workbench/plots/`; Save as figure now writes a CE `wiki/figures/` page with caption + provenance. | Use Save as figure for wiki/graph wiring. |
| Packs | With many pack tabs open the tab strip scrolls; there's no overflow dropdown yet. | Scroll the strip horizontally. |
| Codex provider | No per-call rail card (upstream has no PreToolUse). MCP works. | Claude Code or Grok Build for rail cards. Details: [`providers.md`](providers.md). |
| Muse Code | Preview: docs-only spawn, no MCP, no rail card, `--disable-approval`. Contributor-tier models may train on your prompts. | Prefer `muse-spark-1.2`. Use Claude Code / Grok Build for cards + SB tools. Details: [`providers.md`](providers.md). |

## Platform support

macOS is the exercised path (a launchd service). The Windows (Scheduled
Task) and Linux (systemd `--user`) service paths in `service.py` are
implemented but not yet tested — treat them as beta.

On first install or first start, macOS may show **python3.13** (the
daemon) asking to access data from other apps and/or the Keychain.
That is expected — see [README → macOS permission prompts](../README.md#macos-permission-prompts-expected).
Allow both for a normal install.

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
