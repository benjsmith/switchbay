import { useCallback, useEffect, useRef, useState } from "react";
import {
  OPEN_UPLOAD_VAULT_EVENT,
  describeUploadResult,
  loadIngestPref,
  saveIngestPref,
  uploadToVault,
} from "../../lib/uploadVault.ts";
import { toast } from "../../lib/toast";

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * The graph sidebar `+` dialog: pick one or more files, choose whether to
 * ingest them, upload to vault/raw/. Mounted once by App and opened with
 * `openUploadVaultDialog()` from every `+` (built-in sidebar, Zen graph,
 * and CE's sidebar when skill embeds are proxied).
 */
export default function UploadVaultDialog() {
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [ingest, setIngest] = useState<boolean>(() => loadIngestPref());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onOpen = () => {
      setFiles([]);
      setError(null);
      setIngest(loadIngestPref());
      setOpen(true);
    };
    window.addEventListener(OPEN_UPLOAD_VAULT_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_UPLOAD_VAULT_EVENT, onOpen);
  }, []);

  const close = useCallback(() => {
    if (!busy) setOpen(false);
  }, [busy]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;

  const onPick = (ev: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(ev.target.files ?? []);
    ev.target.value = "";
    if (picked.length === 0) return;
    setFiles((prev) => {
      const byName = new Map(prev.map((f) => [f.name, f]));
      for (const f of picked) byName.set(f.name, f);
      return Array.from(byName.values());
    });
  };

  const onToggle = (v: boolean) => {
    setIngest(v);
    saveIngestPref(v);
  };

  const onUpload = async () => {
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const result = await uploadToVault(files, ingest);
      const out = describeUploadResult(result);
      toast(out.text, { err: out.err });
      if (out.openRunId) {
        window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
          detail: { run_id: out.openRunId },
        }));
      }
      setOpen(false);
    } catch (e) {
      setError(`Upload failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sy-confirm-backdrop" onClick={close}>
      <div
        className="sy-confirm sy-upload-vault"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sy-upload-vault-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="sy-upload-vault-title" className="sy-confirm-title">
          Add files to the vault
        </div>
        <div className="sy-confirm-body">
          <p className="sy-upload-vault-hint">
            Files are saved in <code className="sy-confirm-path">vault/raw/</code>.
          </p>
          <button
            type="button"
            className="sy-confirm-btn"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            autoFocus
          >
            {files.length ? "Add more files…" : "Choose files…"}
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            data-testid="upload-vault-input"
            onChange={onPick}
          />
          {files.length > 0 && (
            <ul className="sy-upload-vault-list">
              {files.map((f) => (
                <li key={f.name}>
                  <span className="sy-upload-vault-name">{f.name}</span>
                  <span className="sy-upload-vault-size">{fmtSize(f.size)}</span>
                  <button
                    type="button"
                    className="sy-upload-vault-remove"
                    aria-label={`Remove ${f.name}`}
                    title="Remove"
                    disabled={busy}
                    onClick={() => setFiles((p) => p.filter((x) => x !== f))}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <label className="sy-upload-vault-check">
            <input
              type="checkbox"
              checked={ingest}
              disabled={busy}
              onChange={(e) => onToggle(e.target.checked)}
            />
            <span>Ingest automatically</span>
          </label>
          {error && <p className="sy-upload-vault-error" role="alert">{error}</p>}
        </div>
        <div className="sy-confirm-actions">
          <button type="button" className="sy-confirm-btn" onClick={close} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="sy-confirm-btn sy-confirm-btn--primary"
            onClick={() => void onUpload()}
            disabled={busy || files.length === 0}
          >
            {busy ? "Uploading…" : files.length > 1 ? `Upload ${files.length} files` : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
