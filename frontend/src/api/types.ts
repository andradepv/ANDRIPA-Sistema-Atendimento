// Espelho dos contratos Pydantic do backend (app/schemas). Mantenha sincronizado com o OpenAPI.

export type Role = "ADMIN" | "CAIXA" | "ATENDENTE";
export type TableStatus = "LIVRE" | "OCUPADA";
export type RequestType = "CHAMAR_ATENDENTE" | "NOVO_PEDIDO" | "PEDIR_CONTA";
export type RequestStatus = "PENDENTE" | "CONCLUIDA" | "CANCELADA";

export interface User {
  id: string;
  name: string;
  username: string;
  role: Role;
  active: boolean;
}

export interface Establishment {
  id: string;
  name: string;
  timezone: string;
  orders_enabled: boolean;
}

export interface Me {
  user: User;
  permissions: string[];
  establishment: Establishment;
  csrf_token: string;
}

export interface SessionBrief {
  id: string;
  opened_at: string;
  opened_by_name: string;
}

export interface Table {
  id: string;
  number: number;
  name: string | null;
  status: TableStatus;
  active: boolean;
  public_url: string;
  version: number;
  session: SessionBrief | null;
  pending_calls: number;
  pending_orders: number;
  bill_requested: boolean;
}

export interface OrderItem {
  id: string;
  product_id: string;
  product_name: string;
  unit_price_cents: number;
  quantity: number;
  options: { option_id: string; group: string; name: string; price_cents: number }[];
  notes: string | null;
  line_total_cents: number;
}

export interface Order {
  id: string;
  number: number;
  note: string | null;
  total_cents: number;
  items: OrderItem[];
}

/** Chamado, pedido ou pedido de conta: só é feito e depois resolvido. */
export interface ServiceRequest {
  id: string;
  session_id: string;
  table_id: string;
  table_number: number;
  table_name: string | null;
  type: RequestType;
  status: RequestStatus;
  note: string | null;
  order: Order | null;
  created_at: string;
  completed_at: string | null;
  completed_by_name: string | null;
  version: number;
}

export interface Option {
  id: string;
  name: string;
  price_cents: number;
  active: boolean;
}

export interface OptionGroup {
  id: string;
  name: string;
  min_select: number;
  max_select: number;
  options: Option[];
}

export interface Product {
  id: string;
  category_id: string;
  name: string;
  description: string | null;
  price_cents: number;
  image_url: string | null;
  available: boolean;
  active: boolean;
  position: number;
  option_groups: OptionGroup[];
}

export interface Category {
  id: string;
  name: string;
  position: number;
  active: boolean;
}

export interface MenuCategory {
  id: string;
  name: string;
  products: Product[];
}

export interface SessionDetail {
  id: string;
  table_id: string;
  table_number: number;
  table_name: string | null;
  status: "OPEN" | "CLOSED";
  opened_at: string;
  opened_by_name: string;
  closed_at: string | null;
  closed_by_name: string | null;
  requests: ServiceRequest[];
}

export interface SessionHistory {
  id: string;
  table_id: string;
  table_number: number;
  opened_at: string;
  closed_at: string | null;
  opened_by_name: string;
  closed_by_name: string | null;
  requests_count: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface PublicTable {
  establishment_name: string;
  timezone: string;
  table_number: number;
  table_name: string | null;
  available: boolean;
  orders_enabled: boolean;
}

export interface CustomerSession {
  session_id: string;
  establishment_name: string;
  timezone: string;
  table_number: number;
  table_name: string | null;
  orders_enabled: boolean;
  opened_at: string;
  requests: ServiceRequest[];
  push_public_key: string | null;
}

export interface Notice {
  id: string;
  title: string;
  message: string | null;
  active: boolean;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  actor_name: string | null;
  actor_kind: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface RealtimeEvent {
  id?: number;
  type: string;
  data?: Record<string, unknown>;
}
