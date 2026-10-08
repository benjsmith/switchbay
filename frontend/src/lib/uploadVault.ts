/**
 * Graph sidebar `+` upload: files go to the daemon's POST /api/upload-vault,
 * which saves them in `<workspace>/vault/raw/` and, when asked, queues
 * ingest. Kept free of React so the payload and the remembered choice are
 * testable under plain Node.
 */

/** localStorage key for the dialog's "Ingest automatically" checkbox.
 *  Switchbay has no global auto-ingest setting (watch folders are a
 *  per-folder list), so the default is off and the last choice sticks. */
export const INGEST_PREF_KEY = "sy.uploadVault.ingest";

export const UPLOAD_VAULT_URL = "/api/upload-vault";

export type UploadIngestRun = { file: string; run_id: string; vault_path: string };

export type UploadIngestInfo = {
  requested: boolean;
  /** local_ingest = CE extraction, agent = rail ingest agent, none = saved only. */
  backend: "local_ingest" | "agent" | "none";
  queued: boolean;
  runs: UploadIngestRun[];
  message?: string;
};

export type UploadVaultResult = {
  ok?: boolean;
  saved?: string[];
  ingest?: UploadIngestInfo;
  error?: string;
};

type PrefStore = Pick<Storage, "getItem" | "setItem">;

function defaultStore(): PrefStore | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function loadIngestPref(store: PrefStore | null = defaultStore()): boolean {
  try {
    return store?.getItem(INGEST_PREF_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveIngestPref(value: boolean, store: PrefStore | null = defaultStore()): void {
  try {
    store?.setItem(INGEST_PREF_KEY, value ? "1" : "0");
  } catch {
    /* private mode / quota — the choice just isn't remembered */
  }
}

/** Same multipart shape CE's edit.js sends (one `file` field per file),
 *  plus an `ingest` field. */
export function buildUploadForm(files: Iterable<File>, ingest: boolean): FormData {
  const form = new FormData();
  form.append("ingest", ingest ? "true" : "false");
  for (const f of files) form.append("file", f, f.name);
  return form;
}

export async function uploadToVault(
  files: File[],
  ingest: boolean,
  fetchImpl: typeof fetch = fetch,
): Promise<UploadVaultResult> {
  const res = await fetchImpl(UPLOAD_VAULT_URL, {
    method: "POST",
    body: buildUploadForm(files, ingest),
  });
  let body: UploadVaultResult = {};
  try {
    body = (await res.json()) as UploadVaultResult;
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

/** Toast text for a finished upload, and the run to open in Agents (only
 *  when an ingest agent was started; CE extraction has no transcript). */
export function describeUploadResult(r: UploadVaultResult): {
  text: string;
  err: boolean;
  openRunId: string | null;
} {
  const saved = r.saved ?? [];
  const what = saved.length === 1 ? saved[0] : `${saved.length} files`;
  const base = `Uploaded ${what} to vault/raw/`;
  const ing = r.ingest;
  if (!ing || !ing.requested) return { text: base, err: false, openRunId: null };
  if (!ing.queued) {
    return { text: ing.message || `${base}, not ingested`, err: true, openRunId: null };
  }
  if (ing.backend === "agent") {
    return {
      text: `${base}; ingest agent started`,
      err: false,
      openRunId: ing.runs[0]?.run_id ?? null,
    };
  }
  return { text: `${base}; ingest queued`, err: false, openRunId: null };
}

/** Ask the mounted UploadVaultDialog to open. */
export const OPEN_UPLOAD_VAULT_EVENT = "sy:upload-vault-open";

export function openUploadVaultDialog(): void {
  window.dispatchEvent(new CustomEvent(OPEN_UPLOAD_VAULT_EVENT));
}
