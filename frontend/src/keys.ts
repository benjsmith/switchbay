/**
 * Central keybinding registry (charter rule, decided 2026-07-03).
 *
 * One window keydown listener owns all app shortcuts, replacing the
 * scattered ad-hoc listeners. Two binding shapes:
 *
 *  · CHORD — the leader family: ⌘/Ctrl+K arms for 1.5 s, then a bare
 *    letter fires (`K then T` = thread picker, `K then W` = workspace
 *    switcher, `K then G` = cycle tab). While armed, a matching
 *    follow-up key is swallowed even when an input has focus, so the
 *    letter never types into the composer.
 *  · COMBO — direct modifier+key bindings (⌘J dashboard panel,
 *    ⌘1..9 tabs). Per the charter: only letters, digits and named
 *    keys — never punctuation (relocates/vanishes on non-US layouts;
 *    the legacy Ctrl+]/[ run-lane cycler in Rail predates the rule
 *    and is queued for migration).
 *
 * Components register in an effect and unregister via the returned
 * disposer; `listBindings()` feeds help surfaces.
 */

export type ChordBinding = {
  /** Bare key pressed after the ⌘/Ctrl+K leader (single letter/digit). */
  key: string;
  description: string;
  handler: () => void;
};

export type ComboBinding = {
  key: string;
  /** Accept either ⌘ or Ctrl (default true — cross-platform combos). */
  metaOrCtrl?: boolean;
  /** Require exactly meta (mac ⌘) / exactly ctrl instead. */
  meta?: boolean;
  ctrl?: boolean;
  description: string;
  handler: () => void;
};

const LEADER_WINDOW_MS = 1500;
const chordBindings = new Map<string, ChordBinding>();
const comboBindings = new Set<ComboBinding>();
let leaderAt = 0;
let installed = false;

function isModifierKey(key: string): boolean {
  return key === "Shift" || key === "Meta" || key === "Control" || key === "Alt";
}

function onKeyDown(ev: KeyboardEvent): void {
  const metaOrCtrl = ev.metaKey || ev.ctrlKey;
  // Leader: ⌘/Ctrl+K arms the chord window. preventDefault so the
  // browser's own K bindings (search bars) never see it.
  if (metaOrCtrl && !ev.altKey && !ev.shiftKey && (ev.key === "k" || ev.key === "K")) {
    ev.preventDefault();
    leaderAt = Date.now();
    // The command palette (D5) rides the leader: it opens on this
    // event and calls disarmLeader() to take over key handling —
    // chord letters still work inside it on an empty query, so
    // muscle memory survives.
    window.dispatchEvent(new CustomEvent("sy:leader"));
    return;
  }
  if (leaderAt) {
    if (isModifierKey(ev.key)) return; // stay armed through modifiers
    const armed = Date.now() - leaderAt < LEADER_WINDOW_MS;
    leaderAt = 0;
    if (armed && !ev.metaKey && !ev.ctrlKey && !ev.altKey) {
      const b = chordBindings.get(ev.key.toLowerCase());
      if (b) {
        // Swallow even inside inputs — the whole point of a leader
        // chord is that the follow-up letter is never literal text.
        ev.preventDefault();
        ev.stopPropagation();
        b.handler();
        return;
      }
    }
    // Unmatched follow-up falls through and behaves normally.
  }
  for (const b of comboBindings) {
    if (ev.key.toLowerCase() !== b.key.toLowerCase()) continue;
    if (ev.altKey) continue;
    const wantMetaOrCtrl = b.metaOrCtrl ?? (!b.meta && !b.ctrl);
    const ok = wantMetaOrCtrl
      ? metaOrCtrl
      : (b.meta ? ev.metaKey && !ev.ctrlKey : true) &&
        (b.ctrl ? ev.ctrlKey && !ev.metaKey : true) &&
        (b.meta || b.ctrl ? true : metaOrCtrl);
    if (!ok) continue;
    ev.preventDefault();
    b.handler();
    return;
  }
}

/** Install the single listener. Idempotent; returns an uninstaller
 *  (App calls this once — StrictMode double-mount safe). */
export function installKeyRegistry(): () => void {
  if (installed) return () => { /* second installer owns nothing */ };
  installed = true;
  window.addEventListener("keydown", onKeyDown);
  return () => {
    installed = false;
    window.removeEventListener("keydown", onKeyDown);
  };
}

export function registerChord(b: ChordBinding): () => void {
  const k = b.key.toLowerCase();
  chordBindings.set(k, b);
  return () => {
    if (chordBindings.get(k) === b) chordBindings.delete(k);
  };
}

export function registerCombo(b: ComboBinding): () => void {
  comboBindings.add(b);
  return () => {
    comboBindings.delete(b);
  };
}

/** Palette support: drop the armed chord window (the palette takes
 *  over key handling once it opens). */
export function disarmLeader(): void {
  leaderAt = 0;
}

/** Palette support: run a chord action by its letter. */
export function fireChord(key: string): boolean {
  const b = chordBindings.get(key.toLowerCase());
  if (!b) return false;
  b.handler();
  return true;
}

/** Palette support: the chord list with letters, for empty-query rows. */
export function listChords(): { key: string; description: string }[] {
  return [...chordBindings.entries()].map(([k, b]) => ({
    key: k,
    description: b.description,
  }));
}

/** For help surfaces: every live binding with a display label. */
export function listBindings(): { keys: string; description: string }[] {
  const out: { keys: string; description: string }[] = [];
  for (const [k, b] of chordBindings) {
    out.push({ keys: `⌘K ${k.toUpperCase()}`, description: b.description });
  }
  for (const b of comboBindings) {
    out.push({ keys: `⌘${b.key.toUpperCase()}`, description: b.description });
  }
  return out;
}
