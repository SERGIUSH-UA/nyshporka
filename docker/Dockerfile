# Нишпорка в контейнері: застосунок, рушії читання і ваги — в одному образі.
#
# Для того, хто не хоче ставити Нишпорку на основну систему. Варіант задає
# TORCH: `cpu` (будь-яка машина, зокрема Mac на Apple Silicon — у Docker на Mac
# відеокарти не видно взагалі), `cu126` чи `cu128` (NVIDIA, запуск із
# `--gpus all`). Яке колесо під яку карту — `src/nyshporka/htr/data/engines.yaml`.
#
# 🔴 Окремої бази nvidia/cuda не треба: колеса torch cu12x несуть бібліотеки
# CUDA самі, а драйвер і `nvidia-smi` підкладає NVIDIA Container Toolkit.
#
#   docker build -f docker/Dockerfile --build-arg TORCH=cu126 \
#       --build-arg NYSH_VERSION=0.21.1 -t nyshporka:cuda .

#
# 🔴 Порядок шарів — від того, що міняється рідко, до того, що з кожним релізом:
# система → Python → torch (2.5 ГБ у CUDA) → Нишпорка → рушії й ваги. Оновлення
# образу докачує лише шари, які змінились, але змінився шар — змінились і всі
# над ним. Доти `ARG NYSH_VERSION` стояв угорі, а torch ставився після
# Нишпорки, тож кожен реліз перекачував людям ~4 ГБ (помітив читач у чаті
# 12.10.2026). Щоб незмінний шар мав той самий ідентифікатор, CI збирає з
# `--cache-from` попереднього образу (`docker.yml`).

FROM python:3.11-slim-bookworm

ARG TORCH=cpu

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /usr/local/bin/

# git — PARSeq ставиться з репозиторію (`git+…`: з архіву коміту стає порожній
# strhub, див. engines.yaml); gcc — triton компілює ядра на льоту
# (той самий набір доставляє хмарний бокс, `cloud/run.py`).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git gcc libc6-dev libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Варіант образу — щоб doctor радив тег і `--gpus all`, а не `nysh htr install`
# у шарі, який зникне разом із контейнером (`setup/doctor.py`).
ENV NYSH_DOCKER_IMAGE=${TORCH}

# 🔴 Python — керований uv, а не системний з бази: у bookworm SQLite 3.40, а
# стор прочитаного (`nysh text index/find/crop/sheet`) будує FTS5 з
# `contentless_delete`, якої нема до 3.43. Образи, зібрані до цього рядка,
# падали на ній з `unrecognized option: "contentless_delete"` (заміряно 12.10.2026).
# `manual` — ставиться лише явним `uv python install`, нічого не тягнеться
# мовчки; тека — поза /srv/nysh, бо том людини її перекрив би.
ENV UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=manual \
    UV_PYTHON_INSTALL_DIR=/opt/nysh/python \
    UV_PYTHON_BIN_DIR=/opt/nysh/python/bin \
    VIRTUAL_ENV=/opt/nysh/app \
    PATH=/opt/nysh/app/bin:$PATH \
    NYSHPORKA_HTR_VENV=/opt/nysh/htr \
    XDG_CACHE_HOME=/opt/nysh/cache \
    PYTHONUNBUFFERED=1

# 🔴 Людина монтує ОДНУ теку, /srv/nysh, і в ній живе все, що має пережити
# контейнер: простір (work) і стан користувача (home) — позначка пройдених
# міграцій, ключ `nysh serve`, каталог справ. Доти стан лежав у шарі
# контейнера й зникав з кожним `--rm`: простір щоразу просив `nysh migrate`,
# а ключ доступу до застосунку мінявся на кожному запуску.
# Ваги (XDG_CACHE_HOME) — в образі: вони приходять з ним і з ним оновлюються.
ENV NYSHPORKA_WORKSPACE=/srv/nysh/work \
    XDG_STATE_HOME=/srv/nysh/home/state \
    XDG_CONFIG_HOME=/srv/nysh/home/config \
    XDG_DATA_HOME=/srv/nysh/home/data

