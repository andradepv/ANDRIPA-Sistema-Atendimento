// WebSocket com reconexão (backoff exponencial + jitter), heartbeat e deduplicação por id de evento.
// A cada (re)conexão o chamador recebe `onOpen` e deve recarregar o estado pelo REST:
// eventos perdidos durante a queda são recuperados pelo snapshot, nunca presumidos.

import type { RealtimeEvent } from "../api/types";

export type SocketStatus = "connecting" | "online" | "offline" | "ended";

export interface SocketOptions {
  path: string; // ex.: /api/v1/ws/staff
  authToken?: string; // clientes: token enviado na 1ª mensagem (nunca na URL)
  onEvent: (ev: RealtimeEvent) => void;
  onOpen?: () => void;
  onStatus?: (s: SocketStatus) => void;
  onEnded?: (code: number) => void; // 4001 sessão encerrada, 4003 não autorizado
}

export function openSocket(opts: SocketOptions): () => void {
  let ws: WebSocket | null = null;
  let attempt = 0;
  let stopped = false;
  let retryTimer: number | undefined;
  let pingTimer: number | undefined;
  const seen = new Set<number>();
  const seenOrder: number[] = [];

  const status = (s: SocketStatus) => opts.onStatus?.(s);

  const connect = () => {
    if (stopped) return;
    status("connecting");
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}${opts.path}`);
    ws.onopen = () => {
      if (opts.authToken) ws?.send(JSON.stringify({ type: "auth", token: opts.authToken }));
    };
    ws.onmessage = (m) => {
      let msg: RealtimeEvent;
      try {
        msg = JSON.parse(m.data as string) as RealtimeEvent;
      } catch {
        return;
      }
      if (msg.type === "hello") {
        attempt = 0;
        status("online");
        opts.onOpen?.();
        window.clearInterval(pingTimer);
        pingTimer = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('{"type":"ping"}'), 20000);
        return;
      }
      if (msg.type === "ping") {
        ws?.send('{"type":"pong"}');
        return;
      }
      if (msg.type === "pong") return;
      if (typeof msg.id === "number") {
        if (seen.has(msg.id)) return;
        seen.add(msg.id);
        seenOrder.push(msg.id);
        if (seenOrder.length > 2000) seen.delete(seenOrder.shift()!);
      }
      opts.onEvent(msg);
    };
    ws.onclose = (ev) => {
      window.clearInterval(pingTimer);
      ws = null;
      if (stopped) return;
      if (ev.code === 4001 || ev.code === 4003) {
        status("ended");
        opts.onEnded?.(ev.code);
        return;
      }
      status("offline");
      const delay = Math.min(30000, 1000 * 2 ** attempt) * (0.5 + Math.random() * 0.5);
      attempt += 1;
      retryTimer = window.setTimeout(connect, delay);
    };
  };

  const onOnline = () => {
    if (!ws && !stopped) {
      window.clearTimeout(retryTimer);
      attempt = 0;
      connect();
    }
  };
  window.addEventListener("online", onOnline);
  connect();

  return () => {
    stopped = true;
    window.removeEventListener("online", onOnline);
    window.clearTimeout(retryTimer);
    window.clearInterval(pingTimer);
    ws?.close(1000);
  };
}

/** Insere/atualiza por id respeitando a versão (eventos atrasados não sobrescrevem dados novos). */
export function upsertVersioned<T extends { id: string; version: number }>(list: T[], item: T): T[] {
  const i = list.findIndex((x) => x.id === item.id);
  if (i === -1) return [...list, item];
  if ((list[i]?.version ?? 0) > item.version) return list;
  const copy = list.slice();
  copy[i] = item;
  return copy;
}
