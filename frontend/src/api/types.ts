// Espelho dos contratos Pydantic do backend (app/schemas). Mantenha sincronizado com o OpenAPI.

export type Role = "ADMIN" | "CAIXA" | "ATENDENTE";
export type TableStatus = "LIVRE" | "OCUPADA" | "ENCERRAMENTO_SOLICITADO";
export type RequestType = "CHAMAR_ATENDENTE" | "NOVO_PEDIDO" | "PEDIR_CONTA";
export type RequestStatus = "PENDENTE" | "ASSUMIDA" | "EM_ATENDIMENTO" | "CONCLUIDA" | "CANCELADA";
export type OrderStatus = "RECEBIDO" | "EM_PREPARO" | "PRONTO" | "ENTREGUE" | "CANCELADO";
export type PaymentMethod = "DINHEIRO" | "CARTAO_CREDITO" | "CARTAO_DEBITO" | "PIX" | "OUTRO";

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  active: boolean;
  has_pin: boolean;
}

export interface Establishment {
  id: string;
  name: string;
  timezone: string;
  join_code_required: boolean;
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
  label: string | null;
  opened_at: string;
  opened_by_name: string;
  join_code: string | null;
  close_requested_at: string | null;
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
  pending_requests: number;
  pending_orders: number;
}

export interface ServiceRequest {
  id: string;
  session_id: string;
  table_id: string;
  table_number: number;
  table_name: string | null;
  type: RequestType;
  status: RequestStatus;
  priority: number;
  note: string | null;
  order_id: string | null;
  origin: string;
  assigned_to_id: string | null;
  assigned_to_name: string | null;
  created_at: string;
  updated_at: string;
  claimed_at: string | null;
  completed_at: string | null;
  version: number;
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
  session_id: string;
  table_id: string;
  table_number: number;
  status: OrderStatus;
  origin: string;
  note: string | null;
  total_cents: number;
  created_at: string;
  updated_at: string;
  version: number;
  items: OrderItem[];
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
  table_status: TableStatus;
  label: string | null;
  status: "OPEN" | "CLOSED";
  join_code: string | null;
  opened_at: string;
  opened_by_name: string;
  close_requested_at: string | null;
  closed_at: string | null;
  closed_by_name: string | null;
  payment_method: string | null;
  subtotal_cents: number;
  discount_cents: number;
  total_cents: number;
  pending_orders: number;
  orders: Order[];
  requests: ServiceRequest[];
  version: number;
}

export interface SessionHistory {
  id: string;
  table_number: number;
  label: string | null;
  opened_at: string;
  closed_at: string | null;
  opened_by_name: string;
  closed_by_name: string | null;
  total_cents: number | null;
  payment_method: string | null;
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
  join_code_required: boolean;
  orders_enabled: boolean;
}

export interface CustomerSession {
  session_id: string;
  establishment_name: string;
  timezone: string;
  table_number: number;
  table_name: string | null;
  table_status: TableStatus;
  orders_enabled: boolean;
  opened_at: string;
  requests: ServiceRequest[];
  orders: Order[];
  total_cents: number;
  push_public_key: string | null;
}

export type PromotionKind = "BANNER" | "EVENTO" | "CAMPANHA";

export interface Promotion {
  id: string;
  kind: PromotionKind;
  title: string;
  description: string | null;
  image_url: string | null;
  conditions: string | null;
  starts_at: string;
  ends_at: string;
  active: boolean;
}

export interface Coupon {
  id: string;
  code: string;
  description: string | null;
  discount_type: "PERCENT" | "FIXED";
  value: number;
  min_order_cents: number;
  max_uses: number | null;
  uses_count: number;
  starts_at: string;
  ends_at: string;
  active: boolean;
}

export interface CouponValidation {
  valid: boolean;
  code: string;
  description?: string | null;
  discount_type?: "PERCENT" | "FIXED" | null;
  value?: number | null;
  estimated_discount_cents?: number | null;
  reason?: string | null;
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
