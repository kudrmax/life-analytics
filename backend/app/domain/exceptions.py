"""Domain exceptions — чистые Python-исключения бизнес-логики.

Не зависят от fastapi, asyncpg или любых фреймворков.
Маппинг на HTTP-коды выполняется в main.py через exception handlers.
"""


class DomainError(Exception):
    """Базовое исключение домена."""


class EntityNotFoundError(DomainError):
    """Сущность не найдена или не принадлежит текущему пользователю."""

    def __init__(self, entity: str, entity_id: int) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} not found")


class DuplicateEntityError(DomainError):
    """Попытка создать дублирующую сущность."""

    def __init__(self, entity: str, field: str, value: str) -> None:
        self.entity = entity
        self.field = field
        self.value = value
        super().__init__(f"{entity} with {field} '{value}' already exists")


class InvalidOperationError(DomainError):
    """Невалидная бизнес-операция (400)."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class ConflictError(DomainError):
    """Конфликт бизнес-правила (409)."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)
