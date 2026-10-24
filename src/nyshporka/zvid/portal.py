"""Звід через портал: черга пакетів на nyshporka.online замість флешки.

Власник: `publish` (пакет → черга), `fetch` (повернуті відповіді → `collect`).
Помічник: `take` без файла бере наступний пакет із черги, `give` сам заливає
відповідь, `drop` повертає пакет у чергу.

Ключ — той самий, що в Супрязі (`nysh share login`), і на ту саму довірену
адресу (`share.upload._tok_i_dim`). Пакети й відповіді ходять повз сервер —
підписаними посиланнями сховища; сервер лише видає їх і звіряє sha256.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from nyshporka.zvid import common as C

#: Класи пакетів за голосами всередині: спеціаліст, якого немає в публічних
#: релізах, робить пакет класом, на який власник видає право поштучно.
SPECIALISTS = (("regent", "regent"), ("pysar_x18", "pysar_x18"), ("logofet", "logofet"))


def kind_of(manifest: dict[str, Any]) -> str:
    voices = [str(v).lower() for v in manifest.get("voices") or []]
    for prefix, kind in SPECIALISTS:
        if any(v.startswith(prefix) for v in voices):
            return kind
    return "public"


def _api() -> tuple[str, str]:
    from nyshporka.share.upload import UploadError, _tok_i_dim

    try:
        return _tok_i_dim("")
    except UploadError as exc:
        raise C.ZvidError(str(exc)) from None


def _call(method: str, path: str, body: Any = None) -> dict[str, Any]:
    from nyshporka.share.upload import UploadError, _request

    tok, home = _api()
    try:
        return _request(method, f"{home}/zvid{path}", body=body, auth=tok)
    except UploadError as exc:
        raise C.ZvidError(str(exc)) from None


def _put(url: str, blob: bytes) -> None:
    from nyshporka.share.upload import UploadError
    from nyshporka.share.upload import _put as put

    try:
        put(url, blob)
    except UploadError as exc:
        raise C.ZvidError(str(exc)) from None


def _download(url: str, sha256: str, size: int) -> bytes:
    """Байти за підписаним посиланням — і звірка з тим, що заявив сервер."""
    from nyshporka.sources.http import Fetcher, HttpError, app_ua

    try:
        # Без ключа: підписане посилання саме є правом, а ключ Супряги на
        # адресу сховища не йде ніколи.
        resp = Fetcher(headers={"User-Agent": app_ua()}, timeout=300.0).get(
            url, max_bytes=size + 1)
    except HttpError as exc:
        raise C.ZvidError(f"сховище не віддало пакет: {exc}") from None
    raw = bytes(resp.content)
    got = hashlib.sha256(raw).hexdigest()
    if got != sha256 or len(raw) != size:
        raise C.ZvidError(f"пакет доїхав пошкодженим: {len(raw)} Б, sha {got[:12]}… "
                          f"замість {size} Б, {sha256[:12]}…")
    return raw


# ── власник ─────────────────────────────────────────────────────────────────
def publish(path: Path, *, kind: str = "", note: str = "") -> dict[str, Any]:
    """Пакет → черга порталу. Повторний виклик доливає незалите, не дублює.

    Доповнення (`.zvidpatch`) іде до свого пакета: 20 МБ пакета не
    перезаливаються, новий голос — кілька десятків КБ.
    """
    from nyshporka.zvid import patch as PT

    if path.name.endswith(PT.PATCH_SUFFIX):
        return publish_patch(path)
    with C.open_zip(path) as zf:
        manifest = C.read_json_member(zf, C.MANIFEST)
    C.check_manifest(manifest)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    opys = {"procedure": manifest.get("procedure"), "sets": len(manifest.get("sets") or []),
            "pages": sum(len(s.get("pages") or []) for s in manifest.get("sets") or []),
            "voices": manifest.get("voices") or [], "min_client": manifest.get("min_client")}
    got = _call("POST", "/packs", {"id": manifest["id"], "size": len(raw), "sha256": sha,
                                   "kind": kind or kind_of(manifest),
                                   "note": note or manifest.get("note") or "", "opys": opys})
    if got.get("status") == "nove":
        _put(got["upload"], raw)
    return _call("POST", f"/packs/{manifest['id']}/ready")


def publish_patch(path: Path) -> dict[str, Any]:
    from nyshporka.zvid import patch as PT

    meta = PT.read_patch(path)
    raw = path.read_bytes()
    pid, rev = meta["pack"], int(meta["rev"])
    voices = sorted({v for i in meta.get("items") or [] for v in i.get("voices") or []})
    got = _call("POST", f"/packs/{pid}/patches",
                {"rev": rev, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                 "opys": {"voices": voices, "note": meta.get("note") or ""}})
    if not got.get("ready"):
        _put(got["upload"], raw)
    return _call("POST", f"/packs/{pid}/patches/{rev}/ready")


def queue(status: str = "") -> dict[str, Any]:
    from urllib.parse import urlencode

    return _call("GET", "/packs" + (f"?{urlencode({'status': status})}" if status else ""))


def fetch(*, ws: Any = None) -> list[dict[str, Any]]:
    """Повернуті відповіді → `collect` у набори власника → «прийнято» на порталі."""
    from nyshporka.zvid import owner

    out = []
    for p in queue("povernuto").get("packs") or []:
        got = _call("GET", f"/packs/{p['id']}/answer")
        raw = _download(got["download"], got["answer_sha256"], int(got["answer_size"]))
        inbox = owner.ledger_dir(ws) / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        f = inbox / f"{p['id']}{C.ANSWER_SUFFIX}"
        f.write_bytes(raw)
        rep = owner.collect(f, ws=ws,
                            helper=f"portal:{p['person_id']}" if p.get("person_id") else "")
        pidsumok = {"imported": {k: v["rows"] for k, v in rep.imported.items()},
                    "control": rep.control, "refused": rep.refused, "model": rep.model}
        _call("POST", f"/packs/{p['id']}/accepted", {"pidsumok": pidsumok})
        out.append({"id": p["id"], "file": str(f), **pidsumok,
                    "suspects": sum(v["suspects"] for v in rep.imported.values())})
    return out


# ── помічник ────────────────────────────────────────────────────────────────
def _cached(f: Path, sha256: str, size: int) -> bool:
    """Файл уже лежить і той самий — продовження не качає 20 МБ удруге."""
    return (f.is_file() and f.stat().st_size == size
            and hashlib.sha256(f.read_bytes()).hexdigest() == sha256)


def take(*, pack_id: str = "", base: Path | None = None) -> tuple[Path, list[Path]]:
    """Наступний пакет із черги (або свій узятий — продовження) і його доповнення."""
    got = _call("POST", "/take", {"id": pack_id} if pack_id else {})
    inbox = (base or C.base_dir()) / "_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    f = inbox / f"{got['id']}{C.SUFFIX}"
    if not _cached(f, got["sha256"], int(got["size"])):
        f.write_bytes(_download(got["download"], got["sha256"], int(got["size"])))
    patches = []
    for p in sorted(got.get("patches") or [], key=lambda x: int(x["rev"])):
        pf = inbox / f"{got['id']}.r{int(p['rev'])}.zvidpatch"
        if not _cached(pf, p["sha256"], int(p["size"])):
            pf.write_bytes(_download(p["download"], p["sha256"], int(p["size"])))
        patches.append(pf)
    return f, patches


def mark_portal(root: Path) -> None:
    """Позначити пісочницю як узяту з порталу — `give` тоді заливає сам."""
    st = root / C.STATE
    state = json.loads(st.read_text(encoding="utf-8"))
    state["portal"] = True
    st.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def upload_answer(pack_id: str, answer: Path) -> dict[str, Any]:
    raw = answer.read_bytes()
    with zipfile.ZipFile(answer) as zf:
        meta = json.loads(zf.read(C.META).decode("utf-8"))
    got = _call("POST", f"/packs/{pack_id}/answer",
                {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    _put(got["upload"], raw)
    return _call("POST", f"/packs/{pack_id}/done", {"meta": meta})


def drop(pack_id: str) -> dict[str, Any]:
    return _call("POST", f"/packs/{pack_id}/drop")


def me() -> dict[str, Any]:
    return _call("GET", "/me")
