#!/usr/bin/env bash
# Застосунок у браузері — рівно командою з docs/docker.md і так, як до нього
# ходить браузер хоста: через проброшений порт, з `Host: 127.0.0.1`.
#
# 🔴 0.24.2 вийшла з застосунком, який у Docker не відкривався взагалі: банер
# давав посилання на 172.17.0.2 (з Windows і macOS — таймаут), а 127.0.0.1
# ворота допуску відбивали 403. Юніт-тести мережі Docker не мають, тож стик
# посилання з воротами ловить лише справжній контейнер.
#
#   bash docker/smoke_serve.sh <образ> <том>
#   SMOKE_RUN_ARGS="-e …" — додаткові аргументи `docker run` (для локальної проби)
set -euo pipefail

image=${1:?образ}
volume=${2:?том}
port=8788
name=nysh-smoke-serve
log=$(mktemp)
jar=$(mktemp)
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -f "$log" "$jar"' EXIT

# `-t` — щоб код сполучення друкувався, як у людини з `-it`.
# shellcheck disable=SC2086
docker run -d -t --name "$name" -p "127.0.0.1:$port:8788" -v "$volume:/srv/nysh" \
    ${SMOKE_RUN_ARGS:-} "$image" \
    serve --host 0.0.0.0 --confirm-host 0.0.0.0 --confirm-public --no-browser >/dev/null

code=000
for _ in $(seq 1 90); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/" || true)
    [ "$code" != 000 ] && break
    sleep 1
done
docker logs "$name" >"$log" 2>&1 || true
cat "$log"

fail() { echo "🔴 $*"; exit 1; }

[ "$code" = 200 ] || fail "сторінка допуску на 127.0.0.1:$port відповіла $code"
if grep -Eq "https?://172\.[0-9.]+:$port" "$log"; then
    fail "банер дає посилання на адресу контейнера — з хоста вона не відкривається"
fi
link=$(grep -Eo "http://127\.0\.0\.1:$port/#pair=[A-Za-z0-9_-]+" "$log" | tail -1 || true)
[ -n "$link" ] || fail "у банері немає посилання http://127.0.0.1:$port/#pair=…"
pair=${link##*#pair=}

origin="http://127.0.0.1:$port"
code=$(curl -s -c "$jar" -o /dev/null -w '%{http_code}' -H "Origin: $origin" \
    -H 'Content-Type: application/json' -d "{\"code\":\"$pair\"}" "$origin/api/access")
[ "$code" = 200 ] || fail "допуск кодом із посилання відповів $code"
code=$(curl -s -b "$jar" -o /dev/null -w '%{http_code}' "$origin/api/health")
[ "$code" = 200 ] || fail "з допуском /api/health відповів $code"
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: evil.example' "$origin/api/health")
[ "$code" = 403 ] || fail "чужий Host пройшов ворота ($code)"
echo "✅ застосунок відкривається з хоста: посилання → допуск → консоль"
