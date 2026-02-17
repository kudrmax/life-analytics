DEFAULT_METRICS = [
    # ═══════════════════════════════════════════════════════
    # Утренние рутины
    # ═══════════════════════════════════════════════════════
    {
        "id": "first_alarm",
        "name": "Встал с первого будильника",
        "category": "Утро",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },
    {
        "id": "cold_shower",
        "name": "Холодные процедуры",
        "category": "Утро",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },
    {
        "id": "morning_exercise",
        "name": "Зарядка",
        "category": "Утро",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },

    # ═══════════════════════════════════════════════════════
    # Планирование и продуктивность
    # ═══════════════════════════════════════════════════════
    {
        "id": "top_tasks",
        "name": "Топ задачи на день",
        "category": "Планирование",
        "type": "compound",
        "frequency": "daily",
        "config": {
            "fields": [
                {"name": "planned", "type": "boolean", "label": "Поставил топ задачи"},
                {
                    "name": "count",
                    "type": "number",
                    "label": "Количество задач",
                    "condition": "planned == true",
                },
            ]
        },
    },
    {
        "id": "timeblocking_planned",
        "name": "Распланировал день",
        "category": "Планирование",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },
    {
        "id": "timeblocking_followed",
        "name": "Следовал тайм-блокингу",
        "category": "Планирование",
        "type": "scale",
        "frequency": "daily",
        "config": {"min": 1, "max": 5},
    },
    {
        "id": "procrastination",
        "name": "Уровень прокрастинации",
        "category": "Продуктивность",
        "type": "scale",
        "frequency": "daily",
        "config": {"min": 1, "max": 5},
    },
    {
        "id": "entertainment_content",
        "name": "Развлекательный контент",
        "category": "Продуктивность",
        "type": "scale",
        "frequency": "daily",
        "config": {"min": 1, "max": 5},
    },

    # ═══════════════════════════════════════════════════════
    # Сон
    # ═══════════════════════════════════════════════════════
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

    # ═══════════════════════════════════════════════════════
    # Ментальное состояние (3 раза в день)
    # ═══════════════════════════════════════════════════════
    {
        "id": "mood",
        "name": "Настроение",
        "category": "Состояние",
        "type": "scale",
        "frequency": "multiple",
        "config": {"min": 1, "max": 5},
    },
    {
        "id": "energy",
        "name": "Уровень энергии",
        "category": "Состояние",
        "type": "scale",
        "frequency": "multiple",
        "config": {"min": 1, "max": 5},
    },
    {
        "id": "stress",
        "name": "Уровень стресса",
        "category": "Состояние",
        "type": "scale",
        "frequency": "multiple",
        "config": {"min": 1, "max": 5},
    },

    # ═══════════════════════════════════════════════════════
    # Здоровье
    # ═══════════════════════════════════════════════════════
    {
        "id": "coffee",
        "name": "Кофе",
        "category": "Здоровье",
        "type": "number",
        "frequency": "daily",
        "config": {"min": 0, "max": 10, "label": "чашек"},
    },
    {
        "id": "alcohol",
        "name": "Алкоголь",
        "category": "Здоровье",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },
    {
        "id": "restaurant",
        "name": "Еда в ресторане",
        "category": "Здоровье",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },

    # ═══════════════════════════════════════════════════════
    # Саморазвитие
    # ═══════════════════════════════════════════════════════
    {
        "id": "audiobooks",
        "name": "Аудиокниги",
        "category": "Саморазвитие",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },
    {
        "id": "books",
        "name": "Книги",
        "category": "Саморазвитие",
        "type": "boolean",
        "frequency": "daily",
        "config": {},
    },

    # ═══════════════════════════════════════════════════════
    # Социальное
    # ═══════════════════════════════════════════════════════
    {
        "id": "friends_offline",
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
        "config": {"min": 0, "max": 20},
    },

    # ═══════════════════════════════════════════════════════
    # Цели
    # ═══════════════════════════════════════════════════════
    {
        "id": "blog_work",
        "name": "Работал над блогом",
        "category": "Цели",
        "type": "scale",
        "frequency": "daily",
        "config": {"min": 1, "max": 5},
    },
    {
        "id": "diploma_work",
        "name": "Работал над дипломом",
        "category": "Цели",
        "type": "scale",
        "frequency": "daily",
        "config": {"min": 1, "max": 5},
    },
]