RUN uv python install 3.11 \
 && uv venv /opt/nysh/app --python 3.11 --managed-python \
 && /opt/nysh/app/bin/python -c "import sqlite3; c = sqlite3.connect(':memory:'); c.execute(\"create virtual table f using fts5(t, content='', contentless_delete=1)\")"

# torch — окремим шаром ДО Нишпорки: це майже весь об'єм образу, а між релізами
# він здебільшого той самий. Версію CI бере з `runtime.torch.reference` в
# `engines.yaml` — тієї, яку резолвить kraken, — тож `nysh htr install` нижче
# бачить її задоволеною і не чіпає. Середовище створюється тим самим викликом,
# що й у `htr/env.py: setup`. Без TORCH_SPEC (збірка руками) крок порожній, і
# torch приїде з рушіями, як доти.
ARG TORCH_SPEC=""
RUN [ -z "$TORCH_SPEC" ] || ( uv venv "$NYSHPORKA_HTR_VENV" --python 3.11 \
 && UV_TORCH_BACKEND=${TORCH} uv pip install --python "$NYSHPORKA_HTR_VENV/bin/python" $TORCH_SPEC )

ARG NYSH_VERSION
RUN test -n "$NYSH_VERSION" || (echo "потрібен --build-arg NYSH_VERSION" && exit 1) \
 && for i in 1 2 3 4 5 6 7 8 9 10; do \
      uv pip install "nyshporka[app,archives]==${NYSH_VERSION}" && break; \
      [ "$i" = 10 ] && exit 1; \
      echo "колеса ${NYSH_VERSION} цей вузол PyPI ще не бачить — повтор за 30 с"; sleep 30; \
    done
# ⚠ Повтор не зайвий: на 0.21.3 перевірка в workflow уже бачила колесо в
# простому індексі, а `uv` у збірці за секунду дістав інший вузол CDN без нього.

# Рушії — в окремому середовищі, як і на звичайній машині (пін kraken 7.1.1
# не має права потрапити в застосунок). Колесо torch обирає `uv` за TORCH:
# карти під час збірки немає, тож детект через `nvidia-smi` тут нічого не дав
# би. Простір потрібен лише щоб команда знайшла себе; в образ він не йде.
RUN mkdir -p /tmp/ws && cd /tmp/ws \
 && NYSHPORKA_WORKSPACE=/tmp/ws nysh init /tmp/ws --yes --preset researcher \
 && UV_TORCH_BACKEND=${TORCH} NYSHPORKA_WORKSPACE=/tmp/ws nysh htr install --no-cuda \
 && NYSHPORKA_WORKSPACE=/tmp/ws nysh models get \
 && cd / && rm -rf /tmp/ws /srv/nysh \
 && if [ -n "$TORCH_SPEC" ]; then \
      want=$(echo "$TORCH_SPEC" | tr ' ' '\n' | sed -n 's/^torch==//p'); \
      have=$("$NYSHPORKA_HTR_VENV/bin/python" -c "import torch; print(torch.__version__.split('+')[0])"); \
      [ "$have" = "$want" ] || { echo "рушії замінили torch $want на $have: в образі два torch, reference в engines.yaml застарів"; exit 1; }; \
    fi
# ⚠ Перевірка вище — бо заміна torch у цьому шарі не ламає нічого видимого:
# образ лише мовчки товстішає на 2.5 ГБ, а оновлення знову качає все.

COPY docker/entrypoint.sh /usr/local/bin/nysh-entrypoint
RUN chmod +x /usr/local/bin/nysh-entrypoint

LABEL org.opencontainers.image.source="https://github.com/SERGIUSH-UA/nyshporka" \
      org.opencontainers.image.description="Нишпорка: пошук і читання архівних справ" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

VOLUME /srv/nysh
WORKDIR /srv/nysh
EXPOSE 8788
ENTRYPOINT ["nysh-entrypoint"]
CMD ["doctor"]
