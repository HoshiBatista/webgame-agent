import type { Project, Run } from "./types";

export const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `HTTP ${response.status}`);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}

export const api = {
  projects: () => request<Project[]>("/v1/projects"),
  project: (id: string) => request<Project>(`/v1/projects/${id}`),
  run: (id: string) => request<Run>(`/v1/runs/${id}`),
  create: (prompt: string) =>
    request<{ project_id: string; run_id: string }>("/v1/projects", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ prompt }),
    }),
  revise: (revisionId: string, instruction: string) =>
    request<{ project_id: string; run_id: string }>(
      `/v1/revisions/${revisionId}/revise`,
      {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ instruction }),
      },
    ),
  publish: (revisionId: string) =>
    request<{ share_url: string }>(`/v1/revisions/${revisionId}/publish`, {
      method: "POST",
    }),
  analytics: (revisionId: string, sessionId: string, event_type: string) =>
    request<void>(`/v1/revisions/${revisionId}/analytics`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, event_type, payload: {} }),
    }),
};
