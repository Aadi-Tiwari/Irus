// Path to a file in public/. Next rewrites its own bundle URLs with assetPrefix
// but leaves hand-written public/ references alone, so those go through here or
// they 404 wherever the site is not served from the domain root.
const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export function asset(path: string) {
  return `${BASE}${path}`;
}
