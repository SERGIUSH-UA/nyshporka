"""📜 Звід: пакет → пісочниця помічника → відповідь → набір власника.

Перевіряється шлях цілком, бо кожен шов тут коштує тихо: рядок відповіді,
що ліг під чужий кроп, контрольна сторінка, що потрапила в злиття, підказка
видання, якої агент не побачив, — нічого з цього не падає, лише псує корпус.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from nyshporka.core import workspace as W
from nyshporka.train import sets as S
from nyshporka.train import tasks as T
from nyshporka.train import view as V
from nyshporka.zvid import common as C
from nyshporka.zvid import helper as H
from nyshporka.zvid import owner as OW

PAGE_W, PAGE_H = 600, 400
LINES = {"0001": ["Николай Ивановъ сынъ", "Марѳа Васильева", "Село Ходъ"],
         "0002": ["Иванъ Петровъ", "Анна Ѳедорова"]}
VOICE_B = {"0001": ["Николай Иванов сынь", "Марфа Васильева", "Село Ходь"],
           "0002": ["Иван Петров", "Анна Федорова"]}


def _boxes(n: int) -> list[list[int]]:
    return [[40, 20 + i * 60, PAGE_W - 40, 60 + i * 60] for i in range(n)]


def _page(n: int) -> Image.Image:
    im = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    d = ImageDraw.Draw(im)
    for b in _boxes(n):
        for x in range(b[0] + 10, b[2] - 10, 14):
            d.line((x, b[1] + 8, x + 6, b[3] - 8), fill="black", width=3)
    return im


def _crop(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("L", (PAGE_W - 80, 40), 255)
    d = ImageDraw.Draw(im)
    for x in range(10, im.width - 10, 14):
        d.line((x, 8, x + 6, 32), fill=40, width=3)
    im.save(path)


def _make_set(ws: W.Workspace, name: str, pages: dict[str, list[str]]) -> S.SetSpec:
    reg = S.registry(ws)
    spec = S.SetSpec(name=name, title="Книга 1605", case="ЦДІАК 11-1-4", domain="гродська книга",
                     drafts=[S.Draft(id="regent", dir="drafts/regent"),
                             S.Draft(id="diak", dir="drafts/diak")])
    reg.save(spec)
    meta: dict = {"version": 3, "source_run": "", "pages": {}}
    for pg, ls in pages.items():
        for vid, src in (("regent", ls), ("diak", VOICE_B.get(pg, ls))):
            f = reg.set_dir(name) / "drafts" / vid / f"{pg}.txt"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("\n".join(src) + "\n", encoding="utf-8")
        for i in range(len(ls)):
            _crop(reg.crops_of(spec) / pg / f"line_{i:03d}.png")
        frame = ws.root / "frames" / name / f"{pg}.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        _page(len(ls)).save(frame)
        meta["pages"][pg] = {"n_lines": len(ls), "size": [PAGE_W, PAGE_H], "orient": 0,
                             "boxes": _boxes(len(ls)), "src": str(frame)}
    (reg.crops_of(spec) / S.CUT_META_FILE).write_text(json.dumps(meta), encoding="utf-8")
    return spec


@pytest.fixture
def owner(tmp_path: Path) -> W.Workspace:
    root = tmp_path / "owner" / "space"
    root.mkdir(parents=True)
    (root / W.MARKER).write_text('[workspace]\nschema = 1\nname = "o"\npreset = "lab"\n',
                                 encoding="utf-8")
    ws = W.Workspace(root=root, name="o", origin="test", preset="lab")
    W.use(ws)
    reg = S.registry(ws)
    spec = _make_set(ws, "x17-z4-0006L", LINES)
    (reg.set_dir(spec.name) / "hints").mkdir()
    (reg.set_dir(spec.name) / "hints" / "edition.json").write_text(json.dumps({
        "0001:0": {"text": "Николай Ивановъ сынъ"},
        "0001:1": {"text": "Марѳа Васильева Петровна", "doubt": "межа рядка сумнівна"},
    }, ensure_ascii=False), encoding="utf-8")
    (reg.set_dir(spec.name) / "hints" / "window.json").write_text(json.dumps({
        "0001": {"text": "…а Николай Ивановъ сынъ и Марѳа Васильева…"}}, ensure_ascii=False),
        encoding="utf-8")
    spec.hint_sources = [
        S.HintSource(id="edition", label="ВИД", title="Ділова мова 1981", by="видавці",
                     how="прочитання слів; межі й правопис — з кропа",
                     caveats=["межа рядка підібрана автоматично"], file="hints/edition.json"),
        S.HintSource(id="window", level="page", label="ВИД-СТОР", title="Ділова мова 1981",
                     file="hints/window.json")]
    reg.save(spec)
    ctl = _make_set(ws, "x17-z5-0015R", {"0002": LINES["0002"]})
    merge = reg.set_dir(ctl.name) / "drafts" / "merge"
    merge.mkdir(parents=True)
    (merge / "0002.txt").write_text("\n".join(LINES["0002"]) + "\n", encoding="utf-8")
    (merge / S.META_FILE).write_text(json.dumps(
        {"pages": {"0002": {"conf": {"0": "med", "1": "med"}}}}), encoding="utf-8")
    ctl.drafts.append(S.Draft(id="merge", dir="drafts/merge"))
    reg.save(ctl)
    yield ws
    W.reset()


def _pack(owner: W.Workspace, tmp_path: Path) -> OW.PackReport:
    ctx = tmp_path / "context.md"
    ctx.write_text("# ЦДІАК 11-1-4, 1605\nПравопис — за виданням.\n", encoding="utf-8")
    return OW.build(["x17-z4-0006L"], out=tmp_path / "out", procedure="crop-read",
                    context=ctx, control=["x17-z5-0015R"], ws=owner)


def _answer_all(root: Path, text_of: dict[str, str] | None = None) -> None:
    for f in sorted((root / C.TASKS).glob("*.txt")):
        ans = {}
        for k in H._task_ids(f):
            pg, i = k.rsplit(":", 1)
            ans[k] = {"m": (text_of or {}).get(k, LINES[pg][int(i)]), "c": "med"}
        f.with_name(f.stem + ".answer.json").write_text(json.dumps(ans, ensure_ascii=False),
                                                        encoding="utf-8")


def test_round_trip_imports_work_sets_and_only_measures_control(owner: W.Workspace,
                                                                tmp_path: Path) -> None:
    rep = _pack(owner, tmp_path)
    assert rep.file.is_file() and len(rep.sets) == 2 and len(rep.control) == 1
    with zipfile.ZipFile(rep.file) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read(C.MANIFEST))
    # 🔴 Безлико: ні шифри набору, ні злиття, ні ручних міток контрольного.
    assert not any("x17-" in n for n in names)
    assert not any("/merge/" in n or n.endswith("lines.jsonl") for n in names)
    assert "x17-" not in json.dumps(manifest)
    assert manifest["procedure"] == "crop-read" and C.CONTEXT in names

    base = tmp_path / "helper" / "zvid"
    took = H.take(rep.file, base=base)
    assert took.rows == 7 and took.context and not took.resumed
    work = next(a for a, n in rep.sets.items() if n == "x17-z4-0006L")
    task = next(f.read_text(encoding="utf-8") for f in took.tasks
                if f.name.startswith(work) and "0001" in f.read_text(encoding="utf-8"))
    assert "Ти читаєш КОЖЕН рядок сам" in task
    assert "★ ДЖЕРЕЛА" in task and "ВИД — «Ділова мова 1981», видавці" in task
    assert "  ВИД: Марѳа Васильева Петровна  ⚠ межа рядка сумнівна" in task
    assert "ТЕКСТ ДЖЕРЕЛА ДО СТОРІНКИ 0001" in task
    assert f"nysh zvid give {rep.id}" in task
    assert str(took.root) in task, "шляхи аркушів — у пісочниці помічника"
    # дивилка працює в пісочниці без прогону й без машини власника
    sb = H.sandbox(took.root)
    shot = V.ctx(work, "0001", 1, pad=20, ws=sb)
    assert shot.width > 0
    again = H.take(rep.file, base=base)
    assert again.resumed, "повторний take — продовження"

    ctl = next(a for a, n in rep.sets.items() if n == "x17-z5-0015R")
    _answer_all(took.root, {"0002:1": "Анна Ѳедорова дочь"})
    st = H.status(rep.id, base=base)[0]
    assert st["done"] == st["rows"] == 7
    given = H.give(rep.id, model="claude-test", agents=2, base=base)
    assert given.answered == 7 and given.missing == 0

    got = OW.collect(given.file, ws=owner)
    assert set(got.imported) == {"x17-z4-0006L"} and got.imported["x17-z4-0006L"]["rows"] == 5
    assert got.control["x17-z5-0015R"]["lines"] == 2 and got.control["x17-z5-0015R"]["cer"] > 0
    reg = S.registry(owner)
    merged = (reg.merge_dir(reg.load("x17-z4-0006L")) / "0001.txt").read_text(encoding="utf-8")
    assert merged.splitlines()[0] == "Николай Ивановъ сынъ"
    # контрольна в злиття не потрапила
    cm = (reg.merge_dir(reg.load("x17-z5-0015R")) / "0002.txt").read_text(encoding="utf-8")
    assert "дочь" not in cm
    ledger = json.loads(rep.ledger.read_text(encoding="utf-8"))
    assert ledger["returns"][0]["model"] == "claude-test" and ledger["map"][ctl] == "x17-z5-0015R"


def test_give_refuses_markers_foreign_keys_and_unfinished(owner: W.Workspace,
                                                          tmp_path: Path) -> None:
    rep = _pack(owner, tmp_path)
    base = tmp_path / "helper" / "zvid"
    took = H.take(rep.file, base=base)
    first = sorted((took.root / C.TASKS).glob("*.txt"))[0]
    ids = H._task_ids(first)
    ans = first.with_name(first.stem + ".answer.json")
    ans.write_text(json.dumps({ids[0]: {"m": "Марѳа ‹Васильева|Василиева›", "c": "med"},
                               "9999:0": {"m": "чуже", "c": "med"}}, ensure_ascii=False),
                   encoding="utf-8")
    with pytest.raises(C.ZvidError, match="маркер") as e:
        H.give(rep.id, model="m", base=base)
    assert "не з цього завдання" in str(e.value)
    ans.write_text(json.dumps({ids[0]: {"m": "текст", "c": "med"}}), encoding="utf-8")
    with pytest.raises(C.ZvidError, match="--partial"):
        H.give(rep.id, model="m", base=base)
    with pytest.raises(C.ZvidError, match="модель"):
        H.give(rep.id, model=" ", base=base, partial=True)
    part = H.give(rep.id, model="m", base=base, partial=True)
    assert part.answered == 1 and part.missing == 6


def test_collect_refuses_answer_on_recut_frames(owner: W.Workspace, tmp_path: Path) -> None:
    rep = _pack(owner, tmp_path)
    base = tmp_path / "helper" / "zvid"
    took = H.take(rep.file, base=base)
    _answer_all(took.root)
    given = H.give(rep.id, model="m", base=base)
    reg = S.registry(owner)
    spec = reg.load("x17-z4-0006L")
    cm = reg.crops_of(spec) / S.CUT_META_FILE
    meta = json.loads(cm.read_text(encoding="utf-8"))
    meta["pages"]["0001"]["boxes"][0][1] += 5
    cm.write_text(json.dumps(meta), encoding="utf-8")
    got = OW.collect(given.file, ws=owner)
    assert "x17-z4-0006L" not in got.imported
    assert any("рамки змінились" in r for r in got.refused)


def test_private_set_never_packs(owner: W.Workspace, tmp_path: Path) -> None:
    reg = S.registry(owner)
    spec = reg.load("x17-z4-0006L")
    spec.private = True
    reg.save(spec)
    assert reg.load("x17-z4-0006L").private
    with pytest.raises(C.ZvidError, match="private"):
        OW.build(["x17-z4-0006L"], out=tmp_path / "out", ws=owner)


def test_take_refuses_zip_slip_and_newer_client(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zvid"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(C.ZvidError, match="неприпустимий шлях"):
        H.take(bad, base=tmp_path / "b")
    newer = tmp_path / "newer.zvid"
    with zipfile.ZipFile(newer, "w") as zf:
        zf.writestr(C.MANIFEST, json.dumps({"format": "zvid", "version": 1,
                                            "id": "zv20261024-abcdef", "min_client": "99.0",
                                            "sets": []}))
    with pytest.raises(C.ZvidError, match="nysh update"):
        H.take(newer, base=tmp_path / "b")


def test_literal_source_grounds_label_for_suspects(owner: W.Workspace) -> None:
    """Мітка з видання при слабких голосах не йде людині як «домисел»."""
    reg = S.registry(owner)
    spec = reg.load("x17-z4-0006L")
    support = T.literal_support(reg, spec, "0001")
    assert support == {0: ["Николай Ивановъ сынъ"], 1: ["Марѳа Васильева Петровна"]}
    from nyshporka.train import gate as G

    merged = ["Николай Ивановъ сынъ", "", ""]
    conf = {0: "med"}
    weak = [["Ншкол Иван сн", "", ""], ["Нкл Ивнвъ", "", ""]]
    g = G.gate_page("0001", list(merged), weak, dict(conf))
    assert any(i == 0 for i, _ in g.suspects)
    g2 = G.gate_page("0001", list(merged), weak, dict(conf), support=support)
    assert not any(i == 0 for i, _ in g2.suspects)


# ── портал ───────────────────────────────────────────────────────────────────
class _FakePortal:
    """Сервер черги в пам'яті: той самий порядок викликів, що в `app/routers/zvid.py`."""

    def __init__(self) -> None:
        self.bytes: dict[str, bytes] = {}
        self.packs: dict[str, dict] = {}
        self.accepted: dict[str, dict] = {}

    def call(self, method: str, path: str, body: object = None) -> dict:
        import hashlib

        b = body if isinstance(body, dict) else {}
        if path == "/packs" and method == "POST":
            self.packs[b["id"]] = {**b, "status": "nove"}
            return {"id": b["id"], "status": "nove", "upload": f"put:{b['id']}"}
        if path.endswith("/ready"):
            pid = path.split("/")[2]
            p = self.packs[pid]
            assert hashlib.sha256(self.bytes[pid]).hexdigest() == p["sha256"]
            p["status"] = "vilnyi"
            return {"id": pid, "kind": p["kind"], "status": "vilnyi", "size": p["size"]}
        if path == "/take":
            pid = next(k for k, v in self.packs.items() if v["status"] == "vilnyi")
            self.packs[pid]["status"] = "vzhato"
            p = self.packs[pid]
            return {"id": pid, "size": p["size"], "sha256": p["sha256"], "download": f"get:{pid}"}
        if path.endswith("/answer") and method == "POST":
            pid = path.split("/")[2]
            self.packs[pid]["answer"] = b
            return {"upload": f"put:{pid}.answer"}
        if path.endswith("/done"):
            pid = path.split("/")[2]
            self.packs[pid]["status"], self.packs[pid]["meta"] = "povernuto", b["meta"]
            return {"id": pid, "status": "povernuto"}
        if path.startswith("/packs?status=povernuto"):
            return {"packs": [{"id": k} for k, v in self.packs.items() if v["status"] == "povernuto"]}
        if path.endswith("/answer") and method == "GET":
            pid = path.split("/")[2]
            a = self.packs[pid]["answer"]
            return {"download": f"get:{pid}.answer", "answer_sha256": a["sha256"],
                    "answer_size": a["size"]}
        if path.endswith("/accepted"):
            pid = path.split("/")[2]
            self.accepted[pid] = b["pidsumok"]
            self.packs[pid]["status"] = "pryiniato"
            return {"id": pid}
        raise AssertionError(f"неочікуваний виклик {method} {path}")


