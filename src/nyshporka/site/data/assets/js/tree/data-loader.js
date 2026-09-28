// Завантаження tree.json: на localhost — спершу tree.full.json (повна
// версія з фото і точними роками приватних), потім fallback на public.

export async function loadTree(publicUrl) {
  const isLocal =
    location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  const bust = isLocal ? `?t=${Date.now()}` : '';
  const fetchOpts = isLocal ? { cache: 'no-store' } : {};

  if (isLocal) {
    const fullUrl = publicUrl.replace(/tree\.json$/, 'tree.full.json');
    try {
      const r = await fetch(fullUrl + bust, fetchOpts);
      if (r.ok) {
        const data = await r.json();
        document.body.dataset.nyshTreeMode = 'full';
        return data;
      }
    } catch (_) { /* fall through */ }
  }
  const r = await fetch(publicUrl + bust, fetchOpts);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  document.body.dataset.nyshTreeMode = 'public';
  return await r.json();
}
