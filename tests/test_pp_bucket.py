"""PP-моделі у fp16 з кошиками форм: коли вмикається і що робить обгортка.

Заміряно 18.11.2026: на V100 fp16 + кошики 64 px — розпізнавання +59 %, на GTX 1650
той самий fp16 учетверо повільніший. Тому `auto` вирішує за картою (як для Писаря),
а кошики лише доповнюють вхід до сітки форм і повертають вихід вихідної форми.
"""
from __future__ import annotations

import sys
import types

import pytest

from nyshporka.htr import runner as R


def _fake_torch(monkeypatch: pytest.MonkeyPatch, name: str, cap: tuple[int, int]) -> None:
    cuda = types.SimpleNamespace(get_device_name=lambda i: name,
                                 get_device_capability=lambda i: cap)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cuda))


@pytest.mark.parametrize(("name", "cap", "want"), [
    ("Tesla V100-SXM2-32GB", (7, 0), True),
    ("NVIDIA GeForce RTX 3060", (8, 6), True),
    ("NVIDIA GeForce GTX 1650", (7, 5), False),
    ("NVIDIA GeForce GTX 1080 Ti", (6, 1), False),
])
def test_auto_za_kartoiu(monkeypatch: pytest.MonkeyPatch, name: str,
                         cap: tuple[int, int], want: bool) -> None:
    _fake_torch(monkeypatch, name, cap)
    assert R.pp_fp16_wanted("auto", "cuda:0")[0] is want


def test_ruchky_i_procesor(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_torch(monkeypatch, "NVIDIA GeForce GTX 1650", (7, 5))
    assert R.pp_fp16_wanted("fp16", "cuda:0")[0] is True
    assert R.pp_fp16_wanted("fp32", "cuda:0")[0] is False
    assert R.pp_fp16_wanted("auto", "cpu")[0] is False
    assert R.pp_fp16_wanted("fp16", "cpu")[0] is False


def test_defoly() -> None:
    assert R.PP_PRECISION == "auto"
    assert R.PP_BUCKET == 64


def test_koshyk_formy_i_vykhid() -> None:
    torch = pytest.importorskip("torch")
    from nyshporka.htr.patches import pp_bucket

    seen: list[tuple[int, ...]] = []

    class Net(torch.nn.Module):
        def forward(self, x, seq_lens=None):  # type: ignore[no-untyped-def]
            seen.append(tuple(x.shape))
            logits = x.mean(dim=(1, 2), keepdim=True)[:, :, :, ::4].repeat(1, 5, 1, 1)
            lens = None if seq_lens is None else (seq_lens // 4)
            return logits, lens

    net = pp_bucket.enable_bucket(Net(), 64)
    x = torch.rand(3, 3, 48, 200)
    lens = torch.tensor([200, 150, 90])
    logits, out_lens = net(x, lens)
    assert seen[-1] == (4, 3, 48, 256)          # рядки до степеня двійки, ширина до кроку
    assert logits.shape[0] == 3                 # зайві рядки відкинуто
    assert logits.shape[-1] == 50               # вихід вихідної ширини (200 / 4)
    assert out_lens.tolist() == [50, 37, 22]
    # уже на сітці — без доповнення
    net(torch.rand(4, 3, 48, 128), torch.tensor([128] * 4))
    assert seen[-1] == (4, 3, 48, 128)
