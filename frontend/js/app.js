// ─── State ───
let currentDate = todayStr();
let metrics = [];
let currentPage = 'today';
let currentUser = null;
let isAuthenticated = false;
let corrPollInterval = null;

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

function navigateTo(page, params = {}) {
    currentPage = page;

    // Cleanup polling
    if (corrPollInterval) { clearInterval(corrPollInterval); corrPollInterval = null; }

    // Hide nav for auth pages
    const nav = document.querySelector('nav');
    if (nav) {
        nav.style.display = (page === 'login' || page === 'register') ? 'none' : '';
    }

    const activePage = page === 'metric-detail' ? 'dashboard' : page;
    document.querySelectorAll('[data-page]').forEach(b => b.classList.toggle('active', b.dataset.page === activePage));
    const main = document.getElementById('main');

    switch (page) {
        case 'login': renderLogin(main); break;
        case 'register': renderRegister(main); break;
        case 'today': renderToday(main); break;
        case 'history': renderHistory(main); break;
        case 'dashboard': renderDashboard(main); break;
        case 'metric-detail': renderMetricDetail(main, params.metricId); break;
        case 'settings': renderSettings(main, params); break;
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
        <div class="today-actions">
            <button class="btn-small" id="today-edit-metrics">
                <i data-lucide="settings"></i> Редактировать метрики
            </button>
            <button class="btn-small" id="today-add-metric">
                <i data-lucide="plus"></i> Добавить метрику
            </button>
        </div>
    `;

    if (window.lucide) lucide.createIcons();

    document.getElementById('prev-day').onclick = () => { changeDay(-1); };
    document.getElementById('next-day').onclick = () => { changeDay(1); };
    document.getElementById('go-today').onclick = () => { currentDate = todayStr(); renderTodayForm(); };
    document.getElementById('today-add-metric').onclick = () => { navigateTo('settings', { openAddModal: true }); };
    document.getElementById('today-edit-metrics').onclick = () => { navigateTo('settings'); };

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

    // Auto metrics section
    const autoMetrics = summary.auto_metrics || [];
    if (autoMetrics.length > 0) {
        html += '<div class="auto-metrics-section">';
        html += '<h3 class="category-title">Автоматические</h3>';
        html += '<div class="auto-metrics-note">Вычисляются автоматически. Нельзя отключить.</div>';
        for (const am of autoMetrics) {
            const isBool = am.auto_type === 'nonzero';
            let displayVal;
            if (isBool) {
                displayVal = am.value ? 'Да' : 'Нет';
            } else if (am.auto_type === 'day_of_week') {
                const days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
                displayVal = days[am.value - 1];
            } else if (am.auto_type === 'month') {
                const months = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'];
                displayVal = months[am.value - 1];
            } else {
                displayVal = String(am.value);
            }
            const filledClass = 'filled';
            html += `<div class="metric-card auto-metric ${filledClass}">
                <div class="metric-header">
                    <label class="metric-label">${am.name}</label>
                    <span class="computed-badge">авто</span>
                </div>
                <div class="computed-value">${displayVal}</div>
            </div>`;
        }
        html += '</div>';
    }

    form.innerHTML = html;
    attachInputHandlers();

    // Update progress bar (skip computed metrics)
    let total = 0;
    let filled = 0;
    for (const m of summary.metrics) {
        if (m.type === 'computed') continue;
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
    // Computed metric — read-only display
    if (m.type === 'computed') {
        const entry = m.entry;
        const val = entry ? entry.value : null;
        const isFilled = val !== null && val !== undefined;
        const rt = m.result_type || 'float';
        let displayVal;
        if (!isFilled) {
            displayVal = '—';
        } else if (rt === 'bool') {
            displayVal = val ? 'Да' : 'Нет';
        } else if (rt === 'time') {
            displayVal = String(val);
        } else if (rt === 'int') {
            displayVal = String(Math.round(val));
        } else {
            displayVal = typeof val === 'number' ? val.toFixed(2) : String(val);
        }
        return `<div class="metric-card ${isFilled ? 'filled' : ''}" data-metric-id="${m.metric_id}" data-metric-type="computed">
            <div class="metric-header">
                <label class="metric-label">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</label>
                <span class="computed-badge">авто</span>
            </div>
            <div class="computed-value ${isFilled ? '' : 'empty'}">${displayVal}</div>
        </div>`;
    }

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

    // Update progress bar (skip computed metrics)
    let total = 0;
    let filled = 0;
    for (const m of summary.metrics) {
        if (m.type === 'computed') continue;
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
                const valStr = _formatEntryValue(s.entry, m.type, m.result_type);
                html += `<div class="summary-row"><span class="summary-label">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name} — ${s.label}</span><span class="summary-value">${valStr}</span></div>`;
            }
        } else {
            if (!m.entry) continue;
            hasAny = true;
            const valStr = _formatEntryValue(m.entry, m.type, m.result_type);
            html += `<div class="summary-row"><span class="summary-label">${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</span><span class="summary-value">${valStr}</span></div>`;
        }
    }

    if (!hasAny) {
        html += `<div class="summary-row"><span class="summary-label" style="color:var(--text-dim)">Нет записей</span></div>`;
    }

    html += '</div>';
    detail.innerHTML = html;
}

function _formatEntryValue(entry, type, resultType) {
    if (type === 'computed') {
        const v = entry.value;
        if (v === null || v === undefined) return '—';
        const rt = resultType || 'float';
        if (rt === 'bool') return v ? 'Да' : 'Нет';
        if (rt === 'time') return String(v);
        if (rt === 'int') return String(Math.round(v));
        return typeof v === 'number' ? v.toFixed(2) : String(v);
    }
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
        <div class="stats-header">
            <h2 class="stats-title">Статистика</h2>
            <div class="stats-controls">
                <input type="date" id="dash-start" value="${start}">
                <span class="stats-dash">—</span>
                <input type="date" id="dash-end" value="${end}">
                <button class="btn-icon" id="dash-refresh" title="Обновить">
                    <i data-lucide="refresh-cw"></i>
                </button>
            </div>
        </div>
        <div id="trends-section"></div>
        <div id="correlation-section"></div>
    `;

    if (window.lucide) lucide.createIcons();

    document.getElementById('dash-refresh').addEventListener('click', () => {
        loadDashboard(
            document.getElementById('dash-start').value,
            document.getElementById('dash-end').value
        );
    });

    await loadDashboard(start, end);
}

async function loadDashboard(start, end) {
    // Destroy previous trend charts
    trendChartInstances.forEach(c => c.destroy());
    trendChartInstances = [];

    const trendsEl = document.getElementById('trends-section');
    let trendsHtml = '<h3>Графики и данные</h3><div class="trends-list">';
    const trendData = [];
    for (const m of metrics) {
        const trend = await api.getTrends(m.id, start, end);
        if (trend.points && trend.points.length > 0) {
            trendData.push({ metric: m, points: trend.points });
            trendsHtml += `<div class="trend-card-row" data-metric-id="${m.id}" style="cursor:pointer">
                <div class="trend-card-header">
                    <h4>${m.icon ? '<span class="metric-icon">' + m.icon + '</span>' : ''}${m.name}</h4>
                    <i data-lucide="info" class="trend-info-icon"></i>
                </div>
                <div class="trend-chart-container"><canvas id="trend-chart-${m.id}"></canvas></div>
            </div>`;
        }
    }
    trendsHtml += '</div>';
    trendsEl.innerHTML = trendsHtml;

    // Initialize Chart.js for each trend card
    const style = getComputedStyle(document.documentElement);
    const colors = {
        accent: style.getPropertyValue('--accent').trim(),
        green: style.getPropertyValue('--green').trim(),
        red: style.getPropertyValue('--red').trim(),
    };
    for (const { metric, points } of trendData) {
        const canvas = document.getElementById(`trend-chart-${metric.id}`);
        if (!canvas) continue;
        const mt = metric.type === 'computed' ? (metric.result_type || 'float') : metric.type;
        const config = buildChartConfig(points, mt, colors, { compact: true });
        trendChartInstances.push(new Chart(canvas.getContext('2d'), config));
    }

    if (window.lucide) lucide.createIcons({ nameAttr: 'data-lucide' });

    // Attach click on entire card
    trendsEl.querySelectorAll('.trend-card-row[data-metric-id]').forEach(card => {
        card.addEventListener('click', () => {
            navigateTo('metric-detail', { metricId: parseInt(card.dataset.metricId) });
        });
    });

    // Correlation section
    const corrEl = document.getElementById('correlation-section');
    corrEl.innerHTML = `
        <div class="corr-header">
            <div class="corr-header-left">
                <h3>Корреляции</h3>
                <span class="corr-count" id="corr-count"></span>
                <button class="corr-help-btn" id="corr-help-btn">?</button>
            </div>
            <button class="btn-primary btn-sm" id="corr-calc-all">Рассчитать</button>
        </div>
        <div id="corr-reports"></div>
    `;

    document.getElementById('corr-help-btn').addEventListener('click', showCorrelationHelp);

    document.getElementById('corr-calc-all').addEventListener('click', async () => {
        await api.createCorrelationReport(start, end);
        loadCorrelationReport(start, end);
    });

    loadCorrelationReport(start, end);
}

async function loadCorrelationReport(start, end) {
    const container = document.getElementById('corr-reports');
    if (!container) return;

    const data = await api.getCorrelationReport();

    if (!data.running && !data.report) {
        container.innerHTML = '<p style="color:var(--text-dim);font-size:13px;">Нет отчётов. Нажмите «Рассчитать все корреляции».</p>';
        return;
    }

    let html = '';

    if (data.running) {
        html += '<div class="corr-running">Рассчитываем корреляции...</div>';
        if (!corrPollInterval) {
            corrPollInterval = setInterval(async () => {
                if (currentPage !== 'dashboard') {
                    clearInterval(corrPollInterval);
                    corrPollInterval = null;
                    return;
                }
                const check = await api.getCorrelationReport();
                if (!check.running) {
                    clearInterval(corrPollInterval);
                    corrPollInterval = null;
                    loadCorrelationReport(start, end);
                }
            }, 3000);
        }
    } else if (corrPollInterval) {
        clearInterval(corrPollInterval);
        corrPollInterval = null;
    }

    html += '<div id="corr-report-detail"></div>';
    container.innerHTML = html;

    const countEl = document.getElementById('corr-count');
    if (countEl && data.report) {
        countEl.textContent = data.report.pairs.length;
    }

    if (data.report) {
        renderCorrelationReport(data.report, document.getElementById('corr-report-detail'));
    }
}

function showCorrelationHelp() {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal" style="max-width:520px">
            <h2>Как это читать</h2>
            <div style="text-align:left;font-size:14px;line-height:1.7">
                <p>Мы сравнили все ваши метрики попарно и нашли, какие из них ходят вместе.</p>
                <p>Каждая карточка — одна пара. Вот пример:</p>
                <div class="corr-pair-row" style="pointer-events:none;margin:8px 0 12px">
                    <div class="corr-col-metric">
                        <span class="metric-icon">💪</span>
                        <div class="corr-metric-text">
                            <div class="corr-metric-name">Зарядка утром</div>
                            <div class="corr-pair-hint"><span class="corr-word-pos">да</span></div>
                        </div>
                    </div>
                    <div class="corr-arrow">↔</div>
                    <div class="corr-col-metric">
                        <span class="metric-icon">😇</span>
                        <div class="corr-metric-text">
                            <div class="corr-metric-name">Настроение</div>
                            <div class="corr-pair-hint"><span class="corr-word-pos">выше</span></div>
                        </div>
                    </div>
                    <div class="corr-col-info">
                        <div class="corr-pair-value strong">0.987</div>
                        <div class="corr-info-sub">12 дн.</div>
                    </div>
                </div>
                <p><b>0.987</b> — сила связи от 0 до 1. Чем ближе к единице, тем закономерность заметнее. <b>12 дн.</b> — по скольким дням считали.</p>
                <p><b>да / выше</b> — подсказки направления. Читается так: «в дни, когда зарядка — <i>да</i>, настроение обычно — <i>выше</i>».</p>
                <p><b>Верхний блок</b> (p&lt;0.05) — пары, где связь статистически надёжная: вероятность, что совпадение случайно, меньше 5%. <b>Нижний блок</b> — связь не доказана или пока мало данных.</p>
                <p><b>Пары «вчера → сегодня»</b> — мы также проверяем, влияет ли вчерашнее значение одной метрики на сегодняшнее значение другой:</p>
                <div class="corr-pair-row" style="pointer-events:none;margin:8px 0 12px">
                    <div class="corr-col-metric">
                        <span class="metric-icon">☕</span>
                        <div class="corr-metric-text">
                            <div class="corr-day-label">вчера</div>
                            <div class="corr-metric-name">Кофе</div>
                            <div class="corr-pair-hint"><span class="corr-word-pos">больше</span></div>
                        </div>
                    </div>
                    <div class="corr-arrow">↔</div>
                    <div class="corr-col-metric">
                        <span class="metric-icon">😴</span>
                        <div class="corr-metric-text">
                            <div class="corr-day-label">сегодня</div>
                            <div class="corr-metric-name">Качество сна</div>
                            <div class="corr-pair-hint"><span class="corr-word-neg">ниже</span></div>
                        </div>
                    </div>
                    <div class="corr-col-info">
                        <div class="corr-pair-value medium">0.540</div>
                        <div class="corr-info-sub">18 дн.</div>
                    </div>
                </div>
                <p>Результатам можно верить от ~10 дней общих данных. Чем больше дней — тем точнее.</p>
                <p style="color:var(--text-dim);font-style:italic">Важно: связь — это ещё не причина. Зарядка и настроение могут совпадать не потому, что одно вызывает другое, а потому что оба зависят, например, от качества сна.</p>
            </div>
            <div class="modal-actions">
                <button class="btn-primary" id="corr-help-close">Понятно</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.getElementById('corr-help-close').addEventListener('click', () => overlay.remove());
}

function corrTypeWords(type) {
    const g = w => `<span class="corr-word-pos">${w}</span>`;
    const r = w => `<span class="corr-word-neg">${w}</span>`;
    switch (type) {
        case 'bool': return [g('да'), r('нет')];
        case 'time': return ['позже', 'раньше'];
        case 'scale': return [g('выше'), r('ниже')];
        default: return [g('больше'), r('меньше')];
    }
}

function corrHintWords(typeA, typeB, r) {
    if (!typeA || !typeB) return ['', ''];
    const [posA] = corrTypeWords(typeA);
    const [posB, negB] = corrTypeWords(typeB);
    const wordA = posA;
    const wordB = r > 0 ? posB : negB;
    return [wordA, wordB];
}

function renderCorrMetricLabel(label, icon, slotLabel, hint, dayLabel) {
    const iconHtml = `<span class="metric-icon">${icon || ''}</span>`;
    const slotHtml = slotLabel ? `<span class="corr-slot-badge">${slotLabel}</span>` : '';
    const dayHtml = dayLabel ? `<div class="corr-day-label">${dayLabel}</div>` : '';
    return `${iconHtml}<div class="corr-metric-text">${dayHtml}<div class="corr-metric-name">${label}${slotHtml}</div><div class="corr-pair-hint">${hint}</div></div>`;
}

function renderCorrPair(p) {
    const r = p.correlation;
    const absR = Math.abs(r);
    const cls = absR > 0.7 ? 'strong' : absR > 0.3 ? 'medium' : 'weak';
    const isLagged = p.lag_days && p.lag_days > 0;

    const typeLeft = isLagged ? p.type_b : p.type_a;
    const typeRight = isLagged ? p.type_a : p.type_b;
    const [hintA, hintB] = corrHintWords(typeLeft, typeRight, r);

    const labelA = renderCorrMetricLabel(isLagged ? p.label_b : p.label_a, isLagged ? p.icon_b : p.icon_a, isLagged ? p.slot_label_b : p.slot_label_a, hintA, isLagged ? 'вчера' : '');
    const labelB = renderCorrMetricLabel(isLagged ? p.label_a : p.label_b, isLagged ? p.icon_a : p.icon_b, isLagged ? p.slot_label_a : p.slot_label_b, hintB, isLagged ? 'сегодня' : '');

    return `<div class="corr-pair-row">
        <div class="corr-col-metric">${labelA}</div>
        <div class="corr-arrow">↔</div>
        <div class="corr-col-metric">${labelB}</div>
        <div class="corr-col-info">
            <div class="corr-pair-value ${cls}">${absR.toFixed(3)}</div>
            <div class="corr-info-sub">${p.data_points} дн.</div>
        </div>
    </div>`;
}

function renderCorrelationReport(report, container) {
    if (!report.pairs || report.pairs.length === 0) {
        container.innerHTML = '<p style="color:var(--text-dim);font-size:13px;">Нет данных для корреляций.</p>';
        return;
    }

    const sig = report.pairs.filter(p => p.data_points >= 10 && p.p_value !== null && p.p_value < 0.05);
    const insig = report.pairs.filter(p => p.data_points < 10 || p.p_value === null || p.p_value >= 0.05);

    const strong = sig.filter(p => Math.abs(p.correlation) > 0.7);
    const medium = sig.filter(p => { const a = Math.abs(p.correlation); return a > 0.3 && a <= 0.7; });
    const weak = sig.filter(p => Math.abs(p.correlation) <= 0.3);

    let html = '';

    if (sig.length > 0) {
        html += '<div class="corr-section">';
        html += '<div class="corr-section-header">Статистически значимо <span class="corr-sig corr-sig-yes">p&lt;0.05</span></div>';
        if (strong.length > 0) {
            html += '<div class="corr-subsection-header">Сильная корреляция</div>';
            for (const p of strong) html += renderCorrPair(p);
        }
        if (medium.length > 0) {
            html += '<div class="corr-subsection-header">Средняя корреляция</div>';
            for (const p of medium) html += renderCorrPair(p);
        }
        if (weak.length > 0) {
            html += '<div class="corr-subsection-header">Слабая корреляция</div>';
            for (const p of weak) html += renderCorrPair(p);
        }
        html += '</div>';
    }

    if (insig.length > 0) {
        html += '<div class="corr-section corr-section-low">';
        html += '<div class="corr-section-header">Незначимо или мало данных</div>';
        for (const p of insig) html += renderCorrPair(p);
        html += '</div>';
    }

    container.innerHTML = html;
}

// ─── Charts ───
let trendChartInstances = [];
let detailChartInstance = null;

function formatShortDate(dateStr) {
    const months = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
    const parts = dateStr.split('-');
    return parseInt(parts[2]) + ' ' + months[parseInt(parts[1]) - 1];
}

function buildChartConfig(points, metricType, colors, options = {}) {
    const compact = options.compact || false;
    const labels = points.map(p => formatShortDate(p.date));
    const values = points.map(p => p.value);
    const showPoints = points.length <= 30;
    const chartType = (metricType === 'int' || metricType === 'float') ? 'number' : metricType;
    const xConfig = { ticks: { maxTicksLimit: compact ? 4 : 7, maxRotation: 0 }, grid: { display: false } };

    if (chartType === 'bool') {
        return {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    data: values.map(() => 1),
                    backgroundColor: values.map(v => v === 1 ? colors.green : colors.red),
                    borderRadius: 3,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: !compact, callbacks: { label: ctx => values[ctx.dataIndex] === 1 ? 'Да' : 'Нет' } },
                },
                interaction: compact ? { mode: null } : undefined,
                events: compact ? [] : undefined,
                scales: {
                    y: { min: 0, max: 1, display: false },
                    x: xConfig,
                },
            },
        };
    }

    const yConfig = { grid: { color: 'rgba(128,128,128,0.1)' } };
    if (chartType === 'time') {
        yConfig.min = 0; yConfig.max = 1439;
        yConfig.ticks = { callback: v => minutesToHHMM(v), stepSize: 360 };
    } else if (chartType === 'scale') {
        yConfig.min = 0; yConfig.max = 100;
        yConfig.ticks = { callback: v => v + '%' };
    }

    const config = {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data: values,
                borderColor: colors.accent,
                backgroundColor: colors.accent + '22',
                fill: true,
                tension: 0.3,
                pointRadius: showPoints ? 3 : 0,
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: !compact } },
            interaction: compact ? { mode: null } : undefined,
            events: compact ? [] : undefined,
            scales: {
                y: yConfig,
                x: xConfig,
            },
        },
    };
    if (chartType === 'time') {
        config.options.plugins.tooltip = {
            callbacks: { label: ctx => minutesToHHMM(ctx.parsed.y) }
        };
    }
    return config;
}
let formulaTokens = [];
let formulaBuilderInitialized = false;

