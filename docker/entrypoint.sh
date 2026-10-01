#!/bin/sh
# Вхід контейнера: простір у /srv/nyshporka створюється при першому запуску, далі —
# звичайна команда `nysh …`.
#
# 🔴 Простір не можна покласти в образ: /srv/nyshporka — том, і змонтована тека людини
# його перекриє. Тож він з'являється там, де людина його бачить, і лише якщо
# його там ще немає — наявне дослідження не чіпається.
set -e

ws="${NYSHPORKA_WORKSPACE:-/srv/nyshporka}"
if [ ! -f "$ws/nyshporka.toml" ]; then
    nysh init "$ws" --yes --preset researcher
fi

exec nysh "$@"
