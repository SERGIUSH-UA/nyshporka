"""🏛 Архівний шар: знання про фонди, каталоги справ, завантажувачі.

Поки що тут лише пак архівів — декларативне знання, винесене з коду в дані.
Каталог справ і читання прогонів переїжджають наступними.
"""

from nyshporka.archives.pack import ArchivesPack, Fond, Repository, active, load

__all__ = ["ArchivesPack", "Fond", "Repository", "active", "load"]
