import { useEffect, useState } from 'react';

interface DraftChoice {
  id: string;
  hash: string;
  currentId: string | null;
  lastPromptId: string | null;
}

function readChoice(key: string): DraftChoice | null {
  try {
    return JSON.parse(sessionStorage.getItem(key) ?? 'null');
  } catch {
    return null;
  }
}

// Keep a draft as the edit source across reloads without promoting it to the
// server's accepted working revision. The studio verifies it against the chat.
export function useVariantDraft(userId: string, chatId: string) {
  const key = `gameforge:variant-draft:${userId}:${chatId}`;
  const [saved, setSaved] = useState(() => ({ key, choice: readChoice(key) }));
  useEffect(() => setSaved({ key, choice: readChoice(key) }), [key]);
  function remember(choice: DraftChoice | null) {
    setSaved({ key, choice });
    try {
      if (choice) sessionStorage.setItem(key, JSON.stringify(choice));
      else sessionStorage.removeItem(key);
    } catch {
      // The in-memory choice still works when storage is unavailable.
    }
  }
  return [saved.key === key ? saved.choice : null, remember] as const;
}
