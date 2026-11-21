# Role of the AI

Facts a compliance team can map onto the EU AI Act and the GDPR. This page does not classify the system under either instrument and does not state that a deployment complies.

## What is called, and where

The enterprise profile allows GitHub Copilot and the local backends llama.cpp, MLX (macOS only), and Ollama. Other providers are off until `providers` in the admin file turns one on, and an outbound call still has to pass the egress allowlist.

| Provider | Where the model runs | Who turns it on |
|---|---|---|
| GitHub Copilot | `api.githubcopilot.com`, after device-code sign-in at `copilot.host` | On by default in enterprise. The admin sets `copilot.host` and can set `lock_host` |
| llama.cpp, MLX | `127.0.0.1`, ports `8878`–`8887`, weights under the per-user state directory or a local snapshot | On by default. The person picks the weights in Settings. Enterprise does not download Hugging Face weights unless `hf_model_download` is on |
| Ollama | `127.0.0.1:11434` | On by default, if Ollama is installed |
| Anthropic, OpenAI, xAI, Gemini, Meta, and the coding CLIs | The vendor host named in [Network](network.md) | Off until the admin sets that provider true and allowlists the host |

The admin file is the allowlist. A provider that is off is not called. Local servers are loopback. There is no separate check that a weight file sits inside `paths.trust_boundary`. That list applies to workspace folders.

The rail model picker selects the model for the chat, `/curate`, and the chief of staff. Independent investigators may use other models the admin has allowed, from the Copilot catalog or a local backend. The person unchecks a row to deny it. Admin-disallowed providers are not used even if a workspace ladder names them.

## What is sent

A Copilot or other hosted call sends the system prompt (including exclusion rules and the page-focus line), the conversation, and tool results. Tool results can include wiki text, vault extracts, and remote pages wrapped as untrusted. Local backends receive the same prompt on loopback. It does not leave the machine for those backends.

Search snippets and page bodies from a mount are included when the model calls `search_wiki` or `read_wiki_page`. Source calls return text only when Review marks the capture usable. A mandatory unlabeled capture is withheld.

Web search and fetch send the query or URL only when `web_egress` is on and the workspace toggle is on, and only after a one-time approval. Both default off in enterprise.

## What the system does by itself, and what waits

The model proposes tool calls. The daemon runs a registry tool after the exclusion check.

| Action | What happens |
|---|---|
| Read the local wiki, search, read a mounted graph | Runs when the model calls the tool. A confidential read raises the session label |
| Deny exclusion rule | The tool does not run |
| Ask exclusion rule | The permission card waits for Approve or Deny |
| Shell command, when `agent_run_command` is on | Existing approval card and hard-deny rules |
| Web search or fetch | One-time card. Not remembered |
| Write a wiki page | The curation path scores, scrubs, and commits, or files a proposal on the Reviews tab. Reviews is a backlog the person accepts or rejects |
| Write to a remote graph | A proposal, unless every direct-write condition holds. Enterprise defaults to proposals |
| Public write without a Presidio analysis | Dialog: OK, Always allow, or Cancel |
| Public write that Presidio flags | Refused. No dialog |
| Declassify a page | Runs when the caller can edit the page. No reason and no admin approval. Audited |
| GitHub publish, PDF export | Refused while the session label is above `public`, and publish refuses files above `public` |
| Import into `vault/ext` | Applied only after the scrub. A hit is quarantined |

The model can lower a page when that page is editable. Publish, and a public write that has not been scanned, still wait for a person. Lowering the session label still requires `human_confirmed` and a reason.

## Decisions about people

Switch Bay does not score, rank, or take an action about a natural person as a decision. Source tools can return rows a catalog already holds (a Work IQ entity, a Unity Catalog privilege, a Quick entity). The result is text in a capture or, if the person snapshots it, a file under `vault/ext`. Nothing in this product grants or denies a person's access to another system. The access check asks the catalog that already owns the item and drops a search hit. It does not write a decision back.

## Traceability

The audit log records confidential reads, refusals, declassification, remote proposals, source-call ids, import and quarantine, Presidio toggle changes, and public-write allows. It does not record prompt text or model replies. The chat reply itself is stamped `classification: <label>` and stored in the workspace chat history. Capture files hold source payloads outside the workspace. See [Audit](audit.md).

## What the person sees

The chat badge shows the session label when it is above `public`. Replies end with the classification line. Remote pages from trust `org` or `external` are wrapped as untrusted, and search hits carry `untrusted: true`. Citations name the mount, path, and revision. The Reviews tab lists unlabeled captures and proposed pages. Settings shows exclusion rules, the Presidio toggle (unless an admin removed it), and Always-allow rules with their scope. A permission card names the tool that is waiting.

## Retention

Chat history stays in the workspace until the person deletes it, or moves to the state directory when local history is on. Captures are kept until `sources.capture_retention_days` is greater than 0, in which case older files are deleted on the next source call. The audit log is not rotated. Snapshot copies and the live-page cache remain until removed from the state directory. Publish does not include `.workbench/`, the state directory, or files above `public`.

## What the deployer sets

The admin file chooses the profile, the providers, the egress hosts, whether public writes exist, whether the Presidio toggle is available and for which OS users, whether Review is mandatory, which graphs and sources may be used, and how long captures are kept. The enterprise template leaves remote mounts, sources, and public writes closed. Page declassification is not an admin switch. Filling those lists is an administrative act.

When Presidio is off, or not installed, the product does not analyze the text. The notice shown to the person is the sentence in [Licensing and IP](legal.md). The deployer who turns the toggle off, or who does not install the optional Presidio group, is the one who has accepted that the scan does not run.
