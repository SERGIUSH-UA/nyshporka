// Аватар: фото (якщо є) або силует+ініціали як SVG-fallback.
// Викликається з node-renderer.js для кожного вузла.
//
// Повертає рядок SVG-фрагмента, який можна вставити всередину <g> вузла.

const AVATAR_R = 18;  // радіус аватара (px у SVG-координатах)

export function renderAvatar(node, defs) {
  const bgColor = sexColor(node.sex);
  // Силует+ініціали як основа.
  const initials = (node.initials || '?').slice(0, 2);
  let inner = `
    <circle cx="0" cy="0" r="${AVATAR_R}" fill="${bgColor}" class="avatar-bg"></circle>
    <text class="avatar-initials" x="0" y="5" text-anchor="middle">${initials}</text>
  `;
  // Якщо є фото — додаємо <image> поверх (clip — окремий circle).
  if (node.has_photo && node.photo_url) {
    const clipId = `avatar-clip-${node.id}`;
    defs.add(
      `<clipPath id="${clipId}"><circle cx="0" cy="0" r="${AVATAR_R}"/></clipPath>`,
    );
    inner += `
      <image href="${escapeAttr(node.photo_url)}"
             x="${-AVATAR_R}" y="${-AVATAR_R}"
             width="${AVATAR_R * 2}" height="${AVATAR_R * 2}"
             clip-path="url(#${clipId})"
             preserveAspectRatio="xMidYMid slice"
             onerror="this.style.display='none'"></image>
    `;
  }
  // Border (статева ознака або частковий privacy-маркер).
  inner += `<circle cx="0" cy="0" r="${AVATAR_R}" fill="none" stroke="${strokeColor(node)}" stroke-width="2" class="avatar-border"></circle>`;
  return inner;
}

function sexColor(sex) {
  if (sex === 'F') return '#f4d6c4';
  if (sex === 'M') return '#c4d4f4';
  return '#dadada';
}

function strokeColor(node) {
  if (node.has_disputed) return '#e44';
  if (node.private) return '#888';
  if (node.sex === 'F') return '#c97';
  if (node.sex === 'M') return '#36c';
  return '#777';
}

function escapeAttr(s) {
  return String(s).replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export const AVATAR_RADIUS = AVATAR_R;
