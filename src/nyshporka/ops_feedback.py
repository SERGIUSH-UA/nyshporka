"""📮 Операція відгуку: вада, ідея чи питання — на портал, з консолі чи від агента.

Логіка й межі — `share/feedback.py`. Тут — конверт і одне правило:

🔴 **Без `confirm` нічого не відправляється.** Перший виклик віддає перегляд —
рівно те, що піде на портал (очищений текст, діагностика, вкладення з
розмірами). Агент показує його людині й шле вдруге з `confirm: true` лише після
її згоди; консоль робить те саме вікном підтвердження.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


class FeedbackArgs(BaseModel):
    text: str = Field(description="що сталося чи що пропонуєте — словами людини")
    kind: str = Field(default="vada", description="vada (вада) | ideia (ідея) | pytannia (питання)")
    files: list[str] = Field(default_factory=list,
                             description="шляхи до знімків (PNG/JPEG/WebP) чи журналів "
                                         "(.txt/.log/.json), до 5")
    images: list[dict[str, Any]] = Field(default_factory=list,
                                         description="знімки з консолі: {name, data base64}")
    logs: list[dict[str, Any]] = Field(default_factory=list,
                                       description="журнали з консолі: {name, text}")
    diag: bool = Field(default=True, description="додати версію, систему й спосіб установки")
    lang: str = Field(default="", description="мова консолі")
    confirm: bool = Field(default=False, description="справді надіслати; без нього — лише "
                                                     "перегляд того, що піде")

    def only_shows(self) -> bool:
        return not self.confirm


@op("feedback.send", summary="Відгук про Нишпорку на портал: текст, знімки, журнали",
    args=FeedbackArgs, mutates=True, section="core",
    when="надіслати відгук про Нишпорку чи повідомити про ваду")
def feedback_send(a: FeedbackArgs) -> Envelope:
    """Перегляд без `confirm`, відправка з ним. Лише з входом у Супрягу."""
    from nyshporka.share import feedback as F

    try:
        att = F.prepare(a.files, a.images, a.logs)
        shown = F.preview(a.text, a.kind, att, a.diag, a.lang)
    except F.FeedbackError as exc:
        return fail(str(exc))
    if not a.confirm:
        env = ok({**shown, "sent": False})
        if not shown["logged_in"]:
            env.warn("login", "щоб надіслати, потрібен вхід у Супрягу: nysh share login")
        env.warn("confirm", "це лише перегляд: покажіть його людині, і після її згоди "
                            "повторіть із confirm: true", level="agent")
        return env
    try:
        sent = F.send(a.text, a.kind, att, a.diag, a.lang)
    except F.FeedbackError as exc:
        return fail(str(exc))
    return ok({**shown, **sent, "sent": True})
