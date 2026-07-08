const DEFAULT_API_BASE = "";

export function getApiBase(): string {
  const configuredBase = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE;
  if (configuredBase.trim()) {
    return normalizeApiBase(configuredBase);
  }

  return getBrowserPathApiBase();
}

export function apiUrl(path: string, base = getApiBase()): string {
  const normalizedBase = normalizeApiBase(base);
  const normalizedPath = normalizePath(path);

  if (!normalizedBase) {
    return normalizedPath.startsWith("/") ? normalizedPath : `/${normalizedPath}`;
  }
  if (!normalizedPath) {
    return normalizedBase;
  }
  return `${normalizedBase}/${normalizedPath}`;
}

export function normalizeApiBase(base: string): string {
  const trimmed = base.trim();
  if (!trimmed || trimmed === "/") {
    return "";
  }

  const hasProtocol = /^https?:\/\//.test(trimmed);
  if (hasProtocol) {
    return trimmed.replace(/\/+$/g, "");
  }

  const hasLeadingSlash = trimmed.startsWith("/");
  const withoutSlashes = trimmed.replace(/^\/+|\/+$/g, "");
  return hasLeadingSlash ? `/${withoutSlashes}` : withoutSlashes;
}

function normalizePath(path: string): string {
  return path.trim().replace(/^\/+|\/+$/g, "");
}

function getBrowserPathApiBase(): string {
  if (typeof window === "undefined") {
    return "";
  }

  return normalizeApiBase(window.location.pathname);
}
