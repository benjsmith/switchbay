/**
 * Light/dark theme persistence. Ported from
 * curiosity-engine/template/wiki-view/static/theme.js so we keep the
 * same `:root[data-theme="…"]` mechanism. The initial theme is applied
 * before React mounts (see main.tsx) to avoid a flash of the wrong
 * palette.
 */

const KEY = "switchbay.theme";
export type Theme = "dark" | "light";

export function initialTheme(): Theme {
  const stored = localStorage.getItem(KEY) as Theme | null;
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem(KEY, t);
}

export function currentTheme(): Theme {
  const t = document.documentElement.dataset.theme;
  return t === "light" ? "light" : "dark";
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}
