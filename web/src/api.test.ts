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
});