function renderFormulaTokens() {
    const container = document.getElementById('nm-formula-tokens');
    if (!container) return;
    if (formulaTokens.length === 0) {
        container.innerHTML = '<span class="formula-tokens-empty">Добавьте метрики и операторы</span>';
        return;
    }
    const opLabels = {'+': '+', '-': '−', '*': '×', '/': '÷'};
    container.innerHTML = formulaTokens.map((tok, i) => {
        if (tok.type === 'metric') {
            const icon = tok.icon ? `<span class="metric-icon">${tok.icon}</span>` : '';
            return `<span class="formula-chip formula-chip-metric">${icon}${tok.name || tok.slug}<button type="button" class="chip-remove" data-idx="${i}">&times;</button></span>`;
        } else if (tok.type === 'op') {
            return `<span class="formula-chip formula-chip-op">${opLabels[tok.value] || tok.value}<button type="button" class="chip-remove" data-idx="${i}">&times;</button></span>`;
        } else if (tok.type === 'number') {
            return `<span class="formula-chip formula-chip-number">${tok.value}<button type="button" class="chip-remove" data-idx="${i}">&times;</button></span>`;
        } else if (tok.type === 'lparen') {
            return `<span class="formula-chip formula-chip-paren">(<button type="button" class="chip-remove" data-idx="${i}">&times;</button></span>`;
        } else if (tok.type === 'rparen') {
            return `<span class="formula-chip formula-chip-paren">)<button type="button" class="chip-remove" data-idx="${i}">&times;</button></span>`;
        }
        return '';
    }).join('');
    container.querySelectorAll('.chip-remove').forEach(btn => {
        btn.addEventListener('click', () => {
            formulaTokens.splice(parseInt(btn.dataset.idx), 1);
            renderFormulaTokens();
        });
    });
}

