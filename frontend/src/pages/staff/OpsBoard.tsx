import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage, newIdempotencyKey } from "../../api/http";
import type { Page, ServiceRequest, SessionDetail, SessionHistory, Table } from "../../api/types";
import { Dialog, Empty, useNow, useToast } from "../../components/ui";
import { clock, dateTime, elapsed, getDoneActionLabel, money, requestStatusLabel, requestTitle, requestTypeLabel, tableStatusLabel } from "../../lib/format";
import { Link } from "../../lib/router";
import { useStaff } from "./StaffData";

const rank = { PENDENTE: 0, ASSUMIDA: 1, EM_ATENDIMENTO: 2, CONCLUIDA: 3, CANCELADA: 3 } as const;

export function sortRequests(list: ServiceRequest[]): ServiceRequest[] {
  return [...list].sort(
    (a, b) => rank[a.status] - rank[b.status] || (b.priority ?? 0) - (a.priority ?? 0) || a.created_at.localeCompare(b.created_at),
  );
}

function TableTile({ t, onClick }: { t: Table; onClick: (t: Table) => void }) {
  return (
    <button className={`table-tile tt-${t.status}`} onClick={() => onClick(t)}>
      <span className="table-tile__num">{t.number}</span>
      <span className="table-tile__status">{tableStatusLabel[t.status]}</span>
      {t.session?.label && <span className="table-tile__label">{t.session.label}</span>}
      {t.pending_requests > 0 && (
        <span className="table-tile__alerts">{`${t.pending_requests} chamado${t.pending_requests > 1 ? "s" : ""}`}</span>
      )}
    </button>
  );
}

/** Mesas na posição que ocupam no salão (planta ativa); mesas sem posição logo abaixo. */
function FloorPlan({ tables, onSelect }: { tables: Table[]; onSelect: (t: Table) => void }) {
  const { layout } = useStaff();
  const placed = useMemo(() => {
    const pos = new Map((layout?.items ?? []).map((i) => [i.table_id, i]));
    return tables.flatMap((t) => (pos.has(t.id) ? [{ t, x: pos.get(t.id)!.x, y: pos.get(t.id)!.y }] : []));
  }, [tables, layout]);
  const loose = tables.filter((t) => !placed.some((p) => p.t.id === t.id));
  if (placed.length === 0) return <TableList tables={tables} onSelect={onSelect} />;
  const minX = Math.min(...placed.map((p) => p.x));
  const minY = Math.min(...placed.map((p) => p.y));
  const maxX = Math.max(...placed.map((p) => p.x));
  const maxY = Math.max(...placed.map((p) => p.y));
  return (
    <>
      <p className="muted small">Planta: {layout?.name}</p>
      <div className="plan-scroll">
        <div
          className="plan"
          style={{ gridTemplateColumns: `repeat(${maxX - minX + 1}, minmax(104px, 1fr))`, gridTemplateRows: `repeat(${maxY - minY + 1}, auto)` }}
        >
          {placed.map(({ t, x, y }) => (
            <div key={t.id} style={{ gridColumn: x - minX + 1, gridRow: y - minY + 1 }}>
              <TableTile t={t} onClick={onSelect} />
            </div>
          ))}
        </div>
      </div>
      {loose.length > 0 && (
        <>
          <h2 className="s-h2">Sem posição na planta</h2>
          <TableList tables={loose} onSelect={onSelect} />
        </>
      )}
    </>
  );
}

function TableList({ tables, onSelect }: { tables: Table[]; onSelect: (t: Table) => void }) {
  return (
    <ul className="tables">
      {tables.map((t) => (
        <li key={t.id}>
          <TableTile t={t} onClick={onSelect} />
        </li>
      ))}
    </ul>
  );
}

const VIEW_KEY = "andripa.salao.view";