def test_portal_round_trip(owner: W.Workspace, tmp_path: Path,
                           monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.zvid import portal as P

    fake = _FakePortal()
    monkeypatch.setattr(P, "_call", fake.call)
    monkeypatch.setattr(P, "_put", lambda url, blob: fake.bytes.__setitem__(url[4:], blob))
    monkeypatch.setattr(P, "_download", lambda url, sha, size: fake.bytes[url[4:]])

    rep = _pack(owner, tmp_path)
    got = P.publish(rep.file)
    assert got["status"] == "vilnyi" and fake.packs[rep.id]["kind"] == "regent", \
        "голос Регента робить пакет класом regent, а не public"
    assert "x17-" not in json.dumps(fake.packs[rep.id]["opys"])

    base = tmp_path / "helper" / "zvid"
    f = P.take(base=base)
    took = H.take(f, base=base)
    P.mark_portal(took.root)
    _answer_all(took.root)
    given = H.give(rep.id, model="claude-test", base=base)
    P.upload_answer(rep.id, given.file)
    assert fake.packs[rep.id]["status"] == "povernuto"
    assert fake.packs[rep.id]["meta"]["model"] == "claude-test"

    out = P.fetch(ws=owner)
    assert [o["id"] for o in out] == [rep.id]
    assert fake.accepted[rep.id]["imported"] == {"x17-z4-0006L": 5}
    assert "x17-z5-0015R" in fake.accepted[rep.id]["control"]


def test_kind_of_names_the_specialist() -> None:
    from nyshporka.zvid.portal import kind_of

    assert kind_of({"voices": ["regent_v2", "kdiak7_crops"]}) == "regent"
    assert kind_of({"voices": ["pysar_x18_v1"]}) == "pysar_x18"
    assert kind_of({"voices": ["pysar_cyr_v28", "diak_cyr_v7"]}) == "public"
