DEFAULT_METRICS = [
    # Сон и энергия
    {
        "id": "wake_up_time",
        "name": "Время подъёма",
        "category": "Сон",
        "type": "time",
        "frequency": "daily",
        "config": {},
    },
    {
        "id": "bedtime",
        "name": "Время отбоя",
        "category": "Сон",
        "type": "time",
        "frequency": "daily",
        "config": {},
    },
    {
        "id": "sleep_quality",
        "name": "Качество сна",
        "category": "Сон",
        "type": "scale",
        "frequency": "daily",
        "config": {"min": 1, "max": 5},
    },
    # Многоразовые
    {
        "id": "mood",
        "name": "Настроение",
        "category": "Ментальное",
        "type": "scale",
        "frequency": "multiple",
        "config": {"min": 1, "max": 5},
    },
    {
        "id": "energy",
        "name": "Уровень энергии",
        "category": "Ментальное",
        "type": "scale",
        "frequency": "multiple",
        "config": {"min": 1, "max": 5},
    },
    {
        "id": "stress",
        "name": "Уровень стресса",
        "category": "Ментальное",
        "type": "scale",
        "frequency": "multiple",
        "config": {"min": 1, "max": 5},
    },
    # Здоровье
    {
        "id": "workout",
        "name": "Тренировка",
        "category": "Здоровье",
        "type": "compound",
        "frequency": "daily",
        "config": {
            "fields": [
                {"name": "done", "type": "boolean", "label": "Была тренировка"},
                {
                    "name": "type",
                    "type": "enum",
                    "label": "Тип",
                    "options": ["кардио", "силовая", "растяжка", "йога", "другое"],
                    "condition": "done == true",
                },
            ]
        },
    },
    {
        "id": "alcohol",
        "name": "Алкоголь",
        "category": "Здоровье",
        "type": "compound",
        "frequency": "daily",
        "config": {
            "fields": [
                {"name": "consumed", "type": "boolean", "label": "Пил алкоголь"},
                {
                    "name": "amount",
                    "type": "number",
                    "label": "Порций",
                    "condition": "consumed == true",
                },
            ]
        },
    },
    {
        "id": "fastfood",
        "name": "Фастфуд",
        "category": "Здоровье",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },
    {
        "id": "meals",
        "name": "Приёмов пищи",
        "category": "Здоровье",
        "type": "number",
        "frequency": "daily",
        "config": {"min": 0, "max": 10},
    },
    {
        "id": "coffee",
        "name": "Кофе",
        "category": "Здоровье",
        "type": "number",
        "frequency": "daily",
        "config": {"min": 0, "max": 20, "label": "чашек"},
    },
    # Социальное
    {
        "id": "friends",
        "name": "Виделся с друзьями",
        "category": "Социальное",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },
    {
        "id": "new_people",
        "name": "Новые знакомства",
        "category": "Социальное",
        "type": "number",
        "frequency": "daily",
        "config": {"min": 0},
    },
    # Ментальное (daily)
    {
        "id": "meditation",
        "name": "Медитация",
        "category": "Ментальное",
        "type": "compound",
        "frequency": "daily",
        "config": {
            "fields": [
                {"name": "done", "type": "boolean", "label": "Медитировал"},
                {
                    "name": "minutes",
                    "type": "number",
                    "label": "Минут",
                    "condition": "done == true",
                },
            ]
        },
    },
    {
        "id": "reading",
        "name": "Чтение",
        "category": "Ментальное",
        "type": "compound",
        "frequency": "daily",
        "config": {
            "fields": [
                {"name": "done", "type": "boolean", "label": "Читал"},
                {
                    "name": "minutes",
                    "type": "number",
                    "label": "Минут",
                    "condition": "done == true",
                },
            ]
        },
    },
    # Продуктивность
    {
        "id": "productive_hours",
        "name": "Часов продуктивной работы",
        "category": "Продуктивность",
        "type": "number",
        "frequency": "daily",
        "config": {"min": 0, "max": 24, "step": 0.5},
    },
    {
        "id": "screen_time",
        "name": "Экранное время",
        "category": "Продуктивность",
        "type": "number",
        "frequency": "daily",
        "config": {"min": 0, "max": 24, "step": 0.5, "label": "часов"},
    },
    {
        "id": "todoist_planned",
        "name": "Задач запланировано",
        "category": "Продуктивность",
        "type": "number",
        "frequency": "daily",
        "source": "todoist",
        "config": {},
    },
    {
        "id": "todoist_completed",
        "name": "Задач выполнено",
        "category": "Продуктивность",
        "type": "number",
        "frequency": "daily",
        "source": "todoist",
        "config": {},
    },
    {
        "id": "gcal_events",
        "name": "Событий в календаре",
        "category": "Продуктивность",
        "type": "number",
        "frequency": "daily",
        "source": "google_calendar",
        "config": {},
    },
    # Финансы
    {
        "id": "big_expense",
        "name": "Крупные траты",
        "category": "Финансы",
        "type": "compound",
        "frequency": "daily",
        "config": {
            "fields": [
                {"name": "had", "type": "boolean", "label": "Были крупные траты"},
                {
                    "name": "amount",
                    "type": "number",
                    "label": "Сумма",
                    "condition": "had == true",
                },
            ]
        },
    },
    {
        "id": "impulse_buy",
        "name": "Импульсивные покупки",
        "category": "Финансы",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },
]
