// ─── State ───
let currentDate = todayStr();
let metrics = [];
let currentPage = 'today';
let currentUser = null;
let isAuthenticated = false;

function todayStr() {
    return new Date().toISOString().slice(0, 10);
}

// ─── Theme Management ───
const THEME_KEY = 'la_theme';

function initTheme() {
    const savedTheme = localStorage.getItem(THEME_KEY) || 'dark';
    applyTheme(savedTheme);
}

function applyTheme(theme) {
    if (theme === 'light') {
        document.documentElement.setAttribute('data-theme', 'light');
        updateThemeIcon('☀️');
    } else {
        document.documentElement.removeAttribute('data-theme');
        updateThemeIcon('🌙');
    }
    localStorage.setItem(THEME_KEY, theme);
}

function updateThemeIcon(icon) {
    const themeIcon = document.querySelector('.theme-icon');
    if (themeIcon) {
        themeIcon.textContent = icon;
    }
}

function toggleTheme() {
    const currentTheme = localStorage.getItem(THEME_KEY) || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme);
}

function setupThemeToggle() {
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }
}

// ─── Init ───
document.addEventListener('DOMContentLoaded', async () => {
    initTheme();
    setupThemeToggle();
    setupNav();
    if (window.lucide) lucide.createIcons();
    await checkAuth();

    if (isAuthenticated) {
        await loadMetrics();
        navigateTo('today');
    } else {
        navigateTo('login');
    }
});

async function checkAuth() {
    const token = api.getToken();
    if (!token) {
        isAuthenticated = false;
        return;
    }

    try {
        currentUser = await api.getCurrentUser();
        isAuthenticated = true;
    } catch (error) {
        isAuthenticated = false;
        api.clearToken();
    }
}

function setupNav() {
    document.querySelectorAll('[data-page]').forEach(btn => {
        btn.addEventListener('click', () => navigateTo(btn.dataset.page));
    });
}

async function loadMetrics() {
    metrics = await api.getMetrics(true);
}

function navigateTo(page) {
    currentPage = page;

    // Hide nav for auth pages
    const nav = document.querySelector('nav');
    if (nav) {
        nav.style.display = (page === 'login' || page === 'register') ? 'none' : '';
    }

    document.querySelectorAll('[data-page]').forEach(b => b.classList.toggle('active', b.dataset.page === page));
    const main = document.getElementById('main');

    switch (page) {
        case 'login': renderLogin(main); break;
        case 'register': renderRegister(main); break;
        case 'today': renderToday(main); break;
        case 'history': renderHistory(main); break;
        case 'dashboard': renderDashboard(main); break;
        case 'settings': renderSettings(main); break;
    }
}

// Make navigateTo global for API error handling
window.navigateTo = navigateTo;

// ─── Auth Pages ───
function renderLogin(container) {
    container.innerHTML = `
        <div class="auth-container">
            <div class="auth-card">
                <h2>Life Analytics</h2>
                <p class="auth-subtitle">Вход в систему</p>
                <form id="login-form" class="auth-form">
                    <label class="form-label">
                        <span class="label-text">Имя пользователя</span>
                        <input id="login-username" class="form-input" required autocomplete="username">
                    </label>
                    <label class="form-label">
                        <span class="label-text">Пароль</span>
                        <input id="login-password" type="password" class="form-input" required autocomplete="current-password">
                    </label>
                    <div id="login-error" class="error-message"></div>
                    <button type="submit" class="btn-primary btn-full">Войти</button>
                </form>
                <div class="auth-footer">
                    Нет аккаунта? <a href="#" id="goto-register">Зарегистрироваться</a>
                </div>
            </div>
        </div>
    `;

    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;
        const errorEl = document.getElementById('login-error');

        try {
            errorEl.textContent = '';
            const response = await api.login(username, password);
            api.setToken(response.access_token, response.username);
            isAuthenticated = true;
            currentUser = { username: response.username };
            await loadMetrics();
            navigateTo('today');
        } catch (error) {
            errorEl.textContent = error.message || 'Неверные учетные данные';
        }
    });

    document.getElementById('goto-register').addEventListener('click', (e) => {
        e.preventDefault();
        navigateTo('register');
    });
}

function renderRegister(container) {
    container.innerHTML = `
        <div class="auth-container">
            <div class="auth-card">
                <h2>Life Analytics</h2>
                <p class="auth-subtitle">Регистрация</p>
                <form id="register-form" class="auth-form">
                    <label class="form-label">
                        <span class="label-text">Имя пользователя</span>
                        <input id="register-username" class="form-input" required autocomplete="username" minlength="3" maxlength="30">
                        <span class="field-hint">От 3 до 30 символов</span>
                    </label>
                    <label class="form-label">
                        <span class="label-text">Пароль</span>
                        <input id="register-password" type="password" class="form-input" required autocomplete="new-password" minlength="8">
                        <span class="field-hint">Минимум 8 символов</span>
                    </label>
                    <label class="form-label">
                        <span class="label-text">Подтверждение пароля</span>
                        <input id="register-password2" type="password" class="form-input" required autocomplete="new-password">
                    </label>
                    <div id="register-error" class="error-message"></div>
                    <button type="submit" class="btn-primary btn-full">Зарегистрироваться</button>
                </form>
                <div class="auth-footer">
                    Уже есть аккаунт? <a href="#" id="goto-login">Войти</a>
                </div>
            </div>
        </div>
    `;

    document.getElementById('register-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('register-username').value.trim();
        const password = document.getElementById('register-password').value;
        const password2 = document.getElementById('register-password2').value;
        const errorEl = document.getElementById('register-error');

        if (username.length < 3 || username.length > 30) {
            errorEl.textContent = 'Имя пользователя должно быть от 3 до 30 символов';
            return;
        }

        if (password.length < 8) {
            errorEl.textContent = 'Пароль должен содержать минимум 8 символов';
            return;
        }

        if (password !== password2) {
            errorEl.textContent = 'Пароли не совпадают';
            return;
        }

        try {
            errorEl.textContent = '';
            const response = await api.register(username, password);
            api.setToken(response.access_token, response.username);
            isAuthenticated = true;
            currentUser = { username: response.username };
            await loadMetrics();
            navigateTo('today');
        } catch (error) {
            errorEl.textContent = error.message || 'Ошибка регистрации';
        }
    });

    document.getElementById('goto-login').addEventListener('click', (e) => {
        e.preventDefault();
        navigateTo('login');
    });
}

// ─── Today Page ───
async function renderToday(container) {
    container.innerHTML = `
        <div class="day-header">
            <div class="day-progress">
                <div class="progress-track">
                    <div class="progress-fill" id="progress-fill" style="width: 0%"></div>
                </div>
                <span class="progress-count" id="progress-count">0%</span>
            </div>
            <button class="go-today-btn" id="go-today" style="display:none" title="Вернуться к сегодня">
                <i data-lucide="undo-2"></i>
            </button>
            <div class="day-nav">
                <button class="day-nav-arrow" id="prev-day">
                    <i data-lucide="chevron-left"></i>
                </button>
                <span class="day-nav-date" id="current-date-label"></span>
                <button class="day-nav-arrow" id="next-day">
                    <i data-lucide="chevron-right"></i>
                </button>
            </div>
        </div>
        <div id="metrics-form"></div>
    `;

    if (window.lucide) lucide.createIcons();

    document.getElementById('prev-day').onclick = () => { changeDay(-1); };
    document.getElementById('next-day').onclick = () => { changeDay(1); };
    document.getElementById('go-today').onclick = () => { currentDate = todayStr(); renderTodayForm(); };

    await renderTodayForm();
}