export function OpsBoard() {
  const { tables, requests, layout } = useStaff();
  const [selected, setSelected] = useState<Table | null>(null);
  const [view, setView] = useState<"planta" | "lista">("planta");
  const sorted = useMemo(() => sortRequests(requests), [requests]);

  useEffect(() => {
    try {
      if (localStorage.getItem(VIEW_KEY) === "lista") setView("lista");
    } catch {
      /* sem armazenamento: mantém a planta */
    }
  }, []);

  const choose = (v: "planta" | "lista") => {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* ignora */
    }
  };

  return (
    <div className="ops">
      <section className="ops__queue" aria-labelledby="q-h">
        <h1 id="q-h" className="s-h1">
          Solicitações <span className="count">{requests.length}</span>
        </h1>
        {requests.length === 0 ? (
          <Empty>Nada aguardando. Chamados, pedidos e pedidos de conta aparecem aqui na hora.</Empty>
        ) : (
          <ul className="queue">
            {sorted.map((r) => (
              <RequestCard key={r.id} r={r} />
            ))}
          </ul>
        )}
      </section>
      <section className="ops__tables" aria-labelledby="t-h">
        <div className="inline s-head">
          <h1 id="t-h" className="s-h1">Mesas</h1>
          {layout && layout.items.length > 0 && (
            <div className="seg" role="group" aria-label="Forma de exibir as mesas">
              <button className={view === "planta" ? "is-on" : ""} aria-pressed={view === "planta"} onClick={() => choose("planta")}>
                Planta
              </button>
              <button className={view === "lista" ? "is-on" : ""} aria-pressed={view === "lista"} onClick={() => choose("lista")}>
                Lista
              </button>
            </div>
          )}
        </div>
        {tables.length === 0 ? (
          <Empty>Nenhuma mesa cadastrada. Um administrador cadastra as mesas em Mesas.</Empty>
        ) : view === "planta" ? (
          <FloorPlan tables={tables} onSelect={setSelected} />
        ) : (
          <TableList tables={tables} onSelect={setSelected} />
        )}
      </section>
      {selected && <TableDetail tableId={selected.id} />}
    </div>
  );
}

/** Botão que avança ou resolve a solicitação: atendido, repassado à cozinha -> entregue, ou conta finalizada. */
function DoneButton({ r, small = true }: { r: ServiceRequest; small?: boolean }) {
  const { can, resync } = useStaff();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  if (r.type === "PEDIR_CONTA" && !can("tables.close")) {
    return <span className="muted small">O caixa finaliza a conta</span>;
  }

  const done = async () => {
    setBusy(true);
    try {
      await api(`/service-requests/${r.id}/complete`, { body: {} });
      if (r.type === "PEDIR_CONTA") toast(`Conta da mesa ${r.table_number} finalizada. Mesa liberada.`, "ok");
      else if (r.type === "NOVO_PEDIDO" && r.status === "PENDENTE") toast(`Pedido da mesa ${r.table_number} enviado para a cozinha.`, "ok");
      else if (r.type === "NOVO_PEDIDO" && r.status === "EM_ATENDIMENTO") toast(`Pedido da mesa ${r.table_number} marcado como entregue.`, "ok");
      else if (r.type === "LIBERAR_MESA") toast(`Mesa ${r.table_number} liberada.`, "ok");
    } catch (e) {
      toast(errorMessage(e), "error");
      void resync();
    } finally {
      setBusy(false);
    }
  };

  return (
    <button className={`btn btn--primary${small ? " btn--small" : ""}`} disabled={busy} onClick={() => void done()}>
      {getDoneActionLabel(r)}
    </button>
  );
}

function RequestCard({ r }: { r: ServiceRequest }) {
  const { me } = useStaff();
  const now = useNow();
  const tz = me.establishment.timezone;

  return (
    <li className={`req req--${r.type} rs-${r.status}`}>
      <div className="req__top">
        <Link to={`/painel/mesa/${r.table_id}`} className="req__table">
          Mesa {r.table_number}
        </Link>
        <span className="req__type">{requestTypeLabel[r.type]}</span>
      </div>
      <div className="req__meta">
        <time dateTime={r.created_at}>{clock(r.created_at, tz)}</time>
        <span className={elapsedClass(r.created_at, now)}>há {elapsed(r.created_at, now)}</span>
      </div>
      {r.order && <OrderLines r={r} />}
      {r.note && !r.order && <p className="req__note">{r.note}</p>}
      {(r.status === "PENDENTE" || r.status === "EM_ATENDIMENTO") && (
        <div className="req__actions">
          <DoneButton r={r} />
        </div>
      )}
    </li>
  );
}

