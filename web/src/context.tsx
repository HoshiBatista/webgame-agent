import { createContext, useContext } from 'react';
import type { ChatSummary, Session } from './types';
export const SessionContext = createContext<{
  session: Session;
  updateSession: (session: Session) => void;
  refresh: () => Promise<void>;
}>({} as never);
export function useSession() {
  return useContext(SessionContext);
}
export type ChatTitleChange = Pick<ChatSummary, 'id' | 'title' | 'updated_at'>;
export function chatsChanged(change?: ChatTitleChange) {
  window.dispatchEvent(new CustomEvent('gameforge:chats', { detail: change }));
}
