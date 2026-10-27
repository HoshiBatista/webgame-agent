import { useLayoutEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

const audiences = [
  { id: 'everyone', label: 'Для всех' },
  { id: 'gamers', label: 'Для геймеров' },
  { id: 'children', label: 'Для детей' },
  { id: 'seniors', label: 'Для старших' },
  { id: 'beginners', label: 'Для новичков' },
  { id: 'family', label: 'Для семьи' },
  { id: 'learning', label: 'Для обучения' },
  { id: 'relax', label: 'Для отдыха' },
];

export default function AudienceSelector({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const row = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });

  function measure() {
    const element = row.current;
    if (!element) return;
    const left = element.scrollLeft > 1;
    const right = element.scrollLeft + element.clientWidth < element.scrollWidth - 1;
    setEdges((previous) =>
      previous.left === left && previous.right === right ? previous : { left, right },
    );
  }

  function reveal(button: HTMLButtonElement) {
    const element = row.current;
    if (!element?.clientWidth) return;
    const bounds = element.getBoundingClientRect();
    const item = button.getBoundingClientRect();
    const left = bounds.left + 4;
    const right = bounds.right - 4;
    const distance =
      item.left < left ? item.left - left : item.right > right ? item.right - right : 0;
    if (distance) element.scrollTo({ left: element.scrollLeft + distance, behavior: 'instant' });
  }

  useLayoutEffect(() => {
    const element = row.current;
    if (!element) return;
    const selected = element.querySelector<HTMLButtonElement>('[aria-pressed="true"]');
    if (selected) reveal(selected);
    measure();
  }, [value]);

  useLayoutEffect(() => {
    const element = row.current;
    if (!element) return;
    const update = () => {
      const target =
        element.querySelector<HTMLButtonElement>('button:focus-visible') ??
        element.querySelector<HTMLButtonElement>('[aria-pressed="true"]');
      if (target) reveal(target);
      measure();
    };
    const observer = new ResizeObserver(update);
    observer.observe(element);
    for (const button of element.children) observer.observe(button);
    return () => observer.disconnect();
  }, []);

  function scroll(direction: number) {
    const element = row.current;
    if (!element) return;
    element.scrollBy({
      left: direction * element.clientWidth * 0.75,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'instant'
        : 'smooth',
    });
  }

  return (
    <div className="audience-picker">
      <div
        ref={row}
        className="audience-row"
        role="group"
        aria-label="Аудитория игры"
        onScroll={measure}
      >
        {audiences.map((item) => (
          <button
            type="button"
            key={item.id}
            disabled={disabled}
            className={value === item.id ? 'selected' : ''}
            onClick={() => onChange(item.id)}
            onFocus={(event) => {
              // Keep a pressed pointer target still until its click finishes.
              if (!event.currentTarget.matches(':active')) reveal(event.currentTarget);
            }}
            aria-pressed={value === item.id}
          >
            <span
              className="audience-icon"
              aria-hidden="true"
              style={{ maskImage: `url(/assets/audience-${item.id}.svg)` }}
            />
            {item.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="audience-scroll audience-scroll-left"
        aria-label="Предыдущие режимы"
        title="Предыдущие режимы"
        tabIndex={-1}
        disabled={!edges.left}
        onClick={() => scroll(-1)}
      >
        <ChevronLeft size={17} />
      </button>
      <button
        type="button"
        className="audience-scroll audience-scroll-right"
        aria-label="Следующие режимы"
        title="Следующие режимы"
        tabIndex={-1}
        disabled={!edges.right}
        onClick={() => scroll(1)}
      >
        <ChevronRight size={17} />
      </button>
    </div>
  );
}
