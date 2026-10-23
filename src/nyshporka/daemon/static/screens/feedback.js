/**
 * 📮 Відгук про Нишпорку: вада, ідея чи питання — зі знімками й журналами.
 *
 * Два кроки, і другий — обов'язковий: людина пише й прикладає, потім бачить
 * РІВНО те, що піде на портал (текст після очищення шляхів, діагностику,
 * вкладення з розмірами), і лише тоді надсилає. Операція `feedback.send` без
 * `confirm` нічого не відправляє — той самий перегляд отримує й агент.
 *
 * 🔴 Файли не йдуть на портал «як є». Картинку браузер одразу зменшує до
 * 1600 px (canvas → WebP), демон перекодовує ще раз, портал — утретє; журнал
 * читається лише як текст (і лише хвіст великого файла). Список дозволеного —
 * той самий, що в `share/feedback.py`: PNG/JPEG/WebP і .txt/.log/.json, до п'яти.
 */

import { t, LANG } from '../core/strings.js';
import { callOp } from '../core/net.js';
import { esc, el, setView, boxError, maskot, fld } from '../core/view.js';
import { SCREENS, ACTIONS } from '../core/registry.js';
import { toast } from '../core/bits.js';
import { ic } from '/ui/icons.js';

const KINDS = ['vada', 'ideia', 'pytannia'];
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const TEXT_EXT = /\.(txt|log|json)$/i;
const MAX_FILES = 5;
const MAX_SIDE = 1600;
const MAX_IMAGE_READ = 25 * 1024 * 1024;
const MAX_LOG_READ = 2 * 1024 * 1024;

/** Чернетка живе, поки відкрите вікно: закрив — почав наново. */
let FB = fresh();

function fresh() {
  return { kind: 'vada', text: '', diag: true, images: [], logs: [] };
}

const count = () => FB.images.length + FB.logs.length;

SCREENS.feedback = async () => {
  FB = fresh();
  paintCompose();
};

function paintCompose(msg = '') {
  const kinds = KINDS.map((k) => `<label class="fb-kind"><input type="radio" name="kind" value="${k}"${
    FB.kind === k ? ' checked' : ''}><span>${esc(t(`fb.kind.${k}`))}</span></label>`).join('');
  const shot = navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia
    ? `<button type="button" class="ghost" data-act="fb.shot">${ic('image', 'ic-sm')} ${esc(t('fb.shot'))}</button>` : '';
  setView(`<form data-act="fb.preview" id="fb-form" class="fb-form">
      <p class="muted">${esc(t('fb.lead'))}</p>
      <div class="fb-kinds" role="radiogroup" aria-label="${esc(t('fb.kind'))}">${kinds}</div>
      ${fld(t('fb.text'), `<textarea name="text" id="fb-text" rows="6" maxlength="5000" required>${esc(FB.text)}</textarea>`)}
      <div class="fb-drop" id="fb-drop">
        <div class="row">
          <label class="ghost btn-like">${ic('upload', 'ic-sm')} ${esc(t('fb.attach'))}
            <input type="file" id="fb-file" data-act="fb.files" multiple hidden
              accept="${IMAGE_TYPES.join(',')},.txt,.log,.json"></label>
          ${shot}
        </div>
        <small class="muted">${esc(t('fb.drop'))}</small>
        <ul class="fb-files">${filesList()}</ul>
      </div>
      <div id="fb-box">${msg}</div>
      <div class="row dlg-acts"><button type="submit" class="primary">${esc(t('fb.next'))}</button>
        <button type="button" class="ghost" data-act="modal.close">${esc(t('modal.no'))}</button></div>
    </form>`);
  wireDrop();
}

