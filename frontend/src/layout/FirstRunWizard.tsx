import { useEffect, useState } from "react";

/**
 * First-run wizard (D5): shown once per workspace when it has no
 * built wiki yet — the "how do you want to start?" moment. Three
 * paths: start clean (capture + chat build it up), point switchbay
 * at existing files (runs the bulk-ingest ARCHITECTURE SCAN — an
 * agent proposes how the material divides into workspaces before
 * anything is ingested), or watch a folder for new material.
 *
 * Deliberately a one-shot: dismissal is remembered per workspace
 * (localStorage); the rail's pinned "set up wiki" action and the
 * Settings panels remain the standing paths to everything offered
 * here.
 *
 * `ready` sequences this behind the first-install walkthrough — both
 * want the whole screen on a fresh machine, and this modal used to
 * open straight over the tour's first coach-mark. App holds it false
 * until the tour is neither pending nor running.
 */

type Props = {
  workspace: string;
  graphError: string | null;
  /** False while the first-install walkthrough is pending or running. */
  ready: boolean;
  onOpenSettings: () => void;
  onOpenHelp: () => void;
};

const doneKey = (ws: string) => `sy:wizard-done:${ws}`;

export default function FirstRunWizard({
  workspace, graphError, ready, onOpenSettings, onOpenHelp,
}: Props) {
  const [dismissed, setDismissed] = useState(true);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // Local-model offer (ruling 2026-07-05): on a fresh install, prompt
  // whether to set up the best local agent model for this machine —
  // one click, no further config (RAM decides quant/context).
  const [localOffer, setLocalOffer] = useState<{
    label: string; quant: string; est: number;
  } | null>(null);
  const [localState, setLocalState] = useState<"idle" | "starting" | "started">("idle");

  // Re-evaluate on workspace switch, and again when the walkthrough
  // releases the gate. Only a genuinely wiki-less workspace (CE viewer
  // reports "no wiki") triggers the wizard.
  useEffect(() => {
    if (!ready || !workspace || !graphError || !/no wiki/i.test(graphError)) {
      setDismissed(true);
      return;
    }
    try {
      setDismissed(localStorage.getItem(doneKey(workspace)) === "1");
    } catch {
      setDismissed(true);
    }
    setNote(null);
    // Offer the local model only when it's plannable and not yet
    // installed/installing on this machine.
    void fetch("/api/localllm/status")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (!b) return;
        const s = b as {
          plan: { ok: boolean; model_label?: string; quant?: string; est_gb?: number };
          config: unknown; install: { state?: string } | null;
        };
        if (s.plan.ok && !s.config && s.install?.state !== "running") {
          setLocalOffer({
            label: s.plan.model_label ?? "Ornith",
            quant: s.plan.quant ?? "",
            est: s.plan.est_gb ?? 0,
          });
        }
      })
      .catch(() => { /* older daemon */ });
  }, [ready, workspace, graphError]);

  const installLocal = async () => {
    if (localState !== "idle") return;
    setLocalState("starting");
    try {
      const r = await fetch("/api/localllm/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (r.ok) setLocalState("started");
      else setLocalState("idle");
    } catch {
      setLocalState("idle");
    }
  };

  const dismiss = () => {
    try { localStorage.setItem(doneKey(workspace), "1"); } catch { /* quota */ }
    setDismissed(true);
  };

  const pointAtFiles = async () => {
    if (busy) return;
    setBusy(true);
    setNote(null);
    try {
      const r = await fetch("/api/ingest/bulk-scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pick: true }),
      });
      const b = await r.json().catch(() => ({} as Record<string, unknown>));
      if ((b as { cancelled?: boolean }).cancelled) return;
      if (!r.ok) {
        setNote(String((b as { error?: string }).error ?? `HTTP ${r.status}`));
        return;
      }
      const runId = (b as { run_id?: string }).run_id;
      dismiss();
      if (runId) {
        window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
          detail: { run_id: runId },
        }));
      }
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (dismissed) return null;

  return (
    <div className="sy-confirm-backdrop">
      <div
        className="sy-confirm sy-wizard"
        role="dialog"
        aria-labelledby="sy-wizard-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="sy-wizard-title" className="sy-confirm-title">
          New workspace — how do you want to start?
        </div>
        <div className="sy-confirm-body">
          <button
            type="button"
            className="sy-wizard-card"
            onClick={dismiss}
            disabled={busy}
          >
            <span className="sy-wizard-card-title">Start clean</span>
            <span className="sy-wizard-card-body">
              Just talk to it. Chat in the rail; capture with{" "}
              <code>/note</code> · <code>/todo</code> · <code>/decision</code>;
              upload with the Browser's <code>+</code>. The wiki grows as the
              curator files what you feed it.
            </span>
          </button>
          <button
            type="button"
            className="sy-wizard-card"
            onClick={() => void pointAtFiles()}
            disabled={busy}
            aria-busy={busy}
          >
            <span className="sy-wizard-card-title">
              {busy ? "Scanning…" : "Point it at your files"}
            </span>
            <span className="sy-wizard-card-body">
              Choose a folder of existing material. An agent surveys the
              tree first (names only, nothing ingested) and proposes how it
              should divide into workspaces — you stay in charge of what
              actually gets ingested and what that costs.
            </span>
          </button>
          <button
            type="button"
            className="sy-wizard-card"
            onClick={() => { dismiss(); onOpenSettings(); }}
            disabled={busy}
          >
            <span className="sy-wizard-card-title">Watch a folder</span>
            <span className="sy-wizard-card-body">
              Auto-ingest whatever lands in a folder from now on (your
              downloads, a notes export…) — Settings → Watch folders.
            </span>
          </button>
          {localOffer && (
            <div className="sy-wizard-card sy-wizard-card--aside">
              <span className="sy-wizard-card-title">
                Local agent model{localState === "started" ? " — installing ✓" : ""}
              </span>
              <span className="sy-wizard-card-body">
                {localState === "started" ? (
                  <>Downloading in the background — a rail notice lands when
                  it's serving. Routine curation will use it automatically.</>
                ) : (
                  <>
                    This machine can run <b>{localOffer.label}</b>{" "}
                    ({localOffer.quant}, ~{localOffer.est} GB while serving) for
                    routine agent chores — saving your paid provider tokens for
                    planning and review.{" "}
                    <button
                      type="button"
                      className="sy-wizard-link"
                      onClick={(ev) => { ev.stopPropagation(); void installLocal(); }}
                      disabled={localState !== "idle"}
                    >
                      {localState === "starting" ? "starting…" : "Install it (one click, no config)"}
                    </button>
                  </>
                )}
              </span>
            </div>
          )}
          {note && <p className="sy-settings-status sy-settings-status--err">{note}</p>}
          <p className="sy-wizard-foot">
            Unfamiliar terms? <button type="button" className="sy-wizard-link" onClick={() => { onOpenHelp(); }}>Help → Glossary</button>.
            You can also set up an empty wiki any time via the rail's
            pinned action. This card won't show again for this workspace.
          </p>
        </div>
        <div className="sy-confirm-actions">
          <button type="button" className="sy-confirm-btn" onClick={dismiss} disabled={busy}>
            Skip for now
          </button>
        </div>
      </div>
    </div>
  );
}
