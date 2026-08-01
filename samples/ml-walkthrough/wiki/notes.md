---
title: "[con] Notes"
type: concept
created: 2026-04-22
updated: 2026-04-22
---

# Notes

The notes surface is where user-authored raw thinking lands — meeting recaps, phone calls, idea fragments, anything worth capturing without deciding upfront what it is. The curator picks up what's there and turns it into structured wiki content over time (wikilinks in place, entity / concept / fact / todo pages spawned).

## Flow

- **[[new]]** — default landing for `/note` without a topic cue. Drained by `sweep.py sync-notes` on each CURATE sweep. Transient — content doesn't stay here.
- **[[for-attention]]** — items the drain heuristic couldn't classify (no `[[wikilink]]`, no `topic:` cue). User adds `topic: <slug>` to route, or the curator-agent infers context during CURATE. Also transient.
- **`<topic>.md`** (e.g. `wiki/notes/acme.md`, `wiki/notes/project-goldeneye.md`) — topic aggregations. Notes sharing a `[[stem]]` collect here. Users can also create these directly via `/note topic: <name> ...`.

## Atomic-note format

Single-line (bullet) form:
```
- <content> [[wikilinks]] (created: YYYY-MM-DD) (note:N<id>)
```

Multi-line (heading) form:
```
## <first-few-words> (created: YYYY-MM-DD, note:N<id>)
<body paragraph with [[wikilinks]] and (vault:path) citations>
```

`[[wikilinks]]` inside a note drive routing (sweep picks the topic file from the first wikilink stem) AND discovery (the note appears on the linked entity's backlinks). Citations work exactly as on any other wiki page.

## Graph model

Each atomic note becomes a `Note` node in the kuzu graph with an id, content hash (for dedup), and created date. Every wiki page containing `(note:N<id>)` gets an `AppearsIn` edge from the Note. A single note can legitimately cross-appear in multiple topic files — a meeting note about project X and capability Y both carry the same note id with two `AppearsIn` edges.

## See also

- [[todos]] — priority-bucket to-dos, curator-managed.
- [[index|Wiki index]] — browse by page type.
