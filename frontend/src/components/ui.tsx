// Componentes acessíveis próprios (ver docs/adr/0003): HTML semântico, foco visível, aria-live.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

// ---------- Dialog (elemento <dialog> nativo: foco preso e Esc já tratados pelo navegador) ----------
export function Dialog(props: { open: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (props.open && !d.open) d.showModal();
    if (!props.open && d.open) d.close();
  }, [props.open]);
  return (
    <dialog
      ref={ref}
      className={props.wide ? "dialog dialog--wide" : "dialog"}
      onClose={props.onClose}
      aria-labelledby="dialog-title"
      onClick={(e) => {
        if (e.target === ref.current) props.onClose();
      }}
    >
      <div className="dialog__body">
        <header className="dialog__head">
          <h2 id="dialog-title">{props.title}</h2>
          <button type="button" className="icon-btn" onClick={props.onClose} aria-label="Fechar">
            ×
          </button>
        </header>
        {props.open && props.children}
      </div>
    </dialog>
  );
}

// ---------- Toasts (região aria-live) ----------
type Toast = { id: number; text: string; tone: "ok" | "error" | "info" };
const ToastCtx = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-3), { id, text, tone }]);
    window.setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast toast--${t.tone}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

// ---------- relógio para "tempo decorrido" ----------
export function useNow(intervalMs = 15000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function ConnectionBadge({ status }: { status: string }) {
  const label =
    status === "online" ? "Ao vivo" : status === "connecting" ? "Conectando…" : status === "ended" ? "Desconectado" : "Sem conexão — tentando de novo";
  return (
    <span className={`conn conn--${status}`} role="status">
      <span className="conn__dot" aria-hidden="true" />
      {label}
    </span>
  );
}

export function Field(props: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field__label">{props.label}</span>
      {props.children}
      {props.hint && <span className="field__hint">{props.hint}</span>}
    </label>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
