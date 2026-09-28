// SVG-рендер вузла особи: аватар + ім'я + роки. Викликається tree-pane
// для кожного laid-out персонажа.

import { renderAvatar, AVATAR_RADIUS } from '../utils/avatar.js';
import { formatLifespan, escapeHtml } from '../utils/fmt-date.js';

const NODE_W = 130;
const NODE_H = 64;

export function renderPersonNode(g, node, defs, opts = {}) {
  const d = node.data;
  const palette = opts.palette;
  const fillColor = palette ? palette(d.branch_id) : '#9aa';

  const group = g.append('g')
    .attr('class', nodeClass(d))
    .attr('data-id', d.id)
    .attr('transform', `translate(${node.x},${node.y})`);

  // Карткове тло з кольором гілки.
  group.append('rect')
    .attr('class', 'person-card')
    .attr('x', -NODE_W / 2)
    .attr('y', -NODE_H / 2)
    .attr('width', NODE_W)
    .attr('height', NODE_H)
    .attr('rx', 8)
    .attr('ry', 8)
    .attr('fill', '#fff')
    .attr('stroke', fillColor)
    .attr('stroke-width', d.has_disputed ? 3 : 1.5);

  // Кольорова смуга-індикатор гілки зліва.
  group.append('rect')
    .attr('class', 'branch-stripe')
    .attr('x', -NODE_W / 2)
    .attr('y', -NODE_H / 2)
    .attr('width', 5)
    .attr('height', NODE_H)
    .attr('fill', fillColor);

  // Аватар.
  const avatarG = group.append('g')
    .attr('class', 'avatar')
    .attr('transform', `translate(${-NODE_W / 2 + AVATAR_RADIUS + 8}, 0)`);
  avatarG.html(renderAvatar(d, defs));

  // Текст: ім'я + роки.
  const textX = -NODE_W / 2 + AVATAR_RADIUS * 2 + 16;
  const textWidth = NODE_W - (AVATAR_RADIUS * 2 + 24);
  const nameText = group.append('text')
    .attr('class', 'name')
    .attr('x', textX)
    .attr('y', -6);
  nameText.append('tspan').text(truncate(d.name, 18));

  group.append('text')
    .attr('class', 'years')
    .attr('x', textX)
    .attr('y', 12)
    .text(formatLifespan(d) || (d.private ? 'приватна' : ''));

  group.append('text')
    .attr('class', 'pid')
    .attr('x', textX)
    .attr('y', 24)
    .text(d.id);

  // Бейджі: гіпотеза/суперечливо/приватна.
  const badges = [];
  if (d.has_disputed) badges.push({ cls: 'disputed', text: '⚠' });
  if (d.private) badges.push({ cls: 'private', text: '🔒' });
  if (d.fact_count >= 8) badges.push({ cls: 'rich', text: '★' });
  badges.forEach((b, i) => {
    group.append('text')
      .attr('class', `badge badge-${b.cls}`)
      .attr('x', NODE_W / 2 - 8 - i * 14)
      .attr('y', -NODE_H / 2 + 14)
      .text(b.text);
  });

  return group;
}

function nodeClass(d) {
  const cls = ['nysh-tree-node'];
  if (d.private) cls.push('private');
  if (d.has_disputed) cls.push('disputed');
  if (d.is_root) cls.push('root');
  if (d.sex) cls.push(`sex-${d.sex.toLowerCase()}`);
  return cls.join(' ');
}

function truncate(s, n) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

export { NODE_W, NODE_H };
