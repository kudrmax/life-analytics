DEFAULT_METRICS = [
    # ═══════════════════════════════════════════════════════
    # Утренние рутины
    # ═══════════════════════════════════════════════════════
    {
        "slug": "first_alarm",
        "name": "Встал с первого будильника",
        "category": "Утро",
        "type": "bool",
        "config": {},
    },
    {
        "slug": "cold_shower",
        "name": "Холодные процедуры",
        "category": "Утро",
        "type": "bool",
        "config": {},
    },
    {
        "slug": "morning_exercise",
        "name": "Зарядка",
        "category": "Утро",
        "type": "bool",
        "config": {},
    },

    # ═══════════════════════════════════════════════════════
    # Планирование и продуктивность
    # ═══════════════════════════════════════════════════════
    {
        "slug": "top_tasks",
        "name": "Топ задачи на день",
        "category": "Планирование",
        "type": "number",
        "config": {
            "display_mode": "bool_number",
            "bool_label": "Поставил топ задачи",
            "number_label": "Количество задач",
            "min_value": 0,
            "max_value": 20,
            "step": 1,
        },
    },
    {
        "slug": "timeblocking_planned",
        "name": "Распланировал день",
        "category": "Планирование",
        "type": "bool",
        "config": {},
    },
    {
        "slug": "timeblocking_followed",
        "name": "Следовал тайм-блокингу",
        "category": "Планирование",
        "type": "scale",
        "config": {"min_value": 1, "max_value": 5},
    },
    {
        "slug": "procrastination",
        "name": "Уровень прокрастинации",
        "category": "Продуктивность",
        "type": "scale",
        "config": {"min_value": 1, "max_value": 5},
    },
    {
        "slug": "entertainment_content",
        "name": "Развлекательный контент",
        "category": "Продуктивность",
        "type": "scale",
        "config": {"min_value": 1, "max_value": 5},
    },

    # ═══════════════════════════════════════════════════════
    # Сон
    # ═══════════════════════════════════════════════════════
    {
        "slug": "wake_up_time",
        "name": "Время подъёма",
        "category": "Сон",
        "type": "time",
        "config": {},
    },
    {
        "slug": "bedtime",
        "name": "Время отбоя",
        "category": "Сон",
        "type": "time",
        "config": {},
    },
    {
        "slug": "sleep_quality",
        "name": "Качество сна",
        "category": "Сон",
        "type": "scale",
        "config": {"min_value": 1, "max_value": 5},
    },

    # ═══════════════════════════════════════════════════════
    # Ментальное состояние (3 раза в день)
    # ═══════════════════════════════════════════════════════
    {
        "slug": "mood",
        "name": "Настроение",
        "category": "Состояние",
        "type": "scale",
        "measurements_per_day": 3,
        "measurement_labels": ["Утро", "День", "Вечер"],
        "config": {"min_value": 1, "max_value": 5},
    },
    {
        "slug": "energy",
        "name": "Уровень энергии",
        "category": "Состояние",
        "type": "scale",
        "measurements_per_day": 3,
        "measurement_labels": ["Утро", "День", "Вечер"],
        "config": {"min_value": 1, "max_value": 5},
    },
    {
        "slug": "stress",
        "name": "Уровень стресса",
        "category": "Состояние",
        "type": "scale",
        "measurements_per_day": 3,
        "measurement_labels": ["Утро", "День", "Вечер"],
        "config": {"min_value": 1, "max_value": 5},
    },

    # ═══════════════════════════════════════════════════════
    # Здоровье
    # ═══════════════════════════════════════════════════════
    {
        "slug": "coffee",
        "name": "Кофе",
        "category": "Здоровье",
        "type": "number",
        "config": {
            "display_mode": "bool_number",
            "bool_label": "Пил кофе",
            "number_label": "Количество чашек",
            "min_value": 0,
            "max_value": 20,
            "step": 1,
        },
    },
    {
        "slug": "alcohol",
        "name": "Алкоголь",
        "category": "Здоровье",
        "type": "bool",
        "config": {},
    },
    {
        "slug": "restaurant",
        "name": "Еда в ресторане",
        "category": "Здоровье",
        "type": "bool",
        "config": {},
    },

    # ═══════════════════════════════════════════════════════
    # Саморазвитие
    # ═══════════════════════════════════════════════════════
    {
        "slug": "audiobooks",
        "name": "Аудиокниги",
        "category": "Саморазвитие",
        "type": "bool",
        "config": {},
    },
    {
        "slug": "books",
        "name": "Книги",
        "category": "Саморазвитие",
        "type": "bool",
        "config": {},
    },

    # ═══════════════════════════════════════════════════════
    # Социальное
    # ═══════════════════════════════════════════════════════
    {
        "slug": "friends_offline",
        "name": "Виделся с друзьями",
        "category": "Социальное",
        "type": "bool",
        "config": {},
    },
    {
        "slug": "new_people",
        "name": "Новые знакомства",
        "category": "Социальное",
        "type": "number",
        "config": {
            "display_mode": "bool_number",
            "bool_label": "Были новые знакомства",
            "number_label": "Количество человек",
            "min_value": 0,
            "max_value": 50,
            "step": 1,
        },
    },

    # ═══════════════════════════════════════════════════════
    # Цели
    # ═══════════════════════════════════════════════════════
    {
        "slug": "blog_work",
        "name": "Работал над блогом",
        "category": "Цели",
        "type": "scale",
        "config": {"min_value": 1, "max_value": 5},
    },
    {
        "slug": "diploma_work",
        "name": "Работал над дипломом",
        "category": "Цели",
        "type": "scale",
        "config": {"min_value": 1, "max_value": 5},
    },
]