function changeDay(delta) {
    const d = new Date(currentDate);
    d.setDate(d.getDate() + delta);
    currentDate = d.toISOString().slice(0, 10);
    renderTodayForm();
}

async function renderTodayForm() {
    document.getElementById('current-date-label').textContent = formatDate(currentDate);
    const goTodayBtn = document.getElementById('go-today');
    if (goTodayBtn) {
        goTodayBtn.style.display = (currentDate === todayStr()) ? 'none' : '';
    }
    const summary = await api.getDailySummary(currentDate);
    const form = document.getElementById('metrics-form');

    // Group by category
    const categories = {};
    for (const m of summary.metrics) {
        categories[m.category] = categories[m.category] || [];
        categories[m.category].push(m);
    }

    let html = '';
    for (const [cat, items] of Object.entries(categories)) {
        html += `<div class="category"><h3>${cat}</h3>`;
        for (const m of items) {
            html += renderMetricInput(m);
        }
        html += '</div>';
    }
    form.innerHTML = html;
    attachInputHandlers();

    // Update progress bar
    let total = 0;
    let filled = 0;
    for (const m of summary.metrics) {
        if (m.slots && m.slots.length > 0) {
            total += m.slots.length;
            filled += m.slots.filter(s => s.entry !== null).length;
        } else {
            total += 1;
            filled += m.entry !== null ? 1 : 0;
        }
    }
    const pct = total > 0 ? Math.round((filled / total) * 100) : 0;
    document.getElementById('progress-count').textContent = `${pct}%`;
    const progressFill = document.getElementById('progress-fill');
    progressFill.style.width = `${pct}%`;
    progressFill.classList.toggle('complete', filled === total && total > 0);
}

function renderMetricInput(m) {
    // Multi-slot metric
    if (m.slots && m.slots.length > 0) {
        const allFilled = m.slots.every(s => s.entry !== null);
        const filledClass = allFilled ? 'filled' : '';

        let slotsHtml = '<div class="multiple-entry">';
        for (const slot of m.slots) {
            const entry = slot.entry;
            const val = entry ? entry.value : null;
            const entryId = entry ? entry.id : null;

            let input;
            if (m.type === 'time') input = renderTime(val);
            else if (m.type === 'number') input = renderNumber(val);
            else if (m.type === 'scale') {
                const sMin = (entry && entry.scale_min != null) ? entry.scale_min : m.scale_min;
                const sMax = (entry && entry.scale_max != null) ? entry.scale_max : m.scale_max;
                const sStep = (entry && entry.scale_step != null) ? entry.scale_step : m.scale_step;
                input = renderScale(val, sMin, sMax, sStep);
            }
            else input = renderBoolean(val);

            const clearBtn = entry
                ? `<button class="period-clear-btn" data-clear-entry="${entryId}" title="Очистить">&times;</button>`
                : '';

            slotsHtml += `<div class="metric-slot" data-slot-id="${slot.slot_id}" data-entry-id="${entryId || ''}">
                <div class="period-header">
                    <span class="period-label">${slot.label}</span>
                    ${clearBtn}
                </div>
                <div class="metric-input">${input}</div>
            </div>`;
        }
        slotsHtml += '</div>';

        return `<div class="metric-card ${filledClass}" data-metric-id="${m.metric_id}" data-metric-type="${m.type}" data-entry-id="">
            <div class="metric-header">
                <label class="metric-label">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</label>
            </div>
            ${slotsHtml}
        </div>`;
    }

    // Single entry metric (no slots)
    const entry = m.entry;
    const val = entry ? entry.value : null;
    const entryId = entry ? entry.id : null;

    const isFilled = !!entry;
    const filledClass = isFilled ? 'filled' : '';

    let input;
    if (m.type === 'time') input = renderTime(val);
    else if (m.type === 'number') input = renderNumber(val);
    else if (m.type === 'scale') input = renderScale(val, m.scale_min, m.scale_max, m.scale_step);
    else input = renderBoolean(val);

    const clearBtn = entry
        ? `<button class="metric-clear-btn" data-clear-entry="${entryId}" title="Очистить">&times;</button>`
        : '';

    return `<div class="metric-card ${filledClass}" data-metric-id="${m.metric_id}" data-metric-type="${m.type}" data-entry-id="${entryId || ''}">
        <div class="metric-header">
            <label class="metric-label">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</label>
            ${clearBtn}
        </div>
        <div class="metric-input">${input}</div>
    </div>`;
}

function renderBoolean(val) {
    const current = val;
    return `<div class="bool-buttons">
        <button class="bool-btn ${current === true ? 'active yes' : ''}" data-value="true">Да</button>
        <button class="bool-btn ${current === false ? 'active no' : ''}" data-value="false">Нет</button>
    </div>`;
}

function renderNumber(val) {
    const hasFilled = val !== null && val !== undefined;
    const displayVal = hasFilled ? val : '';
    const zeroBtn = hasFilled ? '' : '<button class="number-zero-btn" data-action="set-zero">Установить 0</button>';
    return `<div class="number-input">
        <button class="number-btn" data-action="decrement">&minus;</button>
        <input type="number" class="number-value-input" value="${displayVal}"
               placeholder="—" inputmode="numeric" step="1">
        <button class="number-btn" data-action="increment">&plus;</button>
        ${zeroBtn}
    </div>`;
}

function renderTime(val) {
    if (val) {
        return `<button type="button" class="time-picker-btn has-value" data-action="pick-time">${val}</button>`;
    }
    return `<button type="button" class="time-picker-btn" data-action="pick-time">Указать время</button>`;
}

function renderScale(val, min, max, step) {
    let buttons = '';
    for (let v = min; v <= max; v += step) {
        buttons += `<button class="scale-btn ${val === v ? 'active' : ''}" data-value="${v}">${v}</button>`;
    }
    return `<div class="scale-buttons">${buttons}</div>`;
}

// ─── Event Handlers ───
async function handleNumberChange(e) {
    const input = e.target;
    if (!input.classList.contains('number-value-input')) return;

    const card = input.closest('.metric-card');
    if (!card) return;

    const metricId = card.dataset.metricId;
    const slotEl = input.closest('.metric-slot');
    const entryId = slotEl ? slotEl.dataset.entryId : card.dataset.entryId;
    const slotId = slotEl ? slotEl.dataset.slotId : null;

    const raw = input.value.trim();
    if (raw === '') {
        // Empty input — delete entry to return to null
        if (entryId) {
            try {
                await api.deleteEntry(parseInt(entryId));
                await renderTodayForm();
            } catch (error) { alert('Ошибка: ' + error.message); }
        }
        return;
    }

    const parsed = parseInt(raw);
    if (isNaN(parsed)) {
        input.value = '';
        return;
    }

    try {
        await saveDaily(metricId, entryId, parsed, slotId);
        await renderTodayForm();
    } catch (error) { alert('Ошибка: ' + error.message); }
}

function attachInputHandlers() {
    const form = document.getElementById('metrics-form');
    if (form.dataset.handlersAttached) return;
    form.dataset.handlersAttached = 'true';
    form.addEventListener('click', handleFormClick);
    form.addEventListener('change', handleNumberChange);
}

