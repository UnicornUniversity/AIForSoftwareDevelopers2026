/** Shared escaping helpers. Every string that reaches HTML goes through here. */

const HTML_ESCAPES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

export function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (character) => HTML_ESCAPES[character]);
}

/**
 * A URL is only emitted as an href when it parses as http(s); anything else
 * becomes a dead link rather than a `javascript:` payload.
 */
export function safeHref(value) {
  try {
    const url = new URL(String(value));
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '#';
  } catch {
    return '#';
  }
}

/** Host label without the leading `www.`, or the raw value if unparseable. */
export function hostOf(value) {
  try {
    return new URL(String(value)).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

export function formatDate(value, { long = false } = {}) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';

  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: long ? 'long' : 'short',
    day: 'numeric',
  });
}

export function formatDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';

  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
