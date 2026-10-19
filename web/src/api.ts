import type {
  FeedbackReason,
  GameFeedback,
  Project,
  PublicGame,
  Run,
  User,
} from "./types";

export const API_URL: string = import.meta.env.VITE_API_URL ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const message = await response.text();
    throw new ApiError(message || `HTTP ${response.status}`, response.status);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}

export const api = {
  me: () => request<User>("/v1/auth/me"),
  login: (username: string, password: string) =>
    request<User>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>("/v1/auth/logout", { method: "POST" }),
  publicGames: (sort = "newest", mine = false) =>
    request<PublicGame[]>(`/v1/public-games?sort=${sort}&mine=${mine}`),
  deletePublicGame: (id: string) =>
    request<void>(`/v1/public-games/${id}`, { method: "DELETE" }),
  updatePublicGame: (id: string, title: string) =>
    request<PublicGame>(`/v1/public-games/${id}`, {
      method: "PUT",
      body: JSON.stringify({ title }),
    }),
  likePublicGame: (id: string, liked: boolean) =>
    request<PublicGame>(`/v1/public-games/${id}/like`, {
      method: liked ? "DELETE" : "PUT",
    }),
  remixPublicGame: (id: string) =>
    request<Project>(`/v1/public-games/${id}/remix`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  submitFeedback: (
    revisionId: string,
    rating: number,
    reasons: FeedbackReason[],
    comment: string,
  ) =>
    request<GameFeedback>(`/v1/revisions/${revisionId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ rating, reasons, comment: comment || null }),
    }),
  projects: () => request<Project[]>("/v1/projects"),
  deleteProject: (id: string) =>
    request<void>(`/v1/projects/${id}`, { method: "DELETE" }),
  restoreRevision: (id: string) =>
    request<Project>(`/v1/revisions/${id}/restore`, { method: "POST" }),
  feedback: (id: string) =>
    request<GameFeedback[]>(`/v1/projects/${id}/feedback`),
  exportUrl: (id: string, format: "html" | "zip") =>
    `${API_URL}/v1/revisions/${id}/export?format=${format}`,
  project: (id: string) => request<Project>(`/v1/projects/${id}`),
  run: (id: string) => request<Run>(`/v1/runs/${id}`),
  create: (prompt: string, idempotencyKey: string = crypto.randomUUID()) =>
    request<{ project_id: string; run_id: string }>("/v1/projects", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ prompt }),
    }),
  revise: (
    revisionId: string,
    instruction: string,
    idempotencyKey: string = crypto.randomUUID(),
  ) =>
    request<{ project_id: string; run_id: string }>(
      `/v1/revisions/${revisionId}/revise`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ instruction }),
      },
    ),
  publish: (revisionId: string) =>
    request<{ public_game_id: string; share_url: string }>(
      `/v1/revisions/${revisionId}/publish`,
      {
        method: "POST",
      },
    ),
  analytics: (revisionId: string, sessionId: string, event_type: string) =>
    request<void>(`/v1/revisions/${revisionId}/analytics`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, event_type, payload: {} }),
    }),
};
