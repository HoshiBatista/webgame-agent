export type RunnerRole = 'generator' | 'validator';
export type Provider = 'codex' | 'openai';
export type JobStatus = 'queued' | 'running' | 'waiting' | 'paused' | 'completed' | 'failed' | 'cancelled';
export interface User { id: string | number; username: string; is_staff: boolean }
export interface Session { authenticated: boolean; user: User | null; csrf_token?: string }
export interface Usage { input_tokens: number; cached_input_tokens: number; output_tokens: number; total_tokens: number; calls: number }
export interface ArtifactManifest { html_sha256: string; html_bytes: number; files_sha256: Record<string, string>; spec_sha256: string }
export interface ValidationCheck {
  name: string; status: 'passed' | 'failed' | 'skipped'; message: string;
  check_kind?: string; artifact_sha256?: string; scenario_id?: string; affected_files?: string[];
  command?: string; limitations?: string[]; evidence?: Record<string, unknown>;
}
export interface ReviewIssue {
  file: string; severity: 'error' | 'warning'; message: string; scope: 'local' | 'integration' | 'contract';
  affected_files: string[]; contract_ids: string[]; reproduction: string; expected: string; observed: string; regression_scenario_id: string;
}
export interface ModelReview {
  approved: boolean; summary: string; issues: ReviewIssue[]; provider: string; model: string;
  contract_sha256: string; prompt_sha256: string; artifact_sha256: string;
}
export interface Validation {
  completion_required?: boolean; playthrough?: string;
  status: 'passed' | 'partial' | 'failed' | 'unverified'; checks: ValidationCheck[]; errors: string[]; warnings: string[];
  browser_contract_version?: number; validator_image_sha256?: string; suite_sha256?: string;
  evidence_files?: { path: string; sha256: string; bytes: number }[];
  schema_version?: number; artifact?: ArtifactManifest; review?: ModelReview;
  provenance?: { calls?: unknown[]; iterations?: unknown[]; module_summaries?: Record<string, string> }; binding_status?: 'verified' | 'legacy' | 'mismatch';
}
export interface ModelCall { id: string; operation: string; state: string; started_at: string; finished_at: string | null; usage_known: boolean; stage_fence: number }
export interface JobActivity { worker_contact_at: string | null; worker_connected: boolean; calls: ModelCall[] }
export interface Job {
  pipeline_version?: 'legacy-v1' | 'adaptive-v1';
  id: string; project_id: string; kind: 'generate' | 'revise'; prompt: string; provider: Provider; model: string;
  status: JobStatus; stage: string; progress: number; base_version_id: string | null; result_version_id: string | null;
  runner_id: string | null; created_at: string; updated_at: string; error: string; max_repairs: number; budget_tokens: number; usage: Usage;
  creation_mode?: 'lite' | 'pro'; approval?: 'plan' | 'build' | null;
  activity?: JobActivity; stage_fence?: number; resume_count?: number;
  pause_requested?: boolean; can_resume?: boolean; budget_stopped?: boolean; playthrough_mode?: 'manual' | 'auto';
  budget_usd?: string | null; cost?: Cost | null; pricing?: { model: string; as_of: string; source: string };
}
export interface Project { id: string; title: string; title_pending?: boolean; prompt: string; created_at: string; updated_at: string; latest_version_id: string | null; latest_version_number: number | null; active_job: Job | null; latest_job?: Job | null }
export interface Version {
  visual_review_pending?: boolean;
  id: string; project_id: string; number: number; prompt: string; summary: string; created_at: string; is_reference: boolean;
  validation: Validation; usage: Usage; spec: Record<string, unknown>; download_url: string; source_url: string;
  eligible?: boolean; preview_url?: string | null;
}
export interface VersionDetail extends Version { files: Record<string, string>; html: string; plan?: Record<string, unknown>; provenance?: Record<string, unknown> }
export interface JobEvent { id: number; job_id: string; stage: string; level: 'info' | 'warning' | 'error'; message: string; data: unknown; created_at: string }
export interface Runner { id: string; name: string; role?: RunnerRole; created_at: string; last_seen: string | null; online: boolean; revoked: boolean; capabilities: Record<string, unknown> }
export interface PriceCatalog { as_of: string; service_tier: string; source: string; models: Record<string, {input: string; cached_input: string; cache_write: string; output: string}> }
export interface Cost { estimated_usd: string; upper_usd: string; reserved_usd: string; remaining_usd: string; over_budget: boolean }
export interface JobInsights { adaptive?: Record<string, unknown> | null; visual_pending?: boolean; previous_proposal?: {spec: Record<string, unknown>; plan: Record<string, unknown>} | null; draft_diagnostic?: Validation | null; author_steps?: {summary: string; operations: {op: string; path: string}[]}[]; proposal_current?: boolean; job_id: string; proposal: {spec: Record<string, unknown>; plan: Record<string, unknown>} | null; summary: string; files: string[]; provenance: Record<string, unknown>; validation: Validation | null; feedback: {stage: string; text: string}[]; approval: 'plan' | 'build' | null; version_id: string | null }
export interface JobSettings { pipeline_version?: 'legacy-v1' | 'adaptive-v1'; playthrough_mode?: 'manual' | 'auto'; creation_mode?: 'lite' | 'pro'; provider: Provider; model: string; max_repairs: number; budget_usd: number }
export interface JobInput extends JobSettings { kind: 'generate' | 'revise'; prompt: string; base_version_id?: string | null }
