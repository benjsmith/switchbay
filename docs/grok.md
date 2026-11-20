# Grok on the rail

The rail can use the signed-in `grok` command (Grok Build). That is a
subscription login. Switch Bay does not send `XAI_API_KEY`. If that
variable is set in the environment, it is removed before `grok` starts,
because the CLI would bill the API key instead of the subscription.

## Install and sign in (Linux)

```sh
curl -fsSL https://x.ai/cli/install.sh | bash
```

Open a new shell so `~/.grok/bin` or `~/.local/bin` is on `PATH`, then:

```sh
grok login
```

On a machine with no browser:

```sh
grok login --device-auth
```

The command prints a URL and a short code. Open the URL on a computer
that has a browser, enter the code, and approve it with the account
that has the Grok subscription.

`grok logout` clears that login.

## Make it the rail default

1. Open Switch Bay and go to Settings.
2. Find **Grok Build**. It is available when `grok` is on `PATH` and
   `~/.grok/auth.json` has a login.
3. Click **Make default**.

The rail picker then uses that provider. The suggested model is
`grok-4.6` until `grok models` returns the list for this install.

## Pasted screenshots

A screenshot pasted into the rail is saved under
`.workbench/uploads/` and the message includes
`[attached: <path>]`. Headless `grok -p` has no image flag, so the
pixels are not inside the prompt. Grok sees the picture by reading
that file with its Read tool. Switch Bay adds that instruction to the
prompt when the attachment is an image.

Tool calls the CLI prints as `tool_call` or `tool_use` events are
shown in the rail. Switch Bay tools also run through the workspace MCP
server the CLI loads.
