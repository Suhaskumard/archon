import "@testing-library/jest-dom/vitest";
import "vitest-axe/extend-expect";
import { afterEach, expect, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import * as axeMatchers from "vitest-axe/matchers";

expect.extend(axeMatchers);

afterEach(() => {
  cleanup();
});

// jsdom gaps the app / test libs touch.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

HTMLElement.prototype.scrollIntoView = HTMLElement.prototype.scrollIntoView ?? (() => {});

globalThis.ResizeObserver =
  globalThis.ResizeObserver ??
  (class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver);

globalThis.URL.createObjectURL = globalThis.URL.createObjectURL ?? vi.fn(() => "blob:mock");
globalThis.URL.revokeObjectURL = globalThis.URL.revokeObjectURL ?? vi.fn();
