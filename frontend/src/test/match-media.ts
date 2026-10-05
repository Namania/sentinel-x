type Listener = (event: MediaQueryListEvent) => void;

/** Replace window.matchMedia with a controllable stub. Returns a handle to flip the result. */
export function installMatchMedia(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<Listener>();
  window.matchMedia = (query: string) =>
    ({
      get matches() {
        return matches;
      },
      media: query,
      onchange: null,
      addEventListener: (_: string, listener: Listener) => listeners.add(listener),
      removeEventListener: (_: string, listener: Listener) => listeners.delete(listener),
      addListener: (listener: Listener) => listeners.add(listener),
      removeListener: (listener: Listener) => listeners.delete(listener),
      dispatchEvent: () => true,
    }) as unknown as MediaQueryList;
  return {
    setMatches(next: boolean) {
      matches = next;
      for (const listener of listeners)
        listener({ matches: next, media: "" } as MediaQueryListEvent);
    },
  };
}
