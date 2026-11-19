import { ArrowDown, ArrowLeft, ArrowUpRight } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Brand, BrandDisclaimer } from './components';
import { useSession } from './context';
import './model-info.scss';

const models = [
  {
    name: 'Pro',
    art: 'pro',
    description:
      'Составляет план и пишет по нему игру. Подойдёт, если нужно связать несколько правил — например, сбор ресурсов, улучшения героя и победу над боссом.',
  },
  {
    name: 'Lite',
    art: 'lite',
    description:
      'Сразу собирает игру по описанию. Удобно попробовать одну механику, например змейку, которая ускоряется с каждым яблоком, и развить идею в том же чате.',
  },
  {
    name: 'Multiagent',
    art: 'multiagent',
    description:
      'По общему плану несколько агентов параллельно создают игровую механику, графику и звук. Из этих частей собирается одна игра.',
  },
] as const;

function ModelArt({ kind }: { kind: (typeof models)[number]['art'] }) {
  return (
    <div className={`model-art model-art--${kind}`} aria-hidden="true">
      <div className="model-art-shape">
        <i />
        <i />
        <i />
      </div>
    </div>
  );
}

export default function ModelInfo() {
  const { session } = useSession();
  const location = useLocation();
  const variantsSection = useRef<HTMLElement>(null);
  const from = location.state?.from;
  const backTo =
    typeof from === 'string' && from.startsWith('/') && !from.startsWith('//') ? from : '/';
  useEffect(() => {
    if (location.hash === '#four-variants' && variantsSection.current) {
      variantsSection.current.focus({ preventScroll: true });
      variantsSection.current.scrollIntoView?.({ block: 'start' });
    }
  }, [location.hash, location.key]);

  return (
    <div className={`model-info${session.user ? '' : ' landing'}`}>
      <header className="landing-header">
        <Brand />
        {session.user ? (
          <Link className="button button-outline" to={backTo} replace>
            <ArrowLeft size={17} aria-hidden="true" />
            Назад
          </Link>
        ) : (
          <Link className="button button-outline" to="/login">
            Войти <ArrowUpRight size={17} aria-hidden="true" />
          </Link>
        )}
      </header>
      <main className="model-info-main">
        <header className="model-info-intro">
          <h1>Модели beeGame</h1>
          <div>
            <p>
              Выберите модель в шапке чата или в настройках. Можно начать игру с одной моделью и
              переключиться на другую для следующей доработки.
            </p>
            <Link
              className="model-info-jump"
              to={{ search: location.search, hash: '#four-variants' }}
              state={location.state}
              replace
            >
              Как работает режим 4× <ArrowDown size={15} aria-hidden="true" />
            </Link>
          </div>
        </header>
        <div className="model-info-grid">
          {models.map(({ name, art, description }) => (
            <article className="model-info-model" key={name}>
              <ModelArt kind={art} />
              <h2>{name}</h2>
              <p>{description}</p>
            </article>
          ))}
        </div>
        <section
          id="four-variants"
          ref={variantsSection}
          tabIndex={-1}
          className="model-info-variants"
          aria-labelledby="variants-title"
        >
          <div className="model-info-variant-mark" aria-hidden="true">
            4×
          </div>
          <div className="model-info-variant-copy">
            <h2 id="variants-title">Четыре варианта одной игры</h2>
            <p>
              В Pro режим <strong>4×</strong> включён по умолчанию. По одному запросу параллельно
              создаются четыре независимые версии. Сыграть в готовую версию можно, пока остальные
              ещё создаются.
            </p>
            <p>
              Выберите понравившийся вариант в чате, чтобы продолжить его доработку. Если нужна одна
              версия, снимите галочку <strong>4×</strong> в шапке чата перед отправкой запроса.
            </p>
          </div>
        </section>
      </main>
      <footer className="landing-footer">
        <div className="landing-footer-main">
          <Brand />
          <BrandDisclaimer />
        </div>
      </footer>
    </div>
  );
}