function populateFormulaMetricSelect(editingMetricId) {
    const sel = document.getElementById('nm-formula-metric-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">Добавить метрику...</option>';
    metrics.filter(m => m.type !== 'computed' && m.enabled && m.id !== editingMetricId).forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = (m.icon || '') + ' ' + m.name;
        opt.dataset.slug = m.slug;
        opt.dataset.name = m.name;
        opt.dataset.icon = m.icon || '';
        sel.appendChild(opt);
    });
}

function setupFormulaBuilderHandlers(overlay) {
    if (formulaBuilderInitialized) return;
    formulaBuilderInitialized = true;

    const metricSelect = overlay.querySelector('#nm-formula-metric-select');
    if (metricSelect) {
        metricSelect.addEventListener('change', () => {
            const val = metricSelect.value;
            if (!val) return;
            const opt = metricSelect.selectedOptions[0];
            formulaTokens.push({
                type: 'metric',
                id: parseInt(val),
                slug: opt.dataset.slug,
                name: opt.dataset.name,
                icon: opt.dataset.icon || undefined,
            });
            metricSelect.value = '';
            renderFormulaTokens();
        });
    }

    overlay.querySelectorAll('.formula-op-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const op = btn.dataset.op;
            if (op === '(' || op === ')') {
                formulaTokens.push({ type: op === '(' ? 'lparen' : 'rparen' });
            } else {
                formulaTokens.push({ type: 'op', value: op });
            }
            renderFormulaTokens();
        });
    });

    const addNumBtn = overlay.querySelector('#nm-formula-add-num');
    const numInput = overlay.querySelector('#nm-formula-num-input');
    if (addNumBtn && numInput) {
        addNumBtn.addEventListener('click', () => {
            const v = parseFloat(numInput.value);
            if (isNaN(v)) return;
            formulaTokens.push({ type: 'number', value: v });
            numInput.value = '';
            renderFormulaTokens();
        });
    }

    const clearBtn = overlay.querySelector('#nm-formula-clear-last');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            formulaTokens.pop();
            renderFormulaTokens();
        });
    }
}

