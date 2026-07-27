import { useEffect, useState } from "react";

/** A skill row from /api/skills. `writable` marks the two user-owned
 *  scopes (workspace / user); built-ins (ce / pack) are read-only. */
export type SkillSummary = {
  name: string;
  description: string;
  when_to_use: string;
  source: string;
  path: string;
  writable?: boolean;
  health?: "ok" | "warn" | "fail";
};

type FullSkill = SkillSummary & { body?: string };

type Diag = { level: "ok" | "warn" | "fail"; code: string; message: string };
type Explain = {
  diagnostics: Diag[];
  health: "ok" | "warn" | "fail";
  match: { would_fire?: boolean; reason?: string; model?: string; error?: string } | null;
  suggestion: { description: string } | null;
};

type Draft = {
  mode: "new" | "edit";
  scope: "workspace" | "user";
  origName: string;   // for edit: the name we're updating
  name: string;
  description: string;
  body: string;
};

const EMPTY_DRAFT: Draft = {
  mode: "new", scope: "workspace", origName: "",
  name: "", description: "", body: "",
};

/** Skills panel with local-first authoring: list + New / Edit / Delete /
 *  Promote, plus "Save this thread as a skill". Read-only built-ins show
 *  their trigger; user skills are editable inline. Nothing here ever
 *  fetches a skill from the web — authoring is deliberately local. */
