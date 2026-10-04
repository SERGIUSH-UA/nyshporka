"""📄 Лічильник сторінок PDF: пам'ятає між запусками й не стягує хмарних файлів.

Відгук стороннього користувача (macOS, 0.18.1, жовтень 2026): кожна
перебудова реєстру відкривала кожен PDF справи заново, а PDF у теці OneDrive,
вивантажений у хмару, при відкритті стягувався цілком. Перебудова висіла на
0% CPU годинами, і через це не заводилась навіть нова справа.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from nyshporka import pdfcount as PC


def _pdf(path: Path, pages: int) -> Path:
    import pypdfium2 as pdfium

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(100, 100)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Перелік відкритих файлів: лічильник відкриття загорнуто, не підмінено."""
    seen: list[str] = []
    real = PC._open_count

    def spy(path: str) -> int:
        seen.append(path)
        return real(path)

    monkeypatch.setattr(PC, "_open_count", spy)
    return seen


def test_count_survives_a_new_process_without_opening(tmp_path: Path, opened) -> None:
    """Друга перебудова (новий процес) бере число з диска, файл не відкривається."""
    f = _pdf(tmp_path / "справа" / "8433.pdf", 3)
    assert PC.pages(f) == 3
    assert len(opened) == 1

    PC._reset()                       # як новий запуск `nysh`
    assert PC.pages(f) == 3
    assert len(opened) == 1, "незмінний PDF відкрито вдруге — кеш на диску не працює"


def test_changed_file_is_recounted(tmp_path: Path, opened) -> None:
    """Перекачаний чи дописаний файл перечитується сам: ключ несе розмір і mtime."""
    f = _pdf(tmp_path / "8433.pdf", 3)
    assert PC.pages(f) == 3
    _pdf(f, 5)
    PC._reset()
    assert PC.pages(f) == 5

    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    PC._reset()
    assert PC.pages(f) == 5
    assert len(opened) == 3, "зміна mtime при тому самому розмірі має перечитувати файл"


def test_cloud_file_without_count_is_not_opened(tmp_path: Path, opened, monkeypatch) -> None:
    """🔴 Головне: хмарна заглушка без числа в кеші не відкривається."""
    f = _pdf(tmp_path / "справа" / "8433.pdf", 4)
    monkeypatch.setattr(PC, "cloud_placeholder", lambda st: True)

    with PC.session() as sess, pytest.raises(PC.CloudPdf):
        PC.pages(f)
    assert opened == []
    assert sess.skipped == {os.path.abspath(f): f.stat().st_size}

    # Явна дія над справою стягує файл і запам'ятовує число...
    assert PC.pages(f, fetch=True) == 4
    # ...і далі заглушка вже не завада: число з кешу, без відкриття.
    PC._reset()
    assert PC.pages(f) == 4
    assert len(opened) == 1


def test_fetch_session_counts_cloud_files(tmp_path: Path, opened, monkeypatch) -> None:
    """`--fetch-cloud`: перебудова стягує заглушку один раз і нічого не пропускає."""
    f = _pdf(tmp_path / "8433.pdf", 2)
    monkeypatch.setattr(PC, "cloud_placeholder", lambda st: True)
    with PC.session(fetch=True) as sess:
        assert PC.pages(f) == 2
    assert sess.skipped == {}
    got = PC.cloud_report()
    assert got is not None and got["files"] == {}


def test_cloud_report_for_doctor(tmp_path: Path, monkeypatch) -> None:
    """Перебудова записує пропущене; пораховане згодом зі звіту зникає."""
    f = _pdf(tmp_path / "справа" / "8433.pdf", 2)
    assert PC.cloud_report() is None
    monkeypatch.setattr(PC, "cloud_placeholder", lambda st: True)
    with PC.session(), pytest.raises(PC.CloudPdf):
        PC.pages(f)
    got = PC.cloud_report()
    assert got is not None and list(got["files"]) == [os.path.abspath(f)]

    PC.pages(f, fetch=True)
    got = PC.cloud_report()
    assert got is not None and got["files"] == {}


def test_broken_session_does_not_overwrite_report(tmp_path: Path, monkeypatch) -> None:
    """Обірвана перебудова бачила не всі справи — її перелік не записується."""
    f = _pdf(tmp_path / "8433.pdf", 2)
    monkeypatch.setattr(PC, "cloud_placeholder", lambda st: True)
    with pytest.raises(RuntimeError), PC.session():
        with pytest.raises(PC.CloudPdf):
            PC.pages(f)
        raise RuntimeError("обрив")
    assert PC.cloud_report() is None


@pytest.mark.parametrize(("attrs", "cloud"), [
    ({"st_flags": PC.SF_DATALESS}, True),                       # macOS dataless
    ({"st_flags": 0x20}, False),                                # інший прапорець
    ({"st_file_attributes": 0x00400000}, True),                 # OneDrive «лише онлайн»
    ({"st_file_attributes": 0x00040000}, True),                 # recall on open
    ({"st_file_attributes": 0x00001000}, True),                 # offline
    ({"st_file_attributes": 0x20 | 0x80000}, False),            # archive + pinned
    ({}, False),                                                # Linux
])
def test_cloud_placeholder_reads_only_attributes(attrs: dict[str, int], cloud: bool) -> None:
    assert PC.cloud_placeholder(SimpleNamespace(**attrs)) is cloud  # type: ignore[arg-type]


def test_missing_and_broken_files_raise(tmp_path: Path) -> None:
    with pytest.raises(PC.PdfCountError):
        PC.pages(tmp_path / "немає.pdf")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 obrizano")
    with pytest.raises(PC.PdfCountError):
        PC.pages(bad)


def test_describe_names_size_and_cure() -> None:
    text = PC.describe({"/a/справа-1/x.pdf": 2_000_000_000, "/a/справа-1/y.pdf": 900_000_000})
    assert "2 PDF" in text and "2.9 ГБ" in text and "справа-1" in text
    assert "--fetch-cloud" in text and "Always Keep on This Device" in text


def test_doctor_shows_cloud_pdfs_without_walking_disk(tmp_path: Path, monkeypatch) -> None:
    """`nysh doctor` бере перелік із останньої перебудови, а не з обходу диска."""
    from nyshporka.setup import doctor

    assert doctor._cloud_pdfs().level == "ok"
    f = _pdf(tmp_path / "справа-7" / "x.pdf", 2)
    monkeypatch.setattr(PC, "cloud_placeholder", lambda st: True)
    with PC.session(), pytest.raises(PC.CloudPdf):
        PC.pages(f)
    got = doctor._cloud_pdfs()
    assert got.level == "warn" and "справа-7" in got.detail
    assert "--fetch-cloud" in got.fix
    assert "PDF справ у хмарі" in {c.name for c in doctor.run()}
