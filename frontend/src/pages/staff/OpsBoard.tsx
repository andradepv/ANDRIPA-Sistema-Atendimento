import { useEffect, useMemo, useState } from "react";
import { api, errorMessage, newIdempotencyKey } from "../../api/http";
import type { ServiceRequest, Table } from "../../api/types";
import { Dialog, Empty, Field, useNow, useToast } from "../../components/ui";
import { clock, elapsed, requestStatusLabel, requestTypeLabel, tableStatusLabel } from "../../lib/format";
import { navigate } from "../../lib/router";
import { useStaff } from "./StaffData";

const rank = { PENDENTE: 0, ASSUMIDA: 1, EM_ATENDIMENTO: 2, CONCLUIDA: 3, CANCELADA: 3 } as const;

export function sortRequests(list: ServiceRequest[]): ServiceRequest[] {
  return [...list].sort(
    (a, b) => rank[a.status] - rank[b.status] || b.priority - a.priority || a.created_at.localeCompare(b.created_at),
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

/** Mesas na posição que ocupam no salão (planta ativa); mesas sem posição vêm logo abaixo. */
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
  const current = selected ? tables.find((t) => t.id === selected.id) ?? selected : null;
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
    </div>
  );
}

function tileAlerts(t: Table): string {
  const parts = [];
  if (t.pending_calls) parts.push("chamou");
  if (t.pending_orders) parts.push(`${t.pending_orders} pedido${t.pending_orders > 1 ? "s" : ""}`);
  return parts.join(" · ");
}

/** O único botão que resolve a solicitação: atendido, repassado à cozinha ou conta finalizada. */
function DoneButton({ r, small = true }: { r: ServiceRequest; small?: boolean }) {
  const { can, resync } = useStaff();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (r.type === "PEDIR_CONTA" && !can("tables.close")) return <span className="muted small">O caixa finaliza a conta</span>;
  const done = async () => {
    setBusy(true);
    try {
      await api(`/service-requests/${r.id}/complete`, { body: {} });
      if (r.type === "PEDIR_CONTA") toast(`Conta da mesa ${r.table_number} finalizada. Mesa liberada.`, "ok");
    } catch (e) {
      toast(errorMessage(e), "error");
      void resync();
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className={`btn btn--primary${small ? " btn--small" : ""}`} disabled={busy} onClick={() => void done()}>
      {doneActionLabel[r.type]}
    </button>
  );
}

function RequestCard({ r }: { r: ServiceRequest }) {
  const { me } = useStaff();
  const now = useNow();
  const tz = me.establishment.timezone;
  return (
    <li className={`req req--${r.type}`}>
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
      {r.note && !r.order && <p className="req__note">“{r.note}”</p>}
      <div className="req__actions">
        {r.status === "PENDENTE" && (
          <button className="btn btn--primary btn--small" disabled={busy} onClick={() => void act("claim")}>
            Assumir
          </button>
        )}
        {r.status === "ASSUMIDA" && (mine || supervisor) && (
          <button className="btn btn--small" disabled={busy} onClick={() => void act("start")}>
            Iniciar atendimento
          </button>
        )}
        {isBill ? (
          can("tables.close") && (
            <button className="btn btn--small" onClick={() => navigate(`/caixa?mesa=${r.table_number}`)}>
              Fechar conta
            </button>
          )
        ) : (
          r.status !== "PENDENTE" &&
          (mine || supervisor) && (
            <button className="btn btn--small" disabled={busy} onClick={() => void act("complete")}>
              Concluir
            </button>
          )
        )}
        {supervisor && (
          <select
            className="select-small"
            aria-label="Prioridade"
            value={r.priority}
            onChange={(e) => void act("priority", { priority: Number(e.target.value) })}
          >
            <option value={0}>Normal</option>
            <option value={1}>Prioridade 1</option>
            <option value={2}>Prioridade 2</option>
            <option value={3}>Urgente</option>
          </select>
        )}
      </div>
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
          {i.notes && <span className="order__note">“{i.notes}”</span>}
        </li>
      ))}
      {r.order.note && <li className="order__note">“{r.order.note}”</li>}
    </ul>
  );
}

function elapsedClass(iso: string, now: number): string {
  const min = (now - new Date(iso).getTime()) / 60000;
  return min >= 5 ? "elapsed elapsed--late" : min >= 2 ? "elapsed elapsed--warn" : "elapsed";
}

function TableDialog({ table, onClose }: { table: Table | null; onClose: () => void }) {
  const { me, can, requests } = useStaff();
  const toast = useToast();
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [keyState, setKey] = useState<string | null>(null);
  const tz = me.establishment.timezone;

export function TableDetail({ tableId }: { tableId: string }) {
  const { me, can, tables, requests } = useStaff();
  const toast = useToast();
  const table = tables.find((t) => t.id === tableId);
  const [current, setCurrent] = useState<SessionDetail | null>(null);
  const [closing, setClosing] = useState(false);
  const [busy, setBusy] = useState(false);
  const tz = me.establishment.timezone;
  const sid = table?.session?.id ?? null;

  // Recarrega o atendimento atual quando algo desta mesa muda em tempo real.
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
          {table.name && <span className="muted"> · {table.name}</span>}
        </h1>
        <span className={`pill tt-${table.status}`}>{table.status === "LIVRE" ? "Livre" : table.bill_requested ? "Pediu a conta" : "Ocupada"}</span>
      </header>

      {table.status === "LIVRE" ? (
        <div className="stack">
          <p className="muted">Mesa livre. Para liberar, use o botão abaixo ou “Liberar mesa” na página da mesa (QR Code) com o seu PIN.</p>
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
                · resolvido às {clock(r.completed_at, tz)}
                {r.completed_by_name && ` por ${r.completed_by_name}`}
              </span>
            )}
          </div>
          {r.order && <OrderLines r={r} />}
          {actions && r.status === "PENDENTE" && (
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

  const sReqs = table.session ? requests.filter((r) => r.session_id === table.session!.id) : [];

  return (
    <section className="stack">
      <h2 className="s-h2">Atendimentos anteriores</h2>
      {!page ? (
        <p className="empty">Carregando…</p>
      ) : page.items.length === 0 ? (
        <Empty>Nenhum atendimento encerrado nesta mesa ainda.</Empty>
      ) : (
        <div className="stack">
          <dl className="facts">
            <div>
              <dt>Situação</dt>
              <dd>{tableStatusLabel[table.status]}</dd>
            </div>
            <div>
              <dt>Aberta às</dt>
              <dd>
                {table.session && clock(table.session.opened_at, tz)} por {table.session?.opened_by_name}
              </dd>
            </div>
            {table.session?.label && (
              <div>
                <dt>Identificação</dt>
                <dd>{table.session.label}</dd>
              </div>
            )}
            {me.establishment.join_code_required && table.session?.join_code && (
              <div>
                <dt>Código para o cliente</dt>
                <dd className="join-code">{table.session.join_code}</dd>
              </div>
            )}
          </dl>
          <p>{sReqs.length} chamado(s) aberto(s) nesta mesa.</p>
          <div className="dialog__actions">
            {table.status === "OCUPADA" && can("tables.request_close") && (
              <button className="btn" onClick={() => void requestClose()}>
                Registrar pedido de conta
              </button>
            )}
            {can("cash.view") && (
              <button className="btn btn--primary" onClick={() => navigate(`/caixa?mesa=${table.number}`)}>
                Ir para o caixa
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