export default function SkillsPanel(props: { focusedThreadId?: string | null }) {
  const [skills, setSkills] = useState<SkillSummary[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [explainFor, setExplainFor] = useState<string | null>(null);
  const [explain, setExplain] = useState<Explain | null>(null);
  const [example, setExample] = useState("");
  const [testing, setTesting] = useState(false);

  const refresh = () =>
    fetch("/api/skills")
      .then((r) => r.json())
      .then((b) => setSkills(b.skills as SkillSummary[]))
      .catch(() => setSkills([]));

  useEffect(() => { refresh(); }, []);

  const startEdit = async (s: SkillSummary) => {
    setMsg(null);
    const r = await fetch(`/api/skill?name=${encodeURIComponent(s.name)}`);
    const b = await r.json();
    const full = (b.skill ?? {}) as FullSkill;
    setDraft({
      mode: "edit", scope: s.source === "user" ? "user" : "workspace",
      origName: s.name, name: s.name,
      description: full.description ?? s.description,
      body: full.body ?? "",
    });
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true); setMsg(null);
    try {
      const url = draft.mode === "new" ? "/api/skills/create" : "/api/skills/update";
      const payload = draft.mode === "new"
        ? { scope: draft.scope, name: draft.name, description: draft.description, body: draft.body }
        : { name: draft.origName, description: draft.description, body: draft.body };
      const r = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const b = await r.json();
      if (!r.ok) { setMsg({ ok: false, text: b.error || `HTTP ${r.status}` }); return; }
      setMsg({ ok: true, text: draft.mode === "new" ? "skill created" : "skill saved" });
      setDraft(null);
      await refresh();
    } finally { setBusy(false); }
  };

  const act = async (path: string, name: string, okText: string) => {
    setBusy(true); setMsg(null);
    try {
      const r = await fetch(path, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const b = await r.json();
      if (!r.ok) { setMsg({ ok: false, text: b.error || `HTTP ${r.status}` }); return; }
      setMsg({ ok: true, text: okText });
      await refresh();
    } finally { setBusy(false); }
  };

  const del = (s: SkillSummary) => {
    if (!window.confirm(`Delete skill "${s.name}"? This removes its SKILL.md.`)) return;
    void act("/api/skills/delete", s.name, "skill deleted");
  };

  const openExplain = async (s: SkillSummary, request?: string) => {
    setExplainFor(s.name);
    if (request === undefined) { setExplain(null); setExample(""); }
    if (request) setTesting(true);
    try {
      const r = await fetch("/api/skills/explain", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: s.name, request: request ?? "" }),
      });
      if (r.ok) setExplain(await r.json() as Explain);
    } finally { setTesting(false); }
  };

  const applySuggestion = async (s: SkillSummary, description: string) => {
    setBusy(true); setMsg(null);
    try {
      // Preserve the body; only swap the trigger/description.
      const cur = await (await fetch(`/api/skill?name=${encodeURIComponent(s.name)}`)).json();
      const body = (cur.skill?.body as string) ?? "";
      const r = await fetch("/api/skills/update", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: s.name, description, body }),
      });
      if (!r.ok) { const b = await r.json(); setMsg({ ok: false, text: b.error }); return; }
      setMsg({ ok: true, text: "trigger updated" });
      await refresh();
      await openExplain(s, example || undefined);
    } finally { setBusy(false); }
  };

  const publish = async (s: SkillSummary) => {
    const priv = !window.confirm(
      `Publish "${s.name}" to GitHub?\n\nOK = PUBLIC (installable by anyone via npx skills add), Cancel = private.`);
    setBusy(true); setMsg(null);
    try {
      const r = await fetch("/api/skills/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: s.name, private: priv }),
      });
      const b = await r.json();
      setMsg(r.ok ? { ok: true, text: `published → ${b.url}` } : { ok: false, text: b.error });
    } finally { setBusy(false); }
  };

  const openInEditor = async (s: SkillSummary) => {
    const r = await fetch("/api/skill/open-in-editor", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: s.name }),
    });
    if (!r.ok) { const b = await r.json(); setMsg({ ok: false, text: b.error }); }
  };

  const saveThread = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await fetch("/api/skills/from-thread", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: props.focusedThreadId || undefined }),
      });
      const b = await r.json();
      setMsg(r.ok
        ? { ok: true, text: "drafting a skill from this thread — it'll appear when the run finishes" }
        : { ok: false, text: b.error || `HTTP ${r.status}` });
    } finally { setBusy(false); }
  };

  return (
    <div className="sy-skills">
      <div className="sy-skills-actions">
        <button type="button" className="sy-skills-btn" disabled={busy}
          onClick={() => { setMsg(null); setDraft({ ...EMPTY_DRAFT }); }}>
          + New skill
        </button>
        <button type="button" className="sy-skills-btn" disabled={busy}
          onClick={() => void saveThread()}
          title="Distill the current thread's workflow into a reusable, private skill">
          ⤓ Save this thread as a skill
        </button>
        {msg && (
          <span className={"sy-skills-msg" + (msg.ok ? "" : " sy-skills-msg--err")}>
            {msg.text}
          </span>
        )}
      </div>

      {draft && (
        <div className="sy-skills-editor">
          <div className="sy-skills-editrow">
            <input className="sy-skills-input" placeholder="skill-name (kebab-case)"
              value={draft.name} disabled={draft.mode === "edit"}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            {draft.mode === "new" && (
              <select className="sy-skills-input sy-skills-scope" value={draft.scope}
                onChange={(e) => setDraft({ ...draft, scope: e.target.value as Draft["scope"] })}>
                <option value="workspace">workspace (private)</option>
                <option value="user">personal (all workspaces)</option>
              </select>
            )}
          </div>
          <input className="sy-skills-input" placeholder="description — start with 'Use when …' so it auto-triggers"
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
          <textarea className="sy-skills-body" rows={8}
            placeholder="SKILL.md body — numbered steps / rules the agent should follow"
            value={draft.body}
            onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
          <div className="sy-skills-editactions">
            <button type="button" className="sy-skills-btn sy-skills-btn--primary"
              disabled={busy || !draft.name.trim() || !draft.body.trim()}
              onClick={() => void save()}>
              {busy ? "Saving…" : draft.mode === "new" ? "Create" : "Save"}
            </button>
            <button type="button" className="sy-skills-btn" disabled={busy}
              onClick={() => setDraft(null)}>Cancel</button>
          </div>
        </div>
      )}

      {skills === null ? (
        <div className="sy-agents-empty">Loading…</div>
      ) : skills.length === 0 ? (
        <div className="sy-agents-empty">
          No skills yet. <code>+ New skill</code> or save a thread as one.
        </div>
      ) : (
        <ul className="sy-agents-list">
          {skills.map((s) => (
            <li key={`${s.source}:${s.name}`} className="sy-agents-row sy-skills-litem">
              <div className="sy-skills-rowmain">
                <code className="sy-agents-name">{s.name}</code>
                <span className="sy-agents-cat">{s.source}</span>
                {s.health && s.health !== "ok" && (
                  <span className={"sy-skills-health sy-skills-health--" + s.health}
                    title={s.health === "fail" ? "won't be discovered / fire" : "trigger may be weak — click Why?"}>
                    ⚠
                  </span>
                )}
                <span className="sy-agents-desc">{s.when_to_use || s.description}</span>
                <span className="sy-skills-rowbtns">
                  <button type="button" className="sy-skills-mini" disabled={busy}
                    title="Why won't this skill fire?"
                    onClick={() => void (explainFor === s.name ? setExplainFor(null) : openExplain(s))}>
                    Why?
                  </button>
                  {s.writable && (
                    <>
                      <button type="button" className="sy-skills-mini" disabled={busy}
                        onClick={() => void startEdit(s)}>Edit</button>
                      {s.source === "workspace" && (
                        <button type="button" className="sy-skills-mini" disabled={busy}
                          title="Open the SKILL.md in the Editor tab"
                          onClick={() => void openInEditor(s)}>↗ Editor</button>
                      )}
                      {s.source === "workspace" && (
                        <button type="button" className="sy-skills-mini" disabled={busy}
                          title="Move to your personal skills (available in every workspace)"
                          onClick={() => void act("/api/skills/promote", s.name, "promoted to personal")}>
                          ↑ Personal
                        </button>
                      )}
                      <button type="button" className="sy-skills-mini" disabled={busy}
                        title="Publish to GitHub (npx skills add)"
                        onClick={() => void publish(s)}>Publish</button>
                      <button type="button" className="sy-skills-mini sy-skills-mini--del"
                        disabled={busy} onClick={() => del(s)}>Delete</button>
                    </>
                  )}
                </span>
              </div>
              {explainFor === s.name && (
                <div className="sy-skills-explain">
                  {explain?.diagnostics.map((d, i) => (
                    <div key={i} className={"sy-skills-diag sy-skills-diag--" + d.level}>
                      {d.level === "ok" ? "✓" : d.level === "warn" ? "⚠" : "✕"} {d.message}
                    </div>
                  ))}
                  <div className="sy-skills-explaintest">
                    <input className="sy-skills-input" placeholder="type a request you expected this to handle…"
                      value={example} disabled={testing} onChange={(e) => setExample(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && example.trim()) void openExplain(s, example.trim()); }} />
                    <button type="button" className="sy-skills-mini" disabled={!example.trim() || testing}
                      onClick={() => void openExplain(s, example.trim())}>
                      {testing ? "Testing…" : "Test"}
                    </button>
                  </div>
                  {testing && <div className="sy-skills-diag sy-skills-diag--ok">⏳ checking against the model…</div>}
                  {explain?.match && (
                    explain.match.error ? (
                      <div className="sy-skills-diag sy-skills-diag--warn">⚠ {explain.match.error}</div>
                    ) : (
                      <div className={"sy-skills-diag sy-skills-diag--" + (explain.match.would_fire ? "ok" : "fail")}>
                        {explain.match.would_fire ? "✓ would fire" : "✕ would NOT fire"}
                        {explain.match.reason ? ` — ${explain.match.reason}` : ""}
                        {explain.match.model ? ` (${explain.match.model})` : ""}
                      </div>
                    )
                  )}
                  {explain?.suggestion && s.writable && (
                    <div className="sy-skills-suggest">
                      <span>Suggested trigger: <em>{explain.suggestion.description}</em></span>
                      <button type="button" className="sy-skills-mini" disabled={busy}
                        onClick={() => void applySuggestion(s, explain.suggestion!.description)}>Apply</button>
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
