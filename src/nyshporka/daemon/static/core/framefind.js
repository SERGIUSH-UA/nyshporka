/**
 * Який аркуш мала на увазі людина, набравши щось у полі «перейти до».
 *
 * Помічник називає знахідку ім'ям кадру («03090», «00412.jpg») або номером за
 * порядком, і людина переписує це з розмови. Тому спершу шукаємо кадр за
 * назвою, і лише коли такого немає — беремо число як номер за порядком.
 *
 * Повертає індекс у `frames` або -1.
 */
export function frameIndex(frames, query) {
  const q = String(query || '').trim().toLowerCase();
  if (!q || !frames.length) return -1;
  const stem = (s) => String(s || '').toLowerCase().replace(/\.[a-z0-9]{2,5}$/, '');
  const labels = frames.map((f) => String((f && f.label) || '').toLowerCase());
  const qs = stem(q);

  let i = labels.findIndex((l) => l === q || stem(l) === qs);
  if (i >= 0) return i;

  if (/^\d+$/.test(qs)) {
    // «3090» проти «03090.jpg» і «film_03090.jpg»: останнє число назви, без нулів.
    const want = Number(qs);
    i = labels.findIndex((l) => {
      const m = stem(l).match(/(\d+)\D*$/);
      return m !== null && Number(m[1]) === want;
    });
    if (i >= 0) return i;
    return want >= 1 && want <= frames.length ? want - 1 : -1;
  }
  return labels.findIndex((l) => l.includes(q));
}