async function handleFormClick(e) {
    const btn = e.target;
    const card = btn.closest('.metric-card');
    if (!card) return;

    const metricId = card.dataset.metricId;
    const slotEl = btn.closest('.metric-slot');
    const entryId = slotEl ? slotEl.dataset.entryId : card.dataset.entryId;
    const slotId = slotEl ? slotEl.dataset.slotId : null;

    // Clear metric entry
    if (btn.dataset.clearEntry) {
        try {
            const clearEntryId = parseInt(btn.dataset.clearEntry);
            await api.deleteEntry(clearEntryId);
            await renderTodayForm();
        } catch (error) {
            alert('Ошибка при удалении: ' + error.message);
        }
        return;
    }

    // Boolean buttons
    if (btn.classList.contains('bool-btn')) {
        try {
            const boolVal = btn.dataset.value === 'true';
            await saveDaily(metricId, entryId, boolVal, slotId);
            await renderTodayForm();
        } catch (error) {
            alert('Ошибка: ' + error.message);
        }
        return;
    }

    // Scale buttons
    if (btn.classList.contains('scale-btn')) {
        try {
            await saveDaily(metricId, entryId, parseInt(btn.dataset.value), slotId);
            await renderTodayForm();
        } catch (error) {
            alert('Ошибка: ' + error.message);
        }
        return;
    }

    // Number "=0" button
    if (btn.dataset.action === 'set-zero') {
        try {
            await saveDaily(metricId, entryId, 0, slotId);
            await renderTodayForm();
        } catch (error) { alert('Ошибка: ' + error.message); }
        return;
    }

    // Number +/- buttons
    if (btn.classList.contains('number-btn')) {
        const container = slotEl || card;
        const input = container.querySelector('.number-value-input');
        let currentVal = input.value !== '' ? parseInt(input.value) : 0;
        if (isNaN(currentVal)) currentVal = 0;
        const newVal = currentVal + (btn.dataset.action === 'increment' ? 1 : -1);
        try {
            await saveDaily(metricId, entryId, newVal, slotId);
            await renderTodayForm();
        } catch (error) { alert('Ошибка: ' + error.message); }
        return;
    }

    // Time picker
    const timeTrigger = btn.closest('[data-action="pick-time"]');
    if (timeTrigger) {
        if (document.querySelector('.cp-overlay')) return; // prevent multiple
        const currentVal = timeTrigger.classList.contains('has-value') ? timeTrigger.textContent.trim() : '';
        showClockPicker(currentVal, async (newVal) => {
            try {
                await saveDaily(metricId, entryId, newVal, slotId);
                await renderTodayForm();
            } catch (error) {
                alert('Ошибка: ' + error.message);
            }
        });
        return;
    }
}

async function saveDaily(metricId, entryId, value, slotId) {
    if (entryId) {
        await api.updateEntry(parseInt(entryId), { value });
    } else {
        const payload = {
            metric_id: parseInt(metricId),
            date: currentDate,
            value,
        };
        if (slotId) payload.slot_id = parseInt(slotId);
        await api.createEntry(payload);
    }
}

// ─── History Page ───
let historyDate = todayStr();

async function renderHistory(container) {
    historyDate = todayStr();
    container.innerHTML = `
        <div class="day-header">
            <div class="day-progress">
                <div class="progress-track">
                    <div class="progress-fill" id="hist-progress-fill" style="width: 0%"></div>
                </div>
                <span class="progress-count" id="hist-progress-count">0%</span>
            </div>
            <button class="go-today-btn" id="hist-go-today" style="display:none" title="Вернуться к сегодня">
                <i data-lucide="undo-2"></i>
            </button>
            <div class="day-nav">
                <button class="day-nav-arrow" id="hist-prev-day">
                    <i data-lucide="chevron-left"></i>
                </button>
                <span class="day-nav-date" id="hist-date-label"></span>
                <button class="day-nav-arrow" id="hist-next-day">
                    <i data-lucide="chevron-right"></i>
                </button>
            </div>
        </div>
        <div id="history-calendar" class="calendar-grid"></div>
        <div id="day-detail"></div>
    `;

    if (window.lucide) lucide.createIcons();

    document.getElementById('hist-prev-day').onclick = () => changeHistoryDay(-1);
    document.getElementById('hist-next-day').onclick = () => changeHistoryDay(1);
    document.getElementById('hist-go-today').onclick = () => { historyDate = todayStr(); updateHistoryView(); };

    await updateHistoryView();
}

function changeHistoryDay(delta) {
    const d = new Date(historyDate);
    d.setDate(d.getDate() + delta);
    historyDate = d.toISOString().slice(0, 10);
    updateHistoryView();
}

async function updateHistoryView() {
    // Update header
    document.getElementById('hist-date-label').textContent = formatDate(historyDate);
    const goBtn = document.getElementById('hist-go-today');
    if (goBtn) goBtn.style.display = (historyDate === todayStr()) ? 'none' : '';

    // Render calendar for the month of historyDate
    renderCalendar(historyDate.slice(0, 7));

    // Load and show day detail + progress
    await showDayDetail(historyDate);
}

function renderCalendar(yearMonth) {
    const [year, month] = yearMonth.split('-').map(Number);
    const daysInMonth = new Date(year, month, 0).getDate();
    const grid = document.getElementById('history-calendar');

    const dayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
    let html = dayNames.map(d => `<div class="cal-header">${d}</div>`).join('');

    const firstDay = (new Date(year, month - 1, 1).getDay() + 6) % 7;
    for (let i = 0; i < firstDay; i++) html += '<div class="cal-empty"></div>';

    for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const isTodayCls = dateStr === todayStr() ? 'today' : '';
        const isSelected = dateStr === historyDate ? 'selected' : '';
        html += `<div class="cal-day ${isTodayCls} ${isSelected}" data-date="${dateStr}">${d}</div>`;
    }
    grid.innerHTML = html;

    grid.querySelectorAll('.cal-day').forEach(el => {
        el.addEventListener('click', () => {
            historyDate = el.dataset.date;
            updateHistoryView();
        });
    });
}

async function showDayDetail(date) {
    const detail = document.getElementById('day-detail');
    const summary = await api.getDailySummary(date);

    // Update progress bar
    let total = 0;
    let filled = 0;
    for (const m of summary.metrics) {
        if (m.slots && m.slots.length > 0) {
            total += m.slots.length;
            filled += m.slots.filter(s => s.entry !== null).length;
        } else {
            total += 1;
            filled += m.entry !== null ? 1 : 0;
        }
    }
    const pct = total > 0 ? Math.round((filled / total) * 100) : 0;
    const progressCount = document.getElementById('hist-progress-count');
    const progressFill = document.getElementById('hist-progress-fill');
    if (progressCount) progressCount.textContent = `${pct}%`;
    if (progressFill) {
        progressFill.style.width = `${pct}%`;
        progressFill.classList.toggle('complete', filled === total && total > 0);
    }

    // Build detail HTML
    let html = `<div class="day-summary">`;
    let hasAny = false;

    for (const m of summary.metrics) {
        if (m.slots && m.slots.length > 0) {
            const filledSlots = m.slots.filter(s => s.entry !== null);
            if (filledSlots.length === 0) continue;
            hasAny = true;
            for (const s of filledSlots) {
                const valStr = _formatEntryValue(s.entry, m.type);
                html += `<div class="summary-row"><span class="summary-label">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name} — ${s.label}</span><span class="summary-value">${valStr}</span></div>`;
            }
        } else {
            if (!m.entry) continue;
            hasAny = true;
            const valStr = _formatEntryValue(m.entry, m.type);
            html += `<div class="summary-row"><span class="summary-label">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</span><span class="summary-value">${valStr}</span></div>`;
        }
    }

    if (!hasAny) {
        html += `<div class="summary-row"><span class="summary-label" style="color:var(--text-dim)">Нет записей</span></div>`;
    }

    html += '</div>';
    detail.innerHTML = html;
}

