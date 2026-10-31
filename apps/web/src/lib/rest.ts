// The few REST calls the UI makes: uploads are multipart and dead letters are an admin endpoint, neither of which
// GraphQL offers. Shapes follow contracts/openapi.yaml (Problem, UploadResult, DeadLetter).
export type Problem = { type: string; title: string; status: number; detail: string | null; code: string;
  duplicate_of?: string | null; duplicate_of_url?: string | null; current_version?: number | null };
export type UploadedInvoice = { id: string; status: string; original_filename: string };
export type UploadResult = { filename: string; status: number; invoice: UploadedInvoice | null; problem: Problem | null };
export type UploadResponse = { status: number; replayed: boolean; retryAfter: string | null; results: UploadResult[] };
export type DeadLetter = { id: string; task_name: string; invoice_id: string; error_code: string; exception_chain: string;
  attempts: number; created_at: string; replayed_at: string | null };

/** POST /v1/invoices. A one-file answer (202 invoice or a problem) is turned into the same list a 207 gives. */
export async function uploadInvoices(files: File[], idempotencyKey: string): Promise<UploadResponse> {
  const body = new FormData();
  files.forEach(f => body.append("files", f, f.name));
  const res = await fetch("/v1/invoices", { method: "POST", body, headers: { "Idempotency-Key": idempotencyKey } });
  const json = await res.json();
  const replayed = res.headers.get("Idempotent-Replayed") === "true";
  const retryAfter = res.headers.get("Retry-After");
  if (res.status === 207) return { status: 207, replayed, retryAfter, results: json.results };
  const ok = res.status < 300;
  const results = files.length === 1 || ok
    ? [{ filename: files[0]?.name ?? "", status: res.status, invoice: ok ? json : null, problem: ok ? null : json }]
    : [{ filename: `${files.length} files`, status: res.status, invoice: null, problem: json }];
  return { status: res.status, replayed, retryAfter, results };
}

export async function listDeadLetters(cursor?: string | null): Promise<{ data: DeadLetter[]; next_cursor: string | null }> {
  const res = await fetch(`/v1/admin/dead-letters?limit=25${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
  if (!res.ok) throw await res.json();
  return res.json();
}

/** 202 queued again, 200 already replayed earlier, 409 the same file was stored since. */
export async function replayDeadLetter(id: string): Promise<{ status: number; body: DeadLetter | Problem }> {
  const res = await fetch(`/v1/admin/dead-letters/${id}/replay`, { method: "POST" });
  return { status: res.status, body: await res.json() };
}
