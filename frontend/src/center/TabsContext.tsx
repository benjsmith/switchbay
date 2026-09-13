import { createContext, useContext, type ReactNode } from "react";
import type { TabSpec } from "../ws";

type Ctx = {
  tabs: TabSpec[];
  activeId: string | null;
  setActive: (id: string) => void;
  /**
   * Activate the first tab matching the given kind. Used by tab-swap
   * buttons (Graph ↔ Editor "show me here" with current selection).
   * Returns true if a tab was found.
   */
  switchToKind: (kind: string) => boolean;
  /**
   * Close a closable user tab (vault-source Editor tabs today).
   * Removes it from the strip and activates a sensible neighbor.
   * No-op when the id is unknown / not closable.
   */
  closeTab: (tabId: string) => void;
};

const TabsContext = createContext<Ctx | null>(null);

export function TabsProvider({ value, children }: { value: Ctx; children: ReactNode }) {
  return <TabsContext.Provider value={value}>{children}</TabsContext.Provider>;
}

export function useTabs(): Ctx {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("useTabs must be inside TabsProvider");
  return ctx;
}