function minutesToHHMM(m) {
    const h = Math.floor(m / 60);
    const min = Math.floor(m % 60);
    return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

async function renderMetricDetail(container, metricId) {
    const metric = metrics.find(m => m.id === metricId);
    if (!metric) { navigateTo('dashboard'); return; }

    const end = todayStr();
    const start = daysAgo(90);

    container.innerHTML = `
        <div class="detail-header">
            <button class="btn-small" id="detail-back"><i data-lucide="arrow-left"></i> Дашборд</button>
            <h2>${metric.icon ? '<span class="metric-icon">' + metric.icon + '</span>' : ''}${metric.name}</h2>
        </div>
        <div class="detail-controls">
            <input type="date" id="detail-start" value="${start}">
            <span>—</span>
            <input type="date" id="detail-end" value="${end}">
            <button class="btn-small" id="detail-refresh">Обновить</button>
        </div>
        <div class="detail-chart-container"><canvas id="detail-chart"></canvas></div>
        <div id="detail-stats"></div>
    `;

    if (window.lucide) lucide.createIcons();

    document.getElementById('detail-back').addEventListener('click', () => navigateTo('dashboard'));
    document.getElementById('detail-refresh').addEventListener('click', () => {
        loadMetricDetail(
            metricId, metric,
            document.getElementById('detail-start').value,
            document.getElementById('detail-end').value
        );
    });

    await loadMetricDetail(metricId, metric, start, end);
}

async function loadMetricDetail(metricId, metric, start, end) {
    const [trend, stats] = await Promise.all([
        api.getTrends(metricId, start, end),
        api.getMetricStats(metricId, start, end),
    ]);

    // Destroy previous chart
    if (detailChartInstance) {
        detailChartInstance.destroy();
        detailChartInstance = null;
    }

    const canvas = document.getElementById('detail-chart');
    if (!canvas) return;
    const style = getComputedStyle(document.documentElement);
    const colors = {
        accent: style.getPropertyValue('--accent').trim(),
        green: style.getPropertyValue('--green').trim(),
        red: style.getPropertyValue('--red').trim(),
    };

    const points = trend.points || [];
    const mt = metric.type === 'computed' ? (metric.result_type || 'float') : metric.type;
    const chartConfig = buildChartConfig(points, mt, colors);

    detailChartInstance = new Chart(canvas.getContext('2d'), chartConfig);

    // Render stats (use result_type for computed)
    const statsType = metric.type === 'computed' ? (metric.result_type || 'float') : metric.type;
    renderDetailStats(stats, statsType);
}

function renderDetailStats(stats, metricType) {
    const el = document.getElementById('detail-stats');
    if (!el) return;

    let cards = `
        <div class="stat-card"><div class="stat-value">${stats.total_entries}</div><div class="stat-label">Записей</div></div>
        <div class="stat-card"><div class="stat-value">${stats.fill_rate}%</div><div class="stat-label">Заполненность</div></div>
    `;

    if (metricType === 'bool') {
        cards += `
            <div class="stat-card"><div class="stat-value">${stats.yes_percent}%</div><div class="stat-label">Да</div></div>
            <div class="stat-card"><div class="stat-value">${stats.current_streak} дн.</div><div class="stat-label">Текущий стрик</div></div>
            <div class="stat-card"><div class="stat-value">${stats.longest_streak} дн.</div><div class="stat-label">Лучший стрик</div></div>
        `;
    } else if (metricType === 'time') {
        cards += `
            <div class="stat-card"><div class="stat-value">${stats.average}</div><div class="stat-label">Среднее</div></div>
            <div class="stat-card"><div class="stat-value">${stats.earliest}</div><div class="stat-label">Раньше всего</div></div>
            <div class="stat-card"><div class="stat-value">${stats.latest}</div><div class="stat-label">Позже всего</div></div>
        `;
    } else if (metricType === 'number' || metricType === 'int' || metricType === 'float') {
        cards += `
            <div class="stat-card"><div class="stat-value">${stats.average}</div><div class="stat-label">Среднее</div></div>
            <div class="stat-card"><div class="stat-value">${stats.min}</div><div class="stat-label">Мин</div></div>
            <div class="stat-card"><div class="stat-value">${stats.max}</div><div class="stat-label">Макс</div></div>
            ${stats.median !== undefined ? `<div class="stat-card"><div class="stat-value">${stats.median}</div><div class="stat-label">Медиана</div></div>` : ''}
        `;
    } else if (metricType === 'scale') {
        cards += `
            <div class="stat-card"><div class="stat-value">${stats.average}%</div><div class="stat-label">Среднее</div></div>
            <div class="stat-card"><div class="stat-value">${stats.min}%</div><div class="stat-label">Мин</div></div>
            <div class="stat-card"><div class="stat-value">${stats.max}%</div><div class="stat-label">Макс</div></div>
        `;
    }

    el.innerHTML = `<h3>Статистика</h3><div class="detail-stats-grid">${cards}</div>`;
}

// ─── Settings Page ───
async function renderSettings(container, { archiveOpen = false, openAddModal = false } = {}) {
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
                : m.type === 'computed' ? '<i data-lucide="calculator"></i> Формула'
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
                : m.type === 'computed' ? '<i data-lucide="calculator"></i> Формула'
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

    if (openAddModal) showAddMetricModal();

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
        if (type === 'computed') {
            return `<div class="computed-value empty">= ?</div>`;
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
        if (type === 'computed') {
            return `<span class="label-text">Тип: Формула</span>
                    <span class="label-hint">Вычисляется автоматически из других метрик</span>`;
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
                ${currentType === 'computed' ? `
                <div class="form-section" id="nm-computed-config" style="display: block">
                    <span class="label-text">Формула</span>
                    <div class="formula-tokens" id="nm-formula-tokens">
                        <span class="formula-tokens-empty">Добавьте метрики и операторы</span>
                    </div>
                    <div class="formula-palette">
                        <select class="formula-metric-select" id="nm-formula-metric-select">
                            <option value="">Добавить метрику...</option>
                        </select>
                        <div class="formula-op-buttons">
                            <button type="button" class="formula-op-btn" data-op="+">+</button>
                            <button type="button" class="formula-op-btn" data-op="-">−</button>
                            <button type="button" class="formula-op-btn" data-op="*">×</button>
                            <button type="button" class="formula-op-btn" data-op="/">÷</button>
                            <button type="button" class="formula-op-btn" data-op="(">(</button>
                            <button type="button" class="formula-op-btn" data-op=")">)</button>
                        </div>
                        <div class="formula-number-add">
                            <input type="number" id="nm-formula-num-input" placeholder="0" step="any">
                            <button type="button" id="nm-formula-add-num">Число</button>
                            <button type="button" class="formula-clear-btn" id="nm-formula-clear-last">← Удалить</button>
                        </div>
                    </div>
                    <div class="formula-result-type">
                        <span class="label-text">Тип результата</span>
                        <select id="nm-result-type">
                            <option value="float" ${existingMetric?.result_type === 'float' ? 'selected' : ''}>Дробное число</option>
                            <option value="int" ${existingMetric?.result_type === 'int' ? 'selected' : ''}>Целое число</option>
                            <option value="bool" ${existingMetric?.result_type === 'bool' ? 'selected' : ''}>Да/Нет</option>
                            <option value="time" ${existingMetric?.result_type === 'time' ? 'selected' : ''}>Время</option>
                        </select>
                    </div>
                    <span class="label-hint">Поддерживаются +, −, ×, ÷ и скобки.</span>
                </div>
                ` : ''}
                <div class="form-section" id="nm-slots-section" ${currentType === 'computed' ? 'style="display:none"' : ''}>
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
                        <label class="radio-inline">
                            <input type="radio" name="nm-type" value="computed" ${currentType === 'computed' ? 'checked' : ''}>
                            <span>Формула</span>
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
                <div class="form-section" id="nm-computed-config" style="display: ${currentType === 'computed' ? 'block' : 'none'}">
                    <span class="label-text">Формула</span>
                    <div class="formula-tokens" id="nm-formula-tokens">
                        <span class="formula-tokens-empty">Добавьте метрики и операторы</span>
                    </div>
                    <div class="formula-palette">
                        <select class="formula-metric-select" id="nm-formula-metric-select">
                            <option value="">Добавить метрику...</option>
                        </select>
                        <div class="formula-op-buttons">
                            <button type="button" class="formula-op-btn" data-op="+">+</button>
                            <button type="button" class="formula-op-btn" data-op="-">−</button>
                            <button type="button" class="formula-op-btn" data-op="*">×</button>
                            <button type="button" class="formula-op-btn" data-op="/">÷</button>
                            <button type="button" class="formula-op-btn" data-op="(">(</button>
                            <button type="button" class="formula-op-btn" data-op=")">)</button>
                        </div>
                        <div class="formula-number-add">
                            <input type="number" id="nm-formula-num-input" placeholder="0" step="any">
                            <button type="button" id="nm-formula-add-num">Число</button>
                            <button type="button" class="formula-clear-btn" id="nm-formula-clear-last">← Удалить</button>
                        </div>
                    </div>
                    <div class="formula-result-type">
                        <span class="label-text">Тип результата</span>
                        <select id="nm-result-type">
                            <option value="float">Дробное число</option>
                            <option value="int">Целое число</option>
                            <option value="bool">Да/Нет</option>
                            <option value="time">Время</option>
                        </select>
                    </div>
                    <span class="label-hint">Поддерживаются +, −, ×, ÷ и скобки. Время можно комбинировать только с временем.</span>
                </div>
                <div class="form-section" id="nm-slots-section" style="display: ${currentType === 'computed' ? 'none' : ''}">
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
                const computedConfig = document.getElementById('nm-computed-config');
                const slotsSection = document.getElementById('nm-slots-section');
                if (scaleConfig) scaleConfig.style.display = selectedType === 'scale' ? 'flex' : 'none';
                if (computedConfig) computedConfig.style.display = selectedType === 'computed' ? 'block' : 'none';
                if (slotsSection) slotsSection.style.display = selectedType === 'computed' ? 'none' : '';
                if (selectedType === 'computed') {
                    formulaTokens = [];
                    formulaBuilderInitialized = false;
                    renderFormulaTokens();
                    populateFormulaMetricSelect();
                    setupFormulaBuilderHandlers(overlay);
                }
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
    } else if (currentType === 'computed') {
        // Edit mode: pre-populate formula builder
        formulaTokens = (existingMetric.formula || []).map(t => {
            if (t.type === 'metric') {
                const m = metrics.find(mm => mm.id === t.id);
                return { ...t, name: m ? m.name : t.slug, icon: m ? m.icon : undefined };
            }
            return { ...t };
        });
        formulaBuilderInitialized = false;
        renderFormulaTokens();
        populateFormulaMetricSelect(existingMetric.id);
        setupFormulaBuilderHandlers(overlay);
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
                if (existingMetric.type === 'computed') {
                    if (formulaTokens.length === 0) {
                        alert('Добавьте хотя бы один элемент в формулу');
                        return;
                    }
                    updateData.formula = formulaTokens.map(t => {
                        if (t.type === 'metric') return { type: 'metric', id: t.id, slug: t.slug };
                        if (t.type === 'op') return { type: 'op', value: t.value };
                        if (t.type === 'number') return { type: 'number', value: t.value };
                        if (t.type === 'lparen') return { type: 'lparen' };
                        if (t.type === 'rparen') return { type: 'rparen' };
                        return t;
                    });
                    updateData.result_type = document.getElementById('nm-result-type').value;
                }
                if (existingMetric.type === 'scale') {
                    const sp = getScaleParams();
                    updateData.scale_min = sp.min;
                    updateData.scale_max = sp.max;
                    updateData.scale_step = sp.step;
                }
                // Send slot_labels if user configured slots (not for computed)
                if (existingMetric.type !== 'computed') {
                    if (slotLabels.length >= 2) {
                        updateData.slot_labels = slotLabels;
                    } else if (slotLabels.length === 0 && (!existingMetric.slots || existingMetric.slots.length === 0)) {
                        // No slots before, no slots now — don't send
                    } else if (slotLabels.length < 2 && existingMetric.slots && existingMetric.slots.length > 0) {
                        alert('Нельзя уменьшить количество замеров меньше 2. Удалите все поля, чтобы не менять настройку.');
                        return;
                    }
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

                if (selectedType === 'computed') {
                    if (formulaTokens.length === 0) {
                        alert('Добавьте хотя бы один элемент в формулу');
                        return;
                    }
                    createData.formula = formulaTokens.map(t => {
                        if (t.type === 'metric') return { type: 'metric', id: t.id, slug: t.slug };
                        if (t.type === 'op') return { type: 'op', value: t.value };
                        if (t.type === 'number') return { type: 'number', value: t.value };
                        if (t.type === 'lparen') return { type: 'lparen' };
                        if (t.type === 'rparen') return { type: 'rparen' };
                        return t;
                    });
                    createData.result_type = document.getElementById('nm-result-type').value;
                }

                if (selectedType !== 'computed' && slotLabels.length >= 2) {
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
