import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { minimapBottomOffset } from "./minimapAnchor";
import type { RailEntry } from "../rail/Rail";
import {
  DecisionRow, PermissionRow, ProposalRow, ProviderRetryRow, MicroEditFeedbackRow,
  LocalModelsCheckRow, LocalModelsDiscoveryRow,
  ReasoningRow, detectUserKind,
  mdWithWikilinks, prettyJson, summariseInput, uploadFile,
} from "../rail/Rail";
import PtyThreadSurface, { type TerminalWsApi } from "../rail/PtyThreadSurface";
import VoiceButton from "../rail/VoiceButton";
import ReasoningPicker from "../rail/ReasoningPicker";
import { useComposerDraft } from "../lib/composerDraft";

// One persisted, drag-resizable height for BOTH the chat and the pty
// view — so the box no longer jumps between a content-sized chat and a
// fixed 40vh terminal. Default = the compact "new chat box" size; the
// user drags the top handle to grow/shrink and double-clicks it to snap
// back. Promote-to-pane (⇱) remains the route to a full-height surface.
const BOX_H_KEY = "sy:zen-box-h";
const DEFAULT_BOX_H = 160;  // ≈ a fresh chat box (incl. the resize handle)
const MIN_BOX_H = 156;      // the composer + one response line must still fit

function readBoxH(): number {
  try {
    const v = parseInt(localStorage.getItem(BOX_H_KEY) ?? "", 10);
    if (Number.isFinite(v) && v >= MIN_BOX_H) return v;
  } catch { /* storage disabled */ }
  return DEFAULT_BOX_H;
}

/**
 * Zen's floating chat box (charter Zen rulings, 2026-07-05): softly
 * rounded, ~80% width, floats over both panes with a slight glow.
 * Internally split — left half = user inputs (one message at a time,
 * stepped), right half = the paired agent response. Turn pairing is
 * LOCKSTEP: one turn is one view; the stepper drives both sides.
 * Collapsible to a slim pill; click / typing / an incoming response
 * reopens it. In pty mode the terminal takes the full box width at
 * the box's fixed height, with a promote-to-right-pane toggle.
 */

type Props = {
  entries: RailEntry[];
  onSubmit: (text: string, opts: { n: number }) => void;
  focusedThread: string | null;
  focusedThreadKind: string | null;
  onSwitchThread: (threadId: string, kind: string) => void;
  onNewThread: (kind?: "structured-agent" | "interactive-pty") => void;
  termWs: TerminalWsApi | null;
  activeRunIds: Set<string>;
  /** True while a produced artifact awaits the user (go-to arrow on
   *  the response half's last row — one of the three one-click paths). */
  artifactPending: boolean;
  artifactLabel: string | null;
  onJumpArtifact: () => void;
  ptyPromoted: boolean;
  onPromotePty: () => void;
  hasMoreHistory: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
  /** Right-pane Chat surface instead of the floating bottom box. */
  docked?: boolean;
  onDock?: () => void;
  onFloat?: () => void;
};

type Turn = {
  user: Extract<RailEntry, { source: "user" }> | null;
  items: RailEntry[];
};

type VerbInfo = { name: string; aliases: string[]; description: string };

type ThreadRow = {
  thread_id: string;
  title: string | null;
  kind: string;
  last_summary?: string;
  running: number;
};

