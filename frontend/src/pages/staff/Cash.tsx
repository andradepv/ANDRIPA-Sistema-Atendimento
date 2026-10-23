import { useCallback, useEffect, useState } from "react";
import { api, ApiError, errorMessage, newIdempotencyKey } from "../../api/http";
import type { Page, PaymentMethod, SessionDetail, SessionHistory, Table } from "../../api/types";
import { Dialog, Empty, Field, useNow, useToast } from "../../components/ui";
import { clock, dateTime, elapsed, money, orderStatusLabel, paymentLabel, tableStatusLabel } from "../../lib/format";
import { useStaff } from "./StaffData";

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
        {selected ? <SessionPanel table={selected} onClosed={() => setSelectedId(null)} /> : <Empty>Escolha uma mesa para ver a comanda.</Empty>}
      </section>
    </div>
  );
}

function SessionPanel({ table, onClosed }: { table: Table; onClosed: () => void }) {
  const { me, orders, requests } = useStaff();
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

  // Recarrega quando pedidos/chamados desta mesa mudam em tempo real.
  const sig = orders.filter((o) => o.session_id === sid).map((o) => o.id + o.version).join() +
    requests.filter((r) => r.session_id === sid).map((r) => r.id + r.version).join() + table.version;
  useEffect(() => {
    void load();
  }, [load, sig]);

  if (!d) return <p className="empty">Carregando comanda…</p>;
  return (
    <div className="stack">
      <h2 className="s-h1">
        Comanda — mesa {d.table_number} {d.label && <span className="muted">({d.label})</span>}
      </h2>
      <p className="muted">
        Aberta às {clock(d.opened_at, tz)} por {d.opened_by_name}
        {d.close_requested_at && ` · conta pedida às ${clock(d.close_requested_at, tz)}`}
      </p>
      {d.orders.length === 0 ? <Empty>Sem pedidos registrados pelo sistema nesta mesa.</Empty> : (
        <table className="bill-table">
          <thead>
            <tr>
              <th scope="col">Pedido</th>
              <th scope="col">Itens</th>
              <th scope="col">Situação</th>
              <th scope="col" className="num">Valor</th>
            </tr>
          </thead>
          <tbody>
            {d.orders.map((o) => (
              <tr key={o.id} className={o.status === "CANCELADO" ? "is-cancelled" : ""}>
                <td>
                  nº {o.number}
                  <br />
                  <span className="muted small">{clock(o.created_at, tz)}</span>
                </td>
                <td>
                  {o.items.map((i) => (
                    <div key={i.id}>
                      {i.quantity}× {i.product_name}
                      {i.options.length > 0 && <span className="muted"> + {i.options.map((x) => x.name).join(", ")}</span>}
                    </div>
                  ))}
                </td>
                <td>{orderStatusLabel[o.status]}</td>
                <td className="num">{money(o.total_cents)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={3}>Subtotal</th>
              <td className="num"><strong>{money(d.subtotal_cents)}</strong></td>
            </tr>
          </tfoot>
        </table>
      )}
      {d.pending_orders > 0 && (
        <p className="warn-box" role="note">
          {d.pending_orders} pedido(s) ainda não entregue(s). Entregue ou cancele antes de fechar, ou informe o motivo para cancelá-los no fechamento.
        </p>
      )}
      <button className="btn btn--primary" onClick={() => setClosing(true)}>
        Fechar conta e liberar mesa
      </button>
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
  const [method, setMethod] = useState<PaymentMethod>("PIX");
  const [coupon, setCoupon] = useState("");
  const [cancelPending, setCancelPending] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    const k = key ?? newIdempotencyKey("close");
    setKey(k);
    try {
      await api(`/table-sessions/${d.id}/close`, {
        idempotencyKey: k,
        body: {
          payment_method: method,
          coupon_code: coupon || null,
          pending_orders_policy: cancelPending ? "cancel_pending" : "block",
          note: note || null,
          expected_version: d.version,
        },
      });
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
    <Dialog open={props.open} title={`Fechar a mesa ${d.table_number}`} onClose={props.onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <p>
          Subtotal <strong>{money(d.subtotal_cents)}</strong>. O total final, com cupom, é calculado pelo sistema.
        </p>
        <Field label="Forma de pagamento" hint="Apenas registro — o pagamento é feito na maquininha ou no caixa.">
          <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
            {Object.entries(paymentLabel).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Cupom (opcional)">
          <input value={coupon} onChange={(e) => setCoupon(e.target.value.toUpperCase())} maxLength={32} />
        </Field>
        {d.pending_orders > 0 && (
          <>
            <label className="opt">
              <input type="checkbox" checked={cancelPending} onChange={(e) => setCancelPending(e.target.checked)} />
              <span>Cancelar os {d.pending_orders} pedido(s) não entregue(s)</span>
            </label>
            {cancelPending && (
              <Field label="Motivo do cancelamento">
                <input value={note} onChange={(e) => setNote(e.target.value)} required maxLength={280} />
              </Field>
            )}
          </>
        )}
        <p className="muted small">Ao fechar, o celular dos clientes desta mesa perde o acesso imediatamente.</p>
        <div className="dialog__actions">
          <button type="button" className="btn btn--ghost" onClick={props.onClose}>
            Voltar
          </button>
          <button className="btn btn--primary" disabled={busy || (d.pending_orders > 0 && !cancelPending)}>
            {busy ? "Fechando…" : "Fechar conta"}
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
                <th scope="col">Por</th>
                <th scope="col">Pagamento</th>
                <th scope="col" className="num">Total</th>
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
                  <td>{s.payment_method ? paymentLabel[s.payment_method] : "—"}</td>
                  <td className="num">{s.total_cents != null ? money(s.total_cents) : "—"}</td>
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
            <p>
              Subtotal {money(detail.subtotal_cents)} · desconto {money(detail.discount_cents)} · <strong>total {money(detail.total_cents)}</strong>
            </p>
            <ul className="stack">
              {detail.orders.map((o) => (
                <li key={o.id}>
                  nº {o.number} ({orderStatusLabel[o.status]}): {o.items.map((i) => `${i.quantity}× ${i.product_name}`).join(", ")} — {money(o.total_cents)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Dialog>
    </section>
  );
}
