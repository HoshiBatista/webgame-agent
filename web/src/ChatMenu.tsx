import { MoreVertical, Pencil, Trash2 } from 'lucide-react';
import type { ChatSummary } from './types';
import ActionMenu from './ActionMenu';

export default function ChatMenu({
  chat,
  onRename,
  onDelete,
}: {
  chat: ChatSummary;
  onRename: () => void;
  onDelete: () => void;
}) {
  return (
    <ActionMenu
      label={`Действия с чатом «${chat.title || 'Новая игра'}»`}
      triggerClassName="icon-button chat-options-button"
      triggerContent={<MoreVertical size={18} />}
      className="chat-options-menu"
    >
      {(close) => (
        <>
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
        </>
      )}
    </ActionMenu>
  );
}
