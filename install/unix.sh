#!/usr/bin/env sh
# Нишпорка — установлення на Linux / macOS без системного Python.
#
# 🔴 Системний інтерпретатор не використовується: на робочих машинах він або
# старий, або зайнятий чужим проєктом. Інсталятор приносить `uv`, а `uv` —
# власний Python. Усе кладеться в профіль користувача; sudo не потрібен.
set -eu

# Які частини застосунку ставимо (`nysh sections`): catalog | amateur |
# researcher | lab. 🔴 Від цього залежить вага встановлення: читання рукопису
# тягне torch (~2.5 ГБ), і той, хто прийшов подивитись каталог справ, платити
# за нього гігабайтами не повинен.
PRESET="${NYSH_PRESET:-researcher}"
case "$PRESET" in
  catalog) DEFAULT_SOURCE="nyshporka[app,archives]" ;;
  amateur|researcher|lab) DEFAULT_SOURCE="nyshporka[app,archives,htr]" ;;
  *) printf 'невідомий набір «%s»: catalog | amateur | researcher | lab\n' "$PRESET" >&2
     exit 2 ;;
esac
# ⚠ Перелік дублює `core.sections.EXTRAS` — інакше інсталятор мусив би спершу
# поставити пакет, щоб спитати в нього, що ставити. Розбіжність ловить
# `test_installer_extras_match_the_sections`.
SOURCE="${NYSH_SOURCE:-$DEFAULT_SOURCE}"

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
nysh init --yes --preset "$PRESET"
nysh doctor || true

# 🗂 Довідники їдуть В КОМПЛЕКТІ — без них перше питання («де метрики мого
# села») лишається без відповіді, а людина не знає, що саме треба доставити.
# У колесі їх немає навмисно: каталог і код оновлюються за різними годинниками.
SEED="$(ls "$(dirname "$0")"/nyshporka-catalog-*.zip 2>/dev/null | head -1 || true)"
if [ -n "$SEED" ]; then
  TMP="$(mktemp -d)"
  if unzip -q "$SEED" -d "$TMP" 2>/dev/null; then
    nysh catalog install --from "$TMP" || true
  else
    say "⚠ не вдалось розпакувати $SEED — потрібен unzip"
  fi
  rm -rf "$TMP"
else
  say "⚠ довідників поруч немає — пошук по каталогах архівів буде недоступний"
  say "  поставити пізніше: nysh catalog install --from <тека|zip>"
fi

say ""
say "Готово. Далі:"
say "  nysh serve            відкрити застосунок у браузері"
say "  nysh look <тека>      подивитись, що за скани"
say "  nysh models get       завантажити моделі письма"
say "  nysh doctor           перевірити те, що ламається тихо"
