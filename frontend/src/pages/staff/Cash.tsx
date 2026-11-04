import { useCallback, useEffect, useState } from "react";
import { api, ApiError, errorMessage, newIdempotencyKey } from "../../api/http";
import type { Page, SessionDetail, SessionHistory, Table } from "../../api/types";
import { Dialog, Empty, useNow, useToast } from "../../components/ui";
import { clock, dateTime, elapsed, requestStatusLabel, requestTypeLabel, tableStatusLabel } from "../../lib/format";
import { Field } from "../../components/ui";
import { useStaff } from "./StaffData";

/** Caixa: mesas abertas, quem pediu a conta e o encerramento (que libera a mesa e revoga o acesso do cliente). */
export function CashPanel() {
  const { tables } = useStaff();
  const now = useNow();
  const tz = useStaff().me.establishment.timezone;
  const wanted = Number(new URLSearchParams(location.search).get("mesa"));
  const open = tables
    .filter((t) => t.session)
    .sort((a, b) => (a.status === "ENCERRAMENTO_SOLICITADO" ? 0 : 1) - (b.status === "ENCERRAMENTO_SOLICITADO" ? 0 : 1) || a.number - b.number);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  useEffect(() => {
    if (wanted && !selectedId) {
      const t = tables.find((x) => x.number === wanted && x.session);
      if (t) setSelectedId(t.id);
    }
  }, [wanted, tables, selectedId]);
  const selected = open.find((t) => t.id === selectedId) ?? null;

  return (
    <div className="cash">
      <section aria-labelledby="c-h" className="cash__list">
        <h1 id="c-h" className="s-h1">Mesas abertas</h1>
        {open.length === 0 ? <Empty>Nenhuma mesa aberta no momento.</Empty> : (
          <ul className="stack">
            {open.map((t) => (
              <li key={t.id}>
                <button className={`cash-row tt-${t.status}`} aria-pressed={t.id === selectedId} onClick={() => setSelectedId(t.id)}>
                  <span className="cash-row__num">Mesa {t.number}</span>
                  <span>{tableStatusLabel[t.status]}</span>
                  <span className="muted">
                    {t.session?.label ?? ""} aberta às {clock(t.session!.opened_at, tz)} ({elapsed(t.session!.opened_at, now)})
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="cash__detail" aria-live="polite">
        {selected ? <SessionPanel table={selected} onClosed={() => setSelectedId(null)} /> : <Empty>Escolha uma mesa para ver os chamados e encerrar o atendimento.</Empty>}
      </section>
    </div>
  );
}

function SessionPanel({ table, onClosed }: { table: Table; onClosed: () => void }) {
  const { me, requests, can } = useStaff();
  const toast = useToast();
  const [d, setD] = useState<SessionDetail | null>(null);
  const [closing, setClosing] = useState(false);
  const tz = me.establishment.timezone;
  const sid = table.session!.id;

  const load = useCallback(async () => {
    try {
      setD(await api<SessionDetail>(`/table-sessions/${sid}`));
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  }, [sid, toast]);

  // Recarrega quando os chamados desta mesa mudam em tempo real.
  const sig = requests.filter((r) => r.session_id === sid).map((r) => r.id + r.version).join() + table.version;
  useEffect(() => {
    void load();
  }, [load, sig]);

  if (!d) return <p className="empty">Carregando mesa…</p>;
  return (
    <div className="stack">
      <h2 className="s-h1">
        Mesa {d.table_number} {d.label && <span className="muted">({d.label})</span>}
      </h2>
      <p className="muted">
        Aberta às {clock(d.opened_at, tz)} por {d.opened_by_name}
        {d.close_requested_at && ` · conta pedida às ${clock(d.close_requested_at, tz)}`}
      </p>
      {d.requests.length === 0 ? <Empty>Nenhum chamado nesta mesa.</Empty> : (
        <table className="bill-table">
          <thead>
            <tr>
              <th scope="col">Chamado</th>
              <th scope="col">Hora</th>
              <th scope="col">Situação</th>
              <th scope="col">Responsável</th>
            </tr>
          </thead>
          <tbody>
            {d.requests.map((r) => (
              <tr key={r.id}>
                <td>{requestTypeLabel[r.type]}</td>
                <td>{clock(r.created_at, tz)}</td>
                <td>{requestStatusLabel[r.status]}</td>
                <td>{r.assigned_to_name ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {can("tables.close") && (
        <button className="btn btn--primary" onClick={() => setClosing(true)}>
          Encerrar atendimento e liberar mesa
        </button>
      )}
      <CloseDialog
        detail={d}
        open={closing}
        onClose={() => setClosing(false)}
        onDone={() => {
          setClosing(false);
          toast(`Mesa ${d.table_number} encerrada e liberada.`, "ok");
          onClosed();
        }}
        onStale={() => void load()}
      />
    </div>
  );
}

function CloseDialog(props: { detail: SessionDetail; open: boolean; onClose: () => void; onDone: () => void; onStale: () => void }) {
  const d = props.detail;
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState<string | null>(null);
  const active = d.requests.filter((r) => ["PENDENTE", "ASSUMIDA", "EM_ATENDIMENTO"].includes(r.status) && r.type !== "PEDIR_CONTA").length;

  const submit = async () => {
    setBusy(true);
    const k = key ?? newIdempotencyKey("close");
    setKey(k);
    try {
      await api(`/table-sessions/${d.id}/close`, { idempotencyKey: k, body: { expected_version: d.version } });
      setKey(null);
      props.onDone();
    } catch (e) {
      if (!(e instanceof ApiError && e.code === "network_error")) setKey(null);
      if (e instanceof ApiError && e.code === "stale_version") props.onStale();
      toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={props.open} title={`Encerrar a mesa ${d.table_number}`} onClose={props.onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <p>A mesa volta a ficar livre e o QR Code e a etiqueta NFC deixam de funcionar até a próxima abertura.</p>
        {active > 0 && <p className="warn-box" role="note">{active} chamado(s) ainda aberto(s) serão cancelados.</p>}
        <p className="muted small">Ao encerrar, o celular dos clientes desta mesa perde o acesso imediatamente.</p>
        <div className="dialog__actions">
          <button type="button" className="btn btn--ghost" onClick={props.onClose}>
            Voltar
          </button>
          <button className="btn btn--primary" disabled={busy}>
            {busy ? "Encerrando…" : "Encerrar atendimento"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function History() {
  const { me } = useStaff();
  const toast = useToast();
  const [page, setPage] = useState<Page<SessionHistory> | null>(null);
  const [offset, setOffset] = useState(0);
  const [mesa, setMesa] = useState("");
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const tz = me.establishment.timezone;

  useEffect(() => {
    const q = new URLSearchParams({ limit: "30", offset: String(offset) });
    if (mesa) q.set("table_number", mesa);
    api<Page<SessionHistory>>(`/table-sessions?${q}`).then(setPage).catch((e) => toast(errorMessage(e), "error"));
  }, [offset, mesa, toast]);

  return (
    <section>
      <h1 className="s-h1">Histórico de mesas</h1>
      <div className="inline">
        <Field label="Filtrar por mesa">
          <input inputMode="numeric" value={mesa} onChange={(e) => { setMesa(e.target.value.replace(/\D/g, "")); setOffset(0); }} />
        </Field>
      </div>
      {!page ? <p className="empty">Carregando…</p> : page.items.length === 0 ? <Empty>Nenhuma mesa encerrada ainda.</Empty> : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Mesa</th>
                <th scope="col">Aberta</th>
                <th scope="col">Encerrada</th>
                <th scope="col">Encerrada por</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((s) => (
                <tr key={s.id}>
                  <td>
                    <button className="link-btn" onClick={() => api<SessionDetail>(`/table-sessions/${s.id}`).then(setDetail)}>
                      {s.table_number} {s.label && `· ${s.label}`}
                    </button>
                  </td>
                  <td>{dateTime(s.opened_at, tz)}</td>
                  <td>{s.closed_at ? dateTime(s.closed_at, tz) : "—"}</td>
                  <td>{s.closed_by_name ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <button className="btn btn--small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 30))}>
              Anteriores
            </button>
            <span className="muted">
              {offset + 1}–{offset + page.items.length} de {page.total}
            </span>
            <button className="btn btn--small" disabled={offset + 30 >= page.total} onClick={() => setOffset(offset + 30)}>
              Próximos
            </button>
          </div>
        </>
      )}
      <Dialog open={!!detail} title={detail ? `Mesa ${detail.table_number} — ${detail.closed_at ? dateTime(detail.closed_at, tz) : ""}` : ""} onClose={() => setDetail(null)} wide>
        {detail && (
          <div className="stack">
            {detail.requests.length === 0 ? <p className="muted">Nenhum chamado nesta sessão.</p> : (
              <ul className="stack">
                {detail.requests.map((r) => (
                  <li key={r.id}>
                    {clock(r.created_at, tz)} — {requestTypeLabel[r.type]} ({requestStatusLabel[r.status]})
                    {r.assigned_to_name && ` · ${r.assigned_to_name}`}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Dialog>
    </section>
  );
}
