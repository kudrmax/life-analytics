# Default Metrics Archive

These 23 metrics were previously auto-created for new users on registration (from `backend/app/seed.py`). Removed during type system simplification.

## Metrics

| # | Slug | Name | Category | Type |
|---|------|------|----------|------|
| 1 | first_alarm | Встал с первого будильника | Утро | bool |
| 2 | cold_shower | Холодные процедуры | Утро | bool |
| 3 | morning_exercise | Зарядка | Утро | bool |
| 4 | top_tasks | Топ задачи на день | Планирование | number (bool_number) |
| 5 | timeblocking_planned | Распланировал день | Планирование | bool |
| 6 | timeblocking_followed | Следовал тайм-блокингу | Планирование | scale |
| 7 | procrastination | Уровень прокрастинации | Продуктивность | scale |
| 8 | entertainment_content | Развлекательный контент | Продуктивность | scale |
| 9 | wake_up_time | Время подъёма | Сон | time |
| 10 | bedtime | Время отбоя | Сон | time |
| 11 | sleep_quality | Качество сна | Сон | scale |
| 12 | mood | Настроение | Состояние | scale (3x/day) |
| 13 | energy | Уровень энергии | Состояние | scale (3x/day) |
| 14 | stress | Уровень стресса | Состояние | scale (3x/day) |
| 15 | coffee | Кофе | Здоровье | number (bool_number) |
| 16 | alcohol | Алкоголь | Здоровье | bool |
| 17 | restaurant | Еда в ресторане | Здоровье | bool |
| 18 | audiobooks | Аудиокниги | Саморазвитие | bool |
| 19 | books | Книги | Саморазвитие | bool |
| 20 | friends_offline | Виделся с друзьями | Социальное | bool |
| 21 | new_people | Новые знакомства | Социальное | number (bool_number) |
| 22 | blog_work | Работал над блогом | Цели | scale |
| 23 | diploma_work | Работал над дипломом | Цели | scale |
