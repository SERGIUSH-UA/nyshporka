"""Вендоринг раннера трену з gpurunner у `train/guest/parseq_train_runner.py`.

Раннер трену Писаря живе в сусідньому проєкті (`gpurunner`) як «вбудований»
модуль, який там рендериться після блоку параметрів. Для локального й SSH
трену пакет везе його КОПІЮ з кількома правками — і всі правки живуть ТУТ,
одним списком точних замін, а не руками у файлі. Тому дрейф від оригіналу
ловиться перезапуском: `--check` порівнює свіжо зібрану копію з тією, що в
репозиторії.

    uv run python tools/sync_train_runner.py <шлях до gpurunner>          # оновити
    uv run python tools/sync_train_runner.py <шлях до gpurunner> --check  # звірити

Правки (кожна з причиною в самому раннері):
1. `_utc_iso` вклеєно (у gpurunner він приходить із `_common.py`).
2. `_bind_roots` шанує `params["input_root"]`; тека розпакування — під
   `output_root`, а не `/tmp` (Windows).
3. `_ensure_deps(params)` не ставить пакети, коли `no_pip` — локально їх
   ставить `nysh htr install`.
4. Прогрес епох — рядком `@@PROGRESS@@ {json}` (канал `core.progress`), коли
   `progress_json`.
5. `_world_size` повертає 1 на Windows: DDP через fork там немає.
6. `__main__`: `--params <json>` → `main(params)`.
7. Порада в коментарі про скрипт дослідницького репо замінена на команду
   пакета: `test_no_advice_points_at_a_missing_file` не пропускає шлях, якого
   в пакеті немає.
8. База з хабу пінується рядком `pretrained` (`<repo>@<ревізія>#<sha256>`)
   і звіряється sha256 ДО `torch.load`; без піна — гучне попередження.
9. Запасне розпакування `tarfile` — з фільтром `data`; resume вантажиться
   `weights_only=True` (аудит 29.09.2026).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEST = HERE / "src" / "nyshporka" / "train" / "guest" / "parseq_train_runner.py"
SRC_REL = Path("src/gpurunner/_embedded/parseq_train_runner.py")

REPLACEMENTS: list[tuple[str, str]] = [
    # 1. _utc_iso
    (
        "import tarfile\nimport time\nfrom pathlib import Path\n",
        "import tarfile\nimport time\nfrom datetime import datetime, timezone\n"
        "from pathlib import Path\n\n\n"
        "def _utc_iso():\n"
        "    # nyshporka: у gpurunner приходить із _common.py, тут — на місці.\n"
        "    return datetime.now(tz=timezone.utc).isoformat(timespec=\"seconds\")\n",
    ),
    # 2. корені: input_root і тека розпакування під виходом
    (
        "    global KAGGLE_INPUT, KAGGLE_WORKING\n"
        "    out = params.get(\"output_root\")\n"
        "    if out:\n"
        "        KAGGLE_WORKING = Path(out)\n",
        "    global KAGGLE_INPUT, KAGGLE_WORKING, EXTRACT\n"
        "    out = params.get(\"output_root\")\n"
        "    if out:\n"
        "        KAGGLE_WORKING = Path(out)\n"
        "        # nyshporka: тека розпакування — під виходом, а не /tmp: на Windows\n"
        "        # це C:\\tmp, якого нема, а поруч із виходом вона й прибирається.\n"
        "        EXTRACT = KAGGLE_WORKING / \"_input\"\n"
        "    inp = params.get(\"input_root\")\n"
        "    if inp:\n"
        "        KAGGLE_INPUT = Path(inp)\n",
    ),
    # 3. no_pip
    (
        "def _ensure_deps():\n"
        "    try:\n"
        "        import strhub  # noqa: F401\n",
        "def _ensure_deps(params=None):\n"
        "    # nyshporka: локально пакети ставить `nysh htr install`, і pip з-під\n"
        "    # трену лише зіпсував би зібране середовище.\n"
        "    if params and params.get(\"no_pip\"):\n"
        "        return\n"
        "    try:\n"
        "        import strhub  # noqa: F401\n",
    ),
    (
        "    _bind_roots(params)\n    _ensure_deps()\n",
        "    _bind_roots(params)\n    _ensure_deps(params)\n",
    ),
    # 4. прогрес
    (
        "def _bind_roots(params):\n",
        "def _progress(params, epoch, epochs, rec):\n"
        "    # nyshporka: машинний канал прогресу (`core.progress`): рядок із\n"
        "    # префіксом і JSON, щоб застосунок бачив епоху, не розбираючи лог.\n"
        "    if not params.get(\"progress_json\"):\n"
        "        return\n"
        "    payload = {\"v\": 1, \"phase\": \"train\", \"i\": int(epoch), \"n\": int(epochs),\n"
        "               \"item\": f\"ep{int(epoch):02d}\"}\n"
        "    for k in (\"val_cer\", \"val_exact\", \"train_loss\", \"sec\"):\n"
        "        if k in rec:\n"
        "            payload[k] = rec[k]\n"
        "    print(\"@@PROGRESS@@ \" + json.dumps(payload, ensure_ascii=True), flush=True)\n\n\n"
        "def _bind_roots(params):\n",
    ),
    (
        "        history.append(rec)\n",
        "        history.append(rec)\n"
        "        if lead:\n"
        "            _progress(params, epoch, params[\"epochs\"], rec)\n",
    ),
    # 7. порада на скрипт дослідницького репо → команда пакета
    (
        "scripts/pysar_epoch_select.py",
        "локальний відбір по holdout (`nysh train eval`)",
    ),
    # 5. Windows: без DDP
    (
        "    mode = str(params.get(\"ddp\", \"auto\")).lower()\n"
        "    n = _visible_gpus()\n",
        "    mode = str(params.get(\"ddp\", \"auto\")).lower()\n"
        "    if os.name == \"nt\":\n"
        "        return 1  # nyshporka: DDP через fork на Windows немає\n"
        "    n = _visible_gpus()\n",
    ),
    # 8. база з хабу: ревізія й sha256 з рядка `pretrained`, звірка до torch.load
    (
        "def _load_pretrained(params, roots):\n",
        '''def _hub_spec(spec):
    # nyshporka: база з хабу пінується в самому рядку `pretrained` —
    # `<repo>[@<ревізія>][#<sha256>]`. Окремих ключів немає навмисно: перелік
    # параметрів дзеркалить валідацію джоби gpurunner, і новий ключ там дав би
    # відмову. В id репозиторію HF ні `@`, ні `#` не буває.
    rest, _, sha = spec.partition("#")
    repo, _, rev = rest.partition("@")
    sha = sha.strip().lower()
    if sha and (len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha)):
        raise RuntimeError(f"pretrained: після «#» — sha256 (64 шістнадцяткові "
                           f"знаки), а не {sha!r}")
    return repo.strip(), (rev.strip() or None), sha


def _sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _hub_base(spec):
    # nyshporka (аудит 29.09.2026): ваги з хабу — pickle третьої особи, і
    # SECURITY.md обіцяє приймати їх лише зі збігом sha256. Без ревізії
    # `hf_hub_download` бере поточну голову репозиторію: той самий рецепт
    # завтра тягнув би інший файл. Звірка — ДО `torch.load`, не після.
    from huggingface_hub import hf_hub_download
    repo, rev, want = _hub_spec(spec)
    ckpt = Path(hf_hub_download(repo, "best.pt", revision=rev))
    got = _sha256_file(ckpt)
    if want and got != want:
        raise RuntimeError(
            f"pretrained: sha256 best.pt з {repo}@{rev or 'main'} = {got}, а "
            f"рецепт пінує {want} — ваги не ті, трен не стартує")
    if not want:
        # Не відмова: так працював кожен рецепт до піна, і тихо зламати
        # чужий трен гірше. Але й не вдавати, що ваги звірені.
        _log("⚠⚠⚠ pretrained: sha256 НЕ запіновано — ваги з хабу не звірені. "
             f"Запінувати: pretrained=\\"{repo}@{rev or ckpt.parent.name}#{got}\\"")
    _log(f"pretrained <- hub {repo}@{rev or 'main'} sha256={got}")
    return ckpt


def _load_pretrained(params, roots):
''',
    ),
    (
        "        from huggingface_hub import hf_hub_download\n"
        "        ckpt = Path(hf_hub_download(spec, \"best.pt\"))\n"
        "        _log(f\"pretrained <- hub {spec}\")\n",
        "        ckpt = _hub_base(spec)\n",
    ),
    # 9. resume без довільного pickle
    (
        "    payload = torch.load(path, map_location=\"cpu\", weights_only=False)\n",
        '''    # nyshporka (аудит 29.09.2026): `weights_only=True`. Чекпойнт шукається
    # під УСІМ входом, а не лише в датасеті resume, і `weights_only=False`
    # виконав би будь-який pickle, що ліг туди під цим іменем. Повний стан, який
    # пише цей самий раннер (стани оптимізатора, планувальника, скейлера,
    # числа, рядки, списки), вантажиться й так — перевірено на torch 2.13.
    import pickle
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except pickle.UnpicklingError as exc:
        raise RuntimeError(
            f"{path}: не чистий чекпойнт (є об'єкти поза тензорами й словниками) — "
            f"продовження з нього відхилено: {exc}") from exc
''',
    ),
    # 9. запасне розпакування — з фільтром
    (
        "                with tarfile.open(t) as tf:\n"
        "                    tf.extractall(EXTRACT)\n",
        '''                # nyshporka (аудит 29.09.2026): фільтр "data" не пускає
                # абсолютні шляхи, `..`, посилання назовні й спецфайли. Python
                # без нього (3.11 до 3.11.4) — відмова, а не розпакування без
                # гарду.
                if not hasattr(tarfile, "data_filter"):
                    raise RuntimeError(
                        f"{t.name}: tar не вийшов, а tarfile цього Python не має "
                        f"фільтра data — розпакувати безпечно нічим") from exc
                with tarfile.open(t) as tf:
                    tf.extractall(EXTRACT, filter="data")
''',
    ),
]

HEADER = '''"""Раннер трену Писаря — ВЕНДОРЕНА копія з gpurunner ({commit}).

