# Local browser

The rail assistant can open pages on this machine with Playwright's
agent CLI. The browser runs locally. Headless unless you ask for a
visible window.

## What gets installed

A normal install (`make install` or `make install-service`) installs:

- Playwright **1.65.1** under `~/.local/share/switchbay/playwright-cli`
- a `playwright-cli` command on `~/.local/bin` that runs `playwright cli`
- the agent skill at `~/.agents/skills/playwright-cli`
- the browser builds that release uses: Chromium 1255, Firefox 1572,
  WebKit 2388

Those are the same builds Switch Bay's UI tests install. There is
one copy of each in the Playwright browser cache.

`@playwright/cli` 0.1.23 is not installed. That package depends on
Playwright `1.65.0-alpha-2026-10-30` and would download a separate
pre-release set (Chromium 1252, Firefox 1569, WebKit 2386).

Node.js 20 or newer is required. On Linux the installer also installs
Chromium's system libraries when it can do that without asking for a
password. If it cannot, the browser files are still downloaded. If
Chromium then fails to start, run:

```sh
~/.local/share/switchbay/playwright-cli/node_modules/.bin/playwright install --with-deps
```

## Skip the install

```sh
make install NO_BROWSER=1
make install-service NO_BROWSER=1
bash scripts/install.sh --no-browser
python -m switchbay service install --no-browser
```

## Turn it off after install

Settings → **Local browser**. Off removes the `playwright-cli` skill
and the `playwright_cli` tool from the assistant. The files stay on
disk. On puts them back.

## Organisation policy

The enterprise profile leaves browser use off. The install skips the
CLI, and agents do not receive the skill or the tool. An admin turns
it on by setting `features.browser_use` to true in the admin policy
file. See [Enterprise packaging](enterprise.md). A baked policy that
sets the flag false cannot be turned back on by a later overlay.

## Asking the assistant

In the rail, ask it to open a page. It loads the `playwright-cli`
skill and calls `playwright_cli` with that CLI's arguments (`open`,
`snapshot`, `click`, `type`, and the rest of the skill). Session
files for the workspace land in `.playwright-cli/` inside the
workspace.

For a subscription login, set the rail to **Grok Build** (the `grok`
command). Install, sign-in, and pasted screenshots:
[Grok on the rail](grok.md).

The assistant uses the pinned 1.65.1 install. It does not fetch a
newer Playwright or `@playwright/cli`.
