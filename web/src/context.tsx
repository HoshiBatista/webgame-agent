import { createContext, useContext } from 'react';
import type { Session } from './types';
export const SessionContext = createContext<{
  session: Session;
  updateSession: (session: Session) => void;
  refresh: () => Promise<void>;
}>({} as never);
export function useSession() {
  return useContext(SessionContext);
}
export function chatsChanged() {
  window.dispatchEvent(new Event('gameforge:chats'));
}
