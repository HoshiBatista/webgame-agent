export interface User {
  id: string;
  username: string;
  is_staff: boolean;
}
export interface Preferences {
  theme: 'light' | 'dark';
  notes: string[];
  model_profile?: string;
}
export interface ModelProfile {
  id: string;
  name: string;
  description: string;
  available: boolean;
  unavailable_reason: string;
}
export interface Budget {
  limit_usd: number | string;
  spent_usd: number | string;
  reserved_usd: number | string;
  unknown_usd: number | string;
  available_usd: number | string;
}
export interface Session {
  user: User | null;
  csrfToken: string;
  preferences: Preferences;
  capabilities: {
    provider: string;
    model: string;
    models: Array<string | { id: string; name?: string; priced?: boolean }>;
    local_only: boolean;
    model_profiles?: ModelProfile[];
    default_model_profile?: string;
  };
  budget: Budget;
}
export interface Finding {
  message?: string;
  code?: string;
  [key: string]: unknown;
}
export interface Report {
  status: string;
  findings: Array<Finding | string>;
  facts: unknown[];
  stages?: Array<{ stage: string; status: string }>;
  elapsed_seconds?: number;
}
export interface Revision {
  id: string;
  title: string;
  number: number;
  artifact_hash: string;
  design: Record<string, unknown>;
  checks: unknown[];
  created_at: string;
  accepted: boolean;
  verification: 'automatic' | 'manual' | 'none';
  preview_url: string;
  export_url: string;
  parent_id: string | null;
  report: Report | null;
}
export type RunStatus =
  | 'queued'
  | 'generating'
  | 'checking'
  | 'succeeded'
  | 'needs_attention'
  | 'unverified'
  | 'failed'
  | 'cancelled'
  | 'unknown';
export interface ApiErrorData {
  code: string;
  message: string;
  details?: unknown;
}
export interface Run {
  id: string;
  chat_id: string;
  operation: string;
  model_profile?: string;
  model_label?: string;
  model?: string;
  provider?: string;
  status: RunStatus;
  stage: string;
  message: string;
  prompt: string;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  base_revision_id: string | null;
  candidate_revision_id: string | null;
  result_revision_id: string | null;
  error: ApiErrorData | null;
  can_cancel: boolean;
  can_continue: boolean;
  can_retry_unknown?: boolean;
  can_confirm: boolean;
  attempts: number;
  max_repair_attempts?: number;
  max_model_calls?: number;
  elapsed_seconds: number;
  events_url: string;
  budget: Budget;
  metrics: Record<string, unknown>;
}
export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  run_id: string | null;
}
export interface ChatSummary {
  id: string;
  title: string;
  audience: string;
  updated_at: string;
  current_revision: Revision | string | null;
  active_run: Run | null;
}
export interface Chat extends ChatSummary {
  created_at: string;
  current_revision: Revision | null;
  candidate_revision: Revision | null;
  messages: Message[];
  revisions: Revision[];
  runs: Run[];
  source_publication: string | null;
}
export interface Publication {
  id: string;
  title: string;
  author: { id?: string; username: string };
  created_at: string;
  updated_at: string;
  revision_id: string;
  artifact_hash: string;
  preview_url: string;
  thumbnail_url: string | null;
  likes: number;
  liked: boolean;
  is_owner: boolean;
  source_chat_id: string | null;
  verification: string;
  public_url: string;
}
export interface RunEvent {
  id: number;
  kind: string;
  message: string;
  created_at: string;
  details?: unknown;
}
