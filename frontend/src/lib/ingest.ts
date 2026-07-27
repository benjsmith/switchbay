/**
 * Stage a file into the vault + kick a background ingest agent. Returns
 * the run id (or null on failure). Shared by the Browser sidebar's `+`
 * (Power) and the graph toolbar's `+` (Zen) so both add-file affordances
 * behave identically.
 */
export async function ingestFile(file: File): Promise<string | null> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch("/api/ingest/from-upload", { method: "POST", body: form });
  if (!r.ok) return null;
  const body = (await r.json()) as { run_id?: string };
  return body.run_id ?? null;
}
