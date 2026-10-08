/**
 * MARCO-AI-CHAT Phase B — simple in-memory event bus for the
 * wake-word → dock-open bridge between root layout and (app) layout.
 */
type Listener = () => void;
const listeners = new Set<Listener>();

export const aiDockEvents = {
  onOpen: (fn: Listener) => {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
  emitOpen: () => {
    listeners.forEach((fn) => fn());
  },
};
