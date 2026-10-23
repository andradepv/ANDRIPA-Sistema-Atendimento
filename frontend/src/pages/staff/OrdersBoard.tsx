import { useState } from "react";
import { api, errorMessage } from "../../api/http";
import type { Order, OrderStatus } from "../../api/types";
import { Dialog, Empty, Field, useNow, useToast } from "../../components/ui";
import { clock, elapsed, money, orderStatusLabel } from "../../lib/format";
import { useStaff } from "./StaffData";

const COLUMNS: OrderStatus[] = ["RECEBIDO", "EM_PREPARO", "PRONTO"];
const NEXT: Partial<Record<OrderStatus, { to: OrderStatus; label: string }>> = {
  RECEBIDO: { to: "EM_PREPARO", label: "Começar preparo" },
  EM_PREPARO: { to: "PRONTO", label: "Marcar como pronto" },
  PRONTO: { to: "ENTREGUE", label: "Entregue na mesa" },
};

export function OrdersBoard() {
  const { orders } = useStaff();
  return (
    <section aria-labelledby="o-h">
      <h1 id="o-h" className="s-h1">Pedidos em andamento</h1>
      {orders.length === 0 ? (
        <Empty>Nenhum pedido em andamento. Pedidos feitos pelo celular dos clientes chegam aqui.</Empty>
      ) : (
        <div className="kanban">
          {COLUMNS.map((c) => {
            const list = orders.filter((o) => o.status === c).sort((a, b) => a.created_at.localeCompare(b.created_at));
            return (
              <div key={c} className="kanban__col">
                <h2 className="kanban__title">
                  {orderStatusLabel[c]} <span className="count">{list.length}</span>
                </h2>
                <ul className="stack">
                  {list.map((o) => (
                    <OrderCard key={o.id} o={o} />
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function OrderCard({ o }: { o: Order }) {
  const { me, can, resync } = useStaff();
  const toast = useToast();
  const now = useNow();
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const next = NEXT[o.status];

  const move = async (status: OrderStatus, why?: string) => {
    setBusy(true);
    try {
      await api(`/orders/${o.id}/status`, { body: { status, reason: why ?? null, expected_version: o.version } });
      setCancelling(false);
    } catch (e) {
      toast(errorMessage(e), "error");
      void resync();
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="order">
      <div className="order__head">
        <strong>Mesa {o.table_number}</strong>
        <span>nº {o.number}</span>
        <time dateTime={o.created_at}>
          {clock(o.created_at, me.establishment.timezone)} · há {elapsed(o.created_at, now)}
        </time>
      </div>
      <ul className="order__items">
        {o.items.map((i) => (
          <li key={i.id}>
            <span className="order__qty">{i.quantity}×</span> {i.product_name}
            {i.options.length > 0 && <span className="muted"> + {i.options.map((x) => x.name).join(", ")}</span>}
            {i.notes && <span className="order__note">“{i.notes}”</span>}
          </li>
        ))}
      </ul>
      {o.note && <p className="order__note">“{o.note}”</p>}
      <div className="order__foot">
        <span>{money(o.total_cents)}</span>
        <div className="req__actions">
          {can("orders.cancel") && (
            <button className="btn btn--ghost btn--small" onClick={() => setCancelling(true)}>
              Cancelar
            </button>
          )}
          {next && (
            <button className="btn btn--primary btn--small" disabled={busy} onClick={() => void move(next.to)}>
              {next.label}
            </button>
          )}
        </div>
      </div>
      <Dialog open={cancelling} title={`Cancelar pedido nº ${o.number}?`} onClose={() => setCancelling(false)}>
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            void move("CANCELADO", reason);
          }}
        >
          <Field label="Motivo" hint="Fica registrado na auditoria.">
            <input value={reason} onChange={(e) => setReason(e.target.value)} required maxLength={280} />
          </Field>
          <div className="dialog__actions">
            <button type="button" className="btn btn--ghost" onClick={() => setCancelling(false)}>
              Voltar
            </button>
            <button className="btn btn--danger" disabled={busy || !reason}>
              Cancelar pedido
            </button>
          </div>
        </form>
      </Dialog>
    </li>
  );
}
