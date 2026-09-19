"""🚚 Швидкий шлях великих файлів — системний `scp` поруч із SFTP paramiko.

SFTP у paramiko дає 0.4–0.45 МБ/с при домашньому аплінку 15 МБ/с: вузьке місце
— сама бібліотека. На орендованій машині це години оплаченого простою, тож
великий файл їде через `scp`. Перевіряється тут три речі, і жодна не потребує
мережі:

* приймач передачі — РОЗМІР на машині, а не нульовий код `scp`;
* будь-яка відмова швидкого шляху — це відкат на SFTP з нотаткою, а не збій;
* ключ, порт і ВЛАСНИЙ файл відбитків доїжджають до `scp` — системний
  `known_hosts` не чіпається й тут.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nyshporka.cloud import ssh as S
from nyshporka.cloud.base import Completed


class FakeSftp:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.puts: list[str] = []
        self.gets: list[str] = []

    def put(self, local: str, remote: str) -> None:
        self.puts.append(remote)
        (self.root / Path(remote).name).write_bytes(Path(local).read_bytes())

    def get(self, remote: str, local: str) -> None:
        self.gets.append(remote)
        Path(local).write_bytes((self.root / Path(remote).name).read_bytes())

    def stat(self, remote: str) -> Any:
        return SimpleNamespace(st_size=(self.root / Path(remote).name).stat().st_size)


@pytest.fixture
def rig(tmp_path: Path, monkeypatch):
    """Сесія без мережі: «машина» — тека, `scp` — підмінений `subprocess.run`."""
    box = tmp_path / "box"
    box.mkdir()
    host = S.Host(name="бокс", user="root", host="203.0.113.7", port=41022,
                  key=str(tmp_path / "id_ed25519"))
    session = S.SshSession(client=None, host=host)
    sftp = FakeSftp(box)
    session._sftp = sftp

    def run(cmd: str, *, timeout=None, on_line=None) -> Completed:
        if "nysh_size=" in cmd:
            name = cmd.split("stat -c %s ")[1].split(" ")[0].strip("'\"")
            p = box / Path(name).name
            return Completed(rc=0, out=f"nysh_size={p.stat().st_size if p.exists() else ''}")
        return Completed(rc=0, out="")

    monkeypatch.setattr(session, "run", run)
    monkeypatch.setattr(S, "FAST_PATH_BYTES", 1000)
    monkeypatch.setattr(S, "_known_hosts_path", lambda: tmp_path / "cfg" / "known_hosts")
    monkeypatch.setattr(S.shutil, "which", lambda name: "/usr/bin/scp")
    calls: list[dict[str, Any]] = []
    behaviour = {"rc": 0, "copy": True, "truncate": False}

    def fake_run(cmd: list[str], **kw: Any) -> Any:
        calls.append({"cmd": cmd, **kw})
        src, dst = cmd[-2], cmd[-1]
        if behaviour["copy"]:
            cwd = Path(kw["cwd"])
            if ":" in dst:                                   # заливка
                data = (cwd / src).read_bytes()
                (box / Path(dst.split(":", 1)[1]).name).write_bytes(
                    data[: len(data) // 2] if behaviour["truncate"] else data)
            else:                                            # забір
                data = (box / Path(src.split(":", 1)[1]).name).read_bytes()
                (cwd / dst).write_bytes(data)
        return SimpleNamespace(returncode=behaviour["rc"], stdout="",
                               stderr="Permission denied (publickey)." if behaviour["rc"] else "")

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    return session, sftp, calls, behaviour, box


def test_a_big_file_goes_through_scp_with_our_key_port_and_known_hosts(rig, tmp_path) -> None:
    session, sftp, calls, _, _box = rig
    big = tmp_path / "case.tar"
    big.write_bytes(b"x" * 5000)

    assert session.put(big, "/workspace/nysh-run/sprava__ab12/case.tar") == 5000
    assert sftp.puts == [], "SFTP не знадобився"
    cmd = calls[0]["cmd"]
    assert cmd[-2:] == ["./case.tar", "root@203.0.113.7:/workspace/nysh-run/sprava__ab12/case.tar"]
    assert cmd[cmd.index("-P") + 1] == "41022"
    assert cmd[cmd.index("-i") + 1].endswith("id_ed25519")
    opts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-o"]
    assert "BatchMode=yes" in opts, "жодного запиту з клавіатури"
    assert "StrictHostKeyChecking=accept-new" in opts, \
        "новий хост — записати, ЗМІНЕНИЙ ключ — відмова"
    assert any(o.startswith("UserKnownHostsFile=") and "known_hosts" in o
               and "cfg" in o for o in opts), "власний файл відбитків, не системний"
    assert calls[0]["cwd"] == str(tmp_path), \
        "локальний файл — відносним іменем: `C:\\…` для scp виглядає як хост"
    assert calls[0]["timeout"] > 300


def test_a_small_file_stays_on_sftp(rig, tmp_path) -> None:
    session, sftp, calls, _, _ = rig
    small = tmp_path / "go.sh"
    small.write_bytes(b"x" * 10)
    session.put(small, "/w/go.sh")
    assert calls == [] and sftp.puts == ["/w/go.sh"]


def test_the_receiver_is_the_size_on_the_box_not_the_exit_code(rig, tmp_path) -> None:
    """🔴 `scp` вийшов нулем, а файл на машині вдвічі коротший: обірваний канал
    лишає файл, який виглядає як покладений."""
    session, sftp, calls, behaviour, box = rig
    behaviour["truncate"] = True
    big = tmp_path / "case.tar"
    big.write_bytes(b"x" * 5000)

    assert session.put(big, "/w/case.tar") == 5000
    assert len(calls) == 1 and sftp.puts == ["/w/case.tar"], "переклали через SFTP"
    assert (box / "case.tar").stat().st_size == 5000
    assert any("байт замість" in n for n in session.notes)


def test_a_failed_scp_falls_back_with_a_note(rig, tmp_path) -> None:
    session, sftp, _, behaviour, _ = rig
    behaviour.update(rc=255, copy=False)
    big = tmp_path / "case.tar"
    big.write_bytes(b"x" * 5000)
    assert session.put(big, "/w/case.tar") == 5000
    assert sftp.puts == ["/w/case.tar"]
    assert any("rc=255" in n and "Permission denied" in n for n in session.notes)


def test_no_scp_in_path_is_not_an_error(rig, tmp_path, monkeypatch) -> None:
    session, sftp, calls, _, _ = rig
    monkeypatch.setattr(S.shutil, "which", lambda name: None)
    big = tmp_path / "case.tar"
    big.write_bytes(b"x" * 5000)
    session.put(big, "/w/case.tar")
    assert calls == [] and sftp.puts == ["/w/case.tar"]
    assert any("немає в PATH" in n for n in session.notes)


def test_a_hanging_scp_is_cut_by_the_timeout(rig, tmp_path, monkeypatch) -> None:
    session, sftp, _, _, _ = rig

    def hang(cmd: list[str], **kw: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(S.subprocess, "run", hang)
    big = tmp_path / "case.tar"
    big.write_bytes(b"x" * 5000)
    session.put(big, "/w/case.tar")
    assert sftp.puts == ["/w/case.tar"]


def test_a_path_that_needs_quoting_never_reaches_scp(rig, tmp_path) -> None:
    """Старий протокол `scp` пропускає шлях крізь оболонку, новий — ні, і лапки,
    потрібні одному, ламають інший. Такі шляхи їдуть через SFTP."""
    session, sftp, calls, _, _ = rig
    big = tmp_path / "case.tar"
    big.write_bytes(b"x" * 5000)
    session.put(big, "/w/тека з пробілом/case.tar")
    assert calls == [] and len(sftp.puts) == 1


def test_a_big_result_comes_back_through_scp_too(rig, tmp_path) -> None:
    session, sftp, calls, behaviour, box = rig
    (box / "result.tar").write_bytes(b"r" * 7000)
    dest = tmp_path / "in" / "x.result.tar"

    assert session.get("/w/result.tar", dest) == 7000
    assert sftp.gets == [] and dest.read_bytes() == b"r" * 7000
    assert calls[0]["cmd"][-2:] == ["root@203.0.113.7:/w/result.tar", "./x.result.tar.part"]
    assert not list(dest.parent.glob("*.part")), "часткового файла не лишається"

    behaviour.update(rc=1, copy=False)
    again = tmp_path / "in" / "y.result.tar"
    assert session.get("/w/result.tar", again) == 7000
    assert sftp.gets == ["/w/result.tar"], "відкат на SFTP"
