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
  public_game_id: string | null;
  public_title: string | null;
  validation: Validation | null;
}

export interface Project {
  id: string;
  title: string;
  prompt: string;
  current_revision_id: string | null;
  forked_from_revision_id: string | null;
  created_at: string;
  revisions: Revision[];
  messages?: ChatMessage[];
}

export interface ChatMessage {
  id: string;
  text: string;
  state: RunState;
  created_at: string;
  revision_id: string | null;
  error: string | null;
}

export interface PublicGame {
  id: string;
  revision_id: string;
  title: string;
  author_username: string;
  genre: string;
  audience: string;
  like_count: number;
  liked_by_me: boolean;
  is_mine: boolean;
  share_url: string;
  published_at: string;
  updated_at: string;
}

export type FeedbackReason =
  | "music"
  | "visuals"
  | "controls"
  | "difficulty"
  | "gameplay"
  | "performance"
  | "bugs"
  | "other";

export interface GameFeedback {
  id: string;
  revision_id: string;
  rating: number;
  reasons: FeedbackReason[];
  comment: string | null;
  created_at: string;
  updated_at: string;
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

export interface User {
  id: string;
  username: string;
  is_admin: boolean;
}
