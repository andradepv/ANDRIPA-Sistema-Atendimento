import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage, newIdempotencyKey } from "../../api/http";
import type { CustomerSession, PublicTable, RealtimeEvent, ServiceRequest } from "../../api/types";
import { Dialog, useToast } from "../../components/ui";
import { clock, requestStatusLabel } from "../../lib/format";
import { openSocket, upsertVersioned, type SocketStatus } from "../../realtime/socket";

const tokenKey = (code: string) => `andripa:tok:${code}`;
function loadToken(code: string): string | null {
  try {
    return localStorage.getItem(tokenKey(code));
  } catch {
    return null;
  }
}
function saveToken(code: string, tok: string | null): void {
  try {
    if (tok) localStorage.setItem(tokenKey(code), tok);
    else localStorage.removeItem(tokenKey(code));
  } catch {
    /* modo privado: o token fica só em memória */
  }
}

type Phase =
  | { kind: "loading" }
  | { kind: "notfound" }
  | { kind: "unavailable"; table: PublicTable }
  | { kind: "join"; table: PublicTable }
  | { kind: "ended"; table: PublicTable | null }
  | { kind: "active"; token: string };

export function CustomerApp({ code }: { code: string }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [table, setTable] = useState<PublicTable | null>(null);

  const check = useCallback(async () => {
    try {
      const t = await api<PublicTable>(`/public/tables/${code}`);
      setTable(t);
      document.title = `Mesa ${t.table_number} · ${t.establishment_name}`;
      if (!t.available) {
        saveToken(code, null);
        setPhase({ kind: "unavailable", table: t });
        return;
      }
      const tok = loadToken(code);
      if (tok) {
        setPhase({ kind: "active", token: tok });
        return;
      }
      if (t.join_code_required) setPhase({ kind: "join", table: t });
      else await join(undefined, t);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setPhase({ kind: "notfound" });
      else setPhase({ kind: "ended", table: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const join = async (joinCode: string | undefined, t: PublicTable) => {
    const r = await api<{ token: string }>(`/public/tables/${code}/join`, {
      body: joinCode ? { join_code: joinCode } : {},
    });
    saveToken(code, r.token);
    setPhase({ kind: "active", token: r.token });
    void t;
  };

  useEffect(() => {
    void check();
  }, [check]);

  const onEnded = useCallback(() => {
    saveToken(code, null);
    setPhase({ kind: "ended", table });
  }, [code, table]);

  if (phase.kind === "loading") return <Splash text="Abrindo a mesa…" />;
  if (phase.kind === "notfound")
    return <Splash title="Mesa não encontrada" text="Leia o QR Code de novo ou aproxime o celular da etiqueta da mesa." />;
  if (phase.kind === "unavailable")
    return (
      <Splash
        title={`Mesa ${phase.table.table_number}`}
        text="Esta mesa ainda não está aberta para atendimento digital. Peça a um atendente para abrir a mesa e leia o QR Code novamente."
        action={{ label: "Verificar de novo", onClick: () => void check() }}
        establishment={phase.table.establishment_name}
      />
    );
  if (phase.kind === "ended")
    return (
      <Splash
        title="Atendimento encerrado"
        text="A conta desta mesa foi fechada. Obrigado pela visita! Se você ainda está na mesa, peça para abri-la de novo."
        action={{ label: "Verificar de novo", onClick: () => void check() }}
        establishment={phase.table?.establishment_name}
      />
    );
  if (phase.kind === "join") return <JoinScreen table={phase.table} onJoin={(c) => join(c, phase.table)} />;
  return <ActiveSession token={phase.token} onEnded={onEnded} />;
}

function Splash(props: {
  title?: string;
  text: string;
  establishment?: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <main className="c-shell c-center">
      <div className="tile-band" aria-hidden="true" />
      {props.establishment && <p className="c-est">{props.establishment}</p>}
      {props.title && <h1 className="c-title">{props.title}</h1>}
      <p className="c-lead">{props.text}</p>
      {props.action && (
        <button className="btn btn--primary" onClick={props.action.onClick}>
          {props.action.label}
        </button>
      )}
    </main>
  );
}

function JoinScreen({ table, onJoin }: { table: PublicTable; onJoin: (code: string) => Promise<void> }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <main className="c-shell c-center">
      <div className="tile-band" aria-hidden="true" />
      <p className="c-est">{table.establishment_name}</p>
      <h1 className="c-title">Mesa {table.table_number}</h1>
      <form
        className="join"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await onJoin(value);
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label htmlFor="jc">Digite o código de 4 números que o atendente informou</label>
        <input
          id="jc"
          className="join__code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="\d{4}"
          maxLength={4}
          value={value}
          onChange={(e) => setValue(e.target.value.replace(/\D/g, ""))}
          aria-invalid={!!error}
          aria-describedby={error ? "jc-err" : undefined}
          required
        />
        {error && (
          <p id="jc-err" className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="btn btn--primary btn--block" disabled={busy || value.length !== 4}>
          {busy ? "Entrando…" : "Entrar na mesa"}
        </button>
      </form>
    </main>
  );
}

// ---------------------------------------------------------------------------------------------

function ActiveSession({ token, onEnded }: { token: string; onEnded: () => void }) {
  const toast = useToast();
  const [s, setS] = useState<CustomerSession | null>(null);
  const [conn, setConn] = useState<SocketStatus>("connecting");

  const ended = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) {
        onEnded();
        return true;
      }
      return false;
    },
    [onEnded],
  );

  const refresh = useCallback(async () => {
    try {
      setS(await api<CustomerSession>("/public/session", { bearer: token }));
    } catch (e) {
      if (!ended(e)) toast(errorMessage(e), "error");
    }
  }, [token, ended, toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    return openSocket({
      path: "/api/v1/ws/customer",
      authToken: token,
      onStatus: setConn,
      onOpen: () => void refresh(),
      onEnded: () => onEnded(),
      onEvent: (ev: RealtimeEvent) => {
        if (ev.type === "session.closed") onEnded();
        else if (ev.type === "request.updated") {
          const r = ev.data!.request as ServiceRequest;
          setS((cur) => (cur ? { ...cur, requests: upsertVersioned(cur.requests, r) } : cur));
        }
      },
    });
  }, [token, refresh, onEnded]);

  if (!s) return <Splash text="Carregando…" />;

  return (
    <div className="c-shell">
      <header className="c-head">
        <div className="tile-band tile-band--thin" aria-hidden="true" />
        <div className="c-head__row">
          <div>
            <p className="c-est">{s.establishment_name}</p>
            <h1 className="c-table">
              Mesa {s.table_number}
              {s.table_name ? <span className="c-table__name"> {s.table_name}</span> : null}
            </h1>
          </div>
          {conn !== "online" && <span className="c-offline">{conn === "connecting" ? "Conectando…" : "Sem conexão"}</span>}
        </div>
      </header>
      <main className="c-main">
        <HomeTab s={s} token={token} onChanged={refresh} onEnded={ended} />
      </main>
    </div>
  );
}

function activeOf(s: CustomerSession, type: ServiceRequest["type"]): ServiceRequest | undefined {
  return s.requests.find((r) => r.type === type && ["PENDENTE", "ASSUMIDA", "EM_ATENDIMENTO"].includes(r.status));
}

function HomeTab(props: {
  s: CustomerSession;
  token: string;
  onChanged: () => Promise<void>;
  onEnded: (e: unknown) => boolean;
}) {
  const { s } = props;
  const toast = useToast();
  const [confirm, setConfirm] = useState<null | "CHAMAR_ATENDENTE" | "PEDIR_CONTA">(null);
  const [busy, setBusy] = useState(false);
  const keyRef = useRef<string | null>(null);
  const call = activeOf(s, "CHAMAR_ATENDENTE");
  const bill = activeOf(s, "PEDIR_CONTA");
  const billRequested = !!bill || s.table_status === "ENCERRAMENTO_SOLICITADO";

  const send = async () => {
    if (!confirm) return;
    setBusy(true);
    keyRef.current ??= newIdempotencyKey("req");
    try {
      await api("/public/service-requests", { body: { type: confirm }, bearer: props.token, idempotencyKey: keyRef.current });
      keyRef.current = null;
      toast(confirm === "PEDIR_CONTA" ? "Pedido de conta enviado ao caixa." : "Chamado enviado. Um atendente já foi avisado.", "ok");
      setConfirm(null);
      await props.onChanged();
    } catch (e) {
      if (!props.onEnded(e)) toast(errorMessage(e), "error"); // mantém a mesma chave: repetir é seguro
    } finally {
      setBusy(false);
    }
  };

  const cancelCall = async () => {
    if (!call) return;
    try {
      await api(`/public/service-requests/${call.id}/cancel`, { body: {}, bearer: props.token });
      await props.onChanged();
    } catch (e) {
      if (!props.onEnded(e)) toast(errorMessage(e), "error");
    }
  };

  return (
    <section aria-labelledby="home-h">
      <h2 id="home-h" className="sr-only">
        Atendimento
      </h2>
      <div className="big-actions">
        <button className="big-btn big-btn--call" onClick={() => setConfirm("CHAMAR_ATENDENTE")} disabled={!!call}>
          <span className="big-btn__title">{call ? "Atendente a caminho" : "Chamar atendente"}</span>
          <span className="big-btn__sub">
            {call ? `${requestStatusLabel[call.status]} · ${call.assigned_to_name ?? "aguardando"}` : "Um toque avisa a equipe"}
          </span>
        </button>
        <button className="big-btn big-btn--bill" onClick={() => setConfirm("PEDIR_CONTA")} disabled={billRequested}>
          <span className="big-btn__title">{billRequested ? "Conta solicitada" : "Pedir a conta"}</span>
          <span className="big-btn__sub">{billRequested ? "O caixa já foi avisado" : "Avisa o caixa"}</span>
        </button>
      </div>

      {call?.status === "PENDENTE" && (
        <p className="c-note">
          Chamou por engano?{" "}
          <button className="link-btn" onClick={() => void cancelCall()}>
            Cancelar chamado
          </button>
        </p>
      )}

      <h3 className="c-h3">Acompanhamento</h3>
      {s.requests.length === 0 ? (
        <p className="empty">Nada por aqui ainda. Seus chamados aparecem aqui em tempo real.</p>
      ) : (
        <ul className="timeline">
          {[...s.requests]
            .sort((a, b) => b.created_at.localeCompare(a.created_at))
            .slice(0, 12)
            .map((x) => (
              <li key={x.id} className={`timeline__item st-${x.status}`}>
                <span>{x.type === "PEDIR_CONTA" ? "Conta" : "Chamado"}</span>
                <span className="pill">{requestStatusLabel[x.status]}</span>
                <time>{clock(x.created_at, s.timezone)}</time>
              </li>
            ))}
        </ul>
      )}

      <Dialog open={!!confirm} title={confirm === "PEDIR_CONTA" ? "Pedir a conta?" : "Chamar um atendente?"} onClose={() => setConfirm(null)}>
        <p>
          {confirm === "PEDIR_CONTA"
            ? `O caixa receberá o pedido de fechamento da mesa ${s.table_number}. Você ainda pode chamar o atendente depois.`
            : `Um atendente virá até a mesa ${s.table_number}.`}
        </p>
        <div className="dialog__actions">
          <button className="btn btn--ghost" onClick={() => setConfirm(null)}>
            Voltar
          </button>
          <button className="btn btn--primary" onClick={() => void send()} disabled={busy}>
            {busy ? "Enviando…" : confirm === "PEDIR_CONTA" ? "Pedir a conta" : "Chamar atendente"}
          </button>
        </div>
      </Dialog>
    </section>
  );
}
