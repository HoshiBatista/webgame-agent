import { useEffect, useState } from 'react';
import { errorText, request } from './api';
import type {
  AnalyticsChoice,
  AnalyticsHistory as History,
  AnalyticsIdea,
  AnalyticsSummary,
} from './types';

function rate(value: number | null) {
  return value === null ? 'Нет данных' : `${value.toLocaleString('ru-RU')}%`;
}
function period(start: string, end: string) {
  return `${start.slice(0, 10)} — ${end.slice(0, 10)} (UTC, конец не включён)`;
}
function Evidence({ idea }: { idea: AnalyticsIdea }) {
  const { candidate: a, baseline: b } = idea.evidence;
  return (
    <p className="analytics-evidence">
      Завершения: {a.finished}/{a.started} ({rate(a.finish_rate)}) против {b.finished}/{b.started} (
      {rate(b.finish_rate)}). Повторы: {a.replayed}/{a.started} против {b.replayed}/{b.started}.
      Сравнение с{' '}
      {idea.rule_id === 'short_round'
        ? 'обычными раундами той же механики'
        : 'остальными механиками того же формата раунда'}
      .
    </p>
  );
}

export default function AnalyticsSuggestions({
  audience,
  choice,
  onChange,
  disabled,
  available,
}: {
  audience: string;
  choice: AnalyticsChoice | null;
  onChange: (value: AnalyticsChoice | null) => void;
  disabled: boolean;
  available: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!open || !available) return;
    const controller = new AbortController();
    let current = true;
    setLoading(true);
    setError('');
    setData(null);
    void request<AnalyticsSummary>(
      `/api/analytics/summary/?audience=${encodeURIComponent(audience)}`,
      {
        signal: controller.signal,
      },
    )
      .then((value) => {
        if (current) setData(value);
      })
      .catch((cause) => {
        if (current) setError(errorText(cause));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [open, audience, available, refresh]);
  const visible = data?.audience === audience ? data : null;
  const staleChoice = !!(
    choice &&
    visible?.dataset &&
    (choice.audience !== audience ||
      choice.selection.dataset_id !== visible.dataset.id ||
      choice.selection.dataset_hash !== visible.dataset.hash ||
      choice.selection.policy_version !== visible.policy_version ||
      choice.selection.recommendation_ids.some(
        (id) => !visible.recommendations.some((idea) => idea.id === id),
      ))
  );
  function toggle(idea: AnalyticsIdea) {
    if (!visible?.dataset || disabled || staleChoice) return;
    const same =
      choice?.selection.dataset_hash === visible.dataset.hash && choice.audience === audience;
    const selected = same ? choice.ideas : [];
    const ideas = selected.some((i) => i.id === idea.id)
      ? selected.filter((i) => i.id !== idea.id)
      : [...selected, idea];
    onChange(
      ideas.length
        ? {
            audience,
            ideas,
            selection: {
              dataset_id: visible.dataset.id,
              dataset_hash: visible.dataset.hash,
              policy_version: visible.policy_version,
              recommendation_ids: ideas.map((i) => i.id).sort(),
            },
          }
        : null,
    );
  }
  return (
    <section className="analytics-panel" aria-label="Идеи на основе данных">
      <div className="analytics-source-bar">
        <strong>Демонстрационные данные</strong>
        {open && (
          <button
            type="button"
            className="text-button"
            aria-label="Свернуть аналитику"
            onClick={() => setOpen(false)}
          >
            Свернуть
          </button>
        )}
      </div>
      {!!choice?.ideas.length && (
        <div aria-label="Выбранные идеи">
          <strong>Для этой новой игры · демонстрационные данные</strong>
          {choice.ideas.map((idea) => (
            <div className="analytics-selected" key={idea.id}>
              <span>{idea.advice}</span>
              <button
                type="button"
                className="text-button"
                disabled={disabled}
                aria-label={`Убрать идею: ${idea.advice}`}
                onClick={() => {
                  const ideas = choice.ideas.filter((i) => i.id !== idea.id);
                  onChange(
                    ideas.length
                      ? {
                          ...choice,
                          ideas,
                          selection: {
                            ...choice.selection,
                            recommendation_ids: ideas.map((i) => i.id).sort(),
                          },
                        }
                      : null,
                  );
                }}
              >
                Убрать
              </button>
            </div>
          ))}
          <p className="field-help">Явный запрос важнее этих идей. Общие пожелания не изменятся.</p>
        </div>
      )}
      {!available ? (
        <p role="status">Аналитика сейчас недоступна. Можно убрать идеи и создать игру без них.</p>
      ) : (
        <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
          <summary>Что подсказывают данные</summary>
          <p>
            <strong>Демонстрационные данные.</strong> Вымышленные наблюдения, а не статистика
            клиентов.
          </p>
          {loading && <p role="status">Загружаем сравнение…</p>}
          {error && <p role="alert">{error} Создание игры без идей остаётся доступным.</p>}
          {visible?.dataset && (
            <p className="field-help">
              {period(visible.dataset.period_start, visible.dataset.period_end)}
            </p>
          )}
          {visible && (
            <>
              {visible.groups.length > 0 && (
                <div
                  className="analytics-table-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label="Сравнение механик"
                >
                  <table>
                    <caption>Телефон, касания. Доли считаются от начатых первых раундов.</caption>
                    <thead>
                      <tr>
                        <th scope="col">Механика</th>
                        <th scope="col">Начато</th>
                        <th scope="col">Завершено</th>
                        <th scope="col">Повтор</th>
                        <th scope="col">Активное время</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visible.groups.map((group) => (
                        <tr key={group.mechanic + group.round_style}>
                          <th scope="row">
                            {group.label},{' '}
                            {group.round_style === 'short' ? 'короткий раунд' : 'обычный раунд'}
                          </th>
                          <td>{group.started}</td>
                          <td>{rate(group.finish_rate)}</td>
                          <td>{rate(group.replay_rate)}</td>
                          <td>
                            {group.mean_active_seconds === null
                              ? 'Нет данных'
                              : `${group.mean_active_seconds.toLocaleString('ru-RU')} с`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {staleChoice && (
                <p role="status">
                  Выбраны идеи из прежнего набора. Чтобы выбрать новые, сначала уберите прежние.
                </p>
              )}
              {visible.recommendations.map((idea) => (
                <article className="analytics-idea" key={idea.id}>
                  <p>{idea.advice}</p>
                  <Evidence idea={idea} />
                  <button
                    type="button"
                    className="button button-small button-outline"
                    disabled={disabled || staleChoice}
                    aria-pressed={!!choice?.selection.recommendation_ids.includes(idea.id)}
                    onClick={() => toggle(idea)}
                  >
                    {choice?.selection.recommendation_ids.includes(idea.id)
                      ? 'Идея выбрана'
                      : 'Учесть в новой игре'}
                  </button>
                </article>
              ))}
              {!visible.recommendations.length && (
                <p role="status">
                  {visible.data_status === 'empty'
                    ? 'Для этой аудитории пока нет данных.'
                    : 'Недостаточно сопоставимых наблюдений или заметной разницы для рекомендации.'}
                </p>
              )}
              <p className="field-help">
                Завершение включает победу и поражение. Повтор — начало второго раунда в той же
                сессии. Различия не доказывают причину и не гарантируют успех новой игры.
              </p>
            </>
          )}
          <button
            type="button"
            className="text-button"
            disabled={loading || disabled}
            onClick={() => setRefresh((v) => v + 1)}
          >
            Обновить данные
          </button>
        </details>
      )}
    </section>
  );
}

export function AnalyticsHistory({ data }: { data?: History | null }) {
  if (!data) return null;
  const labels: Record<string, string> = {
    frozen: 'Идеи сохранены в задании; отправка ещё не подтверждена.',
    prepared: 'Контекст подготовлен; отправка ещё не подтверждена.',
    submitted: 'Запрос отправлен; полный результат ещё не получен.',
    unknown: 'Доставка или результат запроса не подтверждены.',
    received: 'Ответ на запрос с выбранными идеями сохранён.',
    inherited: 'Это основание создания исходной игры; при правке идеи не добавляются заново.',
  };
  return (
    <details className="analytics-panel">
      <summary>Основание аналитических идей · демоданные</summary>
      <p>
        {data.label}, версия {data.dataset_version}. {period(data.period_start, data.period_end)}
      </p>
      <p>{labels[data.context_state || 'inherited']}</p>
      {!data.same_audience && (
        <p>Аудитория изменилась: эти идеи к текущей правке не применялись.</p>
      )}
      {data.recommendations.map((idea) => (
        <article key={idea.id}>
          <p>{idea.advice}</p>
          <Evidence idea={idea} />
        </article>
      ))}
      <p className="field-help">Передача идеи модели не доказывает её реализацию в игре.</p>
    </details>
  );
}
