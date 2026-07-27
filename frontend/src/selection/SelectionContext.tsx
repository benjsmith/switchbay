import { createContext, useContext, type ReactNode } from "react";
import type { Selection } from "../ws";

type Ctx = {
  selection: Selection | null;
  /** Local update + push to daemon (which broadcasts + persists). */
  setSelection: (s: Selection | null) => void;
};

const SelectionContext = createContext<Ctx | null>(null);

export function SelectionProvider({ value, children }: { value: Ctx; children: ReactNode }) {
  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): Ctx {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be inside SelectionProvider");
  return ctx;
}
