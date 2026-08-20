import { useEffect, useState } from "react";

/** "How Switch Bay works" help modal, opened from the top-bar ?-button.
 *  Reuses the .sy-confirm / .sy-settings modal chrome (backdrop, dialog,
 *  close button) so it matches Settings. Content is hand-written and
 *  must stay factually in sync with the data/query model — in
 *  particular the DuckDB-vs-Kuzu distinction, which is easy to get
 *  wrong: they do NOT interact. */

type VersionRow = {
  id: string;
  label: string;
  installed: boolean;
  current: string | null;
};

type Props = {
  open: boolean;
  onClose: () => void;
};

function versionLine(row: VersionRow): string {
  if (!row.installed) return `${row.label} not installed`;
  if (row.current) return `${row.label} ${row.current}`;
  return `${row.label} installed`;
}

export default function HelpModal({ open, onClose }: Props) {
  const [versions, setVersions] = useState<VersionRow[] | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetch("/api/versions")
      .then((r) => r.json())
      .then((body: { components?: VersionRow[] }) => {
        if (cancelled) return;
        const rows = Array.isArray(body.components) ? body.components : [];
        setVersions(rows);
      })
      .catch(() => {
        if (!cancelled) setVersions([]);
      });
    return () => { cancelled = true; };
  }, [open]);

  if (!open) return null;

  return (
    <div className="sy-confirm-backdrop" onClick={onClose}>
      <div
        className="sy-confirm sy-settings sy-help"
        role="dialog"
        aria-labelledby="sy-help-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="sy-help-title" className="sy-confirm-title">How Switch Bay works</div>
        <div className="sy-confirm-body sy-settings-body sy-help-body">

          <p>
            Switch Bay is a workbench over a <strong>curiosity-engine</strong> (CE)
            knowledge base. <strong>Power</strong> mode is three columns: the
            <strong> Browser</strong> (left, your files), the <strong>Tabs</strong>
            {" "}(centre — Graph, Editor, Table, Sheet, Plot, Sketch, Library,
            Projects, Agents, plus any custom tabs you pin), and the
            <strong> Rail</strong> (right, chat and commands). <strong>Zen</strong> mode
            is graph-first with one surface and floating chat — toggle the face
            icon at the bottom of the Browser. One workspace = one folder with a
            <code> vault/</code> of raw sources and a <code>wiki/</code> of
            markdown pages.
          </p>

          <h4>The Rail — what you can type</h4>
          <p>The prefix on the first character decides where your input goes:</p>
          <dl className="sy-help-dl">
            <dt>(no prefix)</dt>
            <dd>Chat with the agent (the model picked in the Rail header).</dd>
            <dt><code>!</code> <span className="sy-help-dim">command</span></dt>
            <dd>Run a shell command in the workspace — opens a new shell <em>thread</em> (the rail becomes an interactive terminal; switch back via the thread bar).</dd>
            <dt><code>!py</code></dt>
            <dd>Open a Python REPL (<code>python3 -i</code>) in the workspace.</dd>
            <dt><code>!sql </code><span className="sy-help-dim">query</span></dt>
            <dd>Run SQL in the <strong>Table</strong> tab (DuckDB — see below) and switch to it.</dd>
            <dt><code>!fn </code><span className="sy-help-dim">formula</span></dt>
            <dd>Drop a spreadsheet formula into the active cell of the <strong>Sheet</strong> tab (<code>!exc</code> is a legacy alias). The rail agent can also write formulas via <code>sheet_set_formula</code> (same path) when you ask in natural language.</dd>
            <dt><code>/micro-edits</code></dt>
            <dd>
              Small Sheet / Sketch / Table / Plot edits use a faster ladder
              rung (default <code>trivial</code>). Status:{" "}
              <code>/micro-edits</code>. Set rung:{" "}
              <code>/micro-edits trivial|normal|hard</code> or{" "}
              <code>/micro-edits global normal</code>. Models per rung:
              Settings → Model ladder.
            </dd>
            <dt><code>/name </code><span className="sy-help-dim">args</span></dt>
            <dd>A slash command (e.g. <code>/plot</code>, <code>/sketch</code>, <code>/viewer</code>, <code>/rescan</code>, <code>/curate</code>, <code>/walkthrough</code>). Type <code>/</code> to autocomplete the list.</dd>
          </dl>

          <h4>The Table tab — DuckDB</h4>
          <p>
            The Table tab is <strong>DuckDB-WASM running in your browser</strong> — full
            DuckDB SQL (CTEs, joins, aggregates). It can query:
          </p>
          <ul className="sy-help-ul">
            <li>
              <strong>Workspace files</strong> — CSV / Parquet / JSON read straight off
              disk through the daemon, e.g.<br />
              <code>SELECT * FROM read_csv_auto('/api/fs/raw?path=vault/data.csv') LIMIT 50;</code><br />
              (find a file in the Browser, right-click → <em>Copy path</em>, paste it after <code>path=</code>).
            </li>
            <li>
              <strong>SQLite / DuckDB databases</strong> — click one and it attaches.
              DuckDB files attach natively; a SQLite file whose extensions DuckDB can't
              load (vec0, FTS5, …) transparently falls back to the daemon's own
              <code> sqlite3</code> (the <code>/api/db/*</code> endpoints) — same UI either way.
            </li>
            <li>
              <strong>Two ready-made tables</strong> seeded for every workspace:
              <code> files</code> (every visible file — path, size, mtime, ext) and
              <code> pages</code> (one row per knowledge-graph node — <code>id, path, type,
              title, degree</code>). Example:<br />
              <code>SELECT type, count(*) FROM pages GROUP BY type ORDER BY 2 DESC;</code>
            </li>
          </ul>

          <h4>The Graph, and where Kuzu fits in</h4>
          <p>
            The Graph tab is CE's knowledge-graph viewer. CE builds the graph with an
            embedded <strong>Kuzu graph database</strong> (stored under the workspace's
            <code> .curator/</code>), then exports it to a <code>data.json</code> of nodes +
            edges that the viewer renders. You explore it <strong>visually</strong> —
            pan, click a node to open its page. After editing the wiki, press
            <strong> rebuild viewer</strong> (or run <code>/viewer</code>) to re-run the
            Kuzu build and refresh the graph. If the Browser still shows deleted
            pages or stale folders, run <code>/rescan</code> for a cold rebuild.
          </p>
          <p className="sy-help-note">
            <strong>Kuzu and the Table tab are separate systems.</strong> Kuzu is CE's
            internal graph engine — it is <em>not</em> exposed as a query surface in
            switchbay. The Table tab's <code>pages</code> table reflects the graph's
            <em> nodes</em> (metadata only — including each node's <code>degree</code>, its
            edge count), but it has no edges and no graph traversal: you can't write
            Kuzu/Cypher queries or follow relationships in SQL. DuckDB = tabular SQL over
            your files; Kuzu = the graph behind the picture.
          </p>
          <p>
            <strong>Asking a question searches the graph.</strong> The graph isn't
            only something you look at. The bundled <strong>curiosity-engine</strong>
            skill gives the Rail agent a <em>query mode</em>: when you chat a question
            (no prefix), it searches the wiki + knowledge graph — following links and
            pulling in related pages — to ground its answer, alongside the
            conversation-history recall. So you query the graph in plain language by
            just asking; the agent does the traversal (you don't write Cypher).
          </p>

          <h4>Glossary</h4>
          <dl className="sy-help-dl">
            <dt>workspace</dt>
            <dd>One folder = one knowledge base. Everything below lives inside it; switch or add workspaces from the top-bar name.</dd>
            <dt>vault</dt>
            <dd>The workspace's <code>vault/</code> of raw originals — files you uploaded, dropped, or that arrived via streams. Raw material in, nothing edited here.</dd>
            <dt>wiki</dt>
            <dd>The <code>wiki/</code> of markdown pages the curator distills OUT of the vault and your conversations — the part that's organized, linked, and searchable.</dd>
            <dt>page / node</dt>
            <dd>One markdown file in the wiki = one node in the Graph. Types: source, note, concept, entity, fact, analysis…</dd>
            <dt>curator</dt>
            <dd>The background agent pass that files new material into the wiki — classifying, linking, deduping. Steer it per-workspace in Settings → Curator profile.</dd>
            <dt>thread</dt>
            <dd>One conversation (or one terminal) in the Rail. Switch threads from the bar under the Rail header; each keeps its own context.</dd>
            <dt>run</dt>
            <dd>One dispatch of an agent inside a thread — what the Agents panel at the bottom tracks live.</dd>
            <dt>sources / provenance</dt>
            <dd>Where a wiki page came from (<code>extracted_from</code>). The Browser's bottom pane has a Sources view of external origins; extracted pages show a "from …" chip.</dd>
            <dt>watch folder</dt>
            <dd>An outside directory Switch Bay polls; new files auto-ingest into the vault + wiki (Settings → Watch folders).</dd>
            <dt>skill / pack</dt>
            <dd>A skill is an instruction bundle agents load for a task; a pack bundles skills + tabs + file actions as an installable extension.</dd>
          </dl>

        </div>
        <div className="sy-confirm-actions sy-help-footer">
          <div className="sy-help-versions" aria-label="Installed versions">
            {versions === null
              ? <span className="sy-help-dim">versions…</span>
              : versions.length === 0
                ? null
                : versions.map((row) => (
                    <div key={row.id}>{versionLine(row)}</div>
                  ))}
          </div>
          <button type="button" className="sy-confirm-btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
