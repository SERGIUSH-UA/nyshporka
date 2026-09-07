#!/usr/bin/env sh
# Нишпорка — зняти з Linux / macOS.
#
#   sh install/uninstall.sh              подивитись, що буде знято
#   sh install/uninstall.sh --yes        зняти
#   sh install/uninstall.sh --yes --all  зняти разом із рушіями, моделями,
#                                        довідниками й скілами агента
#
# 🔴 Уся логіка живе в `nysh uninstall` (`src/nyshporka/setup/uninstall.py`), а
# цей файл лише знаходить команду. Друга копія логіки на sh розійшлася б із
# першою на найближчому виправленні, і розійшлася б мовчки — те саме рішення,
# що вже записане в `install/nyshporka.iss` про `windows.ps1`.
#
# 🔴🔴 Робочий простір не знімається ніде й ніколи: там скани, прочитане й
# роками зібране дослідження. Жоден прапорець цього не міняє.
set -eu

NYSH_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/nyshporka"
INFO_FILE="$NYSH_HOME/install-info.ini"

say() { printf '%s\n' "$*"; }

# Команда: спершу в PATH, далі — там, куди її записав інсталятор. Другий шлях
# не запасний: інсталятор міг НЕ чіпати профіль (`NYSH_NO_MODIFY_PATH=1`), і
# тоді `nysh` у PATH немає й ніколи не було.
NYSH="$(command -v nysh 2>/dev/null || true)"
if [ -z "$NYSH" ] && [ -f "$INFO_FILE" ]; then
  NYSH="$(sed -n 's/^nysh=//p' "$INFO_FILE" | head -1)"
fi

if [ -n "$NYSH" ] && [ -x "$NYSH" ]; then
  exec "$NYSH" uninstall "$@"
fi

# ── команди немає ───────────────────────────────────────────────────────────
# 🔴 Це не тупик, а найчастіший спосіб сюди потрапити: пакет уже знесли руками,
# а слід лишився. Тому кажемо рівно те, що лишилось, і чим це прибрати, —
# мовчазний вихід тут читався б як «нічого не знайдено, все чисто».
say "✗ команди «nysh» немає — застосунок уже знято або поставлено інакше."
say ""
UV="$(command -v uv 2>/dev/null || true)"
if [ -z "$UV" ] && [ -f "$INFO_FILE" ]; then
  UV="$(sed -n 's/^uv=//p' "$INFO_FILE" | head -1)"
fi
[ -n "$UV" ] || UV="uv"
say "Лишилось прибрати руками:"
say "  $UV tool uninstall nyshporka        пакет, якщо він ще стоїть"
if [ -d "$NYSH_HOME" ]; then
  say "  rm -rf $NYSH_HOME"
  say "         тека застосунку разом із власним uv і слідом інсталятора"
fi
if [ -f "$NYSH_HOME/install-trace.txt" ]; then
  say ""
  say "Що інсталятор змінив на цій машині:"
  sed 's/^/  /' "$NYSH_HOME/install-trace.txt"
fi
say ""
say "🔴 Тека дослідження зі сканами й прочитаним не згадана тут навмисно:"
say "   її не знімає ні ця команда, ні «nysh uninstall»."
exit 1
