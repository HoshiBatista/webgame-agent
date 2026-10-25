import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Circle,
  Gamepad2,
  MousePointer2,
  Plus,
  Sparkles,
  Star,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { Brand, BrandDisclaimer } from './components';

export default function Landing() {
  return (
    <div className="landing">
      <header className="landing-header">
        <Brand />
        <Link className="button button-outline" to="/login">
          Войти <ArrowUpRight size={17} />
        </Link>
      </header>
      <main>
        <section className="hero">
          <div className="hero-copy">
            <span className="eyebrow">
              <Sparkles className="tiny-star" size={15} aria-hidden="true" /> От «а что, если…» до
              «сыграем?»
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
            <Link className="button button-primary hero-button" to="/login">
              Создать свою игру <ArrowRight size={20} />
            </Link>
            <div className="hero-benefits">
              <span>
                <Check size={15} /> В вашем стиле
              </span>
              <span>
                <Check size={15} /> Можно поделиться
              </span>
            </div>
          </div>
          <div className="hero-art" aria-hidden="true">
            <Sparkles className="art-spark art-spark-one" size={42} />
            <Star className="art-spark art-spark-two" size={30} />
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
                <Sparkles size={18} />
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
              <b>Можно всё!</b>
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
          <span>Идея</span>
          <i className="landing-strip-arrow" aria-hidden="true" />
          <span>Пара слов</span>
          <i className="landing-strip-arrow" aria-hidden="true" />
          <span>Ваша игра</span>
        </section>
        <section className="how-section">
          <div>
            <span className="eyebrow">Три шага к вашей игре</span>
            <h2>От идеи к готовой игре</h2>
          </div>
          <div className="how-steps">
            <article>
              <span>01</span>
              <h3>Расскажите задумку</h3>
              <p>Про механику и тех, кто будет играть. Достаточно нескольких предложений.</p>
            </article>
            <article>
              <span>02</span>
              <h3>Сделайте своим</h3>
              <p>Сыграйте. Настройте цвета, темп или добавьте пару уровней — одним сообщением.</p>
            </article>
            <article>
              <span>03</span>
              <h3>Пусть играют все</h3>
              <p>
                Поделитесь в ленте или скачайте HTML. Ваша маленькая вселенная ждёт своих игроков.
              </p>
            </article>
          </div>
        </section>
      </main>
      <footer className="landing-footer">
        <div className="landing-footer-main">
          <Brand />
        </div>
        <BrandDisclaimer />
      </footer>
    </div>
  );
}
