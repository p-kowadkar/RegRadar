import { useCallback, useEffect, useState } from "react";
import { setUserKeys } from "../api/client";
import type { UserKeys } from "../types";

const STORAGE_KEY = "regradar:user-keys";

const EMPTY_KEYS: UserKeys = {
  llmKey: "",
  llmProvider: "",
  llmModel: "",
  scraperKey: "",
  scraperProvider: "",
};

function readFromStorage(): UserKeys {
  if (typeof window === "undefined") return EMPTY_KEYS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_KEYS;
    const parsed = JSON.parse(raw) as Partial<UserKeys>;
    return { ...EMPTY_KEYS, ...parsed };
  } catch {
    return EMPTY_KEYS;
  }
}

function writeToStorage(keys: UserKeys): void {
  if (typeof window === "undefined") return;
  // Don't persist completely empty state -- keep storage clean
  const hasAnything =
    keys.llmKey ||
    keys.llmProvider ||
    keys.llmModel ||
    keys.scraperKey ||
    keys.scraperProvider;
  if (!hasAnything) {
    window.localStorage.removeItem(STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(keys));
}

/**
 * BYOK key management. Persists to localStorage, pushes to api/client on every change,
 * and exposes a setter for the SettingsModal.
 *
 * Keys never leave the browser except as X-User-* headers on outbound API requests.
 * Never logged.
 */
export function useUserKeys() {
  const [keys, setKeysState] = useState<UserKeys>(readFromStorage);

  // Push the initial value into the api client (it may have rehydrated after this module's import).
  useEffect(() => {
    setUserKeys(keys);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setKeys = useCallback((next: UserKeys) => {
    setKeysState(next);
    writeToStorage(next);
    setUserKeys(next);
  }, []);

  const clear = useCallback(() => setKeys(EMPTY_KEYS), [setKeys]);

  const hasLLMKey = Boolean(keys.llmKey && keys.llmProvider);
  const hasScraperKey = Boolean(keys.scraperKey && keys.scraperProvider);

  return { keys, setKeys, clear, hasLLMKey, hasScraperKey };
}
