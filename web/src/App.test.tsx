import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { api } from "./api";
import type { Project, Run } from "./types";

vi.mock("./api", () => ({
  API_URL: "http://api.test",
  api: {
    projects: vi.fn(),
    project: vi.fn(),
    run: vi.fn(),
    create: vi.fn(),
    revise: vi.fn(),
    publish: vi.fn(),
    analytics: vi.fn(),
  },
}));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly listeners = new Map<string, EventListener>();
  close = vi.fn();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, listener: EventListener) {
    this.listeners.set(name, listener);
  }
}

const run: Run = {
  id: "run-1",
  project_id: "project-1",
  state: "accepted",
  error: null,
  revision_id: null,
  repair_count: 0,
  created_at: "2026-10-12T10:00:00Z",
  updated_at: "2026-10-12T10:00:00Z",
};

const project: Project = {
  id: "project-1",
  title: "Пчелиный рывок",
  prompt: "Аркада про пчелу",
  current_revision_id: "revision-1",
  created_at: "2026-10-12T10:00:00Z",
  revisions: [
    {
      id: "revision-1",
      parent_id: null,
      title: "Пчелиный рывок",
      genre: "arcade",
      audience: "дети",
      status: "validated",
      model_name: "gpt-6-luna",
      created_at: "2026-10-12T10:00:00Z",
      preview_url: "http://api.test/preview",
      share_url: null,
      validation: {
        passed: true,
        static_passed: true,
        browser_passed: true,
        browser_status: "passed",
        findings: [],
        checks: ["boot", "touch"],
      },
    },
  ],
};

describe("creator application", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("scrollTo", vi.fn());
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    vi.mocked(api.projects).mockResolvedValue([]);
    vi.mocked(api.analytics).mockResolvedValue(undefined);
  });

  it("renders examples and starts a generation", async () => {
    const user = userEvent.setup();
    vi.mocked(api.create).mockResolvedValue({
      project_id: "project-1",
      run_id: "run-1",
    });
    vi.mocked(api.run).mockResolvedValue(run);
    render(<App />);

    expect(
      await screen.findByText("Первая игра появится здесь после генерации."),
    ).toBeVisible();
    const prompt = screen.getByLabelText("Какую игру делаем?");
    await user.clear(prompt);
    await user.type(prompt, "Сделай большой кликер для детей");
    await user.click(
      screen.getByRole("button", { name: /Сгенерировать игру/ }),
    );

    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith(
        "Сделай большой кликер для детей",
      ),
    );
    expect(api.run).toHaveBeenCalledWith("run-1");
    expect(await screen.findByText("Игра собирается")).toBeVisible();
    expect(FakeEventSource.instances[0]?.url).toBe(
      "http://api.test/v1/runs/run-1/events",
    );
  });

  it("opens a validated game, revises it and records game events", async () => {
    const user = userEvent.setup();
    vi.mocked(api.projects).mockResolvedValue([project]);
    vi.mocked(api.project).mockResolvedValue(project);
    vi.mocked(api.revise).mockResolvedValue({
      project_id: project.id,
      run_id: run.id,
    });
    vi.mocked(api.run).mockResolvedValue(run);
    render(<App />);

    await user.click(
      await screen.findByRole("button", { name: /Пчелиный рывок/ }),
    );
    expect(await screen.findByTitle("Пчелиный рывок")).toHaveAttribute(
      "sandbox",
      "allow-scripts",
    );
    fireEvent(
      window,
      new MessageEvent("message", {
        data: { source: "prompt2play-game", type: "game_event", event: "win" },
      }),
    );
    await waitFor(() =>
      expect(api.analytics).toHaveBeenCalledWith(
        "revision-1",
        expect.any(String),
        "win",
      ),
    );

    await user.type(
      screen.getByLabelText("Попросить изменение"),
      "Добавь новый уровень",
    );
    await user.click(
      screen.getByRole("button", { name: /Создать новую ревизию/ }),
    );
    await waitFor(() =>
      expect(api.revise).toHaveBeenCalledWith(
        "revision-1",
        "Добавь новый уровень",
      ),
    );
  });

  it("publishes a validated revision and copies its URL", async () => {
    const user = userEvent.setup();
    const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText");
    vi.mocked(api.projects).mockResolvedValue([project]);
    vi.mocked(api.project).mockResolvedValue(project);
    vi.mocked(api.publish).mockResolvedValue({
      share_url: "https://games.test/share",
    });
    render(<App />);

    await user.click(
      await screen.findByRole("button", { name: /Пчелиный рывок/ }),
    );
    await user.click(await screen.findByRole("button", { name: "Поделиться" }));
    await waitFor(() =>
      expect(clipboardSpy).toHaveBeenCalledWith("https://games.test/share"),
    );
    expect(api.analytics).toHaveBeenCalledWith(
      "revision-1",
      expect.any(String),
      "share",
    );
  });
});
