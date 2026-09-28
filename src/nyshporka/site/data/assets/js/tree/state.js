// Простий реактивний store без зовнішніх залежностей.
// Підписані callback-и викликаються після кожного update; pane вирішує
// сама, чи її стан змінився і чи треба рендерити.

export function createStore(initial) {
  let state = { ...initial };
  const listeners = new Set();
  return {
    get() { return state; },
    update(patch) {
      state = { ...state, ...patch };
      listeners.forEach((fn) => fn(state));
    },
    subscribe(fn) {
      listeners.add(fn);
      fn(state);  // initial call
      return () => listeners.delete(fn);
    },
  };
}

export const initialState = {
  mode: 'overview',          // 'overview' | 'focus'
  focusId: null,             // person id у focus-режимі
  selectedId: null,          // активна особа для Details/Map/Timeline
  hoverId: null,             // hover для підсвітки родичів
  yearCursor: null,          // фільтр по року (timeline scrub)
  ancestorDepth: 5,
  descendantDepth: 3,
  showHypothesis: true,
  showPrivate: true,
};
