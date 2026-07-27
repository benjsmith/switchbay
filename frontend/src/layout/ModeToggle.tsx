import { useEffect, useState } from "react";

/**
 * Power ↔ Zen UI-mode switcher (charter: Zen mode). Drawn in the same
 * grey-outline icon style as the theme toggle: a focused face (eyes
 * open, alert) for Power mode — the 3-column layout — and a
 * meditating face (eyes closed, calm) for Zen mode (graph left,
 * one surface right, floating chat box).
 *
 * The choice is a per-browser global (localStorage) and is announced
 * via the `sy:ui-mode` window event so App can flip the shell without
 * a reload. Rendered in the Power sidebar footer AND in Zen's
 * floating chrome — both instances stay in sync through the event.
 */

export type UiMode = "power" | "zen";

export const UI_MODE_KEY = "sy:ui-mode";

export function readUiMode(): UiMode {
  try {
    return localStorage.getItem(UI_MODE_KEY) === "zen" ? "zen" : "power";
  } catch {
    return "power";
  }
}

export default function ModeToggle() {
  const [mode, setMode] = useState<UiMode>(readUiMode);
  useEffect(() => {
    try { localStorage.setItem(UI_MODE_KEY, mode); } catch { /* quota */ }
  }, [mode]);
  // Track flips from the other instance (power sidebar ↔ zen chrome).
  useEffect(() => {
    const onMode = (ev: Event) => {
      const m = (ev as CustomEvent<{ mode?: UiMode }>).detail?.mode;
      if (m === "power" || m === "zen") setMode(m);
    };
    window.addEventListener("sy:ui-mode", onMode);
    return () => window.removeEventListener("sy:ui-mode", onMode);
  }, []);

  const flip = () => {
    const next: UiMode = mode === "power" ? "zen" : "power";
    // Persist SYNCHRONOUSLY: the dispatch below swaps the shell, which
    // unmounts this very instance — the [mode] effect would never run
    // and localStorage would go stale (icon + reload then disagree
    // with the live shell).
    try { localStorage.setItem(UI_MODE_KEY, next); } catch { /* quota */ }
    setMode(next);
    window.dispatchEvent(new CustomEvent("sy:ui-mode", { detail: { mode: next } }));
  };

  return (
    <button
      type="button"
      className="sy-icon-btn"
      title={mode === "power"
        ? "Switch to Zen mode — graph + one surface + floating chat"
        : "Switch to Power mode — the full 3-column workbench"}
      aria-label="Toggle Power / Zen mode"
      data-tour="mode-toggle"
      onClick={flip}
    >
      {mode === "power" ? (
        // Focused face — eyes open, alert brows, set mouth.
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <circle
            cx="8" cy="8" r="6.2"
            fill="none" stroke="currentColor" strokeWidth="1.2"
          />
          <g stroke="currentColor" strokeWidth="1.1" strokeLinecap="round">
            <line x1="4.6" y1="5.4" x2="6.6" y2="6" />
            <line x1="11.4" y1="5.4" x2="9.4" y2="6" />
            <line x1="6" y1="10.8" x2="10" y2="10.8" />
          </g>
          <circle cx="5.7" cy="7.9" r="0.95" fill="currentColor" />
          <circle cx="10.3" cy="7.9" r="0.95" fill="currentColor" />
        </svg>
      ) : (
        // Meditating face — closed-eye arcs, serene smile.
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <circle
            cx="8" cy="8" r="6.2"
            fill="none" stroke="currentColor" strokeWidth="1.2"
          />
          <g stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" fill="none">
            <path d="M4.6 7.4 q1.1 1.1 2.2 0" />
            <path d="M9.2 7.4 q1.1 1.1 2.2 0" />
            <path d="M5.9 10.4 q2.1 1.5 4.2 0" />
          </g>
        </svg>
      )}
    </button>
  );
}
