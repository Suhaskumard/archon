import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAsync, useErrorGuard, usePoll } from "../hooks";

describe("useAsync", () => {
  it("resolves to data and clears loading", async () => {
    const { result } = renderHook(() => useAsync(() => Promise.resolve(42), []));
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe(42);
    expect(result.current.error).toBeNull();
  });

  it("captures the error message on rejection", async () => {
    const { result } = renderHook(() =>
      useAsync(() => Promise.reject(new Error("boom")), []),
    );
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("does not set state after unmount", async () => {
    let resolve!: (v: number) => void;
    const fn = () => new Promise<number>((r) => (resolve = r));
    const { result, unmount } = renderHook(() => useAsync(fn, []));
    unmount();
    await act(async () => {
      resolve(1);
      await Promise.resolve();
    });
    // no throw / no React "state update on unmounted component" warning
    expect(result.current.data).toBeNull();
  });

  it("reload() re-invokes fn", async () => {
    const fn = vi.fn().mockResolvedValueOnce("a").mockResolvedValueOnce("b");
    const { result } = renderHook(() => useAsync(fn, []));
    await waitFor(() => expect(result.current.data).toBe("a"));
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe("b"));
    expect(fn).toHaveBeenCalledTimes(2);
  });
});

describe("usePoll", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("polls until isTerminal then stops", async () => {
    const states = ["RUNNING", "RUNNING", "COMPLETED"];
    let i = 0;
    const fn = vi.fn(() => Promise.resolve(states[Math.min(i++, states.length - 1)]));
    renderHook(() => usePoll(fn, [], (s) => s === "COMPLETED", 100));

    await vi.advanceTimersByTimeAsync(0); // first call
    expect(fn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(100);
    await vi.advanceTimersByTimeAsync(100);
    expect(fn).toHaveBeenCalledTimes(3);
    const callsAtTerminal = fn.mock.calls.length;
    await vi.advanceTimersByTimeAsync(500);
    expect(fn).toHaveBeenCalledTimes(callsAtTerminal); // frozen
  });

  it("surfaces the error and keeps polling while calls reject", async () => {
    vi.useRealTimers(); // waitFor + fake timers don't mix
    const fn = vi.fn().mockRejectedValue(new Error("net"));
    const { result } = renderHook(() => usePoll(fn, [], () => false, 5));
    await waitFor(() => expect(result.current.error).toBe("net"));
    const calls = fn.mock.calls.length;
    await waitFor(() => expect(fn.mock.calls.length).toBeGreaterThan(calls));
  });

  it("recovers to data once a call resolves terminal", async () => {
    vi.useRealTimers();
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("net"))
      .mockResolvedValue("COMPLETED");
    const { result } = renderHook(() =>
      usePoll(fn, [], (s) => s === "COMPLETED", 5),
    );
    await waitFor(() => expect(result.current.data).toBe("COMPLETED"));
    expect(result.current.error).toBeNull();
  });

  it("clears the pending timer on unmount", async () => {
    const fn = vi.fn(() => Promise.resolve("RUNNING"));
    const { unmount } = renderHook(() => usePoll(fn, [], () => false, 100));
    await vi.advanceTimersByTimeAsync(0);
    unmount();
    const calls = fn.mock.calls.length;
    await vi.advanceTimersByTimeAsync(1000);
    expect(fn).toHaveBeenCalledTimes(calls);
  });
});

describe("useErrorGuard", () => {
  it("captures a thrown error and clears it on the next run", async () => {
    const { result } = renderHook(() => useErrorGuard());
    await act(async () => {
      await result.current.guard(async () => {
        throw new Error("nope");
      });
    });
    expect(result.current.err).toBe("nope");
    await act(async () => {
      await result.current.guard(async () => {});
    });
    expect(result.current.err).toBeNull();
  });
});
