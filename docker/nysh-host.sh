#!/usr/bin/env bash
# nysh на основній системі → nysh у Docker-контейнері Нишпорки.
#
# Для помічника (Claude Code, Codex), що працює ПОЗА контейнером: скіли кличуть
# `nysh …`, а Нишпорка живе в Docker. Обгортка передає команду в запущений
# контейнер і перекладає шляхи в обидва боки: тека на диску ↔ /srv/nysh.
# Без перекладу помічник отримує шлях кропу `/srv/nysh/…` і не може його відкрити.
#
# Покласти під іменем `nysh` у теку з PATH (Git Bash на Windows — `~/bin`,
# macOS і Linux — `~/.local/bin`) і підставити у двох рядках нижче ім'я
# контейнера й теку, змонтовану в /srv/nysh. Змінні середовища NYSH_CONTAINER і
# NYSH_HOST_DIR, якщо задані, мають перевагу.
#
# Довідка: https://nyshporka.online/docs/docker/#pomichnyk-poruch-iz-kontejnerom

box="${NYSH_CONTAINER:-nysh}"
host="${NYSH_HOST_DIR:-$HOME/nysh}"

host="${host//\\//}"
host="${host%/}"
mnt=/srv/nysh

# ⚠ Git Bash (Windows) переписує аргумент `/srv/…` у `C:/Program Files/Git/srv/…`
# ще до docker.exe — і контейнер отримує шлях, якого немає.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

# Одна тека має на Windows три записи: C:\nysh, C:/nysh (так шлях друкуємо
# назад — його відкривають інструменти помічника) і /c/nysh (запис Git Bash).
forms=("$host")
show="$host"
if command -v cygpath >/dev/null 2>&1; then
    show="$(cygpath -m "$host")"
    forms=("$show" "$(cygpath -u "$host")")
fi

to_box() {
    local a="$1" b f
    b="${a//\\//}"
    for f in "${forms[@]}"; do
        if [[ "${b,,}" == "${f,,}" || "${b,,}" == "${f,,}/"* ]]; then
            printf '%s' "$mnt${b:${#f}}"
            return
        fi
    done
    printf '%s' "$a"
}

args=()
for a in "$@"; do
    if [[ "$a" == --*=* ]]; then
        args+=("${a%%=*}=$(to_box "${a#*=}")")
    else
        args+=("$(to_box "$a")")
    fi
done

state="$(docker inspect -f '{{.State.Running}}' "$box" 2>/dev/null)"
if [[ "$state" != "true" ]]; then
    if [[ -z "$state" ]]; then
        echo "nysh: контейнера «$box» немає. Як запустити — https://nyshporka.online/docs/docker/#pomichnyk-poruch-iz-kontejnerom" >&2
    else
        echo "nysh: контейнер «$box» зупинено. Запустіть: docker start $box" >&2
    fi
    exit 125
fi

back() { sed "s#$mnt#${show//&/\\&}#g"; }

set -o pipefail
docker exec "$box" nysh "${args[@]}" 2> >(back >&2) | back
rc=$?
wait
exit $rc
