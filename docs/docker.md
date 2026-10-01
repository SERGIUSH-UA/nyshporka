# Нишпорка в Docker

Готовий образ для тих, хто не хоче ставити Нишпорку на основну систему. У ньому
є застосунок, рушії читання (kraken і PARSeq) і ваги трьох моделей. Нічого
доставляти не треба.

## Який образ брати

| машина | образ | швидкість аркуша |
|---|---|---|
| NVIDIA RTX 20xx–40xx, GTX 16xx, V100, T4, A-серія | `ghcr.io/sergiush-ua/nyshporka:cuda` | ~10–20 с |
| NVIDIA RTX 50xx, H100 | `ghcr.io/sergiush-ua/nyshporka:cuda128` | ~10–20 с |
| без NVIDIA, зокрема Mac на M-чипі | `ghcr.io/sergiush-ua/nyshporka:latest` | ~20 с – 1 хв, залежно від ядер і щільності сторінки |

!!! warning "Mac на Apple Silicon читає лише процесором"
    Docker на Mac не має доступу до відеочипа Apple, тож образ працює на
    процесорі. Нативна установка на Mac теж читає процесором: рушії поки не
    вміють Metal. Отже Docker тут нічого не відбирає, але й не прискорює.

Для образів `cuda` потрібен драйвер NVIDIA на машині. На Linux — ще
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
На Windows досить Docker Desktop із WSL 2.

## Запуск

Змонтуйте свою теку в `/srv/nysh`, інакше прочитане зникне разом із
контейнером. При першому запуску в ній з'являться дві підтеки:

- `work` — робочий простір: скани, прочитаний текст, реєстри;
- `home` — налаштування Нишпорки: ключ доступу до застосунку, каталог справ,
  позначки оновлень.

```sh
# перевірити, що все на місці
docker run --rm -v "$PWD/nysh:/srv/nysh" ghcr.io/sergiush-ua/nyshporka doctor

# прочитати справу: скани кладете в nysh/work/scans/<справа>
docker run --rm -v "$PWD/nysh:/srv/nysh" ghcr.io/sergiush-ua/nyshporka \
    read /srv/nysh/work/scans/<справа>

# те саме на карті NVIDIA
docker run --rm --gpus all -v "$PWD/nysh:/srv/nysh" \
    ghcr.io/sergiush-ua/nyshporka:cuda read /srv/nysh/work/scans/<справа>
```

Без сканів можна спробувати на вкладеній зразковій справі (три аркуші):

```sh
docker run --rm -v "$PWD/nysh:/srv/nysh" ghcr.io/sergiush-ua/nyshporka sample
docker run --rm -v "$PWD/nysh:/srv/nysh" ghcr.io/sergiush-ua/nyshporka \
    read /srv/nysh/work/data/raw/sample-315-159 --rerun --out /srv/nysh/work/sample-out
```

Текст лягає поруч у `*.txt`. Наприкінці читання є рядок
`⏱ темп: … с/стор · … рядк/стор · голосів … · шардів … · <пристрій>` —
це темп вашої машини, і саме його можна порівнювати з чужими замірами.

## Застосунок у браузері

```sh
docker run --rm -it -p 127.0.0.1:8788:8788 -v "$PWD/nysh:/srv/nysh" \
    ghcr.io/sergiush-ua/nyshporka \
    serve --host 0.0.0.0 --confirm-host 0.0.0.0 --confirm-public --no-browser
```

Далі відкрийте http://127.0.0.1:8788/ і введіть код сполучення з термінала.
Код видно лише з `-it`. Без нього введіть ключ доступу: він лежить у вашій
теці, `nysh/home/config/nyshporka/serve/*.key`, і між запусками не міняється.

`--host 0.0.0.0` тут потрібен лише для того, щоб Docker міг передати порт у
контейнер. Назовні машини застосунок не видно, бо порт прив'язано до
`127.0.0.1`. Не прибирайте `127.0.0.1:` з `-p`, якщо не розумієте наслідків:
через застосунок можна писати файли й запускати платну оренду.

## Чого в контейнері немає

- **Сховища паролів системи.** Вхід у Супрягу й ключі, які застосунок зберігає
  в keyring, у контейнері не запам'ятовуються. Ключі сховища й оренди
  передаються змінними середовища (`-e NYSHPORKA_S3_KEY=…`, `-e
  NYSHPORKA_RENT_KEY=…`).
- **Плагіна оренди.** Хмарне читання (`nysh cloud go`) ставиться окремо, і в
  образ його не вкладено.
- **Скілів помічника.** Агент на основній системі контейнер не бачить; скіли
  для нього ставляться звичайною установкою.
