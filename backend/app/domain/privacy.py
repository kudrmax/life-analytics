"""Privacy helpers — маскировка приватных метрик.

Чистые функции без зависимостей от фреймворков.
"""

PRIVATE_MASK: str = "***"
PRIVATE_ICON: str = "🔒"


def mask_name(name: str, is_private: bool, privacy_mode: bool) -> str:
    return PRIVATE_MASK if (is_private and privacy_mode) else name


def mask_icon(icon: str, is_private: bool, privacy_mode: bool) -> str:
    return PRIVATE_ICON if (is_private and privacy_mode) else icon


def is_blocked(is_private: bool, privacy_mode: bool) -> bool:
    return is_private and privacy_mode
