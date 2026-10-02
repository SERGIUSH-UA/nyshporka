#!/bin/sh
# Вхід контейнера: простір у /srv/nysh/work створюється при першому запуску, далі —
# звичайна команда `nysh …`.
#
# 🔴 Простір не можна покласти в образ: /srv/nysh — том, і змонтована тека
# людини його перекриє. Тож він з'являється там, де людина його бачить, і лише якщо
# його там ще немає — наявне дослідження не чіпається.
set -e

# 🔴 Тека людини, змонтована не в /srv/nysh, не помилка для Docker: на /srv/nysh
# мовчки сідає анонімний том (`VOLUME` у Dockerfile), простір створюється в
# ньому, doctor увесь зелений — і з `--rm` прочитане зникає разом із томом.
# Так було в чаті 02.10.2026: монтування в /srv/nyshporka (шлях першої версії
# документації) і жодного попередження.
#
# ⚠ Повідомлення — через printf '%s\n': echo у dash розгортає `\n` усередині
# рядка, і `%cd%\nysh` з підказки для cmd.exe ламався навпіл.
say() { printf '%s\n' "$@" >&2; }

mount_root() {
    # Корінь джерела для точки монтування (поле 4 /proc/self/mountinfo).
    awk -v mp="$1" '$5 == mp { print $4; exit }' /proc/self/mountinfo 2>/dev/null
}

if [ -n "$(mount_root /srv/nyshporka)" ]; then
    say "⛔ Теку змонтовано в /srv/nyshporka, а Нишпорка тримає простір у /srv/nysh." \
        "   Усе прочитане лягло б у тимчасовий том і зникло б разом із контейнером." \
        "   Замініть у команді: -v \"<ваша тека>:/srv/nysh\"" \
        "   (cmd.exe: -v \"%cd%\\nysh:/srv/nysh\" · PowerShell: -v \"\${PWD}\\nysh:/srv/nysh\")"
    exit 2
fi

# Анонімний том — це id із 64 hex-знаків у `…/volumes/<id>/_data`; іменований
# том (`-v nysh:/srv/nysh`) переживає контейнер і попередження не потребує.
if mount_root /srv/nysh | grep -Eq '/volumes/[0-9a-f]{64}/_data$'; then
    say "⚠ /srv/nysh не змонтовано: простір живе в тимчасовому томі контейнера," \
        "  і з --rm прочитане зникне разом із ним. Щоб зберегти роботу, додайте" \
        "  -v \"<ваша тека>:/srv/nysh\" (cmd.exe: -v \"%cd%\\nysh:/srv/nysh\")." \
        ""
fi

ws="${NYSHPORKA_WORKSPACE:-/srv/nysh/work}"
if [ ! -f "$ws/nyshporka.toml" ]; then
    nysh init "$ws" --yes --preset researcher
fi

exec nysh "$@"
