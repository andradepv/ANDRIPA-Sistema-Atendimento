// Estado operacional compartilhado pelos painéis: snapshot REST + eventos em tempo real.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../../api/http";
import type { Me, Order, Page, RealtimeEvent, ServiceRequest, Table } from "../../api/types";
import { openSocket, upsertVersioned, type SocketStatus } from "../../realtime/socket";

interface StaffData {
  me: Me;
  tables: Table[];
  requests: ServiceRequest[];
  orders: Order[];
  conn: SocketStatus;
  resync: () => Promise<void>;
  can: (perm: string) => boolean;
  menuVersion: number;
}

const Ctx = createContext<StaffData | null>(null);
export const useStaff = () => {
  const v = useContext(Ctx);
  if (!v) throw new Error("StaffDataProvider ausente");
  return v;
};

const ACTIVE = new Set(["PENDENTE", "ASSUMIDA", "EM_ATENDIMENTO"]);
const PENDING_ORDERS = new Set(["RECEBIDO", "EM_PREPARO", "PRONTO"]);

function beep(): void {
  try {
    const ctx = new AudioContext();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 880;
    g.gain.setValueAtTime(0.0001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.4);
    navigator.vibrate?.(150);
  } catch {
    /* sem áudio */
  }
}

export function StaffDataProvider({ me, children, onSessionEnded }: { me: Me; children: ReactNode; onSessionEnded: () => void }) {
  const [tables, setTables] = useState<Table[]>([]);
  const [requests, setRequests] = useState<ServiceRequest[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [conn, setConn] = useState<SocketStatus>("connecting");
  const [menuVersion, setMenuVersion] = useState(0);
  const known = useRef(new Set<string>());

  const resync = useCallback(async () => {
    const [t, r, o] = await Promise.all([
      api<Table[]>("/tables"),
      api<Page<ServiceRequest>>("/service-requests?active=true&limit=500"),
      api<Page<Order>>("/orders?active=true&limit=500"),
    ]);
    setTables(t);
    setRequests(r.items);
    setOrders(o.items);
    r.items.forEach((x) => known.current.add(x.id));
  }, []);

  useEffect(() => {
    void resync().catch(() => undefined);
    const t = window.setInterval(() => void resync().catch(() => undefined), 30000);
    return () => window.clearInterval(t);
  }, [resync]);

  useEffect(() => {
    return openSocket({
      path: "/api/v1/ws/staff",
      onStatus: setConn,
      onOpen: () => void resync().catch(() => undefined),
      onEnded: () => onSessionEnded(),
      onEvent: (ev: RealtimeEvent) => {
        const d = ev.data ?? {};
        if (ev.type === "table.updated") {
          setTables((cur) => upsertVersioned(cur, d.table as Table).sort((a, b) => a.number - b.number));
        } else if (ev.type === "request.updated") {
          const r = d.request as ServiceRequest;
          if (r.status === "PENDENTE" && !known.current.has(r.id)) beep();
          known.current.add(r.id);
          setRequests((cur) => {
            const next = upsertVersioned(cur, r);
            return next.filter((x) => ACTIVE.has(x.status));
          });
        } else if (ev.type === "order.updated") {
          const o = d.order as Order;
          setOrders((cur) => upsertVersioned(cur, o).filter((x) => PENDING_ORDERS.has(x.status)));
        } else if (ev.type === "session.closed") {
          const sid = d.session_id as string;
          setRequests((cur) => cur.filter((x) => x.session_id !== sid));
          setOrders((cur) => cur.filter((x) => x.session_id !== sid));
        } else if (ev.type === "menu.updated") {
          setMenuVersion((v) => v + 1);
        }
      },
    });
  }, [resync, onSessionEnded]);

  // Título da aba mostra chamados pendentes (útil com o painel em segundo plano).
  const pending = requests.filter((r) => r.status === "PENDENTE").length;
  useEffect(() => {
    document.title = pending ? `(${pending}) Andripa — Painel` : "Andripa — Painel";
  }, [pending]);

  const can = useCallback((p: string) => me.permissions.includes(p), [me]);
  return (
    <Ctx.Provider value={{ me, tables, requests, orders, conn, resync, can, menuVersion }}>{children}</Ctx.Provider>
  );
}
