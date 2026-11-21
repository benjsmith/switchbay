import { useCallback, useEffect, useState } from "react";

type Rule = { id: string; description: string; decision: "allow" | "ask" | "deny" };
type PublicRule = { id: string; description: string; decision: string; scope: string };

export function SessionBadge() {
  const [label, setLabel] = useState("public");
  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/session/label");
      if (!r.ok) return;
      const body = (await r.json()) as { label?: string };
      setLabel(body.label || "public");
    } catch { /* the badge stays public when the route is absent */ }
  }, []);
  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(id);
  }, [load]);
  if (!label || label === "public") return null;
  return (
    <span className="sy-class-badge" data-label={label} title="This chat uses content at this label">
      {label}
    </span>
  );
}

export function ExclusionRules() {
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [text, setText] = useState("");
  const [decision, setDecision] = useState<Rule["decision"]>("deny");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/exclusion-rules");
      if (!r.ok) return;
      const body = (await r.json()) as { rules?: Rule[] };
      setRules(body.rules ?? []);
    } catch { /* leave the previous list */ }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const save = async (next: Rule[]) => {
    const r = await fetch("/api/exclusion-rules", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules: next }),
    });
    if (!r.ok) {
      setNote("Could not save the rules.");
      return;
    }
    const body = (await r.json()) as { rules?: Rule[] };
    setRules(body.rules ?? next);
    setText("");
  };

  return (
    <div className="sy-exclusion" data-testid="exclusion-rules">
      <p className="sy-settings-blurb">
        Actions you may take that the agent should not. Each line is
        allow, ask, or deny. The agent is told these rules outrank the
        conversation, including any line that says to ignore previous
        instructions. That relies on the model. A later check can
        confirm each action before it runs.
      </p>
      {note && <p className="sy-settings-status sy-settings-status--err">{note}</p>}
      <ul className="sy-settings-perm-list">
        {(rules ?? []).map((rule) => (
          <li key={rule.id} className="sy-settings-perm-row">
            <span className="sy-class-badge" data-label={rule.decision}>{rule.decision}</span>
            <span>{rule.description}</span>
            <span className="sy-spacer" />
            <button type="button" className="sy-confirm-btn" onClick={() => void save((rules ?? []).filter((item) => item.id !== rule.id))}>
              Remove
            </button>
          </li>
        ))}
      </ul>
      <div className="sy-settings-perm-row">
        <input
          aria-label="Exclusion rule"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Describe an action"
        />
        <select aria-label="Rule decision" value={decision} onChange={(e) => setDecision(e.target.value as Rule["decision"])}>
          <option value="allow">Allow</option>
          <option value="ask">Ask</option>
          <option value="deny">Deny</option>
        </select>
        <button type="button" className="sy-confirm-btn" disabled={!text.trim()} onClick={() => void save([...(rules ?? []), { id: "", description: text.trim(), decision }])}>
          Add
        </button>
      </div>
    </div>
  );
}

export function PresidioSetting() {
  const [enabled, setEnabled] = useState(true);
  const [mayToggle, setMayToggle] = useState(true);
  const [guidance, setGuidance] = useState("");
  const [rules, setRules] = useState<PublicRule[]>([]);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/public-write");
      if (!r.ok) return;
      const body = (await r.json()) as {
        presidio_enabled?: boolean;
        user_may_toggle?: boolean;
        guidance?: string;
        rules?: PublicRule[];
      };
      setEnabled(body.presidio_enabled !== false);
      setMayToggle(body.user_may_toggle !== false);
      setGuidance(body.guidance || "");
      setRules(body.rules ?? []);
    } catch { /* settings still render */ }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const toggle = async () => {
    const r = await fetch("/api/public-write/presidio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !enabled }),
    });
    const body = await r.json().catch(() => ({} as { guidance?: string; error?: string; enabled?: boolean }));
    if (!r.ok) {
      setGuidance(body.error || "An admin controls this.");
      return;
    }
    if (typeof body.enabled === "boolean") setEnabled(body.enabled);
    if (body.guidance) setGuidance(body.guidance);
    await load();
  };

  const move = async (id: string, scope: string) => {
    await fetch("/api/public-write/scope", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, scope }),
    });
    await load();
  };

  return (
    <div data-testid="presidio-setting">
      <div className="sy-settings-perm-row">
        <span>
          <strong>Presidio scan:</strong>{" "}
          {enabled
            ? "on for public writes"
            : "off — you are responsible for personal data and the rules that apply"}
        </span>
        <span className="sy-spacer" />
        <button type="button" className="sy-confirm-btn" disabled={!mayToggle} onClick={() => void toggle()}>
          {enabled ? "Turn off" : "Turn on"}
        </button>
      </div>
      {!enabled && guidance && <p className="sy-settings-blurb">{guidance}</p>}
      {rules.map((rule) => (
        <div key={rule.id} className="sy-settings-perm-row" data-scope={rule.scope}>
          <span>{rule.description}</span>
          <span className="sy-class-badge" data-label={rule.scope}>{rule.scope}</span>
          {rule.scope === "global" && (
            <button type="button" className="sy-confirm-btn" onClick={() => void move(rule.id, "workspace")}>
              This workspace only
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

export function PublicWriteDialog() {
  const [open, setOpen] = useState(false);
  const [mount, setMount] = useState("");

  useEffect(() => {
    const onOpen = (ev: Event) => {
      const detail = (ev as CustomEvent).detail as { mount?: string } | undefined;
      setMount(detail?.mount || "");
      setOpen(true);
    };
    window.addEventListener("sy:public-write", onOpen);
    return () => window.removeEventListener("sy:public-write", onOpen);
  }, []);

  if (!open) return null;
  const choose = async (choice: string) => {
    await fetch("/api/public-write/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choice, mount }),
    });
    setOpen(false);
    window.dispatchEvent(new CustomEvent("sy:public-write-done", { detail: { choice } }));
  };
  return (
    <div className="sy-confirm-backdrop" data-testid="public-write-dialog">
      <div className="sy-confirm" role="dialog" aria-labelledby="sy-public-write-title">
        <div id="sy-public-write-title" className="sy-confirm-title">Public write</div>
        <div className="sy-confirm-body">
          <p>
            Presidio is not scanning this write. Continue only if the text
            has no personal data. You take responsibility for that.
          </p>
        </div>
        <div className="sy-confirm-actions">
          <button type="button" className="sy-confirm-btn sy-confirm-btn--primary" onClick={() => void choose("ok")}>OK</button>
          <button type="button" className="sy-confirm-btn" onClick={() => void choose("always")}>Always allow</button>
          <button type="button" className="sy-confirm-btn" onClick={() => void choose("cancel")}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
