#!/usr/bin/env sh
# Нишпорка — установлення на Linux / macOS без системного Python.
#
# 🔴 Системний інтерпретатор не використовується: на робочих машинах він або
# старий, або зайнятий чужим проєктом. Інсталятор приносить `uv`, а `uv` —
# власний Python. Усе кладеться в профіль користувача; sudo не потрібен.
set -eu

SOURCE="${NYSH_SOURCE:-nyshporka[app,archives]}"

say() { printf '%s\n' "$*"; }

if command -v uv >/dev/null 2>&1; then
  say "✓ uv уже є: $(command -v uv)"
else
  say "⬇ uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Інсталятор кладе в ~/.local/bin і не завжди чіпає поточний PATH.
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

say "⬇ Python 3.12…"
uv python install 3.12 >/dev/null

say "⬇ Нишпорка ($SOURCE)…"
uv tool install --python 3.12 --force "$SOURCE"

say ""
nysh init --yes
nysh doctor || true

say ""
say "Готово. Далі:"
say "  nysh serve            відкрити застосунок у браузері"
say "  nysh look <тека>      подивитись, що за скани"
say "  nysh models get       завантажити моделі письма"
say "  nysh doctor           перевірити те, що ламається тихо"
