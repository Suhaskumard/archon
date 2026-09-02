// Shared data-fetching hooks (Phase 17). These replace the ~20 hand-rolled
// per-panel effects that fetched, tracked a mounted flag, and silently swallowed
// errors in the old flat App.tsx. Errors are now surfaced, not discarded.

import { useCallback, useEffect, useRef, useState } from "react";

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Run `fn` whenever `deps` change, exposing `{ data, error, loading, reload }`.
 * Cancels a stale in-flight result on unmount / dep change, and captures the
 * error message rather than discarding it.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fnRef
      .current()
      .then((v) => {
        if (!active) return;
        setData(v);
        setLoading(false);
      })
      .catch((e) => {
        if (!active) return;
        setError(toMessage(e));
        setLoading(false);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}

/**
 * Poll `fn` on an interval until `isTerminal(value)` is true. Uses a chained
 * `setTimeout` (not `setInterval`) so a slow response never stacks requests, and
 * clears the pending timer on unmount / dep change.
 */
export function usePoll<T>(
  fn: () => Promise<T>,
  deps: unknown[],
  isTerminal: (v: T) => boolean,
  intervalMs = 800,
): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const v = await fnRef.current();
        if (!active) return;
        setData(v);
        setError(null);
        if (!isTerminal(v)) timer = setTimeout(tick, intervalMs);
      } catch (e) {
        if (!active) return;
        setError(toMessage(e));
        timer = setTimeout(tick, intervalMs);
      }
    };
    void tick();

    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error };
}

/**
 * Imperative error boundary for POST-style flows (add repo, compute impact, run
 * comparison). Same shape as the old `useError` helper.
 */
export function useErrorGuard() {
  const [err, setErr] = useState<string | null>(null);
  const guard = useCallback(async (fn: () => Promise<void>) => {
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(toMessage(e));
    }
  }, []);
  return { err, guard };
}

export const TERMINAL_RUN_STATES = new Set(["COMPLETED", "FAILED", "CANCELLED"]);
