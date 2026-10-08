/* Tell TypeScript that the forked CE JS files (VS Code graph webview)
 * are side-effect imports with no exports — they attach `Graph`, `Modal`,
 * `Subgraph` to `window`. In the PWA the same globals (plus `Sidebar`)
 * come from Curiosity Engine's own viewer loaded through /embed/ce. */
declare module "./static/graph.js";
declare module "./static/modal.js";
declare module "./static/subgraph.js";
declare module "./static/vendor/knowledge-atlas.js";

declare global {
  interface Window {
    Graph: {
      init(data: unknown): void;
      focus(pageId: string): void;
      clearFocus(): void;
      focusOnPage?(pageId: string): void;
      /** Highlight a set of node ids (graph search). Empty clears. */
      highlightSearch?(ids: string[]): void;
      splitEnter(
        seed: Array<string | { id: string; policy?: "move" | "copy" }>,
        onChange: (sel: Array<{ id: string; policy: "move" | "copy" }>) => void,
      ): void;
      splitExit(): void;
    };
    Sidebar?: {
      init(data: unknown): void;
      setActive(pageId: string): void;
      /** Mark page ids hit by the graph search. Empty clears. */
      setSearchHits?(ids: string[]): void;
    };
    Modal: {
      init(data: unknown, root?: HTMLElement): void;
      open(pageId: string): boolean;
      close(): void;
      refresh?(data: unknown): void;
      setOnClose(cb: () => void): void;
    };
    Subgraph: {
      init(data: unknown): void;
      render?(pageId: string, container: HTMLElement): void;
    };
  }
}

export {};
