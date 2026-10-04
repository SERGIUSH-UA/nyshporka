"""Злиття BatchNorm і гілок RepDWConv у PP-OCRv6 перед читанням — тотожне.

Що робить: кожен BatchNorm у режимі eval вливається у ваги й зсув попередньої
згортки, а RepDWConv (k×k depthwise Conv-BN + 1×1 depthwise + тотожність, далі
BN) зводиться в ОДНУ k×k depthwise-згортку зі зсувом. Чиста алгебра над вагами
(рахується у float64 і повертається в тип ваг), обчислювана функція та сама.

Навіщо: kraken 7.1.1 цього не робить (ні fuse, ні reparam у коді немає), і на
читанні кожен BN — окреме ядро, а кожен RepDWConv — дві згортки й додавання. BN
займали 12.4% часу карти. Ефект 04.10.2026 (GTX 1650): Дяк-Літописець 77.8 →
68.6 мс/рядок, Скриба-PP 104.6 → 94.0, через `pp_read_crops` −11.4%.

Тотожність: текст збігся на всіх перевірках — CPU 200/200, 200/200, 120/120
рядків (пачка 8) і 40/40 (по одному), карта 32/32, через раннер 48/48, holdout
ф.792 143/143 (CER 11.85% до й після); max |Δ логітів| 6.8e-4 при логітах до ~88.
Звірка: `pp_fuse_verify.py <модель> <тека кропів> [N]`.

⚠ Злиту мережу не тренувати й не зберігати: ключі state_dict інші, і завантажувач
kraken її назад не прочитає.
"""
import torch
from kraken.lib.ppocr import backbone as BB
from kraken.lib.ppocr import necks as NK
from torch import nn


@torch.no_grad()
def _fold(conv: nn.Conv2d, bn: nn.BatchNorm2d) -> tuple[torch.Tensor, torch.Tensor]:
    """(W, b) у float64 для згортки, за якою йде BN у режимі eval."""
    w = conv.weight.double()
    b = (conv.bias.double() if conv.bias is not None
         else torch.zeros(w.shape[0], dtype=torch.float64, device=w.device))
    s = bn.weight.double() / torch.sqrt(bn.running_var.double() + bn.eps)
    w = w * s.reshape(-1, 1, 1, 1)
    b = (b - bn.running_mean.double()) * s + bn.bias.double()
    return w, b


def _new_conv(conv: nn.Conv2d, w: torch.Tensor, b: torch.Tensor) -> nn.Conv2d:
    c = nn.Conv2d(conv.in_channels, conv.out_channels, conv.kernel_size, conv.stride,
                  conv.padding, conv.dilation, conv.groups, bias=True,
                  padding_mode=conv.padding_mode)
    dt, dev = conv.weight.dtype, conv.weight.device
    c.weight.data = w.to(dtype=dt, device=dev).contiguous()
    c.bias.data = b.to(dtype=dt, device=dev).contiguous()
    return c.eval().requires_grad_(False)


def _fuse_conv2dbn(m: BB.Conv2DBN) -> nn.Conv2d:
    return _new_conv(m.conv, *_fold(m.conv, m.bn))


@torch.no_grad()
def _fuse_repdw(m: BB.RepDWConv) -> nn.Conv2d:
    """k×k depthwise Conv-BN + 1×1 depthwise + тотожність, далі BN → одна згортка."""
    k = m.kernel_size
    wk, bk = _fold(m.conv.conv, m.conv.bn)                      # (C,1,k,k)
    w1 = m.conv1.weight.double()                                # (C,1,1,1)
    w = wk.clone()
    c = k // 2
    w[:, :, c, c] += w1[:, :, 0, 0]
    w[:, :, c, c] += 1.0                                        # гілка тотожності
    s = m.bn.weight.double() / torch.sqrt(m.bn.running_var.double() + m.bn.eps)
    w = w * s.reshape(-1, 1, 1, 1)
    b = (bk - m.bn.running_mean.double()) * s + m.bn.bias.double()
    return _new_conv(m.conv.conv, w, b)


def fuse_ppocr(rec: nn.Module) -> nn.Module:
    """Злити BN і гілки RepDWConv на місці; повертає `rec` (лише мережу в eval)."""
    if rec.training:
        raise ValueError("зливати можна лише мережу в режимі eval")
    n_bn = 0
    for mod in list(rec.modules()):
        if isinstance(mod, BB.LCNetV4Block):
            tm = mod.token_mixer
            if "rep_dw" in tm._modules:
                tm._modules["rep_dw"] = _fuse_repdw(tm._modules["rep_dw"])
                n_bn += 2
            if "dw_conv" in tm._modules:
                tm._modules["dw_conv"] = _fuse_conv2dbn(tm._modules["dw_conv"])
                n_bn += 1
            cm = mod.channel_mixer
            for key in ("expand", "compress"):
                cm._modules[key] = _fuse_conv2dbn(cm._modules[key])
                n_bn += 1
        elif isinstance(mod, BB._SimpleStem):
            mod.conv1 = _fuse_conv2dbn(mod.conv1)
            mod.conv2 = _fuse_conv2dbn(mod.conv2)
            n_bn += 2
        elif isinstance(mod, BB.ConvBNAct):
            mod.conv = _new_conv(mod.conv, *_fold(mod.conv, mod.bn))
            mod.bn = nn.Identity()
            n_bn += 1
        elif isinstance(mod, NK.ConvBNLayer):
            mod.conv = _new_conv(mod.conv, *_fold(mod.conv, mod.norm))
            mod.norm = nn.Identity()
            n_bn += 1
        elif isinstance(mod, NK.LightSVTRNeck):
            lc = mod.local_conv
            if isinstance(lc[1], nn.BatchNorm2d):
                lc[0] = _new_conv(lc[0], *_fold(lc[0], lc[1]))
                lc[1] = nn.Identity()
                n_bn += 1
    rec._fused_bn = n_bn
    rec._bn_left = sum(isinstance(m, (nn.BatchNorm2d, nn.BatchNorm1d)) for m in rec.modules())
    return rec
