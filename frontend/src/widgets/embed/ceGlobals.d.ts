/* Globals Curiosity Engine's wiki-view scripts attach to `window` once
 * the embed has loaded them (PWA Graph tab and the VS Code graph view).
 * Every one is optional: none exist until CE is installed and loaded. */

declare global {
  interface Window {
    Sidebar?: {
      init(data: unknown): void;
      setActive(pageId: string): void;
      /** Mark page ids hit by the graph search. Empty clears. */
      setSearchHits?(ids: string[]): void;
    };
    Modal?: {
      init(data: unknown, root?: HTMLElement): void;
      open(pageId: string): boolean;
      close(): void;
      refresh?(data: unknown): void;
      setOnClose?(cb: () => void): void;
    };
    FileBrowser?: {
      setSearchHits?(ids: string[]): void;
    };
  }
}

export {};