export default function ZenChatBox({
  entries, onSubmit, focusedThread, focusedThreadKind,
  onSwitchThread, onNewThread, termWs, activeRunIds,
  artifactPending, artifactLabel, onJumpArtifact,
  ptyPromoted, onPromotePty,
  hasMoreHistory, loadingOlder, onLoadOlder,
  docked = false, onDock, onFloat,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [input, setInput] = useComposerDraft();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const responseRef = useRef<HTMLDivElement>(null);
  // Attach-a-file: same upload → `[attached: <path>]` prefix contract
  // as the Power rail (the agent reads the file via its own tools).
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachStatus, setAttachStatus] = useState<string | null>(null);

  // ── Box height (shared by chat + pty, persisted, drag-resizable) ──
  const [boxH, setBoxH] = useState(readBoxH);
  useEffect(() => {
    try { localStorage.setItem(BOX_H_KEY, String(boxH)); } catch { /* quota */ }
  }, [boxH]);
  const boxRef = useRef<HTMLDivElement>(null);
  const draggingH = useRef(false);
  const onHandleDown = (ev: React.PointerEvent<HTMLDivElement>) => {
    ev.preventDefault();
    draggingH.current = true;
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
  };
  const onHandleMove = (ev: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingH.current || !boxRef.current) return;
    // The box is anchored at its bottom edge, so its height is simply
    // the gap from the pointer up to that fixed bottom.
    const bottom = boxRef.current.getBoundingClientRect().bottom;
    const max = Math.round(window.innerHeight * 0.85);
    setBoxH(Math.max(MIN_BOX_H, Math.min(max, Math.round(bottom - ev.clientY))));
  };
  const onHandleUp = (ev: React.PointerEvent<HTMLDivElement>) => {
    draggingH.current = false;
    try { (ev.target as HTMLElement).releasePointerCapture(ev.pointerId); } catch { /* not captured */ }
    window.dispatchEvent(new Event("resize"));  // let the pty terminal refit
  };
  const resetBoxH = () => {
    setBoxH(DEFAULT_BOX_H);
    window.setTimeout(() => window.dispatchEvent(new Event("resize")), 0);
  };

  // Lift the Classic/Atlas overview map when the floating box or
  // collapsed pill would cover its corner. Docked chat is in the
  // right pane and never intersects. Measure live rects so a
  // resize, tab/float flip, or pill collapse all re-park the map.
  useLayoutEffect(() => {
    const root = document.querySelector(".sy-zen") as HTMLElement | null;
    if (!root) return;
    const apply = () => {
      if (docked) {
        root.style.setProperty("--sy-minimap-bottom", "12px");
        return;
      }
      const graph = root.querySelector(".sy-zen-left") as HTMLElement | null;
      const overlay = (boxRef.current ?? root.querySelector(".sy-zen-pill")) as HTMLElement | null;
      if (!graph || !overlay) {
        root.style.setProperty("--sy-minimap-bottom", "12px");
        return;
      }
      const bottom = minimapBottomOffset(
        graph.getBoundingClientRect(),
        overlay.getBoundingClientRect(),
      );
      root.style.setProperty("--sy-minimap-bottom", `${bottom}px`);
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(root);
    const graph = root.querySelector(".sy-zen-left");
    if (graph) ro.observe(graph);
    if (boxRef.current) ro.observe(boxRef.current);
    const pill = root.querySelector(".sy-zen-pill");
    if (pill) ro.observe(pill);
    window.addEventListener("resize", apply);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", apply);
      root.style.setProperty("--sy-minimap-bottom", "12px");
    };
  }, [docked, collapsed, boxH]);

  const resizeHandle = (
    <div
      className="sy-zen-box-handle"
      title="Drag to resize · double-click to reset height"
      onPointerDown={onHandleDown}
      onPointerMove={onHandleMove}
      onPointerUp={onHandleUp}
      onDoubleClick={resetBoxH}
    >
      <span className="sy-zen-box-grip" />
    </div>
  );

  // ── Lockstep turns ────────────────────────────────────────────
  // A turn opens at each user entry; everything until the next user
  // entry is its response. Entries BEFORE the first user entry
  // (connect lines, notices) would otherwise become a leading
  // "· system" turn that greets the user with connection noise —
  // fold pure-system/notice leaders into the first real turn's
  // response instead. Nothing is dropped, only re-homed; a thread
  // with no real turns yet keeps its system turn (else the box
  // would hide the only content it has).
  const turns = useMemo<Turn[]>(() => {
    const raw: Turn[] = [];
    for (const e of entries) {
      if (e.source === "user") {
        raw.push({ user: e, items: [] });
      } else {
        if (raw.length === 0) raw.push({ user: null, items: [] });
        raw[raw.length - 1]!.items.push(e);
      }
    }
    const foldable = (t: Turn) =>
      t.user === null
      && t.items.every((e) => e.source === "system" || e.source === "notice");
    const out: Turn[] = [];
    let carry: RailEntry[] = [];
    for (const t of raw) {
      if (foldable(t)) {
        carry.push(...t.items);
        continue;
      }
      if (carry.length > 0) {
        out.push({ user: t.user, items: [...carry, ...t.items] });
        carry = [];
      } else {
        out.push(t);
      }
    }
    if (carry.length > 0) {
      if (out.length > 0) {
        const last = out[out.length - 1]!;
        out[out.length - 1] = { ...last, items: [...last.items, ...carry] };
      } else {
        out.push({ user: null, items: carry });
      }
    }
    return out;
  }, [entries]);

  // null = follow the latest turn (the default). Stepping back pins
  // an explicit index; stepping forward onto the last turn resumes
  // following.
  const [turnIdx, setTurnIdx] = useState<number | null>(null);
  const lastIdx = Math.max(0, turns.length - 1);
  const shownIdx = turnIdx === null ? lastIdx : Math.min(turnIdx, lastIdx);
  const following = turnIdx === null || shownIdx === lastIdx;
  const turn = turns[shownIdx] ?? null;

  const step = (d: 1 | -1) => {
    const next = Math.max(0, Math.min(lastIdx, shownIdx + d));
    setTurnIdx(next === lastIdx ? null : next);
  };

  // Follow streaming output: keep the response half pinned to its
  // bottom while showing the live turn.
  useEffect(() => {
    if (!following) return;
    const el = responseRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries, following, shownIdx, collapsed]);

  // Reset the stepper when the thread changes (new transcript).
  useEffect(() => { setTurnIdx(null); }, [focusedThread]);

  // ── Collapse pill + reopen triggers ───────────────────────────
  // An incoming assistant segment reopens the box (ruling: incoming
  // responses reopen it). Tracked by assistant-entry count so
  // streaming deltas alone don't fight an explicit collapse.
  const assistantCount = useMemo(
    () => entries.reduce((n, e) => n + (e.source === "assistant" ? 1 : 0), 0),
    [entries],
  );
  const prevAssistantRef = useRef(assistantCount);
  useEffect(() => {
    if (assistantCount > prevAssistantRef.current) setCollapsed(false);
    prevAssistantRef.current = assistantCount;
  }, [assistantCount]);

  // Typing reopens: a bare printable keystroke with nothing focused
  // lands in the composer.
  useEffect(() => {
    if (!collapsed) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.metaKey || ev.ctrlKey || ev.altKey || ev.key.length !== 1) return;
      const t = ev.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      ev.preventDefault();
      setCollapsed(false);
      setInput((cur) => cur + ev.key);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [collapsed]);

  // ── Composer: slash autocomplete + shell-detect chip ──────────
  const [verbs, setVerbs] = useState<VerbInfo[] | null>(null);
  const [acIndex, setAcIndex] = useState(0);
  useEffect(() => {
    fetch("/api/verbs")
      .then((r) => r.json())
      .then((b: { verbs: VerbInfo[] }) => setVerbs(b.verbs))
      .catch(() => setVerbs([]));
  }, [focusedThread]);

  const acMatches = useMemo<VerbInfo[]>(() => {
    if (!verbs || verbs.length === 0) return [];
    if (!input.startsWith("/")) return [];
    const head = input.split("\n", 1)[0]!;
    if (head.includes(" ")) return [];
    const prefix = head.slice(1).toLowerCase();
    const filtered = verbs.filter((v) => {
      if (!prefix) return true;
      if (v.name.toLowerCase().startsWith(prefix)) return true;
      return v.aliases.some((a) => a.toLowerCase().startsWith(prefix));
    });
    return filtered.slice(0, 8);
  }, [input, verbs]);
  const acOpen = acMatches.length > 0;
  useEffect(() => { setAcIndex(0); }, [acMatches.length, input]);
  const acceptSuggestion = (v: VerbInfo) => {
    setInput(`/${v.name} `);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const [shellHint, setShellHint] = useState(false);
  const [chatForced, setChatForced] = useState(false);
  useEffect(() => {
    const t = input.trim();
    setChatForced(false);
    if (!t || t.startsWith("/") || t.startsWith("!") || t.includes("\n")) {
      setShellHint(false);
      return;
    }
    const h = window.setTimeout(() => {
      fetch(`/api/shell/detect?text=${encodeURIComponent(t)}`)
        .then((r) => (r.ok ? r.json() : { shell: false }))
        .then((b: { shell?: boolean }) => setShellHint(b.shell === true))
        .catch(() => setShellHint(false));
    }, 200);
    return () => window.clearTimeout(h);
  }, [input]);

  const submit = () => {
    const text = input.trim();
    if (!text) return;
    const asShell =
      shellHint && !chatForced && !text.startsWith("!") && !text.startsWith("/");
    onSubmit(asShell ? `!${text}` : text, { n: 0 });
    setInput("");
    setShellHint(false);
    setChatForced(false);
    setTurnIdx(null);
  };

  const isPty = focusedThreadKind === "interactive-pty" && !!focusedThread;
  const running = activeRunIds.size > 0;

  const placeBtn = docked ? (
    <button
      type="button"
      className="sy-zen-chat-btn"
      onClick={() => onFloat?.()}
      title="Float this thread at the bottom of the window"
    >
      ⇱ float
    </button>
  ) : (
    <button
      type="button"
      className="sy-zen-chat-btn"
      onClick={() => {
        if (isPty) {
          onPromotePty();
          setCollapsed(true);
        } else {
          onDock?.();
        }
      }}
      title={isPty
        ? "Open this shell as a tab (full height on the right)"
        : "Open this chat as a tab (right pane)"}
    >
      ⇲ tab
    </button>
  );

  // ── Collapsed pill ─────────────────────────────────────────────
  if (collapsed && !docked) {
    return (
      <button
        type="button"
        className="sy-zen-pill"
        onClick={() => {
          setCollapsed(false);
          window.setTimeout(() => inputRef.current?.focus(), 0);
        }}
        title="Open the chat box (or just start typing)"
      >
        <span className="sy-zen-pill-glyph">{isPty ? ">_" : "◈"}</span>
        {isPty ? (ptyPromoted ? "terminal in tab" : "shell") : "chat"}
        {running && <span className="sy-zen-pill-dot" title="runs active" />}
        {artifactPending && (
          <span
            className="sy-zen-pulse-dot"
            title={artifactLabel ? `New: ${artifactLabel}` : "New artifact"}
          />
        )}
      </button>
    );
  }

  // ── PTY mode: terminal takes the full box width, fixed height ──
  if (isPty && !ptyPromoted) {
    return (
      <div
        className={"sy-zen-chatbox sy-zen-chatbox--pty" + (docked ? " sy-zen-chatbox--docked" : "")}
        ref={boxRef}
        style={docked ? undefined : { height: boxH }}
        data-tour="zen-chat"
      >
        {!docked && resizeHandle}
        <div className="sy-zen-chat-toolrow">
          <ThreadDropUp
            focusedThread={focusedThread}
            onSwitchThread={onSwitchThread}
            onNewThread={onNewThread}
            dropDown={docked}
          />
          <span className="sy-spacer" />
          {!docked && (
            <button
              type="button"
              className="sy-zen-chat-btn"
              onClick={() => setCollapsed(true)}
              title="Collapse to a pill"
            >
              ▾
            </button>
          )}
          {placeBtn}
        </div>
        <div className="sy-zen-chat-ptyhost">
          <PtyThreadSurface
            key={`zen-box-${focusedThread}`}
            threadId={focusedThread!}
            ws={termWs}
          />
        </div>
      </div>
    );
  }

  // ── Chat view: lockstep halves ─────────────────────────────────
  return (
    <div
      className={"sy-zen-chatbox" + (docked ? " sy-zen-chatbox--docked" : "")}
      ref={boxRef}
      style={docked ? undefined : { height: boxH }}
      data-tour="zen-chat"
    >
      {!docked && resizeHandle}
      <div className="sy-zen-chat-halves">
        <div className="sy-zen-chat-left">
          <div className="sy-zen-chat-toolrow">
            <ThreadDropUp
              focusedThread={focusedThread}
              onSwitchThread={onSwitchThread}
              onNewThread={onNewThread}
              dropDown={docked}
            />
            <span className="sy-spacer" />
            {turns.length > 0 && (
              <span className="sy-zen-stepper">
                {shownIdx === 0 && hasMoreHistory ? (
                  <button
                    type="button"
                    className="sy-zen-chat-btn"
                    onClick={onLoadOlder}
                    disabled={loadingOlder}
                    title="Load older turns"
                  >
                    {loadingOlder ? "…" : "↞"}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="sy-zen-chat-btn"
                    onClick={() => step(-1)}
                    disabled={shownIdx === 0}
                    title="Previous turn"
                  >
                    ‹
                  </button>
                )}
                <span className="sy-zen-stepper-n" title={following ? "following the latest turn" : "pinned to an older turn"}>
                  {turns.length === 0 ? "0 / 0" : `${shownIdx + 1} / ${turns.length}`}
                </span>
                <button
                  type="button"
                  className="sy-zen-chat-btn"
                  onClick={() => step(1)}
                  disabled={shownIdx >= lastIdx}
                  title="Next turn"
                >
                  ›
                </button>
              </span>
            )}
            {!docked && (
              <button
                type="button"
                className="sy-zen-chat-btn"
                onClick={() => setCollapsed(true)}
                title="Collapse to a pill (typing or a response reopens it)"
              >
                ▾
              </button>
            )}
            {placeBtn}
          </div>
          <div className="sy-zen-chat-usermsg">
            {turn?.user ? (
              <>
                <span className="sy-zen-chat-prefix">›</span>
                {detectUserKind(turn.user.text) && (
                  <span className="sy-kind-chip" data-kind={detectUserKind(turn.user.text)}>
                    {detectUserKind(turn.user.text)}
                  </span>
                )}
                <span className="sy-zen-chat-usertext">{turn.user.text}</span>
              </>
            ) : (
              <span className="sy-zen-chat-usertext sy-zen-chat-usertext--empty">
                {turns.length === 0
                  ? "type a message to begin · / for slash commands"
                  : "· system"}
              </span>
            )}
          </div>
          <div className="sy-zen-composer">
            {acOpen && (
              <div className="sy-zen-ac" role="listbox" aria-label="slash commands">
                {acMatches.map((v, i) => (
                  <button
                    key={v.name}
                    type="button"
                    role="option"
                    aria-selected={i === acIndex}
                    className={"sy-rail-ac-item" + (i === acIndex ? " sy-rail-ac-item--sel" : "")}
                    onMouseDown={(ev) => {
                      ev.preventDefault();
                      acceptSuggestion(v);
                    }}
                    onMouseEnter={() => setAcIndex(i)}
                  >
                    <span className="sy-rail-ac-name">/{v.name}</span>
                    <span className="sy-rail-ac-desc">{v.description}</span>
                  </button>
                ))}
              </div>
            )}
            {shellHint && (
              <div className="sy-zen-interp">
                {chatForced ? (
                  <>⏎ send as <b>chat</b> · Tab: run in a shell thread</>
                ) : (
                  <>⏎ run in a <b>shell thread</b> · Tab: send as chat</>
                )}
              </div>
            )}
            {attachStatus && (
              <div className="sy-zen-interp">{attachStatus}</div>
            )}
            <div className="sy-zen-composer-row">
              <button
                type="button"
                className="sy-zen-chat-btn sy-zen-composer-btn"
                title="Attach a file to the next message"
                aria-label="Attach file"
                onClick={() => fileInputRef.current?.click()}
              >
                <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2 5.5 V12.5 a1 1 0 0 0 1 1 H13 a1 1 0 0 0 1-1 V6 a1 1 0 0 0 -1 -1 H8 L6.5 3.5 H3 a1 1 0 0 0 -1 1 Z"/>
                  <line x1="8" y1="8" x2="8" y2="11"/>
                  <line x1="6.5" y1="9.5" x2="9.5" y2="9.5"/>
                </svg>
              </button>
              <input
                type="file"
                ref={fileInputRef}
                style={{ display: "none" }}
                onChange={async (ev) => {
                  const f = ev.target.files?.[0];
                  ev.target.value = ""; // allow re-picking the same file
                  if (!f) return;
                  await uploadFile(f, setInput, setAttachStatus);
                }}
              />
              <button
                type="button"
                className="sy-zen-chat-btn sy-zen-composer-btn"
                title="Start a new shell thread — the terminal takes the box (⇲ tab opens it full height)"
                aria-label="New shell thread"
                onClick={() => onNewThread("interactive-pty")}
              >
                {">_"}
              </button>
              <textarea
                ref={inputRef}
                className="sy-zen-input"
                rows={2}
                value={input}
                onChange={(ev) => setInput(ev.target.value)}
                onKeyDown={(ev) => {
                  if (acOpen) {
                    if (ev.key === "ArrowDown") {
                      ev.preventDefault();
                      setAcIndex((i) => Math.min(i + 1, acMatches.length - 1));
                      return;
                    }
                    if (ev.key === "ArrowUp") {
                      ev.preventDefault();
                      setAcIndex((i) => Math.max(i - 1, 0));
                      return;
                    }
                    if (ev.key === "Tab" || (ev.key === "Enter" && !ev.shiftKey && acMatches[acIndex])) {
                      ev.preventDefault();
                      acceptSuggestion(acMatches[acIndex]!);
                      return;
                    }
                    if (ev.key === "Escape") {
                      ev.preventDefault();
                      setInput("");
                      return;
                    }
                  }
                  if (ev.key === "Tab" && shellHint) {
                    ev.preventDefault();
                    setChatForced((v) => !v);
                    return;
                  }
                  if (ev.key === "Enter" && !ev.shiftKey) {
                    ev.preventDefault();
                    submit();
                  }
                }}
                placeholder="chat, or use a prefix… (try /view)"
              />
              <ReasoningPicker />
              <VoiceButton
                onText={(text) =>
                  setInput((cur) => (cur.trim() ? `${cur.replace(/\s+$/, "")} ${text}` : text))
                }
              />
            </div>
          </div>
        </div>
        <div className="sy-zen-chat-right">
          <div ref={responseRef} className="sy-zen-chat-response">
            {(!turn || turn.items.length === 0) && (
              <div className="sy-zen-chat-waiting">
                {turn?.user && following && running ? "thinking…" : "—"}
              </div>
            )}
            {turn?.items.map((e) => <ResponseItem key={e.id} entry={e} />)}
          </div>
          {artifactPending && (
            <button
              type="button"
              className="sy-zen-goto"
              onClick={onJumpArtifact}
              title={artifactLabel ? `Open: ${artifactLabel}` : "Open the latest artifact"}
            >
              ↗ {artifactLabel ?? "latest artifact"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** One response-half row. Reuses the rail's card components for
 *  permission / charter-review entries (rulings: cards render inline
 *  in the response half, chips stay consistent with Power). */
function ResponseItem({ entry: e }: { entry: RailEntry }) {
  if (e.source === "decision") return <DecisionRow entry={e} />;
  if (e.source === "proposal") return <ProposalRow entry={e} />;
  if (e.source === "provider_retry") return <ProviderRetryRow entry={e} />;
  if (e.source === "permission") return <PermissionRow entry={e} />;
  if (e.source === "reasoning") return <ReasoningRow text={e.text} />;
  if (e.source === "tool") {
    return (
      <details className="sy-rail-entry sy-rail-tool sy-zen-resp-tool">
        <summary className="sy-rail-tool-summary">
          <span className="sy-rail-prefix" data-kind="tool">⚙</span>
          {!e.result && <span className="sy-rail-running-dot" title="In flight" />}
          <span className="sy-rail-tool-name">{e.name}</span>
          <span className="sy-rail-tool-input">{summariseInput(e.input)}</span>
          {e.result ? (
            <span
              className={
                "sy-rail-tool-result" + (e.result.ok ? "" : " sy-rail-tool-result--err")
              }
            >
              → {e.result.summary}
            </span>
          ) : (
            <span className="sy-rail-tool-result sy-rail-tool-result--running">
              → running…
            </span>
          )}
        </summary>
        <div className="sy-rail-tool-detail">
          <div className="sy-rail-tool-section">input</div>
          <pre className="sy-rail-tool-json">{prettyJson(e.input)}</pre>
          {e.result && (
            <>
              <div className="sy-rail-tool-section">result</div>
              <pre className="sy-rail-tool-json">{prettyJson(e.result)}</pre>
            </>
          )}
        </div>
      </details>
    );
  }
  if (e.source === "assistant") {
    return (
      <div className="sy-zen-resp-md">
        <span
          className="sy-mdview"
          dangerouslySetInnerHTML={{ __html: mdWithWikilinks(e.text) }}
          onClick={(ev) => {
            const a = (ev.target as HTMLElement).closest?.("a.sy-wikilink");
            if (!a) return;
            ev.preventDefault();
            window.dispatchEvent(new CustomEvent("sy:open-wiki-page", {
              detail: { target: a.getAttribute("data-wiki") },
            }));
          }}
        />
        {!e.done && <span className="sy-rail-cursor">▋</span>}
        {e.done && e.meta && <span className="sy-rail-meta">{e.meta}</span>}
      </div>
    );
  }
  if (e.source === "micro_edit_feedback") {
    return <MicroEditFeedbackRow entry={e} />;
  }
  if (e.source === "local_models_check") {
    return <LocalModelsCheckRow entry={e} />;
  }
  if (e.source === "local_models_discovery") {
    return <LocalModelsDiscoveryRow entry={e} />;
  }
  // system / notice — faint breadcrumb line.
  const sysText = "text" in e ? e.text : "";
  return (
    <div className="sy-zen-resp-sys">
      <span className="sy-rail-prefix" data-kind={e.source}>
        {e.source === "notice" ? "»" : "·"}
      </span>
      {e.source === "notice" && e.kind && (
        <span className="sy-kind-chip" data-kind={e.kind}>{e.kind}</span>
      )}
      <span className="sy-zen-resp-systext">{sysText}</span>
    </div>
  );
}

/** Thread switcher as a drop-UP (the box floats at the bottom).
 *  Same data as the Power ThreadBar, trimmed: rows + new chat/shell. */
function ThreadDropUp({
  focusedThread, onSwitchThread, onNewThread, dropDown = false,
}: {
  focusedThread: string | null;
  onSwitchThread: (threadId: string, kind: string) => void;
  onNewThread: (kind?: "structured-agent" | "interactive-pty") => void;
  /** Docked pane: open below the button so the menu isn't clipped. */
  dropDown?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [threads, setThreads] = useState<ThreadRow[]>([]);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuPos, setMenuPos] = useState<{ top?: number; bottom?: number; left: number } | null>(null);

  const placeMenu = () => {
    const el = wrapRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.left, window.innerWidth - 278));
    setMenuPos(dropDown
      ? { top: r.bottom + 8, left }
      : { bottom: window.innerHeight - r.top + 8, left });
  };

  const load = async () => {
    try {
      const r = await fetch("/api/threads");
      if (!r.ok) return;
      const body = (await r.json()) as { threads: ThreadRow[] };
      setThreads(body.threads);
    } catch { /* daemon down — keep the stale list */ }
  };
  /** Archive = remove from the switcher; events stay in the log.
   *  Same semantics as Power's ThreadBar — the daemon kills an
   *  attached shell and refocuses if needed (broadcasts drive the
   *  UI), so no round-trip through Power is ever required. */
  const archive = async (tid: string) => {
    try {
      await fetch(`/api/threads/${encodeURIComponent(tid)}/archive`, { method: "POST" });
      void load();
    } catch { /* daemon down — row stays until the next refresh */ }
  };
  useEffect(() => { void load(); }, [focusedThread]);
  useEffect(() => { if (open) void load(); }, [open]);
  useEffect(() => {
    const onChanged = () => { void load(); };
    window.addEventListener("sy:thread-titled", onChanged);
    window.addEventListener("sy:threads-changed", onChanged);
    return () => {
      window.removeEventListener("sy:thread-titled", onChanged);
      window.removeEventListener("sy:threads-changed", onChanged);
    };
  }, []);
  useLayoutEffect(() => {
    if (!open) return;
    placeMenu();
    window.addEventListener("resize", placeMenu);
    return () => window.removeEventListener("resize", placeMenu);
    // placeMenu reads dropDown + wrapRef; re-run when those change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, dropDown]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      const t = ev.target as Node;
      if (wrapRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const title = (t: ThreadRow): string =>
    t.title
    ?? (t.kind === "interactive-pty" ? "shell" : (t.last_summary?.trim() || "(untitled)"));
  const focused = threads.find((t) => t.thread_id === focusedThread);
  const label = focusedThread
    ? (focused ? title(focused) : "New thread…")
    : "new thread";

  return (
    <div className="sy-zen-threads" ref={wrapRef}>
      <button
        type="button"
        className="sy-zen-chat-btn sy-zen-threads-btn"
        onClick={() => setOpen((o) => !o)}
        title="Switch thread (⌘K then T)"
      >
        <span className="sy-thread-glyph">
          {focused?.kind === "interactive-pty" ? ">_" : "◈"}
        </span>
        <span className="sy-zen-threads-label">{label}</span>
        <span className="sy-thread-caret">{dropDown ? "▾" : "▴"}</span>
      </button>
      {open && createPortal(
        <div
          ref={menuRef}
          className="sy-zen-threads-menu sy-zen-threads-menu--portal"
          role="listbox"
          style={{
            left: menuPos?.left ?? 0,
            top: menuPos?.top,
            bottom: menuPos?.bottom,
          }}
        >
          <div className="sy-zen-threads-new">
            <button
              type="button"
              className="sy-zen-chat-btn"
              onClick={() => { setOpen(false); onNewThread(); }}
              title="Start a new chat thread"
            >
              + chat
            </button>
            <button
              type="button"
              className="sy-zen-chat-btn"
              onClick={() => { setOpen(false); onNewThread("interactive-pty"); }}
              title="Start a new shell thread (the terminal takes the box; ⇲ tab opens it full height)"
            >
              + shell
            </button>
          </div>
          {threads.length === 0 && (
            <div className="sy-thread-empty">no threads yet — say something</div>
          )}
          {threads.map((t) => (
            <button
              key={t.thread_id}
              type="button"
              className={
                "sy-thread-row" + (t.thread_id === focusedThread ? " focused" : "")
              }
              onClick={() => { setOpen(false); onSwitchThread(t.thread_id, t.kind); }}
            >
              <span className="sy-thread-row-kind">
                {t.kind === "interactive-pty" ? ">_" : "◈"}
              </span>
              <span className="sy-thread-row-title">{title(t)}</span>
              {t.running > 0 && <span className="sy-thread-dot" />}
              {(t.running === 0 || t.kind === "interactive-pty") && (
                // Same visibility rule as Power's ThreadBar: pty rows
                // keep the ✕ even while "running" (a fresh shell reads
                // as running until the dormancy detector flips it) —
                // archiving a pty thread explicitly kills its shell.
                <span
                  className="sy-thread-row-del"
                  role="button"
                  tabIndex={-1}
                  title={t.kind === "interactive-pty"
                    ? "Close this shell thread (kills the shell; history stays in the log)"
                    : "Remove from the switcher (history stays in the log — purge from Settings if you really want it gone)"}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    void archive(t.thread_id);
                  }}
                >
                  ✕
                </span>
              )}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </div>
  );
}
