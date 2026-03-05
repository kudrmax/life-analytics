ACTIVITYWATCH_METRICS = {
    'active_screen_time': {
        'name': 'Активное экранное время',
        'description': 'Время за компьютером без AFK (мин)',
        'value_type': 'number',
        'config_fields': [],
    },
    'total_screen_time': {
        'name': 'Общее экранное время',
        'description': 'Всё время с активными окнами (мин)',
        'value_type': 'number',
        'config_fields': [],
    },
    'first_activity': {
        'name': 'Начало активности',
        'description': 'Время первого события за день',
        'value_type': 'time',
        'config_fields': [],
    },
    'last_activity': {
        'name': 'Конец активности',
        'description': 'Время последнего события за день',
        'value_type': 'time',
        'config_fields': [],
    },
    'afk_time': {
        'name': 'Время AFK',
        'description': 'Суммарное время AFK между началом и концом активности (мин)',
        'value_type': 'number',
        'config_fields': [],
    },
    'longest_session': {
        'name': 'Самая длинная сессия',
        'description': 'Самый длинный не-AFK период (мин)',
        'value_type': 'number',
        'config_fields': [],
    },
    'context_switches': {
        'name': 'Переключения контекста',
        'description': 'Смена активного приложения (шт)',
        'value_type': 'number',
        'config_fields': [],
    },
    'break_count': {
        'name': 'Количество перерывов',
        'description': 'AFK-периоды > 5 мин (шт)',
        'value_type': 'number',
        'config_fields': [],
    },
    'unique_apps': {
        'name': 'Уникальных приложений',
        'description': 'Разных приложений за день (шт)',
        'value_type': 'number',
        'config_fields': [],
    },
    'category_time': {
        'name': 'Время в категории',
        'description': 'Суммарное время приложений из категории (мин)',
        'value_type': 'number',
        'config_fields': ['category_id'],
    },
    'app_time': {
        'name': 'Время в приложении',
        'description': 'Время в конкретном приложении (мин)',
        'value_type': 'number',
        'config_fields': ['app_name'],
    },
}

ACTIVITYWATCH_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" xmlns="http://www.w3.org/2000/svg"><rect width="24" height="24" rx="4" fill="#6c5ce7"/><circle cx="12" cy="12" r="7" stroke="#fff" stroke-width="1.5" fill="none"/><path d="M12 8v4.5l3 1.5" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>'
