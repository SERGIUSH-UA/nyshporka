/**
 * 🔎 Поле «прогін» із підказками — пошуком на сервері, порцією.
 *
 * Прогонів десятки тисяч, і весь перелік одним запитом коштував 1–2 с на
 * кожне відкриття екрана з таким полем (Гортач, Набори; замір 23.10.2026).
 * Пункт підказки — шифра й модель, у дію йде ім'я прогону (`cbValue`).
 */

import { t } from './strings.js';
import { callOp } from './net.js';
import { modelName, fmtDay } from './bits.js';
import { attachCombobox } from '/ui/combobox.js';

/** Одна порція прогонів за підрядком (ім'я, шифра, назва); `null` — відмова. */
export async function loadRuns(q = '') {
  const env = await callOp('runs.list', { q, page_size: 30 });
  return env.ok ? ((env.data || {}).runs || []) : null;
}

/** Дрібний підпис прогону: назва справи, сторінок, дата. */
export function runHint(r) {
  return [r.title || '', r.pages_done ? t('pull.pages').replace('{n}', r.pages_done) : '',
    r.updated ? fmtDay(String(r.updated).slice(0, 10)) : ''].filter(Boolean).join(' · ');
}

/** Пункт підказки: шифра й модель, ім'я прогону — у дію. */
export function runItem(r) {
  return { value: r.name, label: r.shifra ? `${r.shifra} · ${modelName(r.model)}` : r.name, hint: runHint(r) };
}

/**
 * Начепити підказки на поле. `first` — уже отримана перша порція (щоб не
 * питати двічі). Повертає комбобокс (для `destroy()`).
 */
export function attachRunPicker(input, first = []) {
  const cb = attachCombobox(input, { items: first.map(runItem), empty: t('view.run.none') });
  let timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const got = await loadRuns(input.value || '');
      if (got && cb && cb.setItems) cb.setItems(got.map(runItem));
    }, 250);
  });
  return cb;
}
