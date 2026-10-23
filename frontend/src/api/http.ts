// Cliente HTTP único. Funcionários: cookie HttpOnly + cabeçalho CSRF. Clientes: Bearer da sessão da mesa.

export const API = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1] ?? "") : null;
}

export function newIdempotencyKey(prefix: string): string {
  const rnd = crypto.getRandomValues(new Uint8Array(12));
  return `${prefix}-${Array.from(rnd, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  bearer?: string | null;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? (opts.body === undefined ? "GET" : "POST");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.bearer) headers.Authorization = `Bearer ${opts.bearer}`;
  else if (method !== "GET") {
    const csrf = readCookie("andripa_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(API + path, {
      method,
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      credentials: "same-origin",
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Sem conexão com o servidor. Verifique a internet e tente de novo.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data as { error?: { code: string; message: string; details?: Record<string, unknown> } })?.error;
    if (res.status === 401 && !opts.bearer && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Erro ${res.status}`, err?.details ?? {});
  }
  return data as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const errs = (e.details as { errors?: { msg: string }[] }).errors;
    if (e.code === "validation_error" && errs?.length) return errs.map((x) => x.msg.replace(/^Value error, /, "")).join("; ");
    return e.message;
  }
  return "Algo deu errado. Tente novamente.";
}
