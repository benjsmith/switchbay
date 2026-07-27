import { useEffect } from "react";

/**
 * Close a modal/dialog on Escape. Most Switch Bay dialogs already do
 * this ad-hoc; this is the shared version for the ones that only had
 * backdrop-click-to-close, so keyboard users get a consistent dismiss.
 */
export function useEscToClose(onClose: () => void, active = true): void {
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, active]);
}
