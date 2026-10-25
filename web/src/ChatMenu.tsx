import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MoreVertical, Pencil, Trash2 } from 'lucide-react';
import type { ChatSummary } from './types';

export default function ChatMenu({
  chat,
  onRename,
  onDelete,
}: {
  chat: ChatSummary;
  onRename: () => void;
  onDelete: () => void;
}) {
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  function close() {
    setPosition(null);
    trigger.current?.focus();
  }
  useEffect(() => {
    if (!position) return;
    menu.current?.querySelector('button')?.focus();
    const outside = (event: PointerEvent) => {
      if (
        !menu.current?.contains(event.target as Node) &&
        !trigger.current?.contains(event.target as Node)
      )
        setPosition(null);
    };
    const dismiss = () => setPosition(null);
    document.addEventListener('pointerdown', outside);
    window.addEventListener('resize', dismiss);
    window.addEventListener('scroll', dismiss, true);
    return () => {
      document.removeEventListener('pointerdown', outside);
      window.removeEventListener('resize', dismiss);
      window.removeEventListener('scroll', dismiss, true);
    };
  }, [position]);
  return (
    <>
      <button
        type="button"
        className="icon-button chat-options-button"
        ref={trigger}
        aria-label={`Действия с чатом «${chat.title || 'Новая игра'}»`}
        aria-haspopup="menu"
        aria-expanded={!!position}
        onClick={() => {
          if (position) {
            close();
            return;
          }
          const box = trigger.current!.getBoundingClientRect();
          setPosition({
            top: Math.min(box.bottom + 5, window.innerHeight - 110),
            left: Math.max(8, Math.min(box.right - 190, window.innerWidth - 198)),
          });
        }}
      >
        <MoreVertical size={18} />
      </button>
      {position &&
        createPortal(
          <div
            className="chat-options-menu"
            role="menu"
            aria-label="Действия с чатом"
            ref={menu}
            style={position}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                close();
              }
              if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
                event.preventDefault();
                const buttons = Array.from(menu.current!.querySelectorAll('button'));
                const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
                buttons[
                  event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? buttons.length - 1
                      : (index + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) %
                        buttons.length
                ]?.focus();
              }
              if (event.key === 'Tab') setPosition(null);
            }}
          >
            <button
              role="menuitem"
              onClick={() => {
                close();
                onRename();
              }}
            >
              <Pencil size={16} /> Переименовать
            </button>
            <button
              role="menuitem"
              className="danger-text"
              onClick={() => {
                close();
                onDelete();
              }}
            >
              <Trash2 size={16} /> Удалить
            </button>
          </div>,
          document.body,
        )}
    </>
  );
}
