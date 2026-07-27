/* Tell TypeScript that the forked CE JS files are side-effect imports
 * with no exports — they attach `Graph`, `Sidebar`, `Modal`, `Subgraph`
 * to `window`. */
declare module "./static/graph.js";
declare module "./static/sidebar.js";
declare module "./static/modal.js";
declare module "./static/subgraph.js";
declare module "./static/edit.js";

declare global {
  interface Window {
    Graph: {
      init(data: unknown): void;
      focus(pageId: string): void;
      clearFocus(): void;
      focusOnPage?(pageId: string): void;
      splitEnter(
        seed: Array<string | { id: string; policy?: "move" | "copy" }>,
        onChange: (sel: Array<{ id: string; policy: "move" | "copy" }>) => void,
      ): void;
      splitExit(): void;
    };
    Sidebar: {
      init(data: unknown): void;
      setActive(pageId: string): void;
    };
    Modal: {
      init(data: unknown): void;
      open(pageId: string): boolean;
      close(): void;
      refresh?(data: unknown): void;
      setOnClose(cb: () => void): void;
    };
    Subgraph: {
      init(data: unknown): void;
      render?(pageId: string, container: HTMLElement): void;
    };
    Edit?: {
      init(data: unknown, refetchData: (currentPageId: string | null) => Promise<void>): void;
      updateForPage(page: unknown): void;
    };
  }
}

export {};
