/**
 * Validate untrusted redirect URLs before assigning them to window.location.
 * Only same-origin relative paths are accepted.
 */
export function isSafeRedirectUrl(value, origin = window.location.origin) {
  if (typeof value !== 'string') {
    return false;
  }
  const url = value.trim();
  if (!url) {
    return false;
  }
  if (/^\/\//.test(url) || /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url)) {
    return false;
  }
  if (!url.startsWith('/')) {
    return false;
  }
  try {
    const parsed = new URL(url, origin);
    return parsed.origin === origin;
  } catch {
    return false;
  }
}
