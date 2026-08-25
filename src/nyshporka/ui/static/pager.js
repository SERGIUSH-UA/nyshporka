/**
 * Посторінкова видача — одна на всі списки обох морд.
 *
 * 🔴 Пейджер несе ЗНАМЕННИК, а не лише стрілки. Список, обрізаний до сторінки й
 * підписаний самою лише парою кнопок, читається як повна відповідь — та сама
 * вада, що й нуль без знаменника, тільки з іншого боку. Тому в смузі завжди
 * стоїть «від–до / усього», і саме `усього` тут головне число.
 *
 * ⚠ Смуга ховається при одній сторінці, але число — ні: його показує сам екран
 * поруч із заголовком. Інакше на короткому списку зникав би і знаменник.
 */
import { ic } from './icons.js';

/**
 * Розмітка смуги гортання.
 *
 * Дія завжди одна — `page`; який саме список гортати, вирішує відкритий екран.
 *
 * @param d  відповідь операції: `page`, `pages`, `page_size`, `total`
 */
export function pager(d) {
  const pages = Number(d.pages || 0);
  if (pages < 2) return '';
  const page = Number(d.page || 0);
  const size = Number(d.page_size || 0);
  const total = Number(d.total || 0);
  const from = page * size + 1;
  const to = Math.min(total, (page + 1) * size);
  return `<div class="row pager">
    <button data-act="page" data-arg="-1"${page ? '' : ' disabled'}
      title="назад">${ic('arrow-left', 'ic-sm')}</button>
    <span class="muted mono">${from}–${to} / ${total}</span>
    <button data-act="page" data-arg="1"${page + 1 < pages ? '' : ' disabled'}
      title="далі">${ic('arrow-right', 'ic-sm')}</button>
  </div>`;
}

/**
 * Новий номер сторінки після кліку — із затиском у межі.
 *
 * 🔴 Затиск ТУТ, а не в кожному екрані: без нього кнопка «далі» на останній
 * сторінці везе за край, операція чесно віддає порожньо, і виглядає це як
 * «справи скінчились», хоч вони на місці.
 */
export function step(page, delta, pages) {
  const last = Math.max(0, Number(pages || 1) - 1);
  return Math.min(last, Math.max(0, Number(page || 0) + Number(delta)));
}
