// Форматування lived_from/to з certainty для UI.

export function formatLifespan(node) {
  if (node.lived_from == null && node.lived_to == null) return '';
  const cert = node.lived_certainty;
  if (cert === 'exact') {
    const f = node.birth || node.lived_from || '?';
    const t = node.death || node.lived_to || '';
    return `${f}–${t}`.replace(/–$/, '');
  }
  const f = node.lived_from ?? '?';
  const t = node.lived_to ?? '?';
  if (cert === 'inferred') return `бл. ${f}–${t}`;
  if (cert === 'approximate') return `~${f}–${t}`;
  return `${f}–${t}`;
}

export function isAliveAt(node, year) {
  if (!node) return false;
  const from = node.lived_from;
  const to = node.lived_to;
  if (from == null && to == null) return false;
  if (from != null && year < from) return false;
  if (to != null && year > to) return false;
  return true;
}

export function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
