#!/usr/bin/env python
"""Скласти реліз ваг: порахувати sha256/size і переписати маніфест паків.

Бік ВИДАВЦЯ. Користувач ваги лише ставить (`nysh models get`).

🔴 Навіщо окремий крок, якщо файли й так можна викласти руками. Бо маніфест без
sha256 робить `nysh models get` мертвим за побудовою: пак, про цілість якого
нічого не відомо, не приймається взагалі. Це не перестраховка — обірвана
закачка лишає файл, який ВИГЛЯДАЄ як модель, і падає він аж усередині torch
повідомленням про формат тензора, тобто причину доводиться здогадувати.

Тому послідовність саме така: спершу порахувати з РЕАЛЬНИХ файлів, потім
викласти ті самі файли. Порахувати «з майбутніх» неможливо, і це добре.

    python tools/make_release.py <тека з вагами> [--release weights-v1] [--dry-run]

Далі — викласти файли ассетами релізу з тим самим тегом:

    gh release create weights-v1 <тека>/*.pt <тека>/*.mlmodel
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "src" / "nyshporka" / "setup" / "data" / "packs.json"
#: Читаємо великими шматками: ваги — сотні мегабайтів, і посимвольний хеш
#: перетворив би складання релізу на каву.
CHUNK = 1 << 20


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("weights_dir", type=Path, help="тека з файлами ваг")
    ap.add_argument("--release", default="", help="тег релізу (типово — з маніфесту)")
    ap.add_argument("--dry-run", action="store_true", help="лише показати, не писати")
    args = ap.parse_args()

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    packs = data.get("packs") or []
    if not packs:
        print("🔴 у маніфесті немає паків", file=sys.stderr)
        return 2

    missing: list[str] = []
    changed = 0
    for p in packs:
        f = args.weights_dir / p["filename"]
        if not f.is_file():
            missing.append(p["filename"])
            continue
        digest, size = sha256(f), f.stat().st_size
        was = p.get("sha256") or ""
        p["sha256"], p["size"] = digest, size
        if args.release:
            p["release"] = args.release
        mark = "=" if was == digest else ("+" if not was else "≠")
        print(f"  {mark} {p['id']:<20} {size / 1e6:8.1f} МБ  {digest[:16]}…")
        changed += was != digest

    if missing:
        # 🔴 Часткового релізу не буває. Маніфест, у якому половина паків має
        # хеш, а половина ні, виглядає справним — і `models get` мовчки
        # відмовиться саме на тому, якого людині бракує.
        print(f"\n🔴 немає файлів: {', '.join(missing)}", file=sys.stderr)
        print("   реліз складається ЦІЛКОМ або не складається", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"\n[dry-run] маніфест не змінено ({changed} записів відрізняються)")
        return 0

    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    tag = args.release or packs[0].get("release") or "weights-v1"
    print(f"\n✅ маніфест переписано: {MANIFEST.relative_to(ROOT)}")
    print(f"   далі: gh release create {tag} "
          + " ".join(f'"{args.weights_dir / p["filename"]}"' for p in packs))
    print("   🔴 викладати саме ті файли, з яких пораховано хеші")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
