# Security posture

[Enterprise security](index.md)

Switch Bay is one Python daemon and a browser app on the same
machine, used by one person. It is a workbench over a folder
(`wiki/` for pages, `vault/` for source files). It is not a
multi-user server, a DLP gateway, or a system that holds keys for
other people.

## What it assumes

The person at the keyboard is the operator. The daemon runs as that
OS user. Files it creates sit in that user's home (or in the
workspace folder they chose). There is no separate Switch Bay
account, and no second user inside one daemon.

The browser app is the UI. Agents in the right-hand chat have tools:
search and read the wiki, propose pages, run workspace commands when
that feature is on, and call models. A tool runs because the agent
asked, inside the permission rules already used for shell and web
(an approval card, a hard deny, and the admin feature flags).
Exclusion rules, described in [Controls](controls.md), are an extra
instruction in the prompt. They do not sit in that permission check.

## The daemon's own boundary

The daemon listens on `127.0.0.1` port `8765` unless the admin file
sets `network.bind_port`. In the enterprise profile a bind address
other than `127.0.0.1` or `::1` is refused at startup.

Loopback is not a private network. Any website open in the browser
can try to call `127.0.0.1`. Two header checks apply to every
request:

- When an `Origin` header is present, its host must be `127.0.0.1`,
  `localhost`, or `::1`. Browsers set `Origin` on cross-site requests
  and on WebSocket handshakes, and page script cannot forge it.
- The `Host` header's hostname must be one of those same names, so a
  DNS-rebinding request that arrives as some other host is refused.

A request with no `Origin` and a loopback `Host` is accepted. That
is how `curl`, local probes, and the agent's own permission callback
reach the daemon. There is no extra shared secret on those calls.

The same loopback rule covers the agent-to-agent endpoint (`POST /a2a`
and the agent card under `/.well-known/`). It is for threads on this
machine. It is not a remote peering channel.

## Enterprise profile

The enterprise profile, set by `SWITCHBAY_PROFILE=enterprise` or by
`"profile": "enterprise"` in the admin file, changes defaults:

- Providers on: GitHub Copilot, llama.cpp, MLX, and Ollama. Hosted
  API providers (Anthropic, OpenAI, xAI, Gemini, Meta) and the
  coding CLIs (Claude Code, Grok Build, Muse Code, Codex) are off
  until an admin turns that provider on. The `providers` section of
  the admin file is applied.
- Features that download toolchains, scan other apps' caches, turn
  on open-web search, publish to GitHub, or call image and video
  APIs are off. The table is in the
  [configuration reference](configuration.md).
- Outbound HTTP from the enterprise profile is limited to loopback,
  the Copilot hosts for `copilot.host`, and any names in
  `network.egress_allowlist`. Hugging Face hosts are added only when
  `hf_model_download` is on. GitHub hosts used by in-app update are
  added only when `in_app_update` is on.
- A workspace path given on the serve command is refused when it
  sits in iCloud, OneDrive, Dropbox, or Google Drive, unless that
  path is under `paths.trust_boundary`. See [Controls](controls.md).

A baked `admin.baked.json` (produced by the company package) makes
later overlay files tighten-only for feature flags and providers:
an overlay can turn a flag off, and cannot turn a baked-off flag
back on. A tester file written by `service install --enterprise-user`
is an overlay with no baked file, so it is not tighten-only.

## What this is not

Labels (`public`, `internal`, `confidential`, `restricted`) are
frontmatter on a page and a rule that a citation keeps the higher
label. They are not encryption, not a mandatory access-control
system, and not a Purview or Unity Catalog policy. The catalog
check that would ask those systems is a stub. See
[Controls](controls.md).

The audit file records ids and reasons for mount, capture, and
refusal events. It does not record page bodies, prompts, or model
replies, and it is not shipped off the machine. See
[Audit log](audit.md).

Remote pages are wrapped so the model can see they came from
elsewhere. That wrapping is a marker in the text, not a sandbox.
See [Untrusted content](untrusted.md).
