# Шкала с подписями: вертикальный layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Когда у scale-метрики заданы подписи к значениям (`labels` непуст), переключать раскладку с горизонтальных чипсин на вертикальный список, чтобы длинные подписи помещались целиком.

**Architecture:** Только frontend. Две правки: добавить CSS-модификатор `.scale-buttons.vertical` в `frontend/css/style.css`, добавить ветку в `renderScale()` в `frontend/js/app.js`, которая навешивает этот класс при наличии подписей. Никаких новых компонентов, никаких изменений HTML-структуры. Все существующие состояния (`hover`, `.active`) работают без правок.

**Tech Stack:** Vanilla JS, plain CSS (без сборки). Изменения подхватываются обычным refresh браузера — frontend сервится через `python -m http.server` (локально) или nginx (Docker).

**Spec:** `docs/superpowers/specs/2026-05-02-scale-vertical-labels-design.md`

---

## Task 1: Добавить CSS-правила вертикальной раскладки

**Files:**
- Modify: `frontend/css/style.css` (после строки 505, перед блоком `/* ─── Bool Buttons ─── */`)

CSS правится первым: до правки JS никакой элемент класс `vertical` ещё не получает, так что добавление правил безопасно — ничего не меняет визуально, пока шаг 2 не активирует ветку.

- [ ] **Step 1: Добавить правила для `.scale-buttons.vertical`**

Открыть `frontend/css/style.css`, найти блок:

```css
.scale-btn:hover { border-color: var(--accent); }
.scale-btn.active {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
}
```

Сразу после закрывающей `}` блока `.scale-btn.active` (после строки 505) вставить:

```css

.scale-buttons.vertical { flex-direction: column; }
.scale-buttons.vertical .scale-btn {
    flex: 0 0 auto;
    white-space: normal;
    text-align: left;
    text-overflow: clip;
    padding: 10px 12px;
    line-height: 1.35;
}
```

**Что эти правила делают:**
- `flex-direction: column` — переключаем основную ось контейнера с горизонтальной на вертикальную, кнопки укладываются друг под друга.
- `flex: 0 0 auto` — отменяем `flex: 1` из базового `.scale-btn`. В column-layout `flex: 1` пытался бы растягивать кнопки по высоте — нам нужно, чтобы каждая занимала ровно столько, сколько требует её содержимое.
- `white-space: normal` — снимаем `white-space: nowrap` из базового стиля, длинные подписи переносятся на следующую строку.
- `text-align: left` — текст слева, читается естественно (центрирование длинных предложений выглядит плохо).
- `text-overflow: clip` — отключаем многоточие из базового стиля; теперь нет нужды обрезать, потому что текст переносится.
- `padding: 10px 12px` — заменяем базовый `padding: 8px 2px` (рассчитанный на узкие чипсины с цифрой) на нормальные горизонтальные отступы.
- `line-height: 1.35` — комфортный межстрочный интервал для многострочных подписей.

- [ ] **Step 2: Не коммитить пока — переходим к Task 2**

Изменения в CSS без правки JS не имеют эффекта (никто не выставляет класс `vertical`). Чтобы коммит был осмысленным и проверяемым, делаем всё одним коммитом в конце Task 2.

---

## Task 2: Активировать ветку в `renderScale()`

**Files:**
- Modify: `frontend/js/app.js` (строки 1393–1402, функция `renderScale`)

- [ ] **Step 1: Заменить функцию `renderScale`**

Открыть `frontend/js/app.js`. Найти функцию (начинается со строки 1393):

```js
function renderScale(val, min, max, step, labels) {
    let buttons = '';
    for (let v = min; v <= max; v += step) {
        const rawText = (labels && labels[String(v)]) ? labels[String(v)] : v;
        const text = (labels && labels[String(v)]) ? _escapeHtml(String(rawText)) : v;
        const title = (labels && labels[String(v)]) ? ` title="${v}"` : '';
        buttons += `<button class="scale-btn ${val === v ? 'active' : ''}" data-value="${v}"${title}>${text}</button>`;
    }
    return `<div class="scale-buttons">${buttons}</div>`;
}
```

Заменить её на:

