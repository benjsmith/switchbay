import { useEffect, useRef } from "react";
import { EditorState, Compartment } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLineGutter } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { bracketMatching, indentOnInput, syntaxHighlighting, defaultHighlightStyle } from "@codemirror/language";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import { autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap } from "@codemirror/autocomplete";

import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { html } from "@codemirror/lang-html";
import { json } from "@codemirror/lang-json";
import { rust } from "@codemirror/lang-rust";
import { go } from "@codemirror/lang-go";

// Legacy modes for languages without a dedicated CM6 package.
import { StreamLanguage } from "@codemirror/language";
import { swift } from "@codemirror/legacy-modes/mode/swift";
import { ruby } from "@codemirror/legacy-modes/mode/ruby";

/**
 * Lightweight code editor — CodeMirror 6 wrapped for the Editor
 * tab's code-file mode (task #24). Emacs-style: line numbers,
 * bracket matching, basic completion, no IDE chrome. Caller
 * picks the language; auto-detection lives in `detectLanguage`
 * below.
 *
 * Read-only file kinds (binaries, oversized, etc.) just don't
 * mount this — the Editor tab shows a placeholder instead.
 */

export type CodeLanguage =
  | "python"
  | "javascript"
  | "typescript"
  | "html"
  | "json"
  | "rust"
  | "go"
  | "swift"
  | "ruby"
  | "plain";


function languageExtension(lang: CodeLanguage) {
  switch (lang) {
    case "python":     return python();
    case "javascript": return javascript({ jsx: true });
    case "typescript": return javascript({ jsx: true, typescript: true });
    case "html":       return html();
    case "json":       return json();
    case "rust":       return rust();
    case "go":         return go();
    case "swift":      return StreamLanguage.define(swift);
    case "ruby":       return StreamLanguage.define(ruby);
    default:           return [];
  }
}


type Props = {
  value: string;
  language: CodeLanguage;
  onChange: (next: string) => void;
  readOnly?: boolean;
};


export default function CodeView({ value, language, onChange, readOnly }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  // Compartments let us swap the language extension at runtime
  // without tearing the whole editor down.
  const langCompartment = useRef(new Compartment());
  const roCompartment = useRef(new Compartment());

  // Mount once.
  useEffect(() => {
    if (!hostRef.current) return;
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        history(),
        bracketMatching(),
        closeBrackets(),
        autocompletion(),
        indentOnInput(),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        highlightSelectionMatches(),
        keymap.of([
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...historyKeymap,
          ...searchKeymap,
          ...completionKeymap,
          indentWithTab,
        ]),
        EditorView.lineWrapping,
        langCompartment.current.of(languageExtension(language)),
        roCompartment.current.of(EditorState.readOnly.of(!!readOnly)),
        EditorView.updateListener.of((v) => {
          if (v.docChanged) onChange(v.state.doc.toString());
        }),
      ],
    });
    const view = new EditorView({ state, parent: hostRef.current });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // Intentionally only on mount — value/language/onChange swaps
    // are handled by the effects below so we never tear the editor
    // down for them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update the doc when `value` changes from above (e.g. a fresh
  // file just loaded), but skip when the change is the user typing
  // (the view's doc already matches).
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === value) return;
    view.dispatch({
      changes: { from: 0, to: current.length, insert: value },
    });
  }, [value]);

  // Swap language on demand.
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({
      effects: langCompartment.current.reconfigure(languageExtension(language)),
    });
  }, [language]);

  // Toggle read-only on demand.
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({
      effects: roCompartment.current.reconfigure(EditorState.readOnly.of(!!readOnly)),
    });
  }, [readOnly]);

  return <div ref={hostRef} className="sy-code-view" />;
}


// ── Language detection ────────────────────────────────────────────


const EXT_LANG: Record<string, CodeLanguage> = {
  ".py": "python", ".pyw": "python",
  ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
  ".jsx": "javascript",
  ".ts": "typescript", ".tsx": "typescript",
  ".html": "html", ".htm": "html",
  ".json": "json", ".jsonl": "json", ".geojson": "json",
  ".rs": "rust",
  ".go": "go",
  ".swift": "swift",
  ".rb": "ruby", ".rake": "ruby", ".gemspec": "ruby",
};


/**
 * Resolve a language from a workspace-relative path + the file
 * contents. Extension wins; if there isn't a known one, a shebang
 * or other characteristic first line carries the decision. Falls
 * back to "plain" so the editor still loads in monospace.
 */
export function detectLanguage(path: string, text: string): CodeLanguage {
  const lower = path.toLowerCase();
  for (const ext of Object.keys(EXT_LANG)) {
    if (lower.endsWith(ext)) return EXT_LANG[ext]!;
  }
  // Specific filenames without extensions.
  const base = lower.split("/").pop() ?? "";
  if (base === "gemfile" || base === "rakefile") return "ruby";
  if (base === "package.json" || base === "tsconfig.json") return "json";
  // Shebang on the first line for scripts without an extension.
  const firstLine = text.slice(0, 200).split("\n", 1)[0] ?? "";
  const m = /^#!\s*\S*\b(python\d*|node|ruby|swift|bash|sh)\b/.exec(firstLine);
  if (m) {
    const kind = m[1]!;
    if (kind.startsWith("python")) return "python";
    if (kind === "node") return "javascript";
    if (kind === "ruby") return "ruby";
    if (kind === "swift") return "swift";
    // bash/sh — no dedicated package; treat as plain.
  }
  return "plain";
}


export const LANGUAGE_CHOICES: CodeLanguage[] = [
  "python", "typescript", "javascript", "html", "json",
  "rust", "go", "swift", "ruby", "plain",
];
