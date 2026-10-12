export type RunState =
  | "accepted"
  | "specifying"
  | "generating"
  | "static_validation"
  | "browser_validation"
  | "repairing"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Finding {
  code: string;
  severity: "error" | "warning";
  message: string;
  repair_hint: string;
}

export interface Validation {
  passed: boolean;
  static_passed: boolean;
  browser_passed: boolean | null;
  browser_status: "passed" | "failed" | "unverified";
  findings: Finding[];
  checks: string[];
}

export interface Revision {
  id: string;
  parent_id: string | null;
  title: string;
  genre: string;
  audience: string;
  status: "candidate" | "validated" | "rejected";
  model_name: string;
  created_at: string;
  preview_url: string | null;
  share_url: string | null;
  validation: Validation | null;
}

export interface Project {
  id: string;
  title: string;
  prompt: string;
  current_revision_id: string | null;
  created_at: string;
  revisions: Revision[];
}

export interface Run {
  id: string;
  project_id: string;
  state: RunState;
  error: string | null;
  revision_id: string | null;
  repair_count: number;
  created_at: string;
  updated_at: string;
}

export interface TimelineEvent {
  id: number;
  event: string;
  message: string;
  created_at: string;
}