function filesList() {
  const row = (x, i, kind) => `<li>${ic(kind === 'image' ? 'image' : 'page', 'ic-sm')}
      <span class="fb-name">${esc(x.name)}</span> <small class="muted">${esc(kb(x.size))}</small>
      <button type="button" class="ghost sm" data-act="fb.unattach" data-arg="${kind}:${i}"
        aria-label="${esc(t('fb.remove'))}">${ic('x', 'ic-sm')}</button></li>`;
  return FB.images.map((x, i) => row(x, i, 'image')).join('') + FB.logs.map((x, i) => row(x, i, 'log')).join('');
}

const kb = (n) => `${Math.max(1, Math.round(Number(n || 0) / 1024))} ${t('fb.kb')}`;

function keepText() {
  const ta = el('fb-text');
  if (ta && typeof ta.value === 'string') FB.text = ta.value;
  const k = document.querySelector('#fb-form input[name="kind"]:checked');
  if (k && KINDS.includes(k.value)) FB.kind = k.value;
}

/** Перетягування й вставка з буфера — лише поки вікно відкрите (вузли з ним і зникають). */
function wireDrop() {
  const zone = el('fb-form');
  if (!zone || !zone.addEventListener) return;
  zone.addEventListener('dragover', (ev) => { ev.preventDefault(); });
  zone.addEventListener('drop', (ev) => {
    ev.preventDefault();
    addFiles(Array.from((ev.dataTransfer || {}).files || []));
  });
  zone.addEventListener('paste', (ev) => {
    const files = Array.from((ev.clipboardData || {}).files || []).filter((f) => IMAGE_TYPES.includes(f.type));
    if (files.length) { ev.preventDefault(); addFiles(files); }
  });
}

/** Картинка → canvas ≤ 1600 px → WebP (data URL). Не картинка — відмова. */
async function shrink(blob) {
  const bmp = await createImageBitmap(blob);
  const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(bmp.width * k));
  c.height = Math.max(1, Math.round(bmp.height * k));
  c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
  if (bmp.close) bmp.close();
  return c.toDataURL('image/webp', 0.85);
}

const dataSize = (url) => Math.round((String(url).split(',')[1] || '').length * 0.75);

async function addFiles(files) {
  keepText();
  let refused = '';
  for (const f of files) {
    if (count() >= MAX_FILES) { refused = t('fb.toomany'); break; }
    try {
      if (IMAGE_TYPES.includes(f.type)) {
        if (f.size > MAX_IMAGE_READ) { refused = t('fb.toobig').replace('{n}', f.name); continue; }
        const data = await shrink(f);
        FB.images.push({ name: f.name.replace(/\.[^.]+$/, '') + '.webp', data, size: dataSize(data) });
      } else if (TEXT_EXT.test(f.name)) {
        const part = f.size > MAX_LOG_READ ? f.slice(f.size - MAX_LOG_READ) : f;
        const text = await part.text();
        FB.logs.push({ name: f.name, text, size: text.length });
      } else {
        refused = t('fb.type').replace('{n}', f.name);
      }
    } catch (_e) {
      refused = t('fb.bad').replace('{n}', f.name);
    }
  }
  paintCompose(refused ? `<div class="warn">${esc(refused)}</div>` : '');
}

/** Знімок екрана: браузер сам питає, що показати; відмова людини — не помилка. */
async function screenshot() {
  keepText();
  if (count() >= MAX_FILES) { paintCompose(`<div class="warn">${esc(t('fb.toomany'))}</div>`); return; }
  let stream = null;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const v = document.createElement('video');
    v.srcObject = stream;
    v.muted = true;
    await v.play();
    await new Promise((r) => setTimeout(r, 250));
    const c = document.createElement('canvas');
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext('2d').drawImage(v, 0, 0);
    const blob = await new Promise((r) => c.toBlob(r, 'image/png'));
    const data = await shrink(blob);
    FB.images.push({ name: `znimok-${FB.images.length + 1}.webp`, data, size: dataSize(data) });
  } catch (_e) {
    // Людина закрила вибір екрана — лишаємо як було.
  } finally {
    if (stream) stream.getTracks().forEach((tr) => tr.stop());
  }
  paintCompose();
}

