// Espelho dos contratos Pydantic do backend (app/schemas). Mantenha sincronizado com o OpenAPI.

export type Role = "ADMIN" | "CAIXA" | "ATENDENTE";
export type TableStatus = "LIVRE" | "OCUPADA" | "ENCERRAMENTO_SOLICITADO";
export type RequestType = "CHAMAR_ATENDENTE" | "PEDIR_CONTA";
export type RequestStatus = "PENDENTE" | "ASSUMIDA" | "EM_ATENDIMENTO" | "CONCLUIDA" | "CANCELADA";

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

export type TagStatus = "PENDENTE" | "GRAVANDO" | "GRAVADA" | "TRAVADA" | "FALHA" | "SUBSTITUIDA";

export interface TagBrief {
  id: string;
  status: TagStatus;
  uid: string | null;
  error: string | null;
  updated_at: string;
}

/** Etiqueta NFC de uma mesa, com tudo que o assistente de gravação precisa. */
export interface Tag {
  id: string;
  table_id: string;
  table_number: number;
  table_name: string | null;
  status: TagStatus;
  url: string;
  uid: string | null;
  error: string | null;
  started_by_name: string;
  lock_authorized_at: string | null;
  written_at: string | null;
  locked_at: string | null;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface ProvisionOut {
  table: Table;
  tag: Tag;
  qr_svg_url: string;
}

export interface LayoutItem {
  table_id: string;
  x: number;
  y: number;
}

/** Planta (template) do salão. A grade tem `cols` × `rows` células. */
export interface Layout {
  id: string;
  name: string;
  is_active: boolean;
  version: number;
  cols: number;
  rows: number;
  items: LayoutItem[];
  updated_at: string;
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
  tag?: TagBrief | null;
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
  origin: string;
  assigned_to_id: string | null;
  assigned_to_name: string | null;
  created_at: string;
  updated_at: string;
  claimed_at: string | null;
  completed_at: string | null;
  version: number;
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
}

export interface CustomerSession {
  session_id: string;
  establishment_name: string;
  timezone: string;
  table_number: number;
  table_name: string | null;
  table_status: TableStatus;
  opened_at: string;
  requests: ServiceRequest[];
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
