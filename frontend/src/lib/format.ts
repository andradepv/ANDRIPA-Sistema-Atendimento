import type { OrderStatus, RequestStatus, RequestType, TableStatus } from "../api/types";

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

export const requestTypeLabel: Record<RequestType, string> = {
  CHAMAR_ATENDENTE: "Chamou o atendente",
  NOVO_PEDIDO: "Novo pedido",
  PEDIR_CONTA: "Pediu a conta",
};

export const requestStatusLabel: Record<RequestStatus, string> = {
  PENDENTE: "Aguardando",
  ASSUMIDA: "Assumido",
  EM_ATENDIMENTO: "Em atendimento",
  CONCLUIDA: "Concluído",
  CANCELADA: "Cancelado",
};

export const orderStatusLabel: Record<OrderStatus, string> = {
  RECEBIDO: "Recebido",
  EM_PREPARO: "Em preparo",
  PRONTO: "Pronto",
  ENTREGUE: "Entregue",
  CANCELADO: "Cancelado",
};

export const tableStatusLabel: Record<TableStatus, string> = {
  LIVRE: "Livre",
  OCUPADA: "Ocupada",
  ENCERRAMENTO_SOLICITADO: "Pediu a conta",
};

export const paymentLabel: Record<string, string> = {
  DINHEIRO: "Dinheiro",
  CARTAO_CREDITO: "Cartão de crédito",
  CARTAO_DEBITO: "Cartão de débito",
  PIX: "Pix",
  OUTRO: "Outro",
};
