/**
 * 🧾 Форма зі схеми операції — для «Усіх дій»: дія без свого екрана.
 *
 * Схема — та сама pydantic-схема, яку віддає `/api/ops` (JSON Schema). Поля
 * будуються з неї, а не пишуться руками: так кожна з двох сотень дій має
 * форму, і ця форма не розходиться з тим, що операція справді приймає.
 *
 * Що вміє: текст, число з межами, так/ні, вибір (`enum`, `Literal`), перелік
 * рядків (через кому), необов'язкове поле (`anyOf` з `null`).
 *
 * 🔴 Порожнє необов'язкове поле не шлеться: інакше `""` перебило б значення
 * за замовчуванням операції, і дія робила б не те, що без форми.
 */
import { esc } from './view.js';

/** Тип поля без обгортки `anyOf: [{…}, {type: null}]`. */
function bare(prop) {
  if (Array.isArray(prop.anyOf)) {
    const real = prop.anyOf.filter((x) => x.type !== 'null');
    if (real.length === 1) return { ...prop, ...real[0], nullable: true };
  }
  return prop;
}

function kindOf(p) {
  if (Array.isArray(p.enum)) return 'enum';
  if (p.const !== undefined) return 'enum';
  if (p.type === 'boolean') return 'bool';
  if (p.type === 'integer' || p.type === 'number') return 'num';
  if (p.type === 'array') return 'list';
  return 'text';
}

/** Поля схеми в порядку оголошення: `{name, kind, p, required}`. */
export function schemaFields(schema) {
  const props = (schema && schema.properties) || {};
  const req = new Set((schema && schema.required) || []);
  return Object.entries(props).map(([name, raw]) => {
    const p = bare(raw);
    return { name, kind: kindOf(p), p, required: req.has(name) };
  });
}

/** Розмітка полів; підпис — опис поля, підказка — ім'я аргументу. */
export function schemaFormHtml(schema) {
  return schemaFields(schema).map(({ name, kind, p, required }) => {
    const label = esc(p.description || p.title || name);
    const id = `sf-${esc(name)}`;
    const def = p.default;
    let control;
    if (kind === 'bool' && p.nullable) {
      // `bool | None`: «не чіпати» — окремий стан, галочка його не вміщає.
      control = `<select id="${id}" name="${esc(name)}"><option value="">—</option>
        <option value="true"${def === true ? ' selected' : ''}>✓</option>
        <option value="false"${def === false ? ' selected' : ''}>✗</option></select>`;
    } else if (kind === 'bool') {
      // Галочка — поруч із підписом, а не окремим рядком під ним.
      return `<label class="chk" for="${id}" title="${esc(name)}"><input type="checkbox" id="${id}"
        name="${esc(name)}"${def ? ' checked' : ''}> ${label}</label>`;
    } else if (kind === 'enum') {
      const opts = Array.isArray(p.enum) ? p.enum : [p.const];
      control = `<select id="${id}" name="${esc(name)}">${required ? '' : '<option value=""></option>'}${
        opts.map((o) => `<option value="${esc(o)}"${o === def ? ' selected' : ''}>${esc(o === '' ? '—' : o)}</option>`).join('')}</select>`;
    } else if (kind === 'num') {
      const lim = [p.minimum !== undefined ? ` min="${p.minimum}"` : '', p.maximum !== undefined ? ` max="${p.maximum}"` : '',
        p.type === 'number' ? ' step="any"' : ''].join('');
      control = `<input type="number" id="${id}" name="${esc(name)}"${lim}${
        def !== undefined && def !== null ? ` value="${esc(def)}"` : ''}${required ? ' required' : ''}>`;
    } else {
      const v = kind === 'list' ? (Array.isArray(def) ? def.join(', ') : '') : (def === undefined || def === null ? '' : def);
      control = `<input id="${id}" name="${esc(name)}" value="${esc(v)}"${required ? ' required' : ''}>`;
    }
    // Ім'я аргументу — у підказці при наведенні: людині досить підпису, а
    // для того, хто перекладає дію в термінал, воно лишається під рукою.
    return `<label class="fld" for="${id}" title="${esc(name)}"><span class="fld-l">${label}${
      required ? ' *' : ''}</span>${control}</label>`;
  }).join('');
}

/**
 * Значення форми з правильними типами. `get(name)` — рядок поля або `null`,
 * `checked(name)` — стан галочки (так тест обходиться без DOM).
 */
export function schemaValues(schema, get, checked) {
  const out = {};
  for (const { name, kind, p, required } of schemaFields(schema)) {
    if (kind === 'bool' && p.nullable) {
      const raw = String(get(name) ?? '');
      if (raw === 'true' || raw === 'false') out[name] = raw === 'true';
      continue;
    }
    if (kind === 'bool') {
      const v = !!checked(name);
      if (v !== !!p.default || required) out[name] = v;
      continue;
    }
    const raw = String(get(name) ?? '').trim();
    if (!raw) {
      if (required) out[name] = kind === 'list' ? [] : '';
      continue;
    }
    if (kind === 'num') out[name] = Number(raw);
    else if (kind === 'list') {
      const items = raw.split(',').map((s) => s.trim()).filter(Boolean);
      const num = p.items && (p.items.type === 'integer' || p.items.type === 'number');
      out[name] = num ? items.map(Number) : items;
    }
    else out[name] = raw;
  }
  return out;
}
