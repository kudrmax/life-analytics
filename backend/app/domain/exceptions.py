"""Domain exceptions — типизированные ошибки бизнес-логики."""

from fastapi import HTTPException


class EntityNotFoundError(HTTPException):
    """Сущность не найдена или не принадлежит текущему пользователю."""

    def __init__(self, entity: str, entity_id: int) -> None:
        super().__init__(status_code=404, detail=f"{entity} not found")
        self.entity = entity
        self.entity_id = entity_id


class DuplicateEntityError(HTTPException):
    """Попытка создать дублирующую сущность."""

    def __init__(self, entity: str, field: str, value: str) -> None:
        super().__init__(status_code=409, detail=f"{entity} with {field} '{value}' already exists")


class InvalidOperationError(HTTPException):
    """Невалидная бизнес-операция."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=400, detail=detail)