function OrderLines({ r }: { r: ServiceRequest }) {
  if (!r.order) return null;
  return (
    <ul className="order__items">
      {r.order.items.map((i) => (
        <li key={i.id}>
          <span className="order__qty">{i.quantity}×</span> {i.product_name}
          {i.options.length > 0 && <span className="muted"> + {i.options.map((x) => x.name).join(", ")}</span>}
          {i.notes && <span className="order__note">{i.notes}</span>}
        </li>
      ))}
      {r.order.note && <li className="order__note">{r.order.note}</li>}
    </ul>
  );
}

function elapsedClass(iso: string, now: number): string {
  const min = (now - new Date(iso).getTime()) / 60000;
  return min >= 5 ? "elapsed elapsed--late" : min >= 2 ? "elapsed elapsed--warn" : "elapsed";
}

export function TableDetail({ tableId }: { tableId: string }) {
  const { me, can, tables, requests } = useStaff();
  const toast = useToast();
  const table = tables.find((t) => t.id === tableId);
  const [current, setCurrent] = useState<SessionDetail | null>(null);
  const [closing, setClosing] = useState(false);
  const [busy, setBusy] = useState(false);
  const tz = me.establishment.timezone;
  const sid = table?.session?.id ?? null;

  const sig = `${table?.version}|` + requests.filter((r) => r.table_id === tableId).map((r) => r.id + r.version).join();

  useEffect(() => {
    if (!sid) {
      setCurrent(null);
      return;
    }
    api<SessionDetail>(`/table-sessions/${sid}`).then(setCurrent).catch((e) => toast(errorMessage(e), "error"));
  }, [sid, sig, toast]);

  if (!table) return <p className="empty">Carregando mesa…</p>;

  const open = async () => {
    setBusy(true);
    try {
      await api(`/tables/${table.id}/open`, { body: {}, idempotencyKey: newIdempotencyKey("open") });
      toast(`Mesa ${table.number} liberada.`, "ok");
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const close = async () => {
    setBusy(true);
    try {
      await api(`/tables/${table.id}/close`, { body: {}, idempotencyKey: newIdempotencyKey("close") });
      toast(`Conta da mesa ${table.number} finalizada. Mesa liberada.`, "ok");
      setClosing(false);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack table-detail">
      <p>
        <Link to="/painel" className="link-btn">
          ← Salão
        </Link>
      </p>
      <header className="table-detail__head">
        <h1 className="s-h1">
          Mesa {table.number}
          {table.name && <span className="muted"> — {table.name}</span>}
        </h1>
        <span className={`pill tt-${table.status}`}>
          {table.status === "AGUARDANDO_LIBERACAO"
            ? "Mesa aguardando ser liberada"
            : table.status === "LIVRE"
              ? "Livre"
              : table.bill_requested
                ? "Pediu a conta"
                : "Ocupada"}
        </span>
      </header>
      {table.status !== "OCUPADA" ? (
        <div className="stack">
          <p className="muted">
            {table.status === "AGUARDANDO_LIBERACAO"
              ? 'Cliente aguardando atendimento na mesa. Aproxime o celular da etiqueta NFC/QR e toque em "Liberar mesa" com seu PIN, ou libere pelo botão abaixo.'
              : 'Mesa livre. Para liberar, use o botão abaixo ou "Liberar mesa" na página da mesa (QR Code) com o seu PIN.'}
          </p>
          {can("tables.open") && (
            <button className="btn btn--primary" disabled={busy} onClick={() => void open()}>
              Liberar mesa
            </button>
          )}
        </div>
      ) : (
        <div className="stack">
          <p>
            Liberada às <strong>{table.session && clock(table.session.opened_at, tz)}</strong> por {table.session?.opened_by_name}
          </p>
          <h2 className="s-h2">Atendimento atual</h2>
          {current ? <Timeline requests={current.requests} tz={tz} actions /> : <p className="empty">Carregando…</p>}
          {can("tables.close") && (
            <button className="btn" onClick={() => setClosing(true)}>
              Finalizar conta e liberar a mesa
            </button>
          )}
        </div>
      )}
      {can("history.view") && <TableHistory tableId={table.id} tz={tz} refreshKey={table.version} />}
      <p className="muted small">
        Página da mesa:{" "}
        <a href={table.public_url} target="_blank" rel="noreferrer">
          <code className="url">{table.public_url}</code>
        </a>
      </p>
      <Dialog open={closing} title={`Finalizar a conta da mesa ${table.number}?`} onClose={() => setClosing(false)}>
        <p>A mesa fica livre para os próximos clientes e os celulares desta mesa saem do atendimento.</p>
        <div className="dialog__actions">
          <button className="btn btn--ghost" onClick={() => setClosing(false)}>
            Voltar
          </button>
          <button className="btn btn--primary" disabled={busy} onClick={() => void close()}>
            {busy ? "Finalizando…" : "Conta finalizada"}
          </button>
        </div>
      </Dialog>
    </div>
  );
}

/** Linha do tempo de um atendimento: o que foi pedido e quando foi resolvido. */
function Timeline({ requests, tz, actions = false }: { requests: ServiceRequest[]; tz: string; actions?: boolean }) {
  if (requests.length === 0) return <Empty>Nenhuma solicitação neste atendimento.</Empty>;
  return (
    <ul className="queue">
      {requests.map((r) => (
        <li key={r.id} className={`req req--${r.type} rs-${r.status}`}>
          <div className="req__top">
            <span className="req__type">{requestTitle(r)}</span>
            <span className="pill">{requestStatusLabel(r)}</span>
            {r.order && <span className="muted">{money(r.order.total_cents)}</span>}
          </div>
          <div className="req__meta">
            <span>Pedido às {clock(r.created_at, tz)}</span>
            {r.completed_at && r.status === "CONCLUIDA" && (
              <span>
                — resolvido às {clock(r.completed_at, tz)}
                {r.completed_by_name && ` por ${r.completed_by_name}`}
              </span>
            )}
          </div>
          {r.order && <OrderLines r={r} />}
          {actions && (r.status === "PENDENTE" || r.status === "EM_ATENDIMENTO") && (
            <div className="req__actions">
              <DoneButton r={r} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function TableHistory({ tableId, tz, refreshKey }: { tableId: string; tz: string; refreshKey: number }) {
  const toast = useToast();
  const [page, setPage] = useState<Page<SessionHistory> | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);

  const load = useCallback(
    () => api<Page<SessionHistory>>(`/table-sessions?table_id=${tableId}&limit=10`).then(setPage),
    [tableId],
  );

  useEffect(() => {
    load().catch((e) => toast(errorMessage(e), "error"));
  }, [load, refreshKey, toast]);

  const toggle = async (id: string) => {
    if (openId === id) {
      setOpenId(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    try {
      setDetail(await api<SessionDetail>(`/table-sessions/${id}`));
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  return (
    <section className="stack">
      <h2 className="s-h2">Atendimentos anteriores</h2>
      {!page ? (
        <p className="empty">Carregando…</p>
      ) : page.items.length === 0 ? (
        <Empty>Nenhum atendimento encerrado nesta mesa ainda.</Empty>
      ) : (
        <ul className="history">
          {page.items.map((h) => (
            <li key={h.id}>
              <button className="history__row" aria-expanded={openId === h.id} onClick={() => void toggle(h.id)}>
                <span>{dateTime(h.opened_at, tz)}</span>
                <span className="muted">{h.requests_count} registro(s)</span>
              </button>
              {openId === h.id && (detail ? <Timeline requests={detail.requests} tz={tz} /> : <p className="empty">Carregando…</p>)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}