function args(confirm) {
  return { text: FB.text, kind: FB.kind, diag: FB.diag, lang: LANG, confirm,
    images: FB.images.map((x) => ({ name: x.name, data: x.data })),
    logs: FB.logs.map((x) => ({ name: x.name, text: x.text })) };
}

function paintPreview(d) {
  const diag = Object.entries(d.diag || {}).map(([k, v]) => `<li><small class="muted">${esc(k)}</small> ${esc(v)}</li>`).join('');
  const files = (d.files || []).map((f) => `<li>${ic(f.kind === 'image' ? 'image' : 'page', 'ic-sm')} ${esc(f.name)}
      <small class="muted">${esc(kb(f.size))}${f.note ? ` · ${esc(f.note)}` : ''}</small></li>`).join('');
  const login = d.logged_in ? '' : `<div class="warn">${esc(t('fb.login'))} <code>nysh share login</code></div>`;
  setView(`<div class="fb-preview">
      <p class="muted">${esc(t('fb.preview.lead'))}</p>
      <div class="card"><small class="muted">${esc(t(`fb.kind.${d.kind}`))}</small>
        <p class="fb-body">${esc(d.text)}</p></div>
      ${files ? `<h4>${esc(t('fb.files'))}</h4><ul class="fb-files">${files}</ul>` : ''}
      <label class="fb-diag"><input type="checkbox" data-act="fb.diag"${FB.diag ? ' checked' : ''}>
        <span>${esc(t('fb.diag'))}</span></label>
      ${FB.diag && diag ? `<ul class="fb-diag-list">${diag}</ul>` : ''}
      ${login}
      <div id="fb-box"></div>
      <div class="row dlg-acts">
        <button type="button" class="primary" data-act="fb.send"${d.logged_in ? '' : ' disabled'}>${ic('envelope', 'ic-sm')} ${esc(t('fb.send'))}</button>
        <button type="button" class="ghost" data-act="fb.back">${esc(t('fb.back'))}</button></div>
    </div>`);
}

async function preview() {
  const env = await callOp('feedback.send', args(false));
  if (!env.ok) { boxError('fb-box', env); return; }
  paintPreview(env.data || {});
}

Object.assign(ACTIONS, {
  'fb.preview': async (ev) => {
    // 🔴 Без цього браузер відправляє форму сам (GET із текстом в адресі) і
    // вікно закривається перезавантаженням — дія форми мусить це скасувати.
    if (ev && ev.preventDefault) ev.preventDefault();
    keepText();
    await preview();
  },
  'fb.files': async (ev) => {
    const files = Array.from((ev.target || {}).files || []);
    await addFiles(files);
  },
  'fb.unattach': (_ev, elm) => {
    keepText();
    const [kind, i] = String(elm.dataset.arg || '').split(':');
    (kind === 'image' ? FB.images : FB.logs).splice(Number(i), 1);
    paintCompose();
  },
  'fb.shot': () => screenshot(),
  'fb.diag': async (ev) => {
    FB.diag = Boolean((ev.target || {}).checked);
    await preview();
  },
  'fb.back': () => paintCompose(),
  'fb.send': async () => {
    const env = await callOp('feedback.send', args(true));
    if (!env.ok) { boxError('fb-box', env); return; }
    const d = env.data || {};
    setView(`<div class="fb-done">${maskot('poshta', 160, 'fb-maskot')}
        <h3>${esc(t('fb.sent').replace('{n}', d.id))}</h3>
        <p class="muted">${esc(t('fb.sent.why'))}</p>
        ${/^https:\/\//.test(d.url || '') ? `<a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(t('fb.mine'))} ↗</a>` : ''}
        <div class="row dlg-acts"><button type="button" class="primary" data-act="modal.close">${esc(t('fb.close'))}</button></div>
      </div>`);
    toast(t('fb.sent').replace('{n}', d.id));
    FB = fresh();
  },
});

