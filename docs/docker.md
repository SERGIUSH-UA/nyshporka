# Нишпорка в Docker

Готовий образ для тих, хто не хоче ставити Нишпорку на основну систему. У ньому
є застосунок, рушії читання (kraken і PARSeq) і ваги трьох моделей. Нічого
доставляти не треба.

!!! tip "Windows з карткою NVIDIA — простіше без Docker"
    Інсталятор [`nyshporka-setup.exe`](https://github.com/SERGIUSH-UA/nyshporka/releases/latest/download/nyshporka-setup.exe)
    сам питає драйвер, яка карта стоїть, і ставить рушії під неї — без WSL,
    без Docker Desktop і без образу на 12 ГБ.

## Який образ брати

| машина | образ | швидкість аркуша |
|---|---|---|
| NVIDIA RTX 20xx–40xx, GTX 9xx/10xx/16xx, V100, T4, A-серія | `ghcr.io/sergiush-ua/nyshporka:cuda` | ~10–20 с |
| NVIDIA RTX 50xx, H100 | `ghcr.io/sergiush-ua/nyshporka:cuda128` | ~10–20 с |
| без NVIDIA, зокрема Mac на M-чипі | `ghcr.io/sergiush-ua/nyshporka:latest` | ~20 с – 1 хв, залежно від ядер і щільності сторінки |

!!! warning "Mac на Apple Silicon читає лише процесором"
    Docker на Mac не має доступу до відеочипа Apple, тож образ працює на
    процесорі. Нативна установка на Mac теж читає процесором: рушії поки не
    вміють Metal. Отже Docker тут нічого не відбирає, але й не прискорює.

Для образів `cuda` потрібен драйвер NVIDIA на машині. На Linux — ще
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
На Windows — Docker Desktop із WSL 2, **версії 4.31 або новіший**: драйвер
NVIDIA від 555 у старішому Docker Desktop не стартує (`Error 500: named symbol not
found`).

!!! note "Перше завантаження `:cuda` довге"
    Образ важить близько 12 ГБ (сам torch із CUDA — близько 4 ГБ одним
    шаром). Після `Download complete` Docker ще розпаковує, і рядок
    `Extracting` може кілька хвилин стояти без руху. Дочекайтесь
    `Status: Downloaded newer image` — далі запуск займає секунди.

Що не так з картою, каже `doctor`: рядок «Прискорення (GPU)» називає, чого
бракує — тегу `:cuda`, прапорця `--gpus all` чи новішого Docker Desktop.

## Запуск

Змонтуйте свою теку в `/srv/nysh`, інакше прочитане зникне разом із
контейнером. Без монтування образ про це попередить, а теку, змонтовану в
`/srv/nyshporka` (так було в першій версії цієї сторінки), відмовиться
запускати. При першому запуску в ній з'являться дві підтеки:

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

!!! warning "Windows: поточна тека пишеться інакше"
    `$PWD` — це Linux, macOS і PowerShell. У `cmd.exe` змінна не підставляється,
    і Docker отримує буквально `$PWD/nysh`. Там пишіть `%cd%`:

    ```bat
    docker run --rm -v "%cd%\nysh:/srv/nysh" ghcr.io/sergiush-ua/nyshporka doctor
    ```

    У PowerShell — `${PWD}`: `-v "${PWD}\nysh:/srv/nysh"`. Або просто повний
    шлях: `-v "C:\nysh:/srv/nysh"`.

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

Термінал надрукує посилання з кодом сполучення:
`http://127.0.0.1:8788/#pair=…`. Відкрийте його в браузері. Якщо в `-p` перед
`:8788` стоїть інший порт (`-p 127.0.0.1:9000:8788`), підставте його в
посилання. Адреса `172.17.0.x` — внутрішня адреса контейнера, з Windows і macOS
вона не відкривається.

Код сполучення діє 10 хв і один раз, а видно його лише з `-it`. Без нього
відкрийте http://127.0.0.1:8788/ і введіть ключ доступу: він лежить у вашій
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
