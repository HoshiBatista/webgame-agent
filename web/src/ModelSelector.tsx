import { useEffect, useId, useRef } from 'react';
import { Check, ChevronDown } from 'lucide-react';
import type { ModelProfile, Session } from './types';

export function selectedProfile(session: Session) {
  if (session.capabilities.provider === 'fake') return '';
  return session.preferences.model_profile || session.capabilities.default_model_profile || '';
}

interface Props {
  options: ModelProfile[];
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}

export function ModelChoices({ options, value, disabled, onChange }: Props) {
  const name = useId();
  return (
    <fieldset className="model-choices" disabled={disabled}>
      <legend className="sr-only">Модель для следующего запроса</legend>
      {options.map((option) => (
        <label className={`model-choice ${value === option.id ? 'selected' : ''}`} key={option.id}>
          <input
            type="radio"
            name={name}
            value={option.id}
            checked={value === option.id}
            disabled={!option.available}
            onChange={() => onChange(option.id)}
          />
          <span>
            <strong>{option.name}</strong>
            {!option.available && <small>{option.unavailable_reason}</small>}
          </span>
          {value === option.id && <Check size={16} aria-hidden="true" />}
        </label>
      ))}
    </fieldset>
  );
}

export default function ModelSelector(props: Props) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (menu.current && !menu.current.contains(event.target as Node)) menu.current.open = false;
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, []);
  const selected = props.options.find((item) => item.id === props.value);
  return (
    <details
      className="model-selector"
      ref={menu}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && menu.current) {
          menu.current.open = false;
          menu.current.querySelector('summary')?.focus();
        }
      }}
    >
      <summary aria-label={`Выбрать модель: ${selected?.name || 'не выбрана'}`}>
        beeGame <strong>{selected?.name || '—'}</strong>
        <ChevronDown size={16} />
      </summary>
      <div className="menu-surface model-selector-menu">
        <ModelChoices
          {...props}
          onChange={(value) => {
            props.onChange(value);
            if (menu.current) {
              menu.current.open = false;
              menu.current.querySelector('summary')?.focus();
            }
          }}
        />
        <p>Выбор сохраняется для следующих запросов и продолжений.</p>
      </div>
    </details>
  );
}
