"""📦 `nysh relocate`: переїзд у одну теку без втрати жодного файла.

🔴 Обіцянки:

- копія звіряється ПОФАЙЛОВО, і розбіжність зупиняє переїзд до того, як щось
  старе зачеплено;
- `run()` нічого старого не видаляє — лише `finish()`, і лише те, що назвав
  `leftovers()`, після ще однієї звірки;
- venv рушіїв не копіюється (він не переноситься), а збирається наново.

Справжні uv і PowerShell тут не кличуться: `runner` — заглушка, ярлики
вимкнено, щоб тест не перевішав ярлики на машині розробника.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def old(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    from nyshporka.core import workspace as W
    from nyshporka.setup import relocate as R
    from nyshporka.setup import update as U

    ws = tmp_path / "C" / "Users" / "x" / "Нишпорка"
    (ws / "data" / "raw" / "spr-1").mkdir(parents=True)
    (ws / "data" / "raw" / "spr-1" / "0001.jpg").write_bytes(b"x" * 100)
    (ws / "config").mkdir()
    (ws / "config" / "research_profile.yaml").write_text("fallback: moje\n", encoding="utf-8")
    (ws / "nyshporka.toml").write_text(
        "[workspace]\nschema = 1\n" f'case_roots = ["{(ws / "data" / "raw").as_posix()}"]\n',
        encoding="utf-8")
    (ws / ".venv_htr" / "Scripts").mkdir(parents=True)
    (ws / ".venv_htr" / "Scripts" / "python.exe").write_bytes(b"venv")

    home = tmp_path / "C" / "Users" / "x" / "AppData" / "Local" / "Programs" / "Nyshporka"
    (home / "uv").mkdir(parents=True)
    uv = home / "uv" / "uv.exe"
    uv.write_bytes(b"uv")
    (home / "install-info.ini").write_text(
        f"[nyshporka]\nuv={uv}\npreset=researcher\npython_dir={home / 'python'}\n",
        encoding="utf-8")
    (home / "python").mkdir()
    (home / "python" / "py.exe").write_bytes(b"py")

    data = tmp_path / "C" / "Users" / "x" / "AppData" / "Local" / "Nyshporka"
    (data / "catalog").mkdir(parents=True)
    (data / "catalog" / "pack.sqlite").write_bytes(b"c" * 50)
    (data / "Cache" / "model").mkdir(parents=True)
    (data / "Cache" / "model" / "w.pt").write_bytes(b"m" * 70)

    W.reset()
    W.use(W.Workspace(root=ws, name="тест", origin="test"))
    monkeypatch.setattr(U, "install_home", lambda: home)
    monkeypatch.setattr("nyshporka.core.appdirs.data_dir", lambda: data)
    monkeypatch.setattr("nyshporka.setup.doctor.engine_venv", lambda: ws / ".venv_htr")
    monkeypatch.setattr(R, "_retarget_shortcuts", lambda *a, **k: None)
    monkeypatch.setattr(R, "_old_uv_cache", lambda uv: "")
    monkeypatch.setattr(U, "tool_env", lambda: True)
    yield {"ws": ws, "home": home, "data": data, "uv": uv}
    W.reset()


def _quiet(*_a, **_k) -> None:
    return None


def test_the_plan_names_every_move_and_writes_nothing(old, tmp_path: Path) -> None:
    from nyshporka.setup import relocate as R

    target = tmp_path / "D" / "Projects" / "Нишпорка"
    p = R.plan(target)
    assert not p.problems, p.problems
    assert p.home_to == target / ".program" and p.engines is True
    # venv рушіїв у вагу простору не входить: він не копіюється
    ws = old["ws"]
    assert p.workspace_bytes == 100 + sum(
        (ws / f).stat().st_size for f in ("config/research_profile.yaml", "nyshporka.toml"))
    assert not target.exists()


def test_a_target_inside_the_old_space_is_refused(old) -> None:
    from nyshporka.setup import relocate as R

    p = R.plan(old["ws"] / "data" / "нове")
    assert any("старому просторі" in x for x in p.problems)


def test_a_copy_that_does_not_match_stops_the_move(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.setup import relocate as R

    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "a" / "f.jpg").write_bytes(b"12345")
    real = R.manifest

    def short_copy(root, skip_top=()):
        got = real(root, skip_top)
        if root.name == "dst":
            got["a/f.jpg"] = 1          # «обрізаний» файл
        return got

    monkeypatch.setattr(R, "manifest", short_copy)
    with pytest.raises(R.RelocateError, match="інший розмір"):
        R.copy_verified(src, tmp_path / "dst", echo=_quiet)


def test_run_copies_installs_and_deletes_nothing(old, tmp_path: Path) -> None:
    from nyshporka.setup import relocate as R

    target = tmp_path / "D" / "Projects" / "Нишпорка"
    calls: list[list[str]] = []
    nysh = R.run(R.plan(target), runner=lambda cmd, env: calls.append(cmd) or 0, echo=_quiet)

    home = target / ".program"
    assert (target / "data" / "raw" / "spr-1" / "0001.jpg").read_bytes() == b"x" * 100
    assert not (target / ".venv_htr").exists()           # venv збирається наново
    assert (home / "data" / "Cache" / "model" / "w.pt").is_file()
    assert (home / "data" / "catalog" / "pack.sqlite").is_file()
    marker = (target / "nyshporka.toml").read_text(encoding="utf-8")
    assert (target / "data" / "raw").as_posix() in marker
    # нова програма — у новій теці, рушії зібрано
    install = next(c for c in calls if c[1:3] == ["tool", "install"])
    assert install[0] == str(home / "uv" / "uv.exe") and install[-1].count("==") == 1
    assert [str(nysh), "htr", "install"] in calls
    info = R._info_at(home)
    assert info["workspace"] == str(target) and info["cache_dir"] == str(home / "cache")
    assert R._info_at(old["home"])["relocated_to"] == str(home)
    # 🔴 старе ціле
    assert (old["ws"] / "data" / "raw" / "spr-1" / "0001.jpg").is_file()
    assert (old["data"] / "Cache" / "model" / "w.pt").is_file()
    assert (old["home"] / "python" / "py.exe").is_file()


def test_finish_removes_only_what_it_named_after_a_second_check(old, tmp_path: Path) -> None:
    from nyshporka.core import workspace as W
    from nyshporka.setup import relocate as R

    target = tmp_path / "D" / "Projects" / "Нишпорка"
    R.run(R.plan(target), runner=lambda cmd, env: 0, echo=_quiet)
    W.use(W.Workspace(root=target, name="тест", origin="test"))
    rec, items = R.leftovers(target / ".program")
    paths = {it.path for it in items if it.how == "rmtree"}
    assert old["ws"] in paths and old["home"] / "python" in paths
    assert old["data"] / "Cache" in paths and old["data"] / "catalog" in paths
    # стан і ключі в старій теці даних — не наші, лишаються
    (old["data"] / "state.json").write_text("{}", encoding="utf-8")

    items = [it for it in items if it.how == "rmtree"]
    R.finish(items, rec, echo=_quiet)
    assert not old["ws"].exists() and not (old["home"] / "python").exists()
    assert (old["data"] / "state.json").is_file()
    assert (target / "data" / "raw" / "spr-1" / "0001.jpg").is_file()


def test_finish_refuses_when_the_new_space_lost_a_file(old, tmp_path: Path) -> None:
    from nyshporka.core import workspace as W
    from nyshporka.setup import relocate as R

    target = tmp_path / "D" / "Projects" / "Нишпорка"
    R.run(R.plan(target), runner=lambda cmd, env: 0, echo=_quiet)
    (target / "data" / "raw" / "spr-1" / "0001.jpg").unlink()
    W.use(W.Workspace(root=target, name="тест", origin="test"))
    with pytest.raises(R.RelocateError, match="бракує"):
        R.leftovers(target / ".program")
    assert (old["ws"] / "data" / "raw" / "spr-1" / "0001.jpg").is_file()


def test_finish_needs_the_record_of_the_move(tmp_path: Path) -> None:
    from nyshporka.setup import relocate as R

    with pytest.raises(R.RelocateError, match="НОВОЮ програмою"):
        R.leftovers(tmp_path)
    assert json
