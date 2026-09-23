/**
 * Аркуш прогону для повноекранної читалки — один спосіб на всі екрани.
 *
 * Сторінку цілком відкривають із двох місць: гортач прочитаного і розбір
 * знахідок. Дві копії того самого завантажувача розійшлися б на першій же
 * правці — і в одному з екранів рамки чи текст мовчки перестали б з'являтись.
 */

import { t } from './strings.js';
import { callOp } from './net.js';

/**
 * Підписи читалки. Спільний модуль словника не має й мати не мусить: він
 * нічого не знає ні про справи, ні про мови — підписи дає той, хто кличе.
 */
export function readerLabels() {
  return {
    prev: t('view.prev'), next: t('view.next'), close: t('lb.close'),
    fit: t('view.zoom.fit'), keys: t('lb.keys'), loading: t('common.loading'),
    text: t('lb.text'), notext: t('lb.notext'), alt: t('sift.alt'),
    boxes: t('lb.boxes'), boxesWhy: t('lb.boxes.why'),
  };
}

/**
 * Знімок, текст і рамки одного аркуша — у форматі `load()` читалки.
 *
 * ⚠ Три запити шлються разом, а не по черзі: послідовно вони склали б
 * трисекундну паузу на кожне гортання, тоді як найдовший із них однаково
 * впирається в рендер знімка.
 *
 * 🔴 Прогін без рамок — не помилка, але мовчати про нього не можна: читалка
 * покаже аркуш без підсвіченого рядка, і без підпису людина вирішить, що
 * рядок хіта просто не знайшовся.
 */
export async function loadPageFull(run, page) {
  const [shot, text, geo] = await Promise.all([
    callOp('page.view', { run, page, region: 'page' }),
    callOp('page.text', { run, page }),
    callOp('page.lines', { run, page }),
  ]);
  if (!shot.ok) return { error: shot.error || '' };
  const g = (geo.ok && geo.data) || {};
  const lines = (text.ok && (text.data || {}).lines) || [];
  return {
    image: (shot.data || {}).image,
    label: g.has ? page : `${page} · ${t('lb.nobox')}`,
    // Порожні рамки — законна відповідь: старі прогони їх не писали, і
    // читалка тоді просто показує знімок без накладки.
    size: g.has ? g.size : null,
    shapes: g.has ? (g.polys || g.boxes || []) : [],
    lines,
  };
}
