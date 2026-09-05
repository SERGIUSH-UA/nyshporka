"""Один ресайз кадру замість двох у `kraken.blla.compute_segmentation_map`.

Що робить стоковий kraken 7.0.2 (`blla.py:101-106`): будує ланцюг трансформів
(режим → LANCZOS-ресайз до висоти сегментера → паддінг → тензор → інверсія),
відрізає його на `PILToTensor` і застосовує голову ланцюга до кадру, щоб
отримати `scal_im` (масштабоване сіре зображення для геометрії), а потім
застосовує ВЕСЬ ланцюг до того самого кадру ще раз, щоб отримати тензор для
мережі. Тобто LANCZOS-ресайз повного скану (5811×4777 і більше → 1800 по
висоті) робиться двічі з одного й того самого PIL — і це найдорожчий крок
підготовки сторінки.

Патч робить голову один раз, а хвіст ланцюга (від `PILToTensor`) прикладає
до вже масштабованого PIL. Обидва проходи детерміновані, тож `scal_im` і
тензор побайтно ті самі — це доводить `seg_resize_verify`, а не ця докстрінг.

Що збережено НАВМИСНО:
- `convert('L')` для `scal_im` робиться ПІСЛЯ ресайзу, як у стоку (для
  3-канальної моделі голова ланцюга дає RGB, сірим стає лише копія);
- гілка `mask` дослівно: маска трансформується власним викликом, її ніхто
  не ресайзить двічі;
- решта тіла (паддінг, інтерполяція, `scale`, повернений словник) — копія
  стоку без змін.

⚠ Порядок установки: `install()` кладе патч у `blla.compute_segmentation_map`,
а `runner.install_gpu_lock` пізніше обгортає те, що там лежить, локом
GPU-фази. Тому цей патч ставиться ДО лока — інакше він обгорнув би лок і
зламав серіалізацію форвардів між шардами.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Версія, на якій тіло функції звірене зі стоком побайтно
#: (`seg_resize_verify`). Це патч чужого коду: інша версія kraken може змінити
#: сам ланцюг трансформів, і розбіжність буде тихою — інша нарізка рядків без
#: помилки в лозі. Тому — гучне попередження й гард імен.
TESTED_KRAKEN = "7.0.2"
TESTED_TORCHVISION = "0.28.0"


def _warn_version_drift() -> None:
    import importlib.metadata as md

    for pkg, tested in (("kraken", TESTED_KRAKEN), ("torchvision", TESTED_TORCHVISION)):
        try:
            have = md.version(pkg)
        except Exception:
            continue
        if have.split("+")[0] != tested:
            print(f"[seg-resize] ⚠ {pkg} {have}, а патч звірений на {tested}. "
                  f"Перезвір: <інтерпретатор рушіїв> -m "
                  f"nyshporka.htr.patches.seg_resize_verify <тека справи> 5",
                  flush=True)


def split_transforms(transforms):
    """Голова (до `PILToTensor`) і хвіст (від нього) ланцюга трансформів.

    Винесено окремо, щоб верифікатор порівнював рівно ті самі два ланцюги, що
    вживає патч, а не свою реконструкцію.
    """
    import torchvision.transforms as tf
    from torchvision.transforms import v2

    tf_idx, _ = next(filter(lambda x: isinstance(x[1], v2.PILToTensor),
                            enumerate(transforms.transforms)))
    head = tf.Compose(transforms.transforms[:tf_idx])
    tail = tf.Compose(transforms.transforms[tf_idx:])
    return head, tail


def compute_segmentation_map_once(im, mask: Optional[Any] = None, model=None,
                                  device: str = "cpu",
                                  autocast: bool = False) -> dict[str, Any]:
    """Копія `blla.compute_segmentation_map` (kraken 7.0.2) з одним ресайзом."""
    import numpy as np
    import torch
    import torch.nn.functional as F
    from kraken.lib import dataset
    from kraken.lib.exceptions import KrakenInputException
    from kraken.lib.util import is_bitonal

    if model.input[1] == 1 and model.one_channel_mode == '1' and not is_bitonal(im):
        logger.warning('Running binary model on non-binary input image '
                       '(mode {}). This will result in severely degraded '
                       'performance'.format(im.mode))

    model.eval()
    model.to(device)

    batch, channels, height, width = model.input
    padding = model.user_metadata['hyper_params']['padding'] if 'padding' in model.user_metadata['hyper_params'] else (0, 0)
    if isinstance(padding, int):
        padding = (padding,) * 4
    elif len(padding) == 2:
        padding = (padding[0], padding[0], padding[1], padding[1])

    transforms = dataset.ImageInputTransforms(batch, height, width, channels, padding, valid_norm=False)
    head, tail = split_transforms(transforms)
    # ── єдина відмінність від стоку: голову ланцюга прикладаємо ОДИН раз ──
    scaled = head(im)
    scal_im = np.array(scaled.convert('L'))
    tensor_im = tail(scaled)
    if mask:
        if mask.mode != '1' and not is_bitonal(mask):
            logger.error('Mask is not bitonal')
            raise KrakenInputException('Mask is not bitonal')
        mask = mask.convert('1')
        if mask.size != im.size:
            logger.error('Mask size {mask.size} doesn\'t match image size {im.size}')
            raise KrakenInputException('Mask size {mask.size} doesn\'t match image size {im.size}')
        logger.info('Masking enabled in segmenter.')
        tensor_im[~transforms(mask).bool()] = 0

    with torch.autocast(device_type=device.split(":")[0], enabled=autocast):
        with torch.no_grad():
            logger.debug('Running network forward pass')
            o, _ = model.nn(tensor_im.unsqueeze(0).to(device))

    logger.debug('Upsampling network output')
    o = F.interpolate(o, size=scal_im.shape)
    o = torch.sigmoid(o)
    padding = [pad if pad else None for pad in padding]
    padding[1] = -padding[1] if padding[1] else None
    padding[3] = -padding[3] if padding[3] else None
    o = o[:, :, padding[2]:padding[3], padding[0]:padding[1]]
    scal_im = scal_im[padding[2]:padding[3], padding[0]:padding[1]]

    o = o.squeeze().cpu().float().numpy()
    scale = np.divide(im.size, o.shape[:0:-1])

    bounding_regions = model.user_metadata['bounding_regions'] if 'bounding_regions' in model.user_metadata else None
    return {'heatmap': o,
            'cls_map': model.user_metadata['class_mapping'],
            'bounding_regions': bounding_regions,
            'scale': scale,
            'scal_im': scal_im}


def install(verbose: bool = False) -> bool:
    """Підмінити `blla.compute_segmentation_map`.

    `blla.segment` резолвить це ім'я як глобал модуля на кожен виклик, тож
    підміни в самому `blla` досить. Оригінал зберігається поруч — його бере
    верифікатор і той, кому треба відкотити на ходу.
    """
    from kraken import blla

    if getattr(blla, "_seg_resize_installed", False):
        return True
    _warn_version_drift()
    missing = [n for n in ("compute_segmentation_map", "segment")
               if not hasattr(blla, n)]
    if missing:
        raise RuntimeError(
            f"seg_resize: у kraken.blla немає {missing} — версія пакета "
            f"розійшлася з патчем (звірено на {TESTED_KRAKEN})")
    blla._compute_segmentation_map_orig = blla.compute_segmentation_map
    blla.compute_segmentation_map = compute_segmentation_map_once
    blla._seg_resize_installed = True
    if verbose:
        print("[seg-resize] один LANCZOS-ресайз кадру замість двох "
              "(scal_im і тензор — з того самого PIL)", flush=True)
    return True
