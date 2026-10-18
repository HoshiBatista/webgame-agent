import { Check, MousePointer2 } from 'lucide-react';

export const DEMO_RECOMMENDATION =
  'Для мобильного управления выделяй крупные, разнесённые зоны касания и проверяй точность ввода, сохраняя механику конкретной игры.';

export default function SyntheticAnalytics({
  onApply,
  applied,
  busy,
}: {
  onApply: () => void;
  applied: boolean;
  busy: boolean;
}) {
  return (
    <section className="synthetic-analytics" aria-label="Демонстрационная аналитика">
      <span className="eyebrow">ДЕМО · СИНТЕТИЧЕСКИЕ ДАННЫЕ</span>
      <h3>Что можно узнать из игры</h3>
      <p className="field-help">
        Пример на вымышленных измерениях. Это не статистика ваших игроков, и мы не собирали эти
        данные из ваших игр.
      </p>
      <dl className="demo-metrics">
        <div>
          <dt>Промахи при касании</dt>
          <dd>40%</dd>
        </div>
        <div>
          <dt>Попыток на действие</dt>
          <dd>3,1</dd>
        </div>
        <div>
          <dt>Размер зоны касания</dt>
          <dd>28 px</dd>
        </div>
      </dl>
      <div className="demo-recommendation">
        <MousePointer2 size={19} />
        <div>
          <strong>Дать пальцам больше места</strong>
          <p>
            В этом примере маленькие зоны совпадают с частыми промахами. Стоит увеличить и разнести
            зоны касания; результат затем проверить в самой игре.
          </p>
        </div>
      </div>
      <p className="field-help">
        По вашему решению рекомендация станет редактируемым пожеланием. Модель выберет подходящее
        решение для конкретной игры.
      </p>
      <button
        className="button button-small button-outline"
        type="button"
        onClick={onApply}
        disabled={busy || applied}
      >
        {applied ? (
          <>
            <Check size={15} /> Пожелание добавлено
          </>
        ) : (
          'Учесть в следующих играх и сохранить'
        )}
      </button>
    </section>
  );
}
