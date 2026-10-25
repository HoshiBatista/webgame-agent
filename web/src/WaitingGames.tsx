import { useEffect, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';
import { request } from './api';
import { GameThumbnail } from './components';
import type { Publication } from './types';

export default function WaitingGames({
  chatId,
  sourcePublicationId,
}: {
  chatId: string;
  sourcePublicationId: string | null;
}) {
  const [games, setGames] = useState<Publication[]>([]);
  useEffect(() => {
    let alive = true;
    request<{ results: Publication[] }>('/api/publications/?sort=popular')
      .then((data) => {
        if (alive) {
          setGames(
            data.results
              .filter((game) => game.source_chat_id !== chatId && game.id !== sourcePublicationId)
              .slice(0, 3),
          );
        }
      })
      .catch(() => {
        // Optional recommendations must not interrupt the generation or its status.
      });
    return () => {
      alive = false;
    };
  }, [chatId, sourcePublicationId]);

  if (!games.length) return null;
  return (
    <section className="waiting-games" aria-label="Игры на время ожидания">
      <h2>Пока создаётся ваша игра — сыграйте в другие</h2>
      <p>Они откроются в новой вкладке. Генерация продолжится в этом чате.</p>
      <ul className="waiting-games-list">
        {games.map((game, index) => (
          <li key={game.id}>
            <Link
              className="game-card waiting-game-card"
              to={`/games/${game.id}`}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Играть в «${game.title}» — новая вкладка`}
            >
              <GameThumbnail game={game} index={index} />
              <div className="waiting-game-info">
                <h3>{game.title}</h3>
                <span className="game-author">
                  {game.author.username}
                  {game.verification === 'manual' && (
                    <span className="manual-badge">Проверил автор</span>
                  )}
                </span>
                <span className="waiting-game-play">
                  Играть <ExternalLink size={14} aria-hidden="true" />
                </span>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
