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
          Chamados <span className="count">{requests.length}</span>
        </h1>
        {requests.length === 0 ? <Empty>Nenhum chamado aberto. Novos chamados aparecem aqui na hora.</Empty> : (
          <ul className="queue">
            {sortRequests(requests).map((r) => (
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
      <TableDialog table={current} onClose={() => setSelected(null)} />
    </div>
  );
}

function RequestCard({ r }: { r: ServiceRequest }) {
  const { me, can, resync } = useStaff();
  const toast = useToast();
  const now = useNow();
  const [busy, setBusy] = useState(false);
  const tz = me.establishment.timezone;
  const mine = r.assigned_to_id === me.user.id;
  const supervisor = can("requests.prioritize");

  const act = async (action: string, body?: unknown) => {
    setBusy(true);
    try {
      await api(`/service-requests/${r.id}/${action}`, { body: body ?? {} });
    } catch (e) {
      toast(errorMessage(e), "error");
      void resync();
    } finally {
      setBusy(false);
    }
  };

  const isBill = r.type === "PEDIR_CONTA";
  return (
    <li className={`req req--${r.type} rs-${r.status}`}>
      <div className="req__top">
        <span className="req__table">Mesa {r.table_number}</span>
        <span className="req__type">{requestTypeLabel[r.type]}</span>
        {r.priority > 0 && <span className="req__prio">Prioridade {r.priority}</span>}
      </div>
      <div className="req__meta">
        <time dateTime={r.created_at}>{clock(r.created_at, tz)}</time>
        <span className={elapsedClass(r.created_at, now, r.status)}>há {elapsed(r.created_at, now)}</span>
        <span className="pill">{requestStatusLabel[r.status]}</span>
        {r.assigned_to_name && <span>{mine ? "com você" : `com ${r.assigned_to_name}`}</span>}
      </div>
      {r.note && <p className="req__note">“{r.note}”</p>}
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

function elapsedClass(iso: string, now: number, status: string): string {
  const min = (now - new Date(iso).getTime()) / 60000;
  if (status !== "PENDENTE") return "elapsed";
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

  if (!table) return <Dialog open={false} title="" onClose={onClose}>{null}</Dialog>;

  const open = async () => {
    setBusy(true);
    const key = keyState ?? newIdempotencyKey("open");
    setKey(key);
    try {
      await api(`/tables/${table.id}/open`, { body: { label: label || null, confirm_secret: secret }, idempotencyKey: key });
      toast(`Mesa ${table.number} aberta.`, "ok");
      setKey(null);
      setSecret("");
      setLabel("");
    } catch (e) {
      toast(errorMessage(e), "error");
      setKey(null); // erro definitivo (PIN errado, mesa já aberta): nova tentativa = nova operação
    } finally {
      setBusy(false);
    }
  };

  const requestClose = async () => {
    try {
      await api(`/tables/${table.id}/request-close`, { body: {} });
      toast(`Pedido de conta da mesa ${table.number} registrado.`, "ok");
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  const sReqs = table.session ? requests.filter((r) => r.session_id === table.session!.id) : [];

  return (
    <Dialog open title={`Mesa ${table.number}${table.name ? ` · ${table.name}` : ""}`} onClose={onClose}>
      {table.status === "LIVRE" ? (
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            void open();
          }}
        >
          <p>Abra a mesa quando o cliente se sentar. O QR Code e a etiqueta NFC passam a funcionar na hora.</p>
          <Field label="Identificação (opcional)" hint="Ex.: nome do cliente ou do grupo">
            <input value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label={me.user.has_pin ? "Seu PIN pessoal" : "Sua senha"} hint="Confirma que é você quem está abrindo a mesa.">
            <input
              type="password"
              inputMode={me.user.has_pin ? "numeric" : undefined}
              autoComplete="off"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              required
              minLength={4}
            />
          </Field>
          <button className="btn btn--primary btn--block" disabled={busy || !can("tables.open")}>
            {busy ? "Abrindo…" : "Abrir mesa"}
          </button>
        </form>
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
    </Dialog>
  );
}