function _formatEntryValue(entry, type) {
    if (type === 'time') {
        return entry.value || '—';
    } else if (type === 'number' || type === 'scale') {
        return entry.value !== null && entry.value !== undefined ? String(entry.value) : '—';
    } else {
        return entry.value ? 'Да' : 'Нет';
    }
}

// ─── Dashboard Page ───
async function renderDashboard(container) {
    const end = todayStr();
    const start = daysAgo(30);

    container.innerHTML = `
        <h2>Дашборд</h2>
        <div class="dashboard-controls">
            <label>Период: <input type="date" id="dash-start" value="${start}"> — <input type="date" id="dash-end" value="${end}"></label>
            <button class="btn-small" id="dash-refresh">Обновить</button>
        </div>
        <div id="streaks-section"></div>
        <div id="trends-section"></div>
        <div id="correlation-section"></div>
    `;

    document.getElementById('dash-refresh').addEventListener('click', () => {
        loadDashboard(
            document.getElementById('dash-start').value,
            document.getElementById('dash-end').value
        );
    });

    await loadDashboard(start, end);
}

async function loadDashboard(start, end) {
    // Streaks
    const streaks = await api.getStreaks();
    const streaksEl = document.getElementById('streaks-section');
    if (streaks.streaks.length > 0) {
        let html = '<h3>Стрики</h3><div class="streaks">';
        for (const s of streaks.streaks) {
            const streakMetric = metrics.find(mt => mt.id === s.metric_id);
            const streakIcon = streakMetric?.icon ? streakMetric.icon + ' ' : '';
            html += `<div class="streak-card"><span class="streak-count">${s.current_streak}</span><span class="streak-label">${streakIcon}${s.metric_name}</span><span class="streak-unit">дней подряд</span></div>`;
        }
        html += '</div>';
        streaksEl.innerHTML = html;
    } else {
        streaksEl.innerHTML = '';
    }

    // Trends — show for all bool metrics (True=1, False=0)
    const trendsEl = document.getElementById('trends-section');
    let trendsHtml = '<h3>Тренды</h3><div class="trends">';
    for (const m of metrics) {
        const trend = await api.getTrends(m.id, start, end);
        if (trend.points && trend.points.length > 0) {
            trendsHtml += `<div class="trend-card"><h4>${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</h4><div class="mini-chart" data-points='${JSON.stringify(trend.points)}'></div></div>`;
        }
    }
    trendsHtml += '</div>';
    trendsEl.innerHTML = trendsHtml;
    renderMiniCharts();

    // Correlation selector
    const corrEl = document.getElementById('correlation-section');
    let corrHtml = '<h3>Корреляции</h3><div class="corr-controls">';
    corrHtml += `<select id="corr-a">${metrics.map(m => `<option value="${m.id}">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</option>`).join('')}</select>`;
    corrHtml += ` vs `;
    corrHtml += `<select id="corr-b">${metrics.map(m => `<option value="${m.id}">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</option>`).join('')}</select>`;
    corrHtml += ` <button class="btn-small" id="corr-calc">Вычислить</button>`;
    corrHtml += '</div><div id="corr-result"></div>';
    corrEl.innerHTML = corrHtml;

    document.getElementById('corr-calc').addEventListener('click', async () => {
        const a = document.getElementById('corr-a').value;
        const b = document.getElementById('corr-b').value;
        const result = await api.getCorrelations(a, b, start, end);
        const el = document.getElementById('corr-result');
        if (result.correlation !== null && result.correlation !== undefined) {
            const strength = Math.abs(result.correlation) > 0.7 ? 'сильная' : Math.abs(result.correlation) > 0.3 ? 'средняя' : 'слабая';
            el.innerHTML = `<div class="corr-value">r = ${result.correlation} (${strength}, ${result.data_points} дней)</div>`;
        } else {
            el.innerHTML = `<div class="corr-value">${result.message || 'Недостаточно данных'}</div>`;
        }
    });
}

