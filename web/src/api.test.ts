import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

describe("API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends an idempotent project request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ project_id: "project", run_id: "run" }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.create("Большая змейка для бабушки")).resolves.toEqual({
      project_id: "project",
      run_id: "run",
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/projects");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.headers).toMatchObject({
      "Idempotency-Key": expect.any(String),
    });
    expect(init.body).toBe(
      JSON.stringify({ prompt: "Большая змейка для бабушки" }),
    );
  });

  it("supports no-content analytics responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );
    await expect(
      api.analytics("revision", "session-id", "win"),
    ).resolves.toBeUndefined();
  });

  it("turns non-success responses into useful errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("provider unavailable", { status: 503 }),
        ),
    );
    await expect(api.projects()).rejects.toThrow("provider unavailable");
  });

  it("uses authenticated studio endpoints for feed filtering, restore and removal", async () => {
    const fetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockImplementation(() =>
        Promise.resolve(new Response("[]", { status: 200 })),
      );
    vi.stubGlobal("fetch", fetchMock);
    await api.publicGames("popular", true);
    await api.feedback("project");
    await api.restoreRevision("revision");
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response(null, { status: 204 })),
    );
    await api.deleteProject("project");
    await api.deletePublicGame("publication");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/v1/public-games?sort=popular&mine=true",
      "/v1/projects/project/feedback",
      "/v1/revisions/revision/restore",
      "/v1/projects/project",
      "/v1/public-games/publication",
    ]);
    expect(fetchMock.mock.calls[2][1]).toMatchObject({
      method: "POST",
      credentials: "include",
    });
    expect(fetchMock.mock.calls[3][1]).toMatchObject({
      method: "DELETE",
      credentials: "include",
    });
    expect(api.exportUrl("revision", "zip")).toBe(
      "/v1/revisions/revision/export?format=zip",
    );
  });
});
