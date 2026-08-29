#!/usr/bin/env sh
# Нишпорка — установлення на Linux / macOS без системного Python.
#
# Запуск із клону:  sh install/unix.sh
# Запуск без клону (саме це дають агентові):
#   curl -LsSf https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/unix.sh | sh
# Набір при цьому передається змінною:
#   curl -LsSf https://raw.githubusercontent.com/SERGIUSH-UA/nyshporka/main/install/unix.sh | NYSH_PRESET=catalog sh
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

# Звідки брати пак довідників, якщо його немає поруч. Та сама адреса, що її
# друкує `nysh catalog list` на порожньому каталозі (`catalog.store.RELEASES_URL`).
CATALOG_URL="https://github.com/SERGIUSH-UA/nyshporka/releases"

say() { printf '%s\n' "$*"; }

# 🐾 Знак ТОЙ САМИЙ, що друкує `nysh info` і старт застосунку — побайтово,
# і це звіряє тест. Інсталятор — найперша поверхня, яку бачить людина, і
# власна лапка тут означала б, що бренд розходиться з першого ж екрана.
say "  ● ● ● ●"
say "  ╭─ ◍ ─╮   Нишпорка"
say "  ╰─────╯   Читає рукопис. Приносить знайдене."
say ""

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

# 🔴 PATH лагодиться ДВІЧІ, і це дві РІЗНІ речі.
# `uv tool install` кладе `nysh` у власну теку, і в PATH її може не бути:
# гілка вище додає її лише тоді, коли uv ставили МИ. Прийшов uv із apt, brew
# чи pipx — і наступний рядок падає «nysh: command not found» рівно тоді, коли
# все вже завантажено й установлено. А `uv tool update-shell` дописує теку в
# профіль оболонки, тобто для НАСТУПНИХ сеансів; поточний про це не дізнається.
BIN="$(uv tool dir --bin 2>/dev/null || true)"
[ -n "$BIN" ] || BIN="$HOME/.local/bin"
case ":$PATH:" in
  *":$BIN:"*) PATH_WAS_MISSING=0 ;;
  *) PATH="$BIN:$PATH"; export PATH; PATH_WAS_MISSING=1
     uv tool update-shell >/dev/null 2>&1 || true ;;
esac

# 🔴 Перевірити ПЕРЕД першим викликом: інакше людина читає «command not found»
# і не має підстав думати, що встановлення взагалі відбулось.
if ! command -v nysh >/dev/null 2>&1; then
  say "✗ пакет установлено, але команди немає (шукали в $BIN)"
  say "  надішліть, будь ласка, вивід «uv tool list» — це вада інсталятора"
  exit 1
fi

# ── слід для оновлення ───────────────────────────────────────────────────────
# 🔴 Той самий файл, що його на Windows пише майстер (`install/windows.ps1`,
# крок 3¾). З нього `nysh update` дізнається, ДЕ лежить uv і ЯКИМ набором
# ставили: набір вгадати не можна, а вгаданий або тягне 2.5 ГБ рушіїв тому,
# хто їх не ставив, або мовчки знімає їх у того, хто ними читає.
# ⚠ Помилка запису не валить установлення: без цього файла ламається оновлення
# однією командою, а не сам застосунок.
NYSH_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/nyshporka"
if mkdir -p "$NYSH_HOME" 2>/dev/null; then
  {
    echo "[nyshporka]"
    echo "nysh=$(command -v nysh)"
    echo "uv=$(command -v uv)"
    echo "preset=$PRESET"
  } > "$NYSH_HOME/install-info.ini" 2>/dev/null || true
fi

say ""
nysh init --yes --preset "$PRESET"
nysh doctor || true

# 🗂 Довідники їдуть В КОМПЛЕКТІ — без них перше питання («де метрики мого
# села») лишається без відповіді, а людина не знає, що саме треба доставити.
# У колесі їх немає навмисно: каталог і код оновлюються за різними годинниками.
# ⚠ Запущений через конвеєр (`curl | sh`) скрипт не має свого файла: `$0`
# дорівнює імені оболонки, і `dirname` дав би поточну теку — тобто пак
# довідників «поруч з інсталятором» шукався б там, де людина просто стоїть.
if [ -f "$0" ]; then
  SEED="$(ls "$(dirname "$0")"/nyshporka-catalog-*.zip 2>/dev/null | head -1 || true)"
else
  SEED=""
fi
if [ -n "$SEED" ]; then
  TMP="$(mktemp -d)"
  if unzip -q "$SEED" -d "$TMP" 2>/dev/null; then
    nysh catalog install --from "$TMP" || true
  else
    say "⚠ не вдалось розпакувати $SEED — потрібен unzip"
  fi
  rm -rf "$TMP"
else
  # 🔴 Порада мусить казати, ЗВІДКИ взяти — див. коментар у windows.ps1.
  say "⚠ довідників поруч немає — пошук по каталогах архівів буде недоступний"
  say "  взяти: $CATALOG_URL"
  say "  далі:  nysh catalog install --from <завантажений zip>"
fi

say ""
say "Готово."

# 🔴 Підказка ПЕРЕД переліком команд і однією фразою, без слова «PATH» —
# див. коментар у windows.ps1: пояснення механіки тут не читається, читається дія.
if [ "$PATH_WAS_MISSING" = 1 ]; then
  say ""
  say "  ⚠ Закрийте цей термінал і відкрийте новий — команди нижче працюють там."
  say "    У терміналах, відкритих до встановлення, «nysh» не знайдеться."
  say "    Якщо й у новому не знайдеться — перезапустіть комп'ютер."
fi

say ""
say "Далі:"
say "  nysh serve            відкрити застосунок у браузері"
say "  nysh look <тека>      подивитись, що за скани"
say "  nysh models get       завантажити моделі письма"
say "  nysh doctor           перевірити те, що ламається тихо"