function renderMiniCharts() {
    document.querySelectorAll('.mini-chart').forEach(el => {
        const points = JSON.parse(el.dataset.points);
        if (points.length === 0) return;

        const values = points.map(p => p.value);
        const max = Math.max(...values);
        const min = Math.min(...values);
        const range = max - min || 1;
        const w = el.offsetWidth || 200;
        const h = 60;

        let svg = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`;
        const step = w / Math.max(points.length - 1, 1);

        let pathD = '';
        for (let i = 0; i < values.length; i++) {
            const x = i * step;
            const y = h - ((values[i] - min) / range) * (h - 10) - 5;
            pathD += (i === 0 ? 'M' : 'L') + `${x.toFixed(1)},${y.toFixed(1)}`;
        }
        svg += `<path d="${pathD}" fill="none" stroke="var(--accent)" stroke-width="2"/>`;
        svg += '</svg>';
        el.innerHTML = svg;
    });
}

// ─── Settings Page ───
async function renderSettings(container, { archiveOpen = false } = {}) {
    const allMetrics = await api.getMetrics(false);
    let html = '<div class="settings-header">';
    html += `<div class="user-info"><i data-lucide="user"></i><span>${localStorage.getItem('la_username') || 'Unknown'}</span></div>`;
    html += '<button class="btn-small btn-logout" id="logout-btn"><i data-lucide="log-out"></i><span>Выйти</span></button>';
    html += '</div>';
    html += '<h2>Настройки метрик</h2>';
    html += '<div class="settings-actions">';
    html += '<button class="btn-primary" id="add-metric"><i data-lucide="plus"></i> Новая метрика</button>';
    html += '<button class="btn-small" id="export-btn"><i data-lucide="download"></i> Экспорт</button>';
    html += '<button class="btn-small" id="import-btn"><i data-lucide="upload"></i> Импорт</button>';
    html += '</div>';
    html += '<input type="file" id="import-file" accept=".zip" style="display:none">';

    const activeMetrics = allMetrics.filter(m => m.enabled);
    const archivedMetrics = allMetrics.filter(m => !m.enabled);

    const categories = {};
    for (const m of activeMetrics) {
        categories[m.category] = categories[m.category] || [];
        categories[m.category].push(m);
    }

    for (const [cat, items] of Object.entries(categories)) {
        html += `<div class="category"><h3>${cat}</h3>`;
        for (const m of items) {
            const slotsBadge = m.slots && m.slots.length > 0
                ? `<span class="setting-slots">${m.slots.length}x</span>` : '';
            const typeIcon = (m.type === 'time' ? '<i data-lucide="clock"></i> Время'
                : m.type === 'number' ? '<i data-lucide="hash"></i> Число'
                : m.type === 'scale' ? '<i data-lucide="sliders-horizontal"></i> Шкала'
                : '<i data-lucide="toggle-left"></i> Да/Нет') + slotsBadge;
            html += `<div class="setting-row">
                <div class="setting-info">
                    <span class="setting-name">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</span>
                    <span class="setting-type">${typeIcon}</span>
                </div>
                <div class="setting-actions">
                    <button class="btn-icon edit-btn" data-metric="${m.id}"><i data-lucide="pencil"></i></button>
                    <button class="btn-icon archive-btn" data-metric="${m.id}"><i data-lucide="archive"></i></button>
                    <button class="btn-icon delete-btn btn-icon-danger" data-metric="${m.id}"><i data-lucide="trash-2"></i></button>
                </div>
            </div>`;
        }
        html += '</div>';
    }

    if (archivedMetrics.length > 0) {
        html += `<div class="archive-section">
            <button class="archive-header" id="archive-toggle">
                <span class="archive-header-text"><i data-lucide="archive"></i> Архив (${archivedMetrics.length})</span>
                <i data-lucide="${archiveOpen ? 'chevron-up' : 'chevron-down'}" class="archive-chevron"></i>
            </button>
            <div class="archive-content" id="archive-content" style="display:${archiveOpen ? 'block' : 'none'}">`;
        for (const m of archivedMetrics) {
            const slotsBadge = m.slots && m.slots.length > 0
                ? `<span class="setting-slots">${m.slots.length}x</span>` : '';
            const typeIcon = (m.type === 'time' ? '<i data-lucide="clock"></i> Время'
                : m.type === 'number' ? '<i data-lucide="hash"></i> Число'
                : m.type === 'scale' ? '<i data-lucide="sliders-horizontal"></i> Шкала'
                : '<i data-lucide="toggle-left"></i> Да/Нет') + slotsBadge;
            html += `<div class="setting-row archived-row">
                <div class="setting-info">
                    <span class="setting-name archived">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</span>
                    <span class="setting-type">${typeIcon}</span>
                </div>
                <div class="setting-actions">
                    <button class="btn-icon unarchive-btn" data-metric="${m.id}"><i data-lucide="archive-restore"></i></button>
                    <button class="btn-icon delete-btn btn-icon-danger" data-metric="${m.id}"><i data-lucide="trash-2"></i></button>
                </div>
            </div>`;
        }
        html += '</div></div>';
    }
    container.innerHTML = html;
    if (window.lucide) lucide.createIcons();

    document.getElementById('logout-btn').addEventListener('click', () => {
        api.logout();
        isAuthenticated = false;
        currentUser = null;
        navigateTo('login');
    });

    document.getElementById('add-metric').addEventListener('click', showAddMetricModal);

    // Export button
    document.getElementById('export-btn').addEventListener('click', async () => {
        try {
            const token = api.getToken();
            const response = await fetch(`${api.API_BASE}/api/export/csv`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (!response.ok) throw new Error('Export failed');

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `life_analytics_${localStorage.getItem('la_username')}_${new Date().toISOString().slice(0,10)}.zip`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);

            alert('Данные экспортированы!');
        } catch (error) {
            alert('Ошибка экспорта: ' + error.message);
        }
    });

    // Import button
    document.getElementById('import-btn').addEventListener('click', () => {
        document.getElementById('import-file').click();
    });

    document.getElementById('import-file').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        try {
            const formData = new FormData();
            formData.append('file', file);

            const token = api.getToken();
            const response = await fetch(`${api.API_BASE}/api/export/import`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: formData
            });

            if (!response.ok) throw new Error('Import failed');

            const result = await response.json();

            let message = 'Импорт завершён!\n\n';
            message += `Метрики: создано ${result.metrics.imported}, обновлено ${result.metrics.updated}\n`;
            message += `Записи: импортировано ${result.entries.imported}, пропущено ${result.entries.skipped}\n`;

            if (result.metrics.errors.length > 0 || result.entries.errors.length > 0) {
                message += '\nОшибки:\n';
                if (result.metrics.errors.length > 0) {
                    message += 'Метрики:\n' + result.metrics.errors.join('\n') + '\n';
                }
                if (result.entries.errors.length > 0) {
                    message += 'Записи:\n' + result.entries.errors.join('\n');
                }
            }

            alert(message);

            await loadMetrics();
            navigateTo('today');
        } catch (error) {
            alert('Ошибка импорта: ' + error.message);
        } finally {
            e.target.value = '';
        }
    });

    // Edit button listeners
    container.querySelectorAll('.edit-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const metricId = btn.dataset.metric;
            const metric = allMetrics.find(m => m.id === parseInt(metricId));
            if (metric) {
                showEditMetricModal(metric);
            }
        });
    });

    container.querySelectorAll('.archive-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const metricId = btn.dataset.metric;
            try {
                await api.updateMetric(metricId, { enabled: false });
                await renderSettings(container);
            } catch (error) {
                alert('Ошибка: ' + error.message);
            }
        });
    });

    container.querySelectorAll('.unarchive-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const metricId = btn.dataset.metric;
            try {
                await api.updateMetric(metricId, { enabled: true });
                await renderSettings(container, { archiveOpen: true });
            } catch (error) {
                alert('Ошибка: ' + error.message);
            }
        });
    });

    const archiveToggle = document.getElementById('archive-toggle');
    if (archiveToggle) {
        archiveToggle.addEventListener('click', () => {
            const content = document.getElementById('archive-content');
            const chevron = archiveToggle.querySelector('.archive-chevron');
            if (content.style.display === 'none') {
                content.style.display = 'block';
                chevron.setAttribute('data-lucide', 'chevron-up');
            } else {
                content.style.display = 'none';
                chevron.setAttribute('data-lucide', 'chevron-down');
            }
            if (window.lucide) lucide.createIcons();
        });
    }

    container.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const metricId = btn.dataset.metric;
            if (confirm('Удалить метрику?')) {
                try {
                    await api.deleteMetric(metricId);
                    await renderSettings(container);
                } catch (error) {
                    alert('Ошибка: ' + error.message);
                }
            }
        });
    });
}

function showMetricModal(mode = 'create', existingMetric = null) {
    const isEdit = mode === 'edit';
    const title = isEdit ? 'Редактировать метрику' : 'Создать метрику';
    const buttonText = isEdit ? 'Сохранить изменения' : 'Создать метрику';
    const currentType = existingMetric?.type || 'bool';

    function getScaleParams() {
        const minEl = document.getElementById('nm-scale-min');
        const maxEl = document.getElementById('nm-scale-max');
        const stepEl = document.getElementById('nm-scale-step');
        return {
            min: minEl ? parseInt(minEl.value) || 1 : (existingMetric?.scale_min || 1),
            max: maxEl ? parseInt(maxEl.value) || 5 : (existingMetric?.scale_max || 5),
            step: stepEl ? parseInt(stepEl.value) || 1 : (existingMetric?.scale_step || 1),
        };
    }

    function previewInputHtml(type) {
        if (type === 'time') {
            return `<button type="button" class="time-picker-btn">Указать время</button>`;
        }
        if (type === 'number') {
            return `<div class="number-input">
                <button class="number-btn" data-action="decrement">&minus;</button>
                <input type="number" class="number-value-input" value="" placeholder="—" inputmode="numeric" step="1">
                <button class="number-btn" data-action="increment">&plus;</button>
                <button class="number-zero-btn" data-action="set-zero">Установить 0</button>
            </div>`;
        }
        if (type === 'scale') {
            const sp = getScaleParams();
            let buttons = '';
            for (let v = sp.min; v <= sp.max; v += sp.step) {
                buttons += `<button class="scale-btn" data-value="${v}">${v}</button>`;
            }
            return `<div class="scale-buttons">${buttons}</div>`;
        }
        return `<div class="bool-buttons">
            <button class="bool-btn" data-value="true">Да</button>
            <button class="bool-btn" data-value="false">Нет</button>
        </div>`;
    }

    function typeHintHtml(type) {
        if (type === 'time') {
            return `<span class="label-text">Тип: Время</span>
                    <span class="label-hint">Запись времени суток (например, отход ко сну)</span>`;
        }
        if (type === 'number') {
            return `<span class="label-text">Тип: Число</span>
                    <span class="label-hint">Целое число с кнопками +/−</span>`;
        }
        if (type === 'scale') {
            return `<span class="label-text">Тип: Шкала</span>
                    <span class="label-hint">Оценка по шкале с настраиваемым диапазоном</span>`;
        }
        return `<span class="label-text">Тип: Да/Нет</span>
                <span class="label-hint">Простой переключатель (было / не было)</span>`;
    }

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal modal-large">
            <h3>${title}</h3>

            <div class="modal-content-split">
            <div class="modal-form">
                <label class="form-label">
                    <span class="label-text">Название</span>
                    <input id="nm-name" placeholder="Например: Зарядка" class="form-input" value="${existingMetric?.name || ''}">
                </label>

                <div class="form-label">
                    <span class="label-text">Иконка</span>
                    <div class="emoji-picker-wrapper">
                        <button type="button" class="emoji-trigger-btn ${existingMetric?.icon ? 'has-icon' : ''}" id="nm-icon-btn">${existingMetric?.icon || '<i data-lucide="smile-plus"></i>'}</button>
                        <button type="button" class="emoji-clear-btn" id="nm-icon-clear" style="display:${existingMetric?.icon ? 'inline' : 'none'}">&times;</button>
                        <input type="hidden" id="nm-icon" value="${existingMetric?.icon || ''}">
                    </div>
                </div>

                <label class="form-label">
                    <span class="label-text">Категория</span>
                    <input id="nm-cat" placeholder="Например: Утро" class="form-input" value="${existingMetric?.category || ''}">
                </label>

                ${isEdit ? `
                <div class="form-section" id="nm-type-section">
                    ${typeHintHtml(currentType)}
                </div>
                ${currentType === 'scale' ? `
                <div class="form-section" id="nm-scale-config" style="display: flex">
                    <span class="label-text">Настройки шкалы</span>
                    <div class="number-options-grid">
                        <label class="form-label-inline">
                            <span>Минимум</span>
                            <input type="number" id="nm-scale-min" class="form-input-small" value="${existingMetric?.scale_min ?? 1}" min="0" step="1">
                        </label>
                        <label class="form-label-inline">
                            <span>Максимум</span>
                            <input type="number" id="nm-scale-max" class="form-input-small" value="${existingMetric?.scale_max ?? 5}" min="1" step="1">
                        </label>
                        <label class="form-label-inline">
                            <span>Шаг</span>
                            <input type="number" id="nm-scale-step" class="form-input-small" value="${existingMetric?.scale_step ?? 1}" min="1" step="1">
                        </label>
                    </div>
                    <span class="label-hint">От 1 до 5, шаг 1 → [1] [2] [3] [4] [5]<br>От 1 до 5, шаг 2 → [1] [3] [5]</span>
                </div>
                ` : ''}
                <div class="form-section" id="nm-slots-section">
                    <span class="label-text">Замеры в день</span>
                    <div class="slot-labels-list" id="nm-slot-labels"></div>
                    <button type="button" class="btn-add-slot" id="nm-add-slot">+ Добавить замер</button>
                    <span class="label-hint">Оставьте пустым для одного замера в день. Добавьте 2+ замера (например Утро, День, Вечер) для нескольких записей.</span>
                </div>
                ` : `
                <div class="form-section" id="nm-type-section">
                    <span class="label-text">Тип метрики</span>
                    <div class="radio-group-inline">
                        <label class="radio-inline">
                            <input type="radio" name="nm-type" value="bool" ${currentType === 'bool' ? 'checked' : ''}>
                            <span>Да/Нет</span>
                        </label>
                        <label class="radio-inline">
                            <input type="radio" name="nm-type" value="time" ${currentType === 'time' ? 'checked' : ''}>
                            <span>Время</span>
                        </label>
                        <label class="radio-inline">
                            <input type="radio" name="nm-type" value="number" ${currentType === 'number' ? 'checked' : ''}>
                            <span>Число</span>
                        </label>
                        <label class="radio-inline">
                            <input type="radio" name="nm-type" value="scale" ${currentType === 'scale' ? 'checked' : ''}>
                            <span>Шкала</span>
                        </label>
                    </div>
                </div>
                <div class="form-section" id="nm-scale-config" style="display: ${currentType === 'scale' ? 'flex' : 'none'}">
                    <span class="label-text">Настройки шкалы</span>
                    <div class="number-options-grid">
                        <label class="form-label-inline">
                            <span>Минимум</span>
                            <input type="number" id="nm-scale-min" class="form-input-small" value="1" min="0" step="1">
                        </label>
                        <label class="form-label-inline">
                            <span>Максимум</span>
                            <input type="number" id="nm-scale-max" class="form-input-small" value="5" min="1" step="1">
                        </label>
                        <label class="form-label-inline">
                            <span>Шаг</span>
                            <input type="number" id="nm-scale-step" class="form-input-small" value="1" min="1" step="1">
                        </label>
                    </div>
                    <span class="label-hint">От 1 до 5, шаг 1 → [1] [2] [3] [4] [5]<br>От 1 до 5, шаг 2 → [1] [3] [5]<br>От 1 до 4, шаг 2 → [1] [3]</span>
                </div>
                <div class="form-section" id="nm-slots-section">
                    <span class="label-text">Замеры в день</span>
                    <div class="slot-labels-list" id="nm-slot-labels"></div>
                    <button type="button" class="btn-add-slot" id="nm-add-slot">+ Добавить замер</button>
                    <span class="label-hint">Оставьте пустым для одного замера в день. Добавьте 2+ замера (например Утро, День, Вечер) для нескольких записей.</span>
                </div>
                `}
            </div>

            <div class="modal-preview-column">
                <div class="preview-sticky">
                    <span class="label-text">Превью</span>
                    <div id="metric-preview" class="metric-preview">
                        <div class="metric-card" id="preview-card">
                            <div class="metric-header">
                                <label class="metric-label">${existingMetric?.icon ? '<span class="metric-icon">' + existingMetric.icon + '</span>' : ''}${existingMetric?.name || 'Название метрики'}</label>
                            </div>
                            <div class="metric-input" id="preview-input">
                                ${previewInputHtml(currentType)}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            </div>

            <div class="modal-actions">
                <button class="btn-primary" id="nm-save">${buttonText}</button>
                <button class="btn-small" id="nm-cancel">Отмена</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    if (window.lucide) lucide.createIcons();

    // ─── Emoji picker setup ───
    const iconBtn = document.getElementById('nm-icon-btn');
    const iconInput = document.getElementById('nm-icon');
    const iconClear = document.getElementById('nm-icon-clear');

    iconBtn.addEventListener('click', (e) => {
        e.preventDefault();
        // Remove existing popup if any
        const existing = document.querySelector('.emoji-popup');
        if (existing) { existing.remove(); return; }

        const popup = document.createElement('div');
        popup.className = 'emoji-popup';
        const picker = document.createElement('emoji-picker');
        popup.appendChild(picker);
        document.body.appendChild(popup);

        // Position near button
        const rect = iconBtn.getBoundingClientRect();
        popup.style.left = rect.left + 'px';
        popup.style.top = (rect.bottom + 4) + 'px';

        // Ensure popup stays within viewport
        requestAnimationFrame(() => {
            const popupRect = popup.getBoundingClientRect();
            if (popupRect.right > window.innerWidth) {
                popup.style.left = (window.innerWidth - popupRect.width - 8) + 'px';
            }
            if (popupRect.bottom > window.innerHeight) {
                popup.style.top = (rect.top - popupRect.height - 4) + 'px';
            }
        });

        picker.addEventListener('emoji-click', (ev) => {
            iconInput.value = ev.detail.unicode;
            iconBtn.textContent = ev.detail.unicode;
            iconBtn.classList.add('has-icon');
            iconClear.style.display = 'inline';
            popup.remove();
            updatePreview();
        });

        // Close on outside click
        setTimeout(() => {
            document.addEventListener('click', function closePopup(ev) {
                if (!popup.contains(ev.target) && ev.target !== iconBtn) {
                    popup.remove();
                    document.removeEventListener('click', closePopup);
                }
            });
        }, 0);
    });

    iconClear.addEventListener('click', (e) => {
        e.preventDefault();
        iconInput.value = '';
        iconBtn.innerHTML = '<i data-lucide="smile-plus"></i>';
        if (window.lucide) lucide.createIcons();
        iconBtn.classList.remove('has-icon');
        iconClear.style.display = 'none';
        updatePreview();
    });

    // Update preview on name change
    document.getElementById('nm-name').addEventListener('input', () => updatePreview());

    // Type selector change (only in create mode)
    if (!isEdit) {
        overlay.querySelectorAll('input[name="nm-type"]').forEach(radio => {
            radio.addEventListener('change', () => {
                const selectedType = overlay.querySelector('input[name="nm-type"]:checked').value;
                const scaleConfig = document.getElementById('nm-scale-config');
                if (scaleConfig) scaleConfig.style.display = selectedType === 'scale' ? 'flex' : 'none';
                updatePreview();
            });
        });

        // Scale config input listeners — update preview in real time
        ['nm-scale-min', 'nm-scale-max', 'nm-scale-step'].forEach(id => {
            const el = overlay.querySelector(`#${id}`);
            if (el) {
                el.addEventListener('input', () => updatePreview());
            }
        });
    } else if (currentType === 'scale') {
        // Edit mode: scale config listeners for preview update
        ['nm-scale-min', 'nm-scale-max', 'nm-scale-step'].forEach(id => {
            const el = overlay.querySelector(`#${id}`);
            if (el) {
                el.addEventListener('input', () => updatePreview());
            }
        });
    }

    function setupPreviewInteractions() {
        document.querySelectorAll('#preview-card .bool-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const buttons = btn.parentElement.querySelectorAll('.bool-btn');
                buttons.forEach(b => b.classList.remove('active', 'yes', 'no'));
                const isYes = btn.dataset.value === 'true';
                btn.classList.add('active', isYes ? 'yes' : 'no');
            });
        });
        document.querySelectorAll('#preview-card .scale-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const buttons = btn.parentElement.querySelectorAll('.scale-btn');
                buttons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        });
    }

    function getCurrentType() {
        if (isEdit) return currentType;
        return overlay.querySelector('input[name="nm-type"]:checked')?.value || 'bool';
    }

    function updatePreview() {
        const type = getCurrentType();
        const rawName = document.getElementById('nm-name').value || 'Название метрики';
        const icon = document.getElementById('nm-icon').value;
        const name = (icon ? '<span class="metric-icon">' + icon + '</span>' : '') + rawName;
        const slotInputs = slotList ? slotList.querySelectorAll('.slot-label-input') : [];
        const labels = Array.from(slotInputs).map(i => i.value.trim()).filter(v => v !== '');
        const previewCard = document.getElementById('preview-card');

        if (labels.length >= 2) {
            // Multi-slot preview
            let slotsHtml = '<div class="multiple-entry">';
            for (const label of labels) {
                slotsHtml += `<div class="metric-slot">
                    <div class="period-header">
                        <span class="period-label">${label}</span>
                    </div>
                    <div class="metric-input">${previewInputHtml(type)}</div>
                </div>`;
            }
            slotsHtml += '</div>';
            previewCard.innerHTML = `
                <div class="metric-header">
                    <label class="metric-label">${name}</label>
                </div>
                ${slotsHtml}`;
        } else {
            // Single preview
            previewCard.innerHTML = `
                <div class="metric-header">
                    <label class="metric-label">${name}</label>
                </div>
                <div class="metric-input" id="preview-input">${previewInputHtml(type)}</div>`;
        }
        setupPreviewInteractions();
    }

    // ─── Slot management ───
    const slotList = document.getElementById('nm-slot-labels');
    const addSlotBtn = document.getElementById('nm-add-slot');

    setupPreviewInteractions();

    function addSlotField(label = '') {
        const row = document.createElement('div');
        row.className = 'slot-label-row';
        row.innerHTML = `<input type="text" class="form-input slot-label-input" placeholder="Например: Утро" value="${label}">
            <button type="button" class="btn-remove-slot">&times;</button>`;
        slotList.appendChild(row);
        row.querySelector('.btn-remove-slot').onclick = () => { row.remove(); updatePreview(); };
        row.querySelector('.slot-label-input').addEventListener('input', updatePreview);
    }

    if (addSlotBtn) {
        addSlotBtn.onclick = () => { addSlotField(''); updatePreview(); };
        // Pre-fill slots in edit mode
        if (isEdit && existingMetric?.slots) {
            for (const s of existingMetric.slots) {
                addSlotField(s.label);
            }
            updatePreview();
        }
    }

    function getSlotLabels() {
        const inputs = slotList ? slotList.querySelectorAll('.slot-label-input') : [];
        return Array.from(inputs).map(i => i.value.trim()).filter(v => v !== '');
    }

    document.getElementById('nm-cancel').onclick = () => overlay.remove();
    document.getElementById('nm-save').onclick = async () => {
        const name = document.getElementById('nm-name').value;
        const category = document.getElementById('nm-cat').value;

        if (!name || !category) {
            alert('Заполните название и категорию');
            return;
        }

        try {
            const slotLabels = getSlotLabels();

            if (isEdit) {
                const icon = document.getElementById('nm-icon').value;
                const updateData = { name, category, icon };
                if (existingMetric.type === 'scale') {
                    const sp = getScaleParams();
                    updateData.scale_min = sp.min;
                    updateData.scale_max = sp.max;
                    updateData.scale_step = sp.step;
                }
                // Send slot_labels if user configured slots
                if (slotLabels.length >= 2) {
                    updateData.slot_labels = slotLabels;
                } else if (slotLabels.length === 0 && (!existingMetric.slots || existingMetric.slots.length === 0)) {
                    // No slots before, no slots now — don't send
                } else if (slotLabels.length < 2 && existingMetric.slots && existingMetric.slots.length > 0) {
                    alert('Нельзя уменьшить количество замеров меньше 2. Удалите все поля, чтобы не менять настройку.');
                    return;
                }
                await api.updateMetric(existingMetric.id, updateData);
            } else {
                const typeRadio = overlay.querySelector('input[name="nm-type"]:checked');
                const selectedType = typeRadio ? typeRadio.value : 'bool';

                const slug = name.toLowerCase()
                    .replace(/\s+/g, '_')
                    .replace(/[^a-z0-9_а-яё]/gi, '')
                    || 'metric_' + Date.now();

                const icon = document.getElementById('nm-icon').value;
                const createData = { slug, name, category, icon, type: selectedType };

                if (selectedType === 'scale') {
                    const sp = getScaleParams();
                    if (sp.min >= sp.max) {
                        alert('Минимум должен быть меньше максимума');
                        return;
                    }
                    if (sp.step < 1 || sp.step > (sp.max - sp.min)) {
                        alert('Шаг должен быть >= 1 и <= (макс - мин)');
                        return;
                    }
                    createData.scale_min = sp.min;
                    createData.scale_max = sp.max;
                    createData.scale_step = sp.step;
                }

                if (slotLabels.length >= 2) {
                    createData.slot_labels = slotLabels;
                }

                await api.createMetric(createData);
            }

            overlay.remove();
            await loadMetrics();
            navigateTo('settings');
        } catch (error) {
            alert(`Ошибка ${isEdit ? 'обновления' : 'создания'} метрики: ` + error.message);
        }
    };
}

