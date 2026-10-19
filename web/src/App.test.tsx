import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { ApiError, api } from "./api";
import type { Project, PublicGame, Run } from "./types";

vi.mock("./api", () => ({
  API_URL: "http://api.test",
  ApiError: class extends Error {
    constructor(
      message: string,
      readonly status: number,
    ) {
      super(message);
    }
  },
  api: {
    me: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    publicGames: vi.fn(),
    updatePublicGame: vi.fn(),
    likePublicGame: vi.fn(),
    remixPublicGame: vi.fn(),
    submitFeedback: vi.fn(),
    feedback: vi.fn(),
    restoreRevision: vi.fn(),
    exportUrl: vi.fn(),
    deleteProject: vi.fn(),
    deletePublicGame: vi.fn(),
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
  forked_from_revision_id: null,
  created_at: "2026-10-12T10:00:00Z",
  revisions: [
    {
      id: "revision-1",
      parent_id: null,
      title: "Пчелиный рывок",
      genre: "arcade",
      audience: "дети",
      status: "validated",
      model_name: "company/code-model",
      created_at: "2026-10-12T10:00:00Z",
      preview_url: "http://api.test/preview",
      share_url: null,
      public_game_id: null,
      public_title: null,
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

const publicGame: PublicGame = {
  id: "public-1",
  revision_id: "revision-elsewhere",
  title: "Космический ремикс",
  author_username: "another-creator",
  genre: "arcade",
  audience: "все",
  like_count: 3,
  liked_by_me: false,
  is_mine: false,
  share_url: "https://games.test/play/public",
  published_at: "2026-10-12T10:00:00Z",
  updated_at: "2026-10-12T10:00:00Z",
};

const creator = { id: "user-1", username: "creator", is_admin: true };

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
    vi.mocked(api.publicGames).mockResolvedValue([]);
    vi.mocked(api.me).mockResolvedValue(creator);
    vi.mocked(api.logout).mockResolvedValue(undefined);
    vi.mocked(api.analytics).mockResolvedValue(undefined);
    vi.mocked(api.feedback).mockResolvedValue([]);
    vi.mocked(api.project).mockResolvedValue(project);
    vi.mocked(api.exportUrl).mockImplementation(
      (id, format) => `/v1/revisions/${id}/export?format=${format}`,
    );
    vi.mocked(api.deleteProject).mockResolvedValue(undefined);
    vi.mocked(api.deletePublicGame).mockResolvedValue(undefined);
    vi.mocked(api.submitFeedback).mockResolvedValue({
      id: "feedback-1",
      revision_id: "revision-1",
      rating: 3,
      reasons: ["music"],
      comment: "Не хватает крутой музыки",
      created_at: "2026-10-12T10:00:00Z",
      updated_at: "2026-10-12T10:00:00Z",
    });
  });

  it("authenticates before loading the personal project history", async () => {
    const user = userEvent.setup();
    vi.mocked(api.me).mockRejectedValue(
      new ApiError("Authentication required", 401),
    );
    vi.mocked(api.login).mockResolvedValue(creator);
    render(<App />);

    await user.type(await screen.findByLabelText("Логин"), "Creator");
    await user.type(screen.getByLabelText("Пароль"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: /Войти/ }));

    await waitFor(() =>
      expect(api.login).toHaveBeenCalledWith(
        "Creator",
        "correct horse battery",
      ),
    );
    expect(await screen.findByText("creator")).toBeVisible();
    expect(api.projects).toHaveBeenCalled();
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
        expect.any(String),
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
      await screen.findByRole("button", { name: "Открыть чат Пчелиный рывок" }),
    );
    expect(await screen.findByTitle("Пчелиный рывок")).toHaveAttribute(
      "sandbox",
      "allow-scripts",
    );
    const preview = screen.getByTitle<HTMLIFrameElement>("Пчелиный рывок");
    fireEvent(
      window,
      new MessageEvent("message", {
        data: { source: "prompt2play-game", type: "game_event", event: "win" },
        source: preview.contentWindow,
      }),
    );
    await waitFor(() =>
      expect(api.analytics).toHaveBeenCalledWith(
        "revision-1",
        expect.any(String),
        "win",
      ),
    );

    await user.click(screen.getByRole("button", { name: "Оценка 3 из 5" }));
    await user.click(screen.getByRole("checkbox", { name: "Музыка и звук" }));
    await user.type(
      screen.getByLabelText("Комментарий к оценке"),
      "Не хватает крутой музыки",
    );
    await user.click(screen.getByRole("button", { name: "Сохранить отзыв" }));
    await waitFor(() =>
      expect(api.submitFeedback).toHaveBeenCalledWith(
        "revision-1",
        3,
        ["music"],
        "Не хватает крутой музыки",
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
        expect.any(String),
      ),
    );
  });

  it("publishes a validated revision and copies its URL", async () => {
    const user = userEvent.setup();
    const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText");
    vi.mocked(api.projects).mockResolvedValue([project]);
    vi.mocked(api.project).mockResolvedValue(project);
    vi.mocked(api.publish).mockResolvedValue({
      public_game_id: "public-1",
      share_url: "https://games.test/share",
    });
    render(<App />);

    await user.click(
      await screen.findByRole("button", { name: "Открыть чат Пчелиный рывок" }),
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

  it("likes a public game and creates an owned remix", async () => {
    const user = userEvent.setup();
    vi.mocked(api.publicGames).mockResolvedValue([publicGame]);
    vi.mocked(api.likePublicGame).mockResolvedValue({
      ...publicGame,
      liked_by_me: true,
      like_count: 4,
    });
    vi.mocked(api.remixPublicGame).mockResolvedValue({
      ...project,
      id: "remix-project",
      title: "Ремикс: Космический ремикс",
      forked_from_revision_id: publicGame.revision_id,
    });
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Лента игр" }));
    expect(await screen.findByText("Космический ремикс")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "♥ 3" }));
    await waitFor(() =>
      expect(api.likePublicGame).toHaveBeenCalledWith("public-1", false),
    );
    await user.click(
      screen.getByRole("button", { name: "Сделать свою версию" }),
    );
    await waitFor(() =>
      expect(api.remixPublicGame).toHaveBeenCalledWith("public-1"),
    );
  });

  it("loads a saved rating, switches revisions and restores an older game", async () => {
    const user = userEvent.setup();
    const older = {
      ...project.revisions[0],
      id: "revision-old",
      title: "Старая игра",
    };
    const history = {
      ...project,
      revisions: [...project.revisions, older],
      messages: [
        {
          id: "message-1",
          text: "Сделай музыку лучше",
          state: "succeeded" as const,
          created_at: run.created_at,
          revision_id: "revision-1",
          error: null,
        },
      ],
    };
    vi.mocked(api.projects).mockResolvedValue([history]);
    vi.mocked(api.project).mockResolvedValue(history);
    vi.mocked(api.restoreRevision).mockResolvedValue({
      ...history,
      current_revision_id: older.id,
    });
    vi.mocked(api.feedback).mockResolvedValue([
      {
        id: "rating",
        revision_id: "revision-1",
        rating: 4,
        reasons: ["music"],
        comment: "Добавь мелодию",
        created_at: run.created_at,
        updated_at: run.updated_at,
      },
    ]);
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "Открыть чат Пчелиный рывок" }),
    );
    expect(await screen.findByDisplayValue("Добавь мелодию")).toBeVisible();
    expect(screen.getByText("Сделай музыку лучше")).toBeVisible();
    expect(screen.getByRole("link", { name: "Скачать ZIP ↓" })).toHaveAttribute(
      "href",
      "/v1/revisions/revision-1/export?format=zip",
    );
    await user.selectOptions(screen.getByLabelText("История версий"), older.id);
    expect(await screen.findByTitle("Старая игра")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "Сделать текущей версией" }),
    );
    await waitFor(() =>
      expect(api.restoreRevision).toHaveBeenCalledWith("revision-old"),
    );
    expect(await screen.findByTitle("Старая игра")).toBeVisible();
  });

  it("waits for a delayed completed project before showing the new preview", async () => {
    const user = userEvent.setup();
    let resolveProject!: (value: Project) => void;
    const delayed = new Promise<Project>((resolve) => {
      resolveProject = resolve;
    });
    vi.mocked(api.create).mockResolvedValue({
      project_id: project.id,
      run_id: run.id,
    });
    vi.mocked(api.project)
      .mockResolvedValueOnce({
        ...project,
        current_revision_id: null,
        revisions: [],
      })
      .mockReturnValueOnce(delayed);
    vi.mocked(api.run).mockResolvedValue({
      ...run,
      state: "succeeded",
      revision_id: "revision-1",
    });
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: /Сгенерировать игру/ }),
    );
    expect(screen.queryByTitle("Пчелиный рывок")).not.toBeInTheDocument();
    await act(async () => {
      resolveProject(project);
      await delayed;
    });
    expect(await screen.findByTitle("Пчелиный рывок")).toBeVisible();
    expect(screen.getByLabelText("Попросить изменение")).not.toBeDisabled();
  });

  it("archives a chat only after confirmation and returns to a fresh conversation", async () => {
    const user = userEvent.setup();
    vi.mocked(api.projects)
      .mockResolvedValueOnce([project])
      .mockResolvedValue([]);
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "Удалить чат Пчелиный рывок" }),
    );
    expect(api.deleteProject).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog");
    expect(
      within(dialog).getByText(/Опубликованная игра и её ссылка сохранятся/),
    ).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await waitFor(() =>
      expect(api.deleteProject).toHaveBeenCalledWith(project.id),
    );
    expect(
      await screen.findByText("Первая игра появится здесь после генерации."),
    ).toBeVisible();
  });

  it("filters the feed and removes an owned publication without removing its chat", async () => {
    const user = userEvent.setup();
    const owned = { ...publicGame, is_mine: true };
    vi.mocked(api.publicGames).mockResolvedValue([owned]);
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Лента игр" }));
    await user.selectOptions(
      screen.getByLabelText("Сортировка ленты"),
      "popular",
    );
    await user.click(
      screen.getByRole("checkbox", { name: "Только мои публикации" }),
    );
    await waitFor(() =>
      expect(api.publicGames).toHaveBeenLastCalledWith("popular", true),
    );
    await user.click(
      screen.getByRole("button", { name: "Удалить публикацию" }),
    );
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Отмена",
      }),
    );
    expect(api.deletePublicGame).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Удалить публикацию" }),
    );
    vi.mocked(api.publicGames).mockResolvedValue([]);
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Удалить",
      }),
    );
    await waitFor(() =>
      expect(api.deletePublicGame).toHaveBeenCalledWith(owned.id),
    );
    expect(api.deleteProject).not.toHaveBeenCalled();
  });

  it("opens public play inside a restricted player and returns to the feed", async () => {
    const user = userEvent.setup();
    vi.mocked(api.publicGames).mockResolvedValue([publicGame]);
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Лента игр" }));
    await user.click(
      await screen.findByRole("button", { name: /Попробовать/ }),
    );
    expect(screen.getByTitle(`Играть: ${publicGame.title}`)).toHaveAttribute(
      "sandbox",
      "allow-scripts",
    );
    await user.click(screen.getByRole("button", { name: "← Назад" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens and closes the mobile player, collapses panels and creates a new chat", async () => {
    const user = userEvent.setup();
    vi.mocked(api.projects).mockResolvedValue([project]);
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "Открыть чат Пчелиный рывок" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "На весь экран" }),
    );
    expect(
      screen.getByRole("region", { name: "Предпросмотр игры" }),
    ).toHaveClass("mobile-player");
    await user.click(screen.getByRole("button", { name: "Закрыть игру" }));
    await user.click(screen.getByRole("button", { name: "Свернуть превью" }));
    await user.click(screen.getByRole("button", { name: "Открыть превью" }));
    await user.click(screen.getByRole("button", { name: "← Свернуть чаты" }));
    await user.click(screen.getByRole("button", { name: "☰ Чаты" }));
    await user.click(screen.getByRole("button", { name: "+ Новая игра" }));
    expect(screen.getByLabelText("Какую игру делаем?")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Выйти" }));
    expect(await screen.findByLabelText("Логин")).toBeVisible();
  });

  it("ignores a slow old chat response after a newer chat was selected", async () => {
    const user = userEvent.setup();
    const second = {
      ...project,
      id: "project-2",
      title: "Вторая игра",
      current_revision_id: "revision-2",
      revisions: [
        { ...project.revisions[0], id: "revision-2", title: "Вторая игра" },
      ],
    };
    let resolveOld!: (value: Project) => void;
    const delayed = new Promise<Project>((resolve) => {
      resolveOld = resolve;
    });
    vi.mocked(api.projects).mockResolvedValue([project, second]);
    vi.mocked(api.project).mockImplementation((id) =>
      id === project.id ? delayed : Promise.resolve(second),
    );
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "Открыть чат Пчелиный рывок" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Открыть чат Вторая игра" }),
    );
    expect(await screen.findByTitle("Вторая игра")).toBeVisible();
    await act(async () => {
      resolveOld(project);
      await delayed;
    });
    expect(screen.getByTitle("Вторая игра")).toBeVisible();
    expect(screen.queryByTitle("Пчелиный рывок")).not.toBeInTheDocument();
  });

  it("does not reopen a generation after the user starts a new chat", async () => {
    const user = userEvent.setup();
    let resolveCreate!: (value: { project_id: string; run_id: string }) => void;
    const delayed = new Promise<{ project_id: string; run_id: string }>(
      (resolve) => {
        resolveCreate = resolve;
      },
    );
    vi.mocked(api.create).mockReturnValue(delayed);
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: /Сгенерировать игру/ }),
    );
    await user.click(screen.getByRole("button", { name: "+ Новая игра" }));
    await act(async () => {
      resolveCreate({ project_id: project.id, run_id: run.id });
      await delayed;
    });
    expect(screen.getByLabelText("Какую игру делаем?")).toBeVisible();
    expect(api.project).not.toHaveBeenCalled();
  });

  it("keeps a newly edited review when the saved review arrives late", async () => {
    const user = userEvent.setup();
    let resolveFeedback!: (
      value: Awaited<ReturnType<typeof api.feedback>>,
    ) => void;
    const delayed = new Promise<Awaited<ReturnType<typeof api.feedback>>>(
      (resolve) => {
        resolveFeedback = resolve;
      },
    );
    vi.mocked(api.feedback).mockReturnValue(delayed);
    vi.mocked(api.projects).mockResolvedValue([project]);
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "Открыть чат Пчелиный рывок" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Оценка 3 из 5" }),
    );
    await user.type(
      screen.getByLabelText("Комментарий к оценке"),
      "Новый отзыв",
    );
    await act(async () => {
      resolveFeedback([
        {
          id: "old",
          revision_id: "revision-1",
          rating: 4,
          reasons: ["music"],
          comment: "Старый отзыв",
          created_at: run.created_at,
          updated_at: run.updated_at,
        },
      ]);
      await delayed;
    });
    expect(screen.getByLabelText("Комментарий к оценке")).toHaveValue(
      "Новый отзыв",
    );
    expect(screen.getByRole("button", { name: "Оценка 3 из 5" })).toHaveClass(
      "selected",
    );
  });

  it("recovers preview polling after a temporary network failure", async () => {
    const user = userEvent.setup();
    vi.mocked(api.create).mockResolvedValue({
      project_id: project.id,
      run_id: run.id,
    });
    vi.mocked(api.run)
      .mockResolvedValueOnce(run)
      .mockRejectedValueOnce(new Error("Temporary network failure"))
      .mockResolvedValue({
        ...run,
        state: "succeeded",
        revision_id: "revision-1",
      });
    vi.mocked(api.project)
      .mockResolvedValueOnce({
        ...project,
        current_revision_id: null,
        revisions: [],
      })
      .mockResolvedValue(project);
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: /Сгенерировать игру/ }),
    );
    expect(await screen.findByText("Temporary network failure")).toBeVisible();
    await waitFor(
      () => expect(screen.getByTitle("Пчелиный рывок")).toBeVisible(),
      { timeout: 4000 },
    );
    expect(api.run).toHaveBeenCalledTimes(3);
    expect(screen.getByLabelText("Попросить изменение")).not.toBeDisabled();
  });

  it("offers an explicit retry after repeated connection failures", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(api.create).mockResolvedValue({
        project_id: project.id,
        run_id: run.id,
      });
      vi.mocked(api.run)
        .mockResolvedValueOnce(run)
        .mockRejectedValue(new Error("Offline"));
      vi.mocked(api.project)
        .mockResolvedValueOnce({
          ...project,
          current_revision_id: null,
          revisions: [],
        })
        .mockResolvedValue(project);
      render(<App />);
      await act(async () => {
        await Promise.resolve();
      });
      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /Сгенерировать игру/ }),
        );
        await Promise.resolve();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(40000);
      });
      const retry = screen.getByRole("button", {
        name: "Повторить проверку статуса",
      });
      expect(api.run).toHaveBeenCalledTimes(6);
      vi.mocked(api.run).mockResolvedValue({
        ...run,
        state: "succeeded",
        revision_id: "revision-1",
      });
      await act(async () => {
        fireEvent.click(retry);
        await Promise.resolve();
      });
      expect(screen.getByTitle("Пчелиный рывок")).toBeVisible();
      expect(screen.queryByText("Offline")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("reuses the creation key after an ambiguous network failure", async () => {
    const user = userEvent.setup();
    vi.mocked(api.create)
      .mockRejectedValueOnce(new Error("Response lost"))
      .mockResolvedValue({ project_id: project.id, run_id: run.id });
    vi.mocked(api.run).mockResolvedValue(run);
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: /Сгенерировать игру/ }),
    );
    expect(await screen.findByText("Response lost")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: /Сгенерировать игру/ }),
    );
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(2));
    const [first, second] = vi.mocked(api.create).mock.calls;
    expect(first[1]).toEqual(expect.any(String));
    expect(second).toEqual(first);
  });

  it("reuses a revision key if acceptance succeeded but status loading failed", async () => {
    const user = userEvent.setup();
    vi.mocked(api.projects).mockResolvedValue([project]);
    vi.mocked(api.revise).mockResolvedValue({
      project_id: project.id,
      run_id: run.id,
    });
    vi.mocked(api.run)
      .mockRejectedValueOnce(new Error("Status unavailable"))
      .mockResolvedValue(run);
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "Открыть чат Пчелиный рывок" }),
    );
    await user.type(
      await screen.findByLabelText("Попросить изменение"),
      "Добавь интересную музыку",
    );
    await user.click(
      screen.getByRole("button", { name: /Создать новую ревизию/ }),
    );
    expect(await screen.findByText("Status unavailable")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: /Создать новую ревизию/ }),
    );
    await waitFor(() => expect(api.revise).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.revise).mock.calls[1]).toEqual(
      vi.mocked(api.revise).mock.calls[0],
    );
  });

  it("keeps publication successful when clipboard and analytics fail", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(
      new Error("Clipboard denied"),
    );
    vi.mocked(api.projects).mockResolvedValue([project]);
    vi.mocked(api.publish).mockResolvedValue({
      public_game_id: "public-1",
      share_url: "https://games.test/published",
    });
    vi.mocked(api.analytics).mockRejectedValue(new Error("Analytics offline"));
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "Открыть чат Пчелиный рывок" }),
    );
    await user.click(await screen.findByRole("button", { name: "Поделиться" }));
    expect(
      await screen.findByText("Игра опубликована. Скопируйте ссылку вручную."),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Публичная ссылка ↗" }),
    ).toHaveAttribute("href", "https://games.test/published");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("locks the submitted review until the server confirms the saved text", async () => {
    const user = userEvent.setup();
    let resolveSave!: (
      value: Awaited<ReturnType<typeof api.submitFeedback>>,
    ) => void;
    const delayed = new Promise<Awaited<ReturnType<typeof api.submitFeedback>>>(
      (resolve) => {
        resolveSave = resolve;
      },
    );
    vi.mocked(api.submitFeedback).mockReturnValue(delayed);
    vi.mocked(api.projects).mockResolvedValue([project]);
    render(<App />);
    await user.click(
      await screen.findByRole("button", { name: "Открыть чат Пчелиный рывок" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Оценка 3 из 5" }),
    );
    await user.click(screen.getByRole("checkbox", { name: "Музыка и звук" }));
    await user.type(
      screen.getByLabelText("Комментарий к оценке"),
      "Отправленный отзыв",
    );
    await user.click(screen.getByRole("button", { name: "Сохранить отзыв" }));
    expect(screen.getByLabelText("Комментарий к оценке")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Оценка 4 из 5" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("checkbox", { name: "Музыка и звук" }),
    ).toBeDisabled();
    await act(async () => {
      resolveSave({
        id: "saved",
        revision_id: "revision-1",
        rating: 3,
        reasons: ["music"],
        comment: "Отправленный отзыв",
        created_at: run.created_at,
        updated_at: run.updated_at,
      });
      await delayed;
    });
    expect(screen.getByLabelText("Комментарий к оценке")).toHaveValue(
      "Отправленный отзыв",
    );
    expect(screen.getByLabelText("Комментарий к оценке")).not.toBeDisabled();
    expect(
      screen.getByText("Учтём этот приоритет в следующей генерации."),
    ).toBeVisible();
  });
});
