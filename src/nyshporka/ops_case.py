"""🖼 Перегляд самої справи: аркуші, а не прочитане.

Дві операції, які закривають найпростіше питання застосунку — «покажи, що я
завантажив». Досі відповіді на нього не було зовсім: подивитись на скан можна
було лише через прогін, тобто спершу прочитай справу рушієм (година чи ніч), і
аж тоді дивись.

🔴 Окремо від `page.view` навмисно. Та операція показує сторінку прогону: вона
знає рамки рядків, кут, яким користувався рушій, і вирізку одного рядка. Тут
нічого цього немає й бути не може — прогону ще нема. Спроба обслужити обидва
випадки однією операцією зробила б перегляд неможливим доти, доки справу не
прочитано, а це рівно та вада, яку операції нижче й прибирають.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


class CaseFramesArgs(BaseModel):
    case: str = Field(description="тека справи (шлях у просторі)")


class CaseFrameArgs(BaseModel):
    case: str = Field(description="тека справи (шлях у просторі)")
    frame: str = Field(description="кадр: ім'я файлу або `pdf:<номер>`")
    width: int = Field(default=1400, ge=200, le=3000,
                       description="ширина показу; більше — довше й важче")


# `agent=False`: це питання ока, і воно вже має свою поверхню. Агент дивиться
# на рядок через `page.view` — там вирізка з рамкою й текстом, тобто те, чим
# судять; суцільне гортання аркушів моделі не додає нічого, зате з'їдає слот у
# переліку, який вона мусить дочитувати цілком при кожному виклику.
@op("case.frames", summary="Аркуші справи: що взагалі можна погортати",
    args=CaseFramesArgs, section="material", agent=False)
def case_frames(a: CaseFramesArgs) -> Envelope:
    """Перелік аркушів справи — кадрами або сторінками PDF.

    🔴 Порожньої відповіді без причини тут не буває. «Аркушів немає» означає
    щонайменше три різні речі — тека порожня, кадри лежать у підтеках, матеріал
    лише в PDF, який нічим відкрити, — і кожна лікується по-своєму.
    """
    from nyshporka.cases.frames import FrameError, listing

    try:
        data = listing(a.case)
    except FrameError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")

    env = ok(data)
    if data["kind"] == "pdf":
        env.warn("pdf_only",
                 "справа лежить одним PDF: кадрів на диску немає, сторінки "
                 "рендеряться на льоту. Рушій читає саме кадри, тож перед "
                 "читанням справу треба буде розібрати на сторінки")
    elif data.get("pdfs"):
        # 🔴 Обидва роди матеріалу поруч — не привід мовчати. Сторінки PDF це
        # інший рендер того самого, і їхня нумерація не зобов'язана збігатися
        # з кадрами; показуючи кадри, кажемо про це прямо.
        env.warn("both_kinds",
                 f"поруч лежить ще й PDF ({', '.join(data['pdfs'][:3])}). "
                 f"Показано кадри — саме їх читатиме рушій; сторінки PDF "
                 f"можуть бути іншим рендером із іншою нумерацією")
    return env


@op("case.frame", summary="Подивитись на аркуш справи", args=CaseFrameArgs,
    section="material", agent=False)
def case_frame(a: CaseFrameArgs) -> Envelope:
    """Один аркуш у вигляді, придатному для перегляду.

    ⚠ Це не доказ-файл: показане тут ніде не зберігається й ні на що не
    посилається. Доказ кладеться в постійне сховище окремою дією.
    """
    from nyshporka.cases.frames import FrameError, render

    try:
        return ok(render(a.case, a.frame, a.width))
    except FrameError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")
