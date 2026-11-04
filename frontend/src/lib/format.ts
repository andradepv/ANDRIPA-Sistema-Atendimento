import type { RequestStatus, RequestType, ServiceRequest, TableStatus } from "../api/types";

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
export const money = (cents: number) => brl.format(cents / 100);

/** Datas chegam em UTC e são exibidas no fuso do estabelecimento. */
export function clock(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: tz }).format(new Date(iso));
}

export function dateTime(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: tz }).format(new Date(iso));
}

export function elapsed(iso: string, now: number): string {
  const s = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "agora";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h} h ${m % 60} min`;
}

export const tableStatusLabel: Record<TableStatus, string> = { LIVRE: "Livre", OCUPADA: "Ocupada" };

/** Como a equipe vê cada solicitação. */
export const requestTypeLabel: Record<RequestType, string> = {
  CHAMAR_ATENDENTE: "Chamou o atendente",
  NOVO_PEDIDO: "Pedido do cardápio",
  PEDIR_CONTA: "Pediu a conta",
};

/** O botão único que resolve cada tipo de solicitação. */
export const doneActionLabel: Record<RequestType, string> = {
  CHAMAR_ATENDENTE: "Atendido",
  NOVO_PEDIDO: "Repassado à cozinha",
  PEDIR_CONTA: "Conta finalizada",
};

const statusByType: Record<RequestType, Record<RequestStatus, string>> = {
  CHAMAR_ATENDENTE: { PENDENTE: "Aguardando", CONCLUIDA: "Atendido", CANCELADA: "Cancelado" },
  NOVO_PEDIDO: { PENDENTE: "Enviado", CONCLUIDA: "Repassado à cozinha", CANCELADA: "Não repassado" },
  PEDIR_CONTA: { PENDENTE: "Solicitada", CONCLUIDA: "Conta finalizada", CANCELADA: "Cancelada" },
};

export const requestStatusLabel = (r: Pick<ServiceRequest, "type" | "status">) => statusByType[r.type][r.status];

/** Título curto da solicitação na linha do tempo do cliente e do histórico. */
export function requestTitle(r: ServiceRequest): string {
  if (r.type === "NOVO_PEDIDO") return r.order ? `Pedido nº ${r.order.number}` : "Pedido";
  return r.type === "PEDIR_CONTA" ? "Conta" : "Chamado";
}

export function orderSummary(r: ServiceRequest): string {
  return (r.order?.items ?? []).map((i) => `${i.quantity}× ${i.product_name}`).join(", ");
}
