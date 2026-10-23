'use client';
import { useEffect, useState } from 'react';

// Only editing drafts live here; uploaded files and analytical results stay on the server.
export function useSessionDraft<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try { const saved = sessionStorage.getItem(key); return saved === null ? initial : JSON.parse(saved) as T; }
    catch { return initial; }
  });
  useEffect(() => { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* Storage can be disabled or full. */ } }, [key, value]);
  return [value, setValue] as const;
}
