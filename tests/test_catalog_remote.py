"""🗂 Каталог довідників із релізу: найновіший `catalog-*`, звірка, повтор.

Що тут тримається тестом:

1. **Найновіший зріз — за всіма сторінками релізів**, а не лише за першою:
   `catalog-*` виходить рідко й зсувається за першу сотню.
2. **Без звірки — нічого.** Архів з іншим sha256 чи розміром не ставиться, і
   старі паки лишаються як були.
3. **Той самий зріз удруге не качається** (позначка `origin`).
4. **Мережу вимкнено — «не перевірено»**, а не «свіжий».
"""
from __future__ import annotations

import hashlib
import io
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


def _pack(path: Path, domain: str, pack_id: str) -> None:
    from nyshporka.catalog import schema

    con = sqlite3.connect(path)
    schema.apply(con, domain)
    con.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)", [
        ("schema", str(schema.SCHEMA_VERSION)), ("domain", domain),
        ("pack_id", pack_id), ("taken", "2026-10-19"), ("rows", "0")])
    con.commit()
    con.close()


@pytest.fixture
def zipped(tmp_path: Path) -> bytes:
    src = tmp_path / "packs"
    src.mkdir()
    _pack(src / "courtbooks-test-2026.10.sqlite", "courtbooks", "courtbooks-test-2026.10")
    _pack(src / "churches-test-2026.09.sqlite", "churches", "churches-test-2026.09")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in src.glob("*.sqlite"):
            z.write(f, f.name)
    return buf.getvalue()


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    from nyshporka.catalog import store as S

    cat = tmp_path / "catalog"
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(cat))
    monkeypatch.delenv("NYSHPORKA_NO_NETWORK", raising=False)
    S.invalidate()
    yield cat
    S.invalidate()


def _release(tag: str, body: bytes, *, digest: str | None = None,
             draft: bool = False) -> dict[str, Any]:
    name = f"nyshporka-catalog-{tag.removeprefix('catalog-')}.zip"
    return {"tag_name": tag, "draft": draft, "assets": [{
        "name": name, "size": len(body),
        "browser_download_url": f"https://example.org/{name}",
        "digest": digest if digest is not None else "sha256:" + hashlib.sha256(body).hexdigest()}]}


def _pages(*pages: list[dict[str, Any]]) -> Any:
    def get(url: str, timeout: float) -> Any:
        n = int(url.rsplit("page=", 1)[1])
        return pages[n - 1] if n <= len(pages) else []
    return get


class _Resp(io.BytesIO):
    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> None:
        self.close()


def _opener(body: bytes) -> Any:
    return lambda req, timeout: _Resp(body)


def test_latest_reads_all_pages_and_skips_drafts(zipped: bytes, catalog: Path) -> None:
    from nyshporka.catalog import remote as R

    page1 = [{"tag_name": f"v0.{i}.0", "assets": []} for i in range(100)]
    page2 = [_release("catalog-2026-08-17", zipped), _release("catalog-2026-12-01", zipped, draft=True),
             _release("catalog-2026-10-19", zipped)]
    rel = R.latest(get_json=_pages(page1, page2))
    assert rel.tag == "catalog-2026-10-19" and rel.known


def test_release_without_digest_is_not_trusted(zipped: bytes, catalog: Path) -> None:
    from nyshporka.catalog import remote as R

    rel = R.latest(get_json=_pages([_release("catalog-2026-10-19", zipped, digest="")]))
    assert not rel.known and "sha256" in rel.why


def test_update_installs_once_then_is_current(zipped: bytes, catalog: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.catalog import remote as R
    from nyshporka.catalog import store as S

    rel = R.latest(get_json=_pages([_release("catalog-2026-10-19", zipped)]))
    monkeypatch.setattr(R, "urlopen", _opener(zipped))
    assert R.update(apply=False, rel=rel).state == "would-install"
    res = R.update(rel=rel)
    assert res.state == "installed" and len(res.installed) == 2
    assert {p.domain for p in S.installed() if p.ok} == {"courtbooks", "churches"}
    assert S.origin() == rel.name
    assert R.update(rel=rel).state == "current"


def test_mismatched_archive_installs_nothing(zipped: bytes, catalog: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.catalog import remote as R
    from nyshporka.catalog import store as S

    rel = R.latest(get_json=_pages([_release("catalog-2026-10-19", zipped)]))
    monkeypatch.setattr(R, "urlopen", _opener(zipped[:-10] + b"x" * 10))
    with pytest.raises(R.CatalogFetchError, match="звірку"):
        R.update(rel=rel)
    assert S.installed() == [] and S.origin() == ""


def test_offline_is_unknown_not_current(catalog: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.catalog import remote as R

    monkeypatch.setenv("NYSHPORKA_NO_NETWORK", "1")
    res = R.update()
    assert res.state == "unknown" and "мережу вимкнено" in res.release.why


def test_nysh_update_honours_no_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--no-catalog` і `NYSH_NO_CATALOG=1` — крок каталогу не питає мережу зовсім."""
    from nyshporka import cli
    from nyshporka.catalog import remote as R

    called: list[int] = []
    monkeypatch.setattr(R, "latest", lambda *a, **k: called.append(1) or R.CatalogRelease(why="x"))
    monkeypatch.setenv("NYSH_NO_CATALOG", "1")
    cli._catalog_step(check=False, skip=False)
    monkeypatch.delenv("NYSH_NO_CATALOG")
    cli._catalog_step(check=False, skip=True)
    assert called == []
    cli._catalog_step(check=True, skip=False)
    assert called == [1]
