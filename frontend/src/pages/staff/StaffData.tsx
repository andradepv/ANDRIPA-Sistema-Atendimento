// Estado operacional compartilhado pelos painéis: snapshot REST + eventos em tempo real.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../../api/http";
import type { Layout, Me, Page, RealtimeEvent, ServiceRequest, Table, Tag } from "../../api/types";
import { openSocket, upsertVersioned, type SocketStatus } from "../../realtime/socket";

interface StaffData {
  me: Me;
  tables: Table[];
  /** Solicitações aguardando resposta (chamados, pedidos e contas). */
  requests: ServiceRequest[];
  /** Planta ativa do salão (null enquanto carrega). */
  layout: Layout | null;
  /** Gravações de etiqueta NFC recentes/em andamento (só administradores recebem a lista). */
  tags: Tag[];
  conn: SocketStatus;
  resync: () => Promise<void>;
  can: (perm: string) => boolean;
}

const Ctx = createContext<StaffData | null>(null);
export const useStaff = () => {
  const v = useContext(Ctx);
  if (!v) throw new Error("StaffDataProvider ausente");
  return v;
};

const ACTIVE = new Set(["PENDENTE", "ASSUMIDA", "EM_ATENDIMENTO"]);

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
  const [layout, setLayout] = useState<Layout | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [conn, setConn] = useState<SocketStatus>("connecting");
  const known = useRef(new Set<string>());

  const resync = useCallback(async () => {
    const [t, r, l, g] = await Promise.all([
      api<Table[]>("/tables"),
      api<Page<ServiceRequest>>("/service-requests?active=true&limit=500"),
      api<Layout>("/layouts/active").catch(() => null),
      me.permissions.includes("tables.provision") ? api<Tag[]>("/admin/tags").catch(() => []) : Promise.resolve([] as Tag[]),
    ]);
    setLayout((cur) => (l && cur && cur.id === l.id && cur.version > l.version ? cur : l));
    setTags(g);
    setTables(t);
    setRequests(r.items);
    r.items.forEach((x) => known.current.add(x.id));
  }, [me]);

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
        } else if (ev.type === "session.closed") {
          const sid = d.session_id as string;
          setRequests((cur) => cur.filter((x) => x.session_id !== sid));
        } else if (ev.type === "layout.updated") {
          // Só a planta ATIVA vale para o Salão; trocar de planta ou mover mesas chega a todos na hora.
          const l = d.layout as Layout;
          if (l.is_active) setLayout((cur) => (cur && cur.id === l.id && cur.version > l.version ? cur : l));
        } else if (ev.type === "tag.updated") {
          const g = d.tag as Tag;
          if (me.permissions.includes("tables.provision")) {
            setTags((cur) => {
              const next = upsertVersioned(cur, g).filter((x) => x.status !== "SUBSTITUIDA");
              return next.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
            });
          }
        }
      },
    });
  }, [resync, onSessionEnded, me]);

  // Título da aba mostra chamados pendentes (útil com o painel em segundo plano).
  const pending = requests.length;
  useEffect(() => {
    document.title = pending ? `(${pending}) Andripa — Painel` : "Andripa — Painel";
  }, [pending]);

  const can = useCallback((p: string) => me.permissions.includes(p), [me]);
  return (
    <Ctx.Provider value={{ me, tables, requests, layout, tags, conn, resync, can }}>{children}</Ctx.Provider>
  );
}