function showAddMetricModal() {
    showMetricModal('create');
}

function showEditMetricModal(metric) {
    showMetricModal('edit', metric);
}

// ─── Clock Picker ───
function showClockPicker(initialValue, callback) {
    let hour = null;
    let minute = null;

    if (initialValue && initialValue.includes(':')) {
        const parts = initialValue.split(':').map(Number);
        hour = parts[0];
        minute = Math.round(parts[1] / 5) * 5;
        if (minute === 60) minute = 55;
    }

    let phase = 'hour';

    const SIZE = 260;
    const CENTER = SIZE / 2;
    const OUTER_R = 100;
    const INNER_R = 66;

    const overlay = document.createElement('div');
    overlay.className = 'cp-overlay';
    // Inline critical styles so no CSS can override the fixed overlay
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);z-index:9999';
    document.documentElement.appendChild(overlay);

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });

    render();

    function numStyle(cx, cy, selected, inner) {
        const s = selected ? 40 : 36;
        const half = s / 2;
        const bg = selected ? 'var(--accent)' : 'transparent';
        const color = selected ? '#fff' : inner ? 'var(--text-dim)' : 'var(--text)';
        const fs = inner ? '12px' : '14px';
        return `position:absolute;left:${(cx - half).toFixed(1)}px;top:${(cy - half).toFixed(1)}px;`
            + `width:${s}px;height:${s}px;`
            + `display:flex;align-items:center;justify-content:center;border-radius:50%;`
            + `font-size:${fs};font-weight:500;color:${color};background:${bg};`
            + `cursor:pointer;user-select:none;z-index:2`;
    }

    function renderNums() {
        let html = '';

        if (phase === 'hour') {
            const outer = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
            const inner = [0, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23];

            outer.forEach((h, i) => {
                const a = (i / 12) * 2 * Math.PI;
                const cx = CENTER + OUTER_R * Math.sin(a);
                const cy = CENTER - OUTER_R * Math.cos(a);
                html += `<div data-val="${h}" ${hour === h ? 'data-selected' : ''} style="${numStyle(cx, cy, hour === h, false)}">${h}</div>`;
            });

            inner.forEach((h, i) => {
                const a = (i / 12) * 2 * Math.PI;
                const cx = CENTER + INNER_R * Math.sin(a);
                const cy = CENTER - INNER_R * Math.cos(a);
                html += `<div data-val="${h}" ${hour === h ? 'data-selected' : ''} style="${numStyle(cx, cy, hour === h, true)}">${String(h).padStart(2, '0')}</div>`;
            });
        } else {
            const mins = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55];
            mins.forEach((m, i) => {
                const a = (i / 12) * 2 * Math.PI;
                const cx = CENTER + OUTER_R * Math.sin(a);
                const cy = CENTER - OUTER_R * Math.cos(a);
                html += `<div data-val="${m}" ${minute === m ? 'data-selected' : ''} style="${numStyle(cx, cy, minute === m, false)}">${String(m).padStart(2, '0')}</div>`;
            });
        }

        return html;
    }

    function renderHand() {
        const val = phase === 'hour' ? hour : minute;
        if (val === null) return '';

        let angleDeg, len;
        if (phase === 'hour') {
            angleDeg = (val % 12) * 30;
            len = (val >= 1 && val <= 12) ? OUTER_R : INNER_R;
        } else {
            angleDeg = (val / 5) * 30;
            len = OUTER_R;
        }

        return `<div class="cp-hand" style="transform:rotate(${angleDeg}deg);height:${len}px"></div>`;
    }

    function render() {
        const hh = hour !== null ? String(hour).padStart(2, '0') : '--';
        const mm = minute !== null ? String(minute).padStart(2, '0') : '--';
        const phaseLabel = phase === 'hour' ? 'Выберите час' : 'Выберите минуты';

        overlay.innerHTML = `
            <div class="cp-dialog">
                <div class="cp-header">
                    <span class="cp-hh ${phase === 'hour' ? 'active' : ''}" id="cp-h">${hh}</span>
                    <span class="cp-colon">:</span>
                    <span class="cp-mm ${phase === 'minute' ? 'active' : ''}" id="cp-m">${mm}</span>
                </div>
                <div class="cp-label">${phaseLabel}</div>
                <div class="cp-face" style="position:relative;width:${SIZE}px;height:${SIZE}px">
                    ${renderNums()}
                    <div class="cp-hand-dot"></div>
                    ${renderHand()}
                </div>
                <div class="cp-actions">
                    <button class="btn-small" id="cp-cancel">Отмена</button>
                    <button class="btn-primary" id="cp-ok" ${hour === null || minute === null ? 'disabled' : ''}>OK</button>
                </div>
            </div>
        `;

        // Events
        overlay.querySelector('#cp-cancel').onclick = () => overlay.remove();
        overlay.querySelector('#cp-ok').onclick = () => {
            if (hour !== null && minute !== null) {
                const v = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
                overlay.remove();
                callback(v);
            }
        };

        overlay.querySelector('#cp-h').onclick = () => { phase = 'hour'; render(); };
        overlay.querySelector('#cp-m').onclick = () => { phase = 'minute'; render(); };

        overlay.querySelectorAll('[data-val]').forEach(el => {
            el.onmouseenter = () => { if (!el.hasAttribute('data-selected')) el.style.background = 'rgba(108,140,255,0.15)'; };
            el.onmouseleave = () => { if (!el.hasAttribute('data-selected')) el.style.background = 'transparent'; };
            el.onclick = () => {
                const v = parseInt(el.dataset.val);
                if (phase === 'hour') {
                    hour = v;
                    phase = 'minute';
                } else {
                    minute = v;
                }
                render();
            };
        });
    }
}

// ─── Helpers ───
function formatDate(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' });
}

function daysAgo(n) {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
}
