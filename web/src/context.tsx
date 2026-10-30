import { createContext, useContext } from 'react';
import type { ChatSummary, Session } from './types';
export interface StudioDraft {
  chatTitle?: string | null;
  prompt: string;
  audience: string | null;
  selectedRevision: string | null;
  idempotencyKey: string;
  lastPayload: string;
}
export const SessionContext = createContext<{
  session: Session;
  updateSession: (session: Session) => void;
  refresh: () => Promise<void>;
  studioDrafts?: Map<string, StudioDraft>;
}>({} as never);
export function useSession() {
  return useContext(SessionContext);
}
export type ChatTitleChange = Pick<ChatSummary, 'id' | 'title' | 'updated_at'>;
export function chatsChanged(change?: ChatTitleChange) {
  window.dispatchEvent(new CustomEvent('gameforge:chats', { detail: change }));
}
