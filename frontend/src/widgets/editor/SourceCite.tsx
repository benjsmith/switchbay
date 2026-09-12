import { useState } from "react";
import {
  classifySourceRef, normalizeWorkspacePath, openWorkspaceFile,
  requestOpenVaultSource, vaultExtractedPath,
} from "../../lib/localPath";
import { isCollapsibleList, readSourcesOpen, writeSourcesOpen } from "./previewLists";

export function CollapsibleSources({ items }: { items: string[] }) {
  const [open, setOpen] = useState(readSourcesOpen);
  return (
    <details
      className="sy-prop-list"
      open={open}
      onToggle={(ev) => {
        const next = ev.currentTarget.open;
        setOpen(next);
        writeSourcesOpen(next);
      }}
    >
      <summary>{items.length} sources</summary>
      {items.map((item, i) => (
        <div key={i}><SourceCite value={item} forceLocal /></div>
      ))}
    </details>
  );
}

export function SourceCite({ value, forceLocal = false }: { value: string; forceLocal?: boolean }) {
  const kind = classifySourceRef(value)
    || (forceLocal && normalizeWorkspacePath(value) ? "local" : null);
  if (kind === "url") {
    return (
      <a href={value} target="_blank" rel="noreferrer" className="sy-source-cite">
        {value}
      </a>
    );
  }
  if (kind === "local") {
    return (
      <a
        href={`#file=${encodeURIComponent(value)}`}
        className="sy-source-cite"
        title={vaultExtractedPath(value)
          ? "Open in the Editor tab"
          : "Open with the system default app"}
        onClick={(ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (requestOpenVaultSource(value)) return;
          void openWorkspaceFile(value);
        }}
      >
        {value}
      </a>
    );
  }
  return <>{value}</>;
}

export function PropertyValue({ name, value }: { name: string; value: string | string[] }) {
  if (isCollapsibleList(name, value)) {
    return <CollapsibleSources items={value.map(String)} />;
  }
  if (Array.isArray(value)) {
    return (
      <>
        {value.map((item, i) => (
          <div key={i}>
            <SourceCite value={String(item)} forceLocal={name === "sources"} />
          </div>
        ))}
      </>
    );
  }
  return (
    <SourceCite
      value={String(value)}
      forceLocal={name === "sources" || name === "extracted_from"}
    />
  );
}