```js
function renderScale(val, min, max, step, labels) {
    let buttons = '';
    for (let v = min; v <= max; v += step) {
        const rawText = (labels && labels[String(v)]) ? labels[String(v)] : v;
        const text = (labels && labels[String(v)]) ? _escapeHtml(String(rawText)) : v;
        const title = (labels && labels[String(v)]) ? ` title="${v}"` : '';
        buttons += `<button class="scale-btn ${val === v ? 'active' : ''}" data-value="${v}"${title}>${text}</button>`;
    }
    const hasLabels = labels && Object.keys(labels).length > 0;
    return `<div class="scale-buttons${hasLabels ? ' vertical' : ''}">${buttons}</div>`;
}
```

Изменено только две последние строки: добавлена константа `hasLabels`, и в строке возврата добавляется ` vertical`, если есть подписи. Логика тела цикла не тронута.

- [ ] **Step 2: Ручная проверка в браузере**

Запустить стэк (если ещё не запущен):

```bash
cd /Users/maxos/PythonProjects/life-analytics
make up
```

Открыть `http://localhost:3000`, залогиниться, перейти на страницу "Сегодня".

Проверить четыре сценария на странице "Сегодня":

1. **Шкала без подписей** (числовая, например 1–5): кнопки идут горизонтально, как раньше. Чипсины узкие, под цифрами. Изменений нет.

2. **Шкала с длинными подписями** (например, 1–3, где подписи — целые предложения вроде "тяжело встать, туман в голове, хочется лечь"): кнопки идут вертикально, каждая на свою строку, длинная подпись переносится на 2–3 строки внутри кнопки, текст выровнен по левому краю.

3. **Шкала с короткими подписями** (например, 1–5, где подписи — "Плохо", "Норм", "Хорошо"): кнопки идут вертикально, по одной строке на значение.

4. **Партиальные подписи** (например, шкала 1–5, подписи только у 1 и 3): кнопки идут вертикально; у значений без подписи показывается просто цифра (как и раньше — это поведение цикла, не layout).

Во всех вертикальных сценариях:
- Тап на кнопку сохраняет значение (проверить: значение записалось, кнопка получила `.active`-стиль с акцентным фоном).
- Hover выделяет border акцентным цветом.

Если что-то отображается криво (например, кнопки слиплись без отступа, текст обрезается, активный стиль выглядит странно) — стоп, разобраться, что не так в правилах CSS.

Если нет шкалы с подписями для теста — создать тестовую через "Настройки → Метрики → ➕": тип "Шкала", выставить min=1, max=3, в полях подписей вписать длинные предложения. Сохранить. Открыть "Сегодня".

- [ ] **Step 3: Коммит обеих правок одним коммитом**

```bash
cd /Users/maxos/PythonProjects/life-analytics
git add frontend/css/style.css frontend/js/app.js
git commit -m "$(cat <<'EOF'
feat: vertical layout for scale metrics with labels

When scale_config.labels has at least one entry, render the scale as a
vertical list so that long labels (full sentences) wrap and remain
readable instead of being truncated with ellipsis. Numeric scales without
labels keep the existing horizontal chip layout.
EOF
)"
```

Один коммит, потому что без обеих правок изменение нерабочее: CSS без JS-класса не активируется, JS без CSS-правил даст просто горизонтальные кнопки с лишним классом.

---

## Task 3 (опционально): Добавить регрессионный тест на бэкенде

**Files:**
- (Возможно) Modify: один из существующих API-тестов scale-метрик в `backend/tests/`

Это чисто frontend-изменение — поведение API не меняется, поле `labels` уже передаётся (см. использование `m.scale_labels` в `app.js` на строках 1268, 1302, 1333). На бэкенде нечего тестировать дополнительно.

Если в ходе ручной проверки (Task 2 Step 2) обнаружится, что API не возвращает `labels` в каком-то из эндпоинтов (`GET /api/daily/...`, `GET /api/metrics/...`) — это **отдельный баг**, фиксируем его отдельным коммитом с тестом, репортим пользователю по правилу "Bugs & Broken Tests" из CLAUDE.md. Не смешиваем с этой правкой.

Если ручная проверка прошла без сюрпризов — Task 3 пропускаем.

---

## Финальная проверка

- [ ] Frontend перезагружен в браузере (Cmd+Shift+R), кэш очищен.
- [ ] Все четыре сценария из Task 2 Step 2 работают корректно.
- [ ] Никаких регрессий: числовые шкалы без подписей выглядят и работают как до правки.
- [ ] Активный/hover/tap-стили работают одинаково в обеих раскладках.
- [ ] Коммит создан, рабочее дерево чистое (`git status`).