🔴 Не редагувати руками: правки живуть у `tools/sync_train_runner.py` як
точні заміни, і `--check` там ловить дрейф від оригіналу. Гість середовища
рушіїв: жодного імпорту пакета (`tests/test_train_guest_isolated.py`).

Запуск: `<python рушіїв> parseq_train_runner.py --params <params.json>`;
`params.json` — словник `TrainParams.as_params()` плюс `input_root`,
`output_root`, `no_pip`, `progress_json`.
"""
'''

MAIN_BLOCK = '''

if __name__ == "__main__":
    # nyshporka: локальний запуск файлом — параметри з JSON, а не з інжекції.
    import argparse as _ap

    _p = _ap.ArgumentParser()
    _p.add_argument("--params", required=True)
    _a = _p.parse_args()
    _params = json.loads(Path(_a.params).read_text(encoding="utf-8"))
    main(_params)
'''


def render(gpurunner: Path) -> str:
    src_path = gpurunner / SRC_REL
    src = src_path.read_text(encoding="utf-8")
    try:
        commit = subprocess.run(["git", "-C", str(gpurunner), "log", "-1", "--format=%h",
                                 "--", str(SRC_REL)], capture_output=True, text=True,
                                encoding="utf-8").stdout.strip() or "?"
    except OSError:
        commit = "?"
    for old, new in REPLACEMENTS:
        if old not in src:
            raise SystemExit(f"заміну не знайдено в оригіналі — раннер змінився:\n{old}")
        src = src.replace(old, new, 1)
    # оригінальний докстрінг лишається, наш заголовок стає перед ним
    return HEADER.format(commit=commit) + src.rstrip("\n") + "\n" + MAIN_BLOCK


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("gpurunner", type=Path, help="корінь репозиторію gpurunner")
    ap.add_argument("--check", action="store_true", help="лише звірити, нічого не писати")
    a = ap.parse_args()
    if not (a.gpurunner / SRC_REL).is_file():
        print(f"немає {a.gpurunner / SRC_REL}", file=sys.stderr)
        return 2
    text = render(a.gpurunner)
    if a.check:
        cur = DEST.read_text(encoding="utf-8") if DEST.is_file() else ""
        if cur == text:
            print("✅ вендорений раннер збігається з оригіналом + правками")
            return 0
        print("🔴 вендорений раннер РОЗІЙШОВСЯ з оригіналом — перезапустити без --check",
              file=sys.stderr)
        return 1
    DEST.write_text(text, encoding="utf-8", newline="\n")
    print(f"записано {DEST} ({len(text.splitlines())} рядків)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
