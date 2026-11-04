// Gravação de etiquetas NFC pelo próprio navegador (Web NFC: Chrome para Android, só em HTTPS).
// O endereço a gravar vem sempre do servidor; aqui só se grava, se lê de volta e (opcionalmente) se trava.

export type NfcErrorCode = "unsupported" | "denied" | "aborted" | "io" | "timeout" | "wrong_tag";

export class NfcError extends Error {
  constructor(
    public code: NfcErrorCode,
    message: string,
  ) {
    super(message);
  }
}

export const nfcSupported = (): boolean => typeof window !== "undefined" && "NDEFReader" in window;

/** Travar (somente leitura permanente) só existe em versões mais novas do Chrome. */
export const nfcLockSupported = (): boolean =>
  nfcSupported() && typeof NDEFReader.prototype.makeReadOnly === "function";

function mapError(e: unknown, timedOut: () => boolean): NfcError {
  if (e instanceof NfcError) return e;
  const name = (e as { name?: string })?.name;
  if (timedOut()) return new NfcError("timeout", "Tempo esgotado. Aproxime a etiqueta do celular e tente de novo.");
  if (name === "AbortError") return new NfcError("aborted", "Operação cancelada.");
  if (name === "NotAllowedError") {
    return new NfcError("denied", "O navegador não tem permissão para usar o NFC. Permita o NFC para este site e tente de novo.");
  }
  if (name === "NotSupportedError") {
    return new NfcError("unsupported", "Este celular ou navegador não suporta NFC. Use o Chrome em um Android com NFC ligado.");
  }
  return new NfcError("io", "Não foi possível falar com a etiqueta. Mantenha-a encostada no celular até terminar.");
}

/** Executa `fn` com um AbortSignal que expira sozinho; `cancel()` permite o usuário desistir. */
export function withTimeout<T>(ms: number, fn: (signal: AbortSignal) => Promise<T>): { promise: Promise<T>; cancel: () => void } {
  const ctl = new AbortController();
  let expired = false;
  const timer = window.setTimeout(() => {
    expired = true;
    ctl.abort();
  }, ms);
  const promise = fn(ctl.signal)
    .catch((e: unknown) => {
      throw mapError(e, () => expired);
    })
    .finally(() => window.clearTimeout(timer));
  return { promise, cancel: () => ctl.abort() };
}

function decodeUrl(records: ReadonlyArray<NDEFRecordRead>): string | null {
  for (const r of records) {
    if ((r.recordType === "url" || r.recordType === "absolute-url") && r.data) {
      return new TextDecoder().decode(r.data);
    }
  }
  return null;
}

export interface TagRead {
  uid: string;
  url: string | null;
}

/** Espera uma etiqueta ser aproximada e devolve seu UID e a URL gravada (se houver). */
export function readTag(signal: AbortSignal): Promise<TagRead> {
  return new Promise<TagRead>((resolve, reject) => {
    const reader = new NDEFReader();
    const stop = new AbortController();
    const done = (fn: () => void) => {
      stop.abort();
      fn();
    };
    signal.addEventListener("abort", () => done(() => reject(new DOMException("abort", "AbortError"))), { once: true });
    reader.onreading = (ev) => done(() => resolve({ uid: ev.serialNumber, url: decodeUrl(ev.message.records) }));
    reader.onreadingerror = () => done(() => reject(new NfcError("io", "A etiqueta foi aproximada, mas não pôde ser lida. Tente de novo.")));
    reader.scan({ signal: stop.signal }).catch((e: unknown) => done(() => reject(e)));
  });
}

/** Grava a URL (apaga o que houver) e devolve o resultado da conferência por leitura. */
export async function writeUrl(url: string, signal: AbortSignal): Promise<void> {
  if (!nfcSupported()) throw new NfcError("unsupported", "Este navegador não grava NFC. Use o Chrome em um Android com NFC.");
  await new NDEFReader().write({ records: [{ recordType: "url", data: url }] }, { overwrite: true, signal });
}

/** Trava a etiqueta (irreversível). Confere antes se é a etiqueta esperada. */
export async function lockTag(expectedUid: string, signal: AbortSignal): Promise<void> {
  if (!nfcLockSupported()) throw new NfcError("unsupported", "Este navegador não consegue travar etiquetas.");
  const seen = await readTag(signal);
  const norm = (u: string) => u.replace(/:/g, "").toUpperCase();
  if (norm(seen.uid) !== norm(expectedUid)) {
    throw new NfcError("wrong_tag", "Esta não é a etiqueta que acabou de ser gravada para esta mesa. Nada foi travado.");
  }
  await new NDEFReader().makeReadOnly?.({ signal });
}
