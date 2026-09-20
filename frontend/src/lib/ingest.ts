/**
 * Stage a file into the vault + kick a background ingest agent. Returns
 * the run id (or null on failure). Shared by the Browser sidebar's `+`
 * (Power) and the graph toolbar's `+` (Zen) so both add-file affordances
 * behave identically.
 *
 * Prefer CE SSOT when the embed proxy is up (`/embed/ce/api/ingest/…`);
 * fall back to Switchbay's local `/api/ingest/from-upload` so drag-drop
 * still works without CE.
 */
async function postIngest(url: string, file: File): Promise<string | null> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(url, { method: "POST", body: form });
  if (!r.ok) return null;
  const body = (await r.json()) as { run_id?: string };
  return body.run_id ?? null;
}

export async function ingestFile(file: File): Promise<string | null> {
  try {
    const viaCe = await postIngest("/embed/ce/api/ingest/from-upload", file);
    if (viaCe) return viaCe;
  } catch {
    // CE down / proxy missing — fall through.
  }
  return postIngest("/api/ingest/from-upload", file);
}
