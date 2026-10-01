/** Joins conditional class names -- a tiny stand-in for `clsx` so styling
 * tweaks never require pulling in a dependency just to toggle a class. */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
