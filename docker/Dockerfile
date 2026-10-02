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

FROM python:3.11-slim-bookworm

ARG NYSH_VERSION
ARG TORCH=cpu

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /usr/local/bin/

# git — PARSeq ставиться з репозиторію; gcc — triton компілює ядра на льоту
# (той самий набір доставляє хмарний бокс, `cloud/run.py`).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git gcc libc6-dev libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Варіант образу — щоб doctor радив тег і `--gpus all`, а не `nysh htr install`
# у шарі, який зникне разом із контейнером (`setup/doctor.py`).
ENV NYSH_DOCKER_IMAGE=${TORCH}

ENV UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
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

RUN test -n "$NYSH_VERSION" || (echo "потрібен --build-arg NYSH_VERSION" && exit 1) \
 && uv venv /opt/nysh/app --python 3.11 \
 && for i in 1 2 3 4 5 6 7 8 9 10; do \
      uv pip install "nyshporka[app,archives]==${NYSH_VERSION}" && break; \
      [ "$i" = 10 ] && exit 1; \
      echo "колеса ${NYSH_VERSION} цей вузол PyPI ще не бачить — повтор за 30 с"; sleep 30; \
    done
# ⚠ Повтор не зайвий: на 0.21.3 перевірка в workflow уже бачила колесо в
# простому індексі, а `uv` у збірці за секунду дістав інший вузол CDN без нього.

# Рушії — в окремому середовищі, як і на звичайній машині (пін kraken 7.0.2
# не має права потрапити в застосунок). Колесо torch обирає `uv` за TORCH:
# карти під час збірки немає, тож детект через `nvidia-smi` тут нічого не дав
# би. Простір потрібен лише щоб команда знайшла себе; в образ він не йде.
RUN mkdir -p /tmp/ws && cd /tmp/ws \
 && NYSHPORKA_WORKSPACE=/tmp/ws nysh init /tmp/ws --yes --preset researcher \
 && UV_TORCH_BACKEND=${TORCH} NYSHPORKA_WORKSPACE=/tmp/ws nysh htr install --no-cuda \
 && NYSHPORKA_WORKSPACE=/tmp/ws nysh models get \
 && rm -rf /tmp/ws /srv/nysh

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
