const INTERACTIVE_SELECTOR = [
  "button",
  "a",
  "input",
  "textarea",
  "select",
  "[role='button']",
  "[role='link']",
  "[contenteditable='true']",
  "[data-window-no-drag]",
].join(",");

type PointerLike = {
  button: number;
  clientY: number;
  target: EventTarget | null;
};

/**
 * Keeps the native macOS drag surface stable across every client view.
 * Page content can change freely; only the non-interactive part of the top strip starts a drag.
 */
export function shouldStartWindowDrag(event: PointerLike, stripHeight = 48): boolean {
  if (event.button !== 0 || event.clientY < 0 || event.clientY > stripHeight) return false;
  if (!(event.target instanceof Element)) return false;
  return event.target.closest(INTERACTIVE_SELECTOR) === null;
}
