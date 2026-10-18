import { useState, type FormEvent } from 'react';
import {
  ArrowRight,
  Check,
  Circle,
  Gamepad2,
  MousePointer2,
  Plus,
  Sparkles,
  Star,
  X,
} from 'lucide-react';
import { Brand, ErrorNotice, Modal } from './components';
import { errorText, getSession, post, setCsrfToken } from './api';
import { useSession } from './context';
import type { Session } from './types';

export function Login({ onClose }: { onClose: () => void }) {
  const { updateSession } = useSession();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await getSession();
      const data = await post<Session>('/api/login/', { username, password });
      setCsrfToken(data.csrfToken);
      updateSession(data);
      onClose();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="С возвращением!" onClose={onClose}>
      <div className="login-decoration" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
      <p className="modal-intro">Ваша следующая игра начинается здесь.</p>
      <form onSubmit={submit} className="form-stack">
        <label>
          Имя пользователя
          <input
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
            placeholder="Как вас зовут в GameForge"
          />
        </label>
        <label>
          Пароль
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            placeholder="Ваш пароль"
          />
        </label>
        {error && <ErrorNotice message={error} />}
        <button className="button button-coral button-block" disabled={busy}>
          {busy ? 'Входим…' : 'Войти в мастерскую'}
          <ArrowRight size={18} />
        </button>
        <p className="form-footnote">Учётную запись выдаёт администратор вашей команды.</p>
      </form>
    </Modal>
  );
}
export default function Landing() {
  const [login, setLogin] = useState(false);
  return (
    <div className="landing">
      <header className="landing-header">
        <Brand />
        <span className="landing-header-note">Маленькие игры. Большие идеи.</span>
        <button className="button button-outline" onClick={() => setLogin(true)}>
          Войти <ArrowRight size={17} />
        </button>
      </header>
      <main>
        <section className="hero">
          <div className="hero-copy">
            <span className="eyebrow">
              <span className="tiny-star">✦</span> От «а что, если» до первого хода
            </span>
            <h1>
              Придумайте.
              <br />А потом <span>поиграем.</span>
            </h1>
            <p className="hero-description">
              Ваша идея — наша отправная точка.
              <br />
              Опишите мини-игру, попробуйте её и добавьте
              <br className="desktop-break" /> немного своего характера.
            </p>
            <button className="button button-coral hero-button" onClick={() => setLogin(true)}>
              Создать свою игру <ArrowRight size={20} />
            </button>
            <div className="hero-benefits">
              <span>
                <Check size={15} /> Без кода
              </span>
              <span>
                <Check size={15} /> В вашем стиле
              </span>
              <span>
                <Check size={15} /> Можно поделиться
              </span>
            </div>
          </div>
          <div className="hero-art" aria-hidden="true">
            <span className="art-spark art-spark-one">✦</span>
            <span className="art-spark art-spark-two">✳</span>
            <div className="idea-label">
              <Sparkles size={16} /> Всё начинается с идеи
            </div>
            <div className="art-window">
              <div className="art-window-top">
                <span />
                <span />
                <span />
                <i>YOUR LITTLE UNIVERSE</i>
              </div>
              <div className="art-scene">
                <div className="scene-grid" />
                <div className="pixel-sun" />
                <div className="floating-coins">
                  <i />
                  <i />
                  <i />
                </div>
                <div className="pixel-creature">
                  <i />
                  <i />
                </div>
                <div className="scene-ground" />
                <span className="scene-cursor">
                  <MousePointer2 size={34} />
                  <b>это вы</b>
                </span>
              </div>
              <div className="art-window-bottom">
                <span>
                  <Gamepad2 size={17} /> Идея становится игрой
                </span>
                <span>✦</span>
              </div>
            </div>
            <div className="art-mini-card">
              <div className="mini-grid">
                <X />
                <Circle />
                <X />
                <Circle />
                <Star />
                <Circle />
                <X />
                <Circle />
                <Plus />
              </div>
              <span>А можно по-своему?</span>
              <b>Можно всё придумать.</b>
            </div>
            <div className="art-sticker">
              PRESS
              <br />
              <strong>CREATE</strong>
              <ArrowRight size={20} />
            </div>
          </div>
        </section>
        <section className="landing-strip">
          <span>Идея →</span>
          <span>Пара слов →</span>
          <span>
            Ваша игра <Star size={21} />
          </span>
        </section>
        <section className="how-section">
          <div>
            <span className="eyebrow">Никакой магии. Ну, почти.</span>
            <h2>
              Маленький путь
              <br />к «ещё одну партию».
            </h2>
          </div>
          <div className="how-steps">
            <article>
              <span>01</span>
              <h3>Расскажите задумку</h3>
              <p>
                Про механику, настроение и тех, кто будет играть. Нескольких предложений достаточно.
              </p>
            </article>
            <article>
              <span>02</span>
              <h3>Сделайте своим</h3>
              <p>Сыграйте. Поменяйте цвета, темп или добавьте пару уровней — просто сообщением.</p>
            </article>
            <article>
              <span>03</span>
              <h3>Пусть играют все</h3>
              <p>Поделитесь в ленте или скачайте HTML. Ваша маленькая вселенная готова к гостям.</p>
            </article>
          </div>
        </section>
      </main>
      <footer className="landing-footer">
        <Brand />
        <span>Сделано для идей, в которые хочется играть.</span>
        <span className="footer-sign">Have a little fun. ✳</span>
      </footer>
      {login && <Login onClose={() => setLogin(false)} />}
    </div>
  );
}
