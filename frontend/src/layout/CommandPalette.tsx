import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { TabSpec, Workspaces } from "../ws";
import { disarmLeader, fireChord, listChords } from "../keys";

/**
 * ⌘K command palette (D5 — the novice's escape hatch): one place to
 * type a workspace, thread, tab, or slash command. Rides the leader
 * chord — opening on ⌘K itself — while keeping chord muscle memory:
 * with an EMPTY query, the chord letters (T/W/G/…) fire their
 * original actions; once you type, they're just text.
 *
 * Sections are built lazily on open: tabs + workspaces from props,
 * threads + slash verbs fetched fresh (both are small lists).
 */

type Item = {
  section: "action" | "tab" | "thread" | "workspace" | "command" | "page";
  label: string;
  hint?: string;
  run: () => void;
};

type ThreadRow = { thread_id: string; title: string | null; kind: string };

type Props = {
  tabs: TabSpec[];
  activeTab: string | null;
  setActiveTab: (id: string) => void;
  workspaces: Workspaces;
  onSwitchThread: (threadId: string, kind: string) => void;
  /** Wiki pages for the fuzzy list (D5 + Zen ruling: page find lives
   *  here). Opened via onOpenPage — Power shows the graph doc modal,
   *  Zen the right-pane Editor; App decides. */
  pages?: { id: string; title: string }[];
  onOpenPage?: (id: string) => void;
  /** Prepended one-off entries (e.g. Zen's "latest artifact" while
   *  one is pending). */
  extra?: { label: string; hint?: string; run: () => void }[];
};

function basename(p: string): string {
  return p.split("/").filter(Boolean).pop() ?? p;
}

export default function CommandPalette({
  tabs, activeTab, setActiveTab, workspaces, onSwitchThread,
  pages, onOpenPage, extra,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const [threads, setThreads] = useState<ThreadRow[]>([]);
  const [verbs, setVerbs] = useState<{ name: string; description: string }[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onLeader = () => {
      disarmLeader();
      setQuery("");
      setIndex(0);
      setOpen(true);
    };
    window.addEventListener("sy:leader", onLeader);
    return () => window.removeEventListener("sy:leader", onLeader);
  }, []);

  // Fresh thread + verb lists each open (cheap; always current).
  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    void fetch("/api/threads")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (b) setThreads((b as { threads: ThreadRow[] }).threads ?? []);
      })
      .catch(() => { /* daemon down */ });
    void fetch("/api/verbs")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (b) {
          setVerbs(((b as {
            verbs: { name: string; description?: string }[];
          }).verbs ?? []).map((v) => ({
            name: v.name,
            description: v.description ?? "",
          })));
        }
      })
      .catch(() => { /* older daemon */ });
  }, [open]);

  const close = useCallback(() => setOpen(false), []);

  const items = useMemo<Item[]>(() => {
    if (!open) return [];
    const out: Item[] = [];
    for (const x of extra ?? []) {
      out.push({ section: "action", label: x.label, hint: x.hint, run: x.run });
    }
    for (const c of listChords()) {
      out.push({
        section: "action",
        label: c.description,
        hint: `⌘K ${c.key.toUpperCase()}`,
        run: () => { fireChord(c.key); },
      });
    }
    for (const t of tabs) {
      out.push({
        section: "tab",
        label: `Tab: ${t.title}`,
        hint: t.id === activeTab ? "current" : t.kind,
        run: () => setActiveTab(t.id),
      });
    }
    for (const th of threads) {
      out.push({
        section: "thread",
        label: `Thread: ${th.title || th.thread_id.slice(0, 8)}`,
        hint: th.kind === "interactive-pty" ? "shell" : "chat",
        run: () => onSwitchThread(th.thread_id, th.kind),
      });
    }
    for (const p of workspaces.paths) {
      out.push({
        section: "workspace",
        label: `Workspace: ${basename(p)}`,
        hint: p === workspaces.active ? "current" : undefined,
        run: () => {
          if (p === workspaces.active) return;
          void fetch("/api/workspaces/switch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: p }),
          });
        },
      });
    }
    for (const v of verbs) {
      out.push({
        section: "command",
        label: `/${v.name}`,
        hint: v.description.slice(0, 60),
        run: () => {
          window.dispatchEvent(new CustomEvent("sy:rail-system-tip", {
            detail: { text: `/${v.name} `, focus: true },
          }));
        },
      });
    }
    // Pages LAST so they never swamp the action/tab/thread rows on an
    // empty query — the fuzzy filter surfaces them once typed.
    if (onOpenPage) {
      for (const p of pages ?? []) {
        out.push({
          section: "page",
          label: p.title,
          hint: p.id === p.title ? undefined : p.id,
          run: () => onOpenPage(p.id),
        });
      }
    }
    return out;
  }, [open, tabs, activeTab, setActiveTab, threads, workspaces, verbs, onSwitchThread, pages, onOpenPage, extra]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (i) => i.label.toLowerCase().includes(q) || (i.hint ?? "").toLowerCase().includes(q),
    );
  }, [items, query]);

  useEffect(() => { setIndex(0); }, [query]);

  if (!open) return null;

  const run = (i: Item | undefined) => {
    if (!i) return;
    close();
    i.run();
  };

  return (
    <div className="sy-confirm-backdrop sy-palette-backdrop" onClick={close}>
      <div className="sy-palette" role="dialog" aria-label="Command palette" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          type="text"
          className="sy-palette-input"
          placeholder="Type a tab, thread, workspace, or /command… (chord letters still work)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
          onKeyDown={(e) => {
            if (e.key === "Escape") { e.preventDefault(); close(); return; }
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setIndex((i) => Math.min(i + 1, filtered.length - 1));
              return;
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setIndex((i) => Math.max(i - 1, 0));
              return;
            }
            if (e.key === "Enter") {
              e.preventDefault();
              run(filtered[index]);
              return;
            }
            // Empty-query chord passthrough: ⌘K then T still means
            // "thread picker" even with the palette in the way.
            if (query === "" && e.key.length === 1 && !e.metaKey && !e.ctrlKey) {
              const chord = listChords().find((c) => c.key === e.key.toLowerCase());
              if (chord) {
                e.preventDefault();
                close();
                fireChord(chord.key);
              }
            }
          }}
        />
        <div className="sy-palette-list" role="listbox">
          {filtered.length === 0 && (
            <div className="sy-palette-empty">no matches</div>
          )}
          {filtered.slice(0, 40).map((i, n) => (
            <button
              key={`${i.section}:${i.label}`}
              type="button"
              role="option"
              aria-selected={n === index}
              className={"sy-palette-item" + (n === index ? " sy-palette-item--sel" : "")}
              onMouseEnter={() => setIndex(n)}
              onClick={() => run(i)}
            >
              <span className={`sy-palette-tag sy-palette-tag--${i.section}`}>
                {i.section}
              </span>
              <span className="sy-palette-label">{i.label}</span>
              {i.hint && <span className="sy-palette-hint">{i.hint}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
