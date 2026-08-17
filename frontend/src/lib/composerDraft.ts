import { useState, type Dispatch, type SetStateAction } from "react";

/** Unsent composer text. Shared by the Power rail and Zen chat box
 *  so a half-written prompt survives a mode switch (and a reload). */
const KEY = "sy:composer-draft";

function read(): string {
  try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; }
}

function write(text: string): void {
  try {
    if (text) localStorage.setItem(KEY, text);
    else localStorage.removeItem(KEY);
  } catch { /* quota / private mode */ }
}

export function useComposerDraft(): [string, Dispatch<SetStateAction<string>>] {
  const [input, setInput] = useState(read);
  const setDraft: Dispatch<SetStateAction<string>> = (value) => {
    setInput((cur) => {
      const next = typeof value === "function" ? value(cur) : value;
      write(next);
      return next;
    });
  };
  return [input, setDraft];
}
