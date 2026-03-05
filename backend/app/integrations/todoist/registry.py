TODOIST_METRICS = {
    'completed_tasks_count': {
        'name': 'Количество выполненных задач',
        'value_type': 'number',
        'config_fields': [],
    },
    'filter_tasks_count': {
        'name': 'Задачи в фильтре (по имени)',
        'value_type': 'number',
        'config_fields': ['filter_name'],
    },
    'query_tasks_count': {
        'name': 'Задачи по запросу',
        'value_type': 'number',
        'config_fields': ['filter_query'],
    },
}

TODOIST_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" xmlns="http://www.w3.org/2000/svg"><rect width="24" height="24" rx="4" fill="#e44332"/><path d="M6 8.5l3.5 2 5-3 3.5 2" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/><path d="M6 12.5l3.5 2 5-3 3.5 2" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/><path d="M6 16.5l3.5 2 5-3 3.5 2" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>'
