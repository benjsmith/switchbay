import { useEffect, useRef } from "react";
import { sidebarTemplate } from "../widgets/graph/template";
import type { GraphData } from "../widgets/graph/types";
import { openUploadVaultDialog } from "../lib/uploadVault.ts";

/**
 * The wiki page list — CE's forked sidebar (pages grouped by type,
 * search, `+` upload), mounted into a slot and driven imperatively via
 * `window.Sidebar`.
 *
 * Shared by the Power sidebar column and the Zen Browser surface.
 * `window.Sidebar` is a SINGLETON over fixed element ids (`#sidebar`,
 * `#sidebar-list`, …), so exactly one of these may be mounted at a
 * time. That holds today because Power and Zen are mutually exclusive
 * shells — if that ever stops being true, this needs an instance-
 * scoped fork of the CE template, not a second mount.
 */

type Props = {
  data: GraphData | null;
  /** Fired when a NEW graph build lands — a rebuilt wiki means the
   *  on-disk file set may have shifted too, so consumers bump their
   *  browsers' refreshKey. */
  onGraphBuild?: () => void;
};

export default function WikiPane({ data, onGraphBuild }: Props) {
  const slotRef = useRef<HTMLDivElement>(null);
  const lastDataRef = useRef<GraphData | null>(null);
  // Kept in a ref so the mount effect doesn't re-run (and re-init the
  // CE sidebar) just because the parent passed a new closure.
  const onBuildRef = useRef(onGraphBuild);
  useEffect(() => { onBuildRef.current = onGraphBuild; }, [onGraphBuild]);

  useEffect(() => {
    if (!slotRef.current) return;
    if (!slotRef.current.querySelector("#sidebar")) {
      slotRef.current.innerHTML = sidebarTemplate;
    }
    if (data && data !== lastDataRef.current) {
      lastDataRef.current = data;
      window.Sidebar.init(data);
      onBuildRef.current?.();
    } else if (!data) {
      // Workspace switched to one with no built graph (data === null).
      // window.Sidebar.init only renders for truthy data, so without
      // this the previous workspace's page list stays in #sidebar-list.
      // Clear it explicitly so the Browser empties on the switch.
      lastDataRef.current = null;
      const list = slotRef.current.querySelector("#sidebar-list");
      if (list) list.innerHTML = "";
      const search = slotRef.current.querySelector<HTMLInputElement>("#sidebar-search");
      if (search) search.value = "";
    }
  }, [data]);

  // Wire the CE-template `#sidebar-upload` button to the upload dialog.
  // Hooking up after the template lands; runs after every re-mount
  // (workspace switch re-injects the markup).
  useEffect(() => {
    const btn = slotRef.current?.querySelector<HTMLButtonElement>("#sidebar-upload");
    if (!btn) return;
    btn.setAttribute("data-tour", "add-files");
    const onClick = () => openUploadVaultDialog();
    btn.addEventListener("click", onClick);
    return () => btn.removeEventListener("click", onClick);
  }, [data]);

  return <div ref={slotRef} className="sy-side-pages-mount" />;
}
