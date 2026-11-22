import type { RequestStatus, RequestType, ServiceRequest, TableStatus, TagStatus } from "../api/types";

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

export const tableStatusLabel: Record<TableStatus, string> = {
  LIVRE: "Livre",
  AGUARDANDO_LIBERACAO: "Mesa aguardando ser liberada",
  OCUPADA: "Ocupada",
};

export const requestTypeLabel: Record<RequestType, string> = {
  LIBERAR_MESA: "Liberar mesa",
  CHAMAR_ATENDENTE: "Chamar atendente",
  NOVO_PEDIDO: "Novo pedido",
  PEDIR_CONTA: "Pedir a conta",
};

export function getDoneActionLabel(r: Pick<ServiceRequest, "type" | "status">): string {
  if (r.type === "NOVO_PEDIDO") {
    return r.status === "EM_ATENDIMENTO" ? "Marcar como entregue" : "Repassado à cozinha";
  }
  if (r.type === "LIBERAR_MESA") return "Liberar mesa";
  if (r.type === "PEDIR_CONTA") return "Conta finalizada";
  return "Atendido";
}

const statusByType: Record<RequestType, Record<RequestStatus, string>> = {
  LIBERAR_MESA: {
    PENDENTE: "Aguardando liberação",
    EM_ATENDIMENTO: "Liberando",
    CONCLUIDA: "Liberada",
    CANCELADA: "Cancelada",
  },
  CHAMAR_ATENDENTE: {
    PENDENTE: "Aguardando",
    EM_ATENDIMENTO: "Em atendimento",
    CONCLUIDA: "Atendido",
    CANCELADA: "Cancelado",
  },
  NOVO_PEDIDO: {
    PENDENTE: "Enviado",
    EM_ATENDIMENTO: "Na cozinha",
    CONCLUIDA: "Entregue",
    CANCELADA: "Não repassado",
  },
  PEDIR_CONTA: {
    PENDENTE: "Solicitada",
    EM_ATENDIMENTO: "Fechando",
    CONCLUIDA: "Conta finalizada",
    CANCELADA: "Cancelada",
  },
};

export const requestStatusLabel = (r: Pick<ServiceRequest, "type" | "status">) => statusByType[r.type][r.status];

export function requestTitle(r: ServiceRequest): string {
  if (r.type === "NOVO_PEDIDO") return r.order ? `Pedido nº ${r.order.number}` : "Pedido";
  if (r.type === "LIBERAR_MESA") return "Liberação da mesa";
  return r.type === "PEDIR_CONTA" ? "Conta" : "Chamado";
}

export function orderSummary(r: ServiceRequest): string {
  return (r.order?.items ?? []).map((i) => `${i.quantity}× ${i.product_name}`).join(", ");
}

export const tagStatusLabel: Record<TagStatus, string> = {
  PENDENTE: "Aguardando gravação",
  GRAVANDO: "Gravando agora",
  GRAVADA: "Gravada e conferida",
  TRAVADA: "Gravada e travada",
  FALHA: "Falhou",
  SUBSTITUIDA: "Substituída",
};
