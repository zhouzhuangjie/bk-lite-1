export type JsonPrimitive = string | number | boolean | null;

export interface JsonSchemaField {
  type: 'string' | 'number' | 'integer' | 'boolean' | 'array';
  title: string;
  description?: string;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  maxItems?: number;
  enum?: JsonPrimitive[];
  items?: { type: 'string'; enum?: JsonPrimitive[] };
  'x-widget'?: 'input' | 'textarea' | 'select' | 'radio' | 'multiselect' | 'number' | 'switch';
}

export interface JsonSchema {
  type: 'object';
  properties: Record<string, JsonSchemaField>;
  required: string[];
  additionalProperties: false;
}

export interface WorkflowStage {
  key: string;
  name: string;
  mode: 'serial' | 'parallel';
  approverIds: number[];
  allowBeforeSign: boolean;
  allowAfterSign: boolean;
}

export interface WorkflowConfig {
  schemaVersion: 1;
  stages: WorkflowStage[];
  handlerIds: number[];
}

export interface ServiceRecord {
  id: number;
  name: string;
  description: string;
  team_id: number;
  status: 'DRAFT' | 'PUBLISHED' | 'DISABLED';
  form_schema: JsonSchema;
  workflow_config: WorkflowConfig;
  draft_revision: number;
  last_published_revision: number;
  current_version: number;
  has_draft: boolean;
  updated_at: string;
}

export interface CatalogService {
  id: number;
  name: string;
  description: string;
  team_id: number;
  current_version: number;
  form_schema: JsonSchema;
  workflow_config?: WorkflowConfig;
  updated_at: string;
}

export interface ServiceVersionRecord {
  id: number;
  service_id: number;
  version: number;
  source_revision: number;
  form_schema: JsonSchema;
  workflow_config: WorkflowConfig;
  content_hash: string;
  publish_status: 'PENDING' | 'READY' | 'FAILED';
  publish_error: string;
  created_by: string;
  created_at: string;
}

export type TicketStatus = 'SUBMITTING' | 'APPROVING' | 'PROCESSING' | 'WAITING_CONFIRMATION' | 'CLOSED' | 'REJECTED';

export interface AuditEventRecord {
  id: number;
  actor_user_id: number | null;
  actor_username: string;
  action: string;
  from_status: string;
  to_status: string;
  reason: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface TicketRecord {
  id: string;
  number: string;
  service_id: number;
  service_name: string;
  service_version_number: number;
  form_schema: JsonSchema;
  workflow_config?: WorkflowConfig;
  requester_user_id: number;
  requester_username: string;
  form_data: Record<string, unknown>;
  status: TicketStatus;
  resolved_at: string | null;
  closed_at: string | null;
  audit_events: AuditEventRecord[];
  created_at: string;
  updated_at: string;
}

export interface TaskRecord {
  id: string;
  ticket_id: string;
  ticket_number: string;
  service_name: string;
  requester_username: string;
  ticket_status: TicketStatus;
  form_data: Record<string, unknown>;
  form_schema: JsonSchema;
  task_type: 'APPROVAL' | 'HANDLING';
  title: string;
  status: 'PENDING' | 'SUBMITTING';
  stage_key: string;
  allow_before_sign: boolean;
  allow_after_sign: boolean;
  sign_parent_key: string;
  created_at: string;
  updated_at: string;
}

export interface UserOption {
  id: number;
  username: string;
  display_name?: string;
}

export interface PageResponse<T> {
  count: number;
  items: T[];
}
