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
        nav.style.display = (page === 'login' || page === 'register') ? 'none' : 'flex';
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
        <div class="page-header">
            <button class="btn-icon" id="prev-day">&larr;</button>
            <h2 id="current-date-label"></h2>
            <button class="btn-icon" id="next-day">&rarr;</button>
            <button class="btn-small" id="go-today">Сегодня</button>
        </div>
        <div id="metrics-form"></div>
    `;

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
}

function renderMetricInput(m) {
    const entry = m.entries[0];
    const val = entry ? entry.value : null;
    const entryId = entry ? entry.id : null;

    // Check if daily metric is filled
    const isFilled = m.measurements_per_day === 1 && entry;
    const filledClass = isFilled ? 'filled' : '';

    let input = '';

    if (m.measurements_per_day > 1) {
        // Show quick buttons + list of entries
        input = renderMultipleInput(m);
    } else if (m.type === 'scale') {
        input = renderScale(m, val);
    } else if (m.type === 'bool') {
        input = renderBoolean(m, val);
    } else if (m.type === 'number') {
        input = renderNumber(m, val);
    } else if (m.type === 'time') {
        input = renderTime(m, val);
    }

    // Add clear button for daily metrics with entries
    const clearBtn = (m.measurements_per_day === 1 && entry)
        ? `<button class="metric-clear-btn" data-clear-entry="${entryId}" title="Очистить">&times;</button>`
        : '';

    return `<div class="metric-card ${filledClass}" data-metric-id="${m.metric_id}" data-entry-id="${entryId || ''}" data-metric-type="${m.type}" data-display-mode="${m.config.display_mode || ''}">
        <div class="metric-header">
            <label class="metric-label">${m.name}</label>
            ${clearBtn}
        </div>
        <div class="metric-input">${input}</div>
    </div>`;
}

function renderScale(m, val) {
    const cfg = m.config;
    const min = cfg.min_value || 1;
    const max = cfg.max_value || 5;
    const current = val ? val.value : null;
    let html = '<div class="scale-buttons">';
    for (let i = min; i <= max; i++) {
        const active = current === i ? 'active' : '';
        html += `<button class="scale-btn ${active}" data-value="${i}">${i}</button>`;
    }
    html += '</div>';
    return html;
}

function renderBoolean(m, val) {
    const current = val ? val.value : null;
    return `<div class="bool-buttons">
        <button class="bool-btn ${current === true ? 'active yes' : ''}" data-value="true">Да</button>
        <button class="bool-btn ${current === false ? 'active no' : ''}" data-value="false">Нет</button>
    </div>`;
}

function renderNumber(m, val) {
    const cfg = m.config;

    if (cfg.display_mode === 'bool_number') {
        return renderBoolNumber(m, val);
    }

    const current = val ? val.number_value : 0;
    const step = cfg.step || 1;
    const min = cfg.min_value ?? 0;
    const max = cfg.max_value ?? 999;
    const label = cfg.unit_label || '';
    return `<div class="number-input">
        <button class="number-btn" data-action="decrement" data-step="${step}" data-min="${min}">−</button>
        <input type="number" value="${current}" step="${step}" min="${min}" max="${max}" data-field="number_value">
        <span class="unit">${label}</span>
        <button class="number-btn" data-action="increment" data-step="${step}" data-max="${max}">+</button>
    </div>`;
}

function renderBoolNumber(m, val) {
    const cfg = m.config;
    const boolVal = val ? val.bool_value : null;
    const numVal = val ? val.number_value : 0;
    const boolLabel = cfg.bool_label || 'Было';
    const numberLabel = cfg.number_label || 'Количество';
    const step = cfg.step || 1;
    const min = cfg.min_value ?? 0;
    const max = cfg.max_value ?? 999;
    const numberHidden = boolVal !== true ? 'hidden' : '';

    return `<div class="bool-number-fields">
        <div class="bool-number-bool">
            <label class="field-label">${boolLabel}</label>
            <div class="bool-buttons">
                <button class="bool-btn ${boolVal === true ? 'active yes' : ''}" data-value="true" data-bool-number="bool">Да</button>
                <button class="bool-btn ${boolVal === false ? 'active no' : ''}" data-value="false" data-bool-number="bool">Нет</button>
            </div>
        </div>
        <div class="bool-number-number ${numberHidden}">
            <label class="field-label">${numberLabel}</label>
            <div class="number-input">
                <button class="number-btn" data-action="decrement" data-step="${step}" data-min="${min}">−</button>
                <input type="number" value="${numVal || 0}" step="${step}" min="${min}" max="${max}" data-field="number_value" data-bool-number="number">
                <button class="number-btn" data-action="increment" data-step="${step}" data-max="${max}">+</button>
            </div>
        </div>
    </div>`;
}

function renderTime(m, val) {
    const current = val ? val.value : '';
    return `<input type="time" value="${current}" data-field="value" class="time-input">`;
}


function renderMultipleInput(m) {
    const cfg = m.config;
    const min = cfg.min_value || 1;
    const max = cfg.max_value || 5;
    const labels = m.measurement_labels || [];

    // Group entries by measurement_number
    const byMeasurement = {};
    for (const e of m.entries) {
        const mn = e.measurement_number;
        if (!byMeasurement[mn] || e.id > byMeasurement[mn].id) {
            byMeasurement[mn] = e;
        }
    }

    let html = '<div class="multiple-entry">';

    for (let i = 1; i <= m.measurements_per_day; i++) {
        const label = labels[i - 1] || `Измерение ${i}`;
        const entry = byMeasurement[i] || null;
        const currentValue = entry ? entry.value.value : null;
        const entryId = entry ? entry.id : '';
        const clearBtn = entry ? `<button class="period-clear-btn" data-clear-period-entry="${entryId}" title="Очистить">&times;</button>` : '';

        html += `<div class="period-section" data-measurement-number="${i}" data-period-entry-id="${entryId}">`;
        html += `<div class="period-header">`;
        html += `<label class="period-label">${label}</label>`;
        html += clearBtn;
        html += `</div>`;
        html += '<div class="scale-buttons">';
        for (let v = min; v <= max; v++) {
            const active = currentValue === v ? 'active' : '';
            html += `<button class="scale-btn ${active}" data-period-value="${v}" data-measurement-number="${i}">${v}</button>`;
        }
        html += '</div>';
        html += '</div>';
    }

    // Show summary if there are any entries
    if (m.summary && Object.keys(byMeasurement).length > 0) {
        html += `<div class="summary-line">Среднее: ${m.summary.avg} | Мин: ${m.summary.min} | Макс: ${m.summary.max}</div>`;
    }

    html += '</div>';
    return html;
}

// ─── Event Handlers ───
function attachInputHandlers() {
    // Delegate events from metrics-form
    const form = document.getElementById('metrics-form');
    form.addEventListener('click', handleFormClick);
    form.addEventListener('change', handleFormChange);
}

async function handleFormClick(e) {
    const btn = e.target;
    const card = btn.closest('.metric-card');
    if (!card) return;

    const metricId = card.dataset.metricId;
    const entryId = card.dataset.entryId;

    console.log('Click detected:', { metricId, entryId, btn: btn.className });

    // Clear metric entry (daily metrics)
    if (btn.dataset.clearEntry) {
        try {
            const clearEntryId = parseInt(btn.dataset.clearEntry);
            console.log('Clear entry clicked:', clearEntryId);
            await api.deleteEntry(clearEntryId);
            await renderTodayForm();
        } catch (error) {
            console.error('Error clearing entry:', error);
            alert('Ошибка при удалении: ' + error.message);
        }
        return;
    }

    // Clear period entry (multiple-frequency metrics)
    if (btn.dataset.clearPeriodEntry) {
        try {
            const clearEntryId = parseInt(btn.dataset.clearPeriodEntry);
            console.log('Clear period entry clicked:', clearEntryId);
            await api.deleteEntry(clearEntryId);
            await renderTodayForm();
        } catch (error) {
            console.error('Error clearing period entry:', error);
            alert('Ошибка при удалении: ' + error.message);
        }
        return;
    }

    // Number increment/decrement buttons
    if (btn.dataset.action === 'increment' || btn.dataset.action === 'decrement') {
        try {
            const input = card.querySelector('input[type="number"]');
            const step = parseFloat(btn.dataset.step) || 1;
            const currentValue = parseFloat(input.value) || 0;
            let newValue;

            if (btn.dataset.action === 'increment') {
                const max = parseFloat(btn.dataset.max) || 999;
                newValue = Math.min(currentValue + step, max);
            } else {
                const min = parseFloat(btn.dataset.min) || 0;
                newValue = Math.max(currentValue - step, min);
            }

            input.value = newValue;
            console.log('Number button clicked:', { action: btn.dataset.action, currentValue, newValue });

            const value = { number_value: newValue };
            // For bool_number, include bool_value from DOM
            if (card.dataset.displayMode === 'bool_number') {
                const activeBtn = card.querySelector('.bool-btn.active[data-bool-number="bool"]');
                value.bool_value = activeBtn ? activeBtn.dataset.value === 'true' : null;
            }

            await saveDaily(metricId, entryId, value);
            await renderTodayForm();
        } catch (error) {
            console.error('Error in number button handler:', error);
            alert('Ошибка: ' + error.message);
        }
        return;
    }

    // Measurement-number scale buttons (for multi-measurement metrics)
    if (btn.dataset.periodValue && btn.dataset.measurementNumber) {
        try {
            const measurementNumber = parseInt(btn.dataset.measurementNumber);
            const value = parseInt(btn.dataset.periodValue);
            const periodSection = btn.closest('.period-section');
            const periodEntryId = periodSection ? periodSection.dataset.periodEntryId : '';

            console.log('Measurement button clicked:', { metricId, measurementNumber, value, periodEntryId });

            if (periodEntryId) {
                // Update existing entry
                await api.updateEntry(parseInt(periodEntryId), {
                    value: { value }
                });
            } else {
                // Create new entry
                await api.createEntry({
                    metric_id: parseInt(metricId),
                    date: currentDate,
                    measurement_number: measurementNumber,
                    value: { value },
                });
            }
            await renderTodayForm();
        } catch (error) {
            console.error('Error in measurement button handler:', error);
            alert('Ошибка: ' + error.message);
        }
        return;
    }

    // Delete entry
    if (btn.dataset.deleteEntry) {
        await api.deleteEntry(parseInt(btn.dataset.deleteEntry));
        renderTodayForm();
        return;
    }

    // Scale buttons (daily)
    if (btn.classList.contains('scale-btn') && !btn.dataset.quickValue) {
        try {
            const value = { value: parseInt(btn.dataset.value) };
            console.log('Saving scale value:', { metricId, entryId, value });
            await saveDaily(metricId, entryId, value);
            console.log('Save successful, re-rendering...');
            await renderTodayForm();
        } catch (error) {
            console.error('Error saving scale value:', error);
            alert('Ошибка сохранения: ' + error.message);
        }
        return;
    }

    // Boolean buttons
    if (btn.classList.contains('bool-btn')) {
        try {
            const boolVal = btn.dataset.value === 'true';
            console.log('Boolean button clicked:', { metricId, boolVal });

            if (btn.dataset.boolNumber === 'bool') {
                // bool_number display mode: save both bool_value and number_value
                const numberInput = card.querySelector('input[data-bool-number="number"]');
                const numberValue = numberInput ? parseFloat(numberInput.value) || 0 : 0;
                const value = { bool_value: boolVal, number_value: numberValue };

                // Toggle number section visibility
                const numberSection = card.querySelector('.bool-number-number');
                if (numberSection) {
                    numberSection.classList.toggle('hidden', !boolVal);
                }

                await saveDaily(metricId, entryId, value);
                await renderTodayForm();
            } else {
                await saveDaily(metricId, entryId, { value: boolVal });
                await renderTodayForm();
            }
        } catch (error) {
            console.error('Error in boolean handler:', error);
            alert('Ошибка: ' + error.message);
        }
        return;
    }

    console.log('No handler matched for this button:', btn);
}

async function handleFormChange(e) {
    const input = e.target;
    const card = input.closest('.metric-card');
    if (!card) return;

    const metricId = card.dataset.metricId;
    const entryId = card.dataset.entryId;

    if (input.dataset.field === 'number_value') {
        const value = { number_value: parseFloat(input.value) };
        // For bool_number, include bool_value from DOM
        if (card.dataset.displayMode === 'bool_number') {
            const activeBtn = card.querySelector('.bool-btn.active[data-bool-number="bool"]');
            value.bool_value = activeBtn ? activeBtn.dataset.value === 'true' : null;
        }
        await saveDaily(metricId, entryId, value);
    } else if (input.dataset.field === 'value') {
        let v = input.value;
        if (input.type === 'number') v = parseFloat(v);
        await saveDaily(metricId, entryId, { value: v });
    }
}

async function saveDaily(metricId, entryId, value) {
    console.log('saveDaily called:', { metricId, entryId, value, currentDate });
    try {
        if (entryId) {
            const result = await api.updateEntry(parseInt(entryId), { value });
            console.log('Update result:', result);
        } else {
            const result = await api.createEntry({
                metric_id: parseInt(metricId),
                date: currentDate,
                measurement_number: 1,
                value,
            });
            console.log('Create result:', result);
        }
    } catch (error) {
        console.error('Error in saveDaily:', error);
        throw error;
    }
}

// ─── History Page ───
async function renderHistory(container) {
    container.innerHTML = `
        <h2>История</h2>
        <input type="month" id="history-month" value="${currentDate.slice(0, 7)}">
        <div id="history-calendar" class="calendar-grid"></div>
        <div id="day-detail"></div>
    `;

    document.getElementById('history-month').addEventListener('change', (e) => {
        renderCalendar(e.target.value);
    });
    renderCalendar(currentDate.slice(0, 7));
}

async function renderCalendar(yearMonth) {
    const [year, month] = yearMonth.split('-').map(Number);
    const daysInMonth = new Date(year, month, 0).getDate();
    const grid = document.getElementById('history-calendar');

    const dayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
    let html = dayNames.map(d => `<div class="cal-header">${d}</div>`).join('');

    // Offset for first day
    const firstDay = (new Date(year, month - 1, 1).getDay() + 6) % 7; // Mon=0
    for (let i = 0; i < firstDay; i++) html += '<div class="cal-empty"></div>';

    for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const isToday = dateStr === todayStr() ? 'today' : '';
        html += `<div class="cal-day ${isToday}" data-date="${dateStr}">${d}</div>`;
    }
    grid.innerHTML = html;

    grid.querySelectorAll('.cal-day').forEach(el => {
        el.addEventListener('click', () => showDayDetail(el.dataset.date));
    });
}

async function showDayDetail(date) {
    const detail = document.getElementById('day-detail');
    const summary = await api.getDailySummary(date);
    let html = `<h3>${formatDate(date)}</h3><div class="day-summary">`;

    for (const m of summary.metrics) {
        if (m.entries.length === 0) continue;
        let valStr = '';
        if (m.measurements_per_day > 1 && m.summary) {
            valStr = `среднее: ${m.summary.avg}`;
        } else if (m.entries[0]) {
            valStr = formatValue(m.entries[0].value, m.type);
        }
        html += `<div class="summary-row"><span class="summary-label">${m.name}</span><span class="summary-value">${valStr}</span></div>`;
    }
    html += '</div>';
    detail.innerHTML = html;
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
            html += `<div class="streak-card"><span class="streak-count">${s.current_streak}</span><span class="streak-label">${s.metric_name}</span><span class="streak-unit">дней подряд</span></div>`;
        }
        html += '</div>';
        streaksEl.innerHTML = html;
    } else {
        streaksEl.innerHTML = '';
    }

    // Trends — show for scale/number metrics
    const trendsEl = document.getElementById('trends-section');
    let trendsHtml = '<h3>Тренды</h3><div class="trends">';
    for (const m of metrics) {
        if (!['scale', 'number'].includes(m.type)) continue;
        const trend = await api.getTrends(m.id, start, end);
        if (trend.points && trend.points.length > 0) {
            trendsHtml += `<div class="trend-card"><h4>${m.name}</h4><div class="mini-chart" data-points='${JSON.stringify(trend.points)}'></div></div>`;
        }
    }
    trendsHtml += '</div>';
    trendsEl.innerHTML = trendsHtml;
    renderMiniCharts();

    // Correlation selector
    const corrEl = document.getElementById('correlation-section');
    const scaleMetrics = metrics.filter(m => ['scale', 'number', 'bool'].includes(m.type));
    let corrHtml = '<h3>Корреляции</h3><div class="corr-controls">';
    corrHtml += `<select id="corr-a">${scaleMetrics.map(m => `<option value="${m.id}">${m.name}</option>`).join('')}</select>`;
    corrHtml += ` vs `;
    corrHtml += `<select id="corr-b">${scaleMetrics.map(m => `<option value="${m.id}">${m.name}</option>`).join('')}</select>`;
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

        const values = points.map(p => p.avg);
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
async function renderSettings(container) {
    // Load ALL metrics for settings (not just enabled)
    const allMetrics = await api.getMetrics(false);
    let html = '<div class="settings-header">';
    html += `<div class="user-info">Пользователь: ${localStorage.getItem('la_username') || 'Unknown'}</div>`;
    html += '<button class="btn-small" id="logout-btn">Выйти</button>';
    html += '</div>';
    html += '<h2>Настройки метрик</h2>';
    html += '<div class="settings-actions">';
    html += '<button class="btn-primary" id="add-metric">+ Новая метрика</button>';
    html += '<button class="btn-small" id="import-defaults-btn">📋 Добавить дефолтные метрики</button>';
    html += '<button class="btn-small" id="export-btn">📥 Экспорт ZIP</button>';
    html += '<button class="btn-small" id="import-btn">📤 Импорт ZIP</button>';
    html += '</div>';
    html += '<input type="file" id="import-file" accept=".zip" style="display:none">';

    const categories = {};
    for (const m of allMetrics) {
        categories[m.category] = categories[m.category] || [];
        categories[m.category].push(m);
    }

    for (const [cat, items] of Object.entries(categories)) {
        html += `<div class="category"><h3>${cat}</h3>`;
        for (const m of items) {
            const typeLabel = getTypeLabel(m.type);
            const freqLabel = getFrequencyLabel(m.measurements_per_day);
            html += `<div class="setting-row">
                <div class="setting-info">
                    <span class="setting-name ${m.enabled ? '' : 'disabled'}">${m.name}</span>
                    <span class="setting-type">${typeLabel} • ${freqLabel}</span>
                </div>
                <div class="setting-actions">
                    <button class="btn-icon edit-btn" data-metric="${m.id}">✏️</button>
                    <button class="btn-icon toggle-btn" data-metric="${m.id}" data-enabled="${m.enabled}">${m.enabled ? '&#x2714;' : '&#x2716;'}</button>
                    <button class="btn-icon delete-btn" data-metric="${m.id}">&times;</button>
                </div>
            </div>`;
        }
        html += '</div>';
    }
    container.innerHTML = html;

    document.getElementById('logout-btn').addEventListener('click', () => {
        api.logout();
        isAuthenticated = false;
        currentUser = null;
        navigateTo('login');
    });

    document.getElementById('add-metric').addEventListener('click', showAddMetricModal);

    // Import default metrics button
    document.getElementById('import-defaults-btn').addEventListener('click', async () => {
        if (!confirm('Импортировать дефолтные метрики?\n\n' +
                     'Существующие метрики будут обновлены, новые — добавлены.\n' +
                     'Ваши записи не будут затронуты.')) {
            return;
        }

        try {
            const result = await api.importDefaults();

            let message = '✅ Импорт дефолтных метрик завершён!\n\n';
            message += `📊 Создано: ${result.imported}\n`;
            message += `🔄 Обновлено: ${result.updated}\n`;

            if (result.errors && result.errors.length > 0) {
                message += '\n⚠️ Ошибки:\n' + result.errors.slice(0, 5).join('\n');
            }

            alert(message);

            await loadMetrics();
            await renderSettings(container);
        } catch (error) {
            alert('❌ Ошибка импорта: ' + error.message);
        }
    });

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

            alert('✅ Данные экспортированы!\n\nСкачан ZIP архив с метриками и записями.');
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

            let message = '✅ Импорт завершён!\n\n';
            message += `📊 Метрики:\n`;
            message += `  Создано: ${result.metrics.imported}\n`;
            message += `  Обновлено: ${result.metrics.updated}\n`;
            message += `\n📝 Записи:\n`;
            message += `  Импортировано: ${result.entries.imported}\n`;
            message += `  Пропущено: ${result.entries.skipped}\n`;

            if (result.metrics.errors.length > 0 || result.entries.errors.length > 0) {
                message += '\n⚠️ Ошибки:\n';
                if (result.metrics.errors.length > 0) {
                    message += 'Метрики:\n' + result.metrics.errors.join('\n') + '\n';
                }
                if (result.entries.errors.length > 0) {
                    message += 'Записи:\n' + result.entries.errors.join('\n');
                }
            }

            alert(message);

            // Refresh page to show new data
            await loadMetrics();
            navigateTo('today');
        } catch (error) {
            alert('Ошибка импорта: ' + error.message);
        } finally {
            e.target.value = ''; // Reset file input
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

    container.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const metricId = btn.dataset.metric;
            const currentEnabled = btn.dataset.enabled === 'true';
            const newEnabled = !currentEnabled;
            console.log('Toggle clicked:', { metricId, currentEnabled, newEnabled });
            try {
                await api.updateMetric(metricId, { enabled: newEnabled });
                await renderSettings(container);
            } catch (error) {
                console.error('Error toggling metric:', error);
                alert('Ошибка: ' + error.message);
            }
        });
    });

    container.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const metricId = btn.dataset.metric;
            console.log('Delete clicked:', metricId);
            if (confirm('Удалить метрику?')) {
                try {
                    await api.deleteMetric(metricId);
                    await renderSettings(container);
                } catch (error) {
                    console.error('Error deleting metric:', error);
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

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal modal-large">
            <h3>${title}</h3>

            <div class="modal-content-split">
            <div class="modal-form">
                <label class="form-label">
                    <span class="label-text">Название</span>
                    <input id="nm-name" placeholder="Например: Экранное время" class="form-input" value="${existingMetric?.name || ''}">
                    <span class="label-hint">Как метрика будет отображаться</span>
                </label>

                <label class="form-label">
                    <span class="label-text">Категория</span>
                    <input id="nm-cat" placeholder="Например: Продуктивность" class="form-input" value="${existingMetric?.category || ''}">
                    <span class="label-hint">Для группировки метрик</span>
                </label>

                <div class="form-section" id="type-section">
                    <span class="label-text">Тип значения${isEdit ? ' <span style="color: #666;">(нельзя изменить)</span>' : ''}</span>
                    <div class="radio-group">
                        <label class="radio-option">
                            <input type="radio" name="type" value="bool" ${!existingMetric || existingMetric.type === 'bool' ? 'checked' : ''} ${isEdit ? 'disabled' : ''}>
                            <div class="radio-content">
                                <strong>Да/Нет</strong>
                                <span>Простой выбор (например: "Тренировка была?")</span>
                            </div>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="type" value="number" ${existingMetric?.type === 'number' ? 'checked' : ''} ${isEdit ? 'disabled' : ''}>
                            <div class="radio-content">
                                <strong>Число</strong>
                                <span>Количество (например: "5 чашек кофе", "2.5 часа работы")</span>
                            </div>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="type" value="scale" ${existingMetric?.type === 'scale' ? 'checked' : ''} ${isEdit ? 'disabled' : ''}>
                            <div class="radio-content">
                                <strong>Шкала 1-5</strong>
                                <span>Оценка (например: "Качество сна: 4 из 5")</span>
                            </div>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="type" value="time" ${existingMetric?.type === 'time' ? 'checked' : ''} ${isEdit ? 'disabled' : ''}>
                            <div class="radio-content">
                                <strong>Время</strong>
                                <span>Указать время (например: "Подъем в 07:30")</span>
                            </div>
                        </label>
                    </div>
                </div>

                <div class="form-section" id="frequency-section">
                    <span class="label-text">Как часто заполнять</span>
                    <div class="radio-group">
                        <label class="radio-option">
                            <input type="radio" name="measurements_per_day" value="1" ${!existingMetric || existingMetric.measurements_per_day === 1 ? 'checked' : ''}>
                            <div class="radio-content">
                                <strong>Один раз в день</strong>
                                <span>Заполняется вечером при подведении итогов</span>
                            </div>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="measurements_per_day" value="3" ${existingMetric?.measurements_per_day === 3 ? 'checked' : ''}>
                            <div class="radio-content">
                                <strong>Три раза в день (оценка 1-5)</strong>
                                <span>Заполняется утром, днём и вечером. Автоматически использует шкалу 1-5 (для настроения, энергии, стресса)</span>
                            </div>
                        </label>
                    </div>
                </div>

                <div id="number-options" class="form-section" style="display: none;">
                    <span class="label-text">Настройки числа</span>

                    <div class="form-label">
                        <span class="label-text">Режим отображения</span>
                        <div class="radio-group-inline">
                            <label class="radio-inline">
                                <input type="radio" name="display_mode" value="number_only" checked>
                                <span>Только число</span>
                            </label>
                            <label class="radio-inline">
                                <input type="radio" name="display_mode" value="bool_number">
                                <span>Да/Нет + Число</span>
                            </label>
                        </div>
                    </div>

                    <div id="bool-number-labels" style="display: none;">
                        <div class="number-options-grid">
                            <label class="form-label-inline">
                                <span>Подпись Да/Нет</span>
                                <input id="nm-bool-label" placeholder="Например: Употреблял алкоголь" class="form-input-small">
                            </label>
                            <label class="form-label-inline">
                                <span>Подпись числа</span>
                                <input id="nm-number-label" placeholder="Например: Количество порций" class="form-input-small">
                            </label>
                        </div>
                    </div>

                    <div class="number-options-grid">
                        <label class="form-label-inline">
                            <span>Единица</span>
                            <input id="nm-unit" placeholder="часов" class="form-input-small">
                        </label>
                        <label class="form-label-inline">
                            <span>Мин</span>
                            <input id="nm-min" type="number" value="0" class="form-input-small">
                        </label>
                        <label class="form-label-inline">
                            <span>Макс</span>
                            <input id="nm-max" type="number" value="100" class="form-input-small">
                        </label>
                        <label class="form-label-inline">
                            <span>Шаг</span>
                            <input id="nm-step" type="number" value="1" step="0.1" class="form-input-small">
                        </label>
                    </div>
                </div>
            </div>

            <div class="modal-preview-column">
                <div class="preview-sticky">
                    <span class="label-text">Превью</span>
                    <div id="metric-preview" class="metric-preview">
                        <!-- Preview will be rendered here -->
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

    // Initialize number fields if editing a number metric
    if (isEdit && existingMetric && existingMetric.type === 'number' && existingMetric.config) {
        if (existingMetric.config.unit_label) {
            document.getElementById('nm-unit').value = existingMetric.config.unit_label;
        }
        if (existingMetric.config.min_value !== undefined) {
            document.getElementById('nm-min').value = existingMetric.config.min_value;
        }
        if (existingMetric.config.max_value !== undefined) {
            document.getElementById('nm-max').value = existingMetric.config.max_value;
        }
        if (existingMetric.config.step !== undefined) {
            document.getElementById('nm-step').value = existingMetric.config.step;
        }
        if (existingMetric.config.display_mode === 'bool_number') {
            const dmRadio = document.querySelector('input[name="display_mode"][value="bool_number"]');
            if (dmRadio) dmRadio.checked = true;
            document.getElementById('bool-number-labels').style.display = 'block';
            if (existingMetric.config.bool_label) {
                document.getElementById('nm-bool-label').value = existingMetric.config.bool_label;
            }
            if (existingMetric.config.number_label) {
                document.getElementById('nm-number-label').value = existingMetric.config.number_label;
            }
        }
    }

    // Update preview on any change
    const updatePreview = () => {
        const name = document.getElementById('nm-name').value || 'Название метрики';
        const measurementsPerDay = parseInt(document.querySelector('input[name="measurements_per_day"]:checked').value);

        // Get current type (or default to scale for multiple)
        let type;
        if (measurementsPerDay > 1) {
            type = 'scale';
            document.getElementById('type-section').style.display = 'none';
        } else {
            type = document.querySelector('input[name="type"]:checked').value;
            document.getElementById('type-section').style.display = 'block';
        }

        // Show/hide and enable/disable frequency options based on type
        const multipleOption = document.querySelector('input[name="measurements_per_day"][value="3"]');
        const multipleLabel = multipleOption.closest('.radio-option');

        if (measurementsPerDay === 1) {
            if (type === 'scale') {
                multipleLabel.style.display = 'flex';
            } else {
                multipleLabel.style.display = 'none';
                document.querySelector('input[name="measurements_per_day"][value="1"]').checked = true;
            }
        }

        // Show/hide options based on type
        const numberOpts = document.getElementById('number-options');
        numberOpts.style.display = (type === 'number' && measurementsPerDay === 1) ? 'block' : 'none';

        // Show/hide bool_number labels
        const displayMode = document.querySelector('input[name="display_mode"]:checked')?.value || 'number_only';
        const boolNumberLabels = document.getElementById('bool-number-labels');
        if (boolNumberLabels) {
            boolNumberLabels.style.display = displayMode === 'bool_number' ? 'block' : 'none';
        }

        // Build mock metric object
        const mockMetric = {
            metric_id: 'preview',
            name: name,
            type: type,
            measurements_per_day: measurementsPerDay,
            measurement_labels: measurementsPerDay === 3 ? ['Утро', 'День', 'Вечер'] : [],
            config: {},
            entries: []
        };

        if (type === 'scale') {
            mockMetric.config.min_value = 1;
            mockMetric.config.max_value = 5;
        } else if (type === 'number') {
            mockMetric.config.unit_label = document.getElementById('nm-unit').value;
            mockMetric.config.min_value = parseFloat(document.getElementById('nm-min').value) || 0;
            mockMetric.config.max_value = parseFloat(document.getElementById('nm-max').value) || 100;
            mockMetric.config.step = parseFloat(document.getElementById('nm-step').value) || 1;
            mockMetric.config.display_mode = displayMode;
            if (displayMode === 'bool_number') {
                mockMetric.config.bool_label = document.getElementById('nm-bool-label').value || 'Было';
                mockMetric.config.number_label = document.getElementById('nm-number-label').value || 'Количество';
            }
        }

        // Render preview
        const preview = document.getElementById('metric-preview');
        let previewHTML = '';

        if (measurementsPerDay > 1) {
            previewHTML = renderMultipleInput(mockMetric);
        } else if (type === 'scale') {
            previewHTML = renderScale(mockMetric, null);
        } else if (type === 'bool') {
            previewHTML = renderBoolean(mockMetric, null);
        } else if (type === 'number') {
            previewHTML = renderNumber(mockMetric, null);
        } else if (type === 'time') {
            previewHTML = renderTime(mockMetric, null);
        }

        preview.innerHTML = `
            <div class="metric-card" id="preview-card">
                <div class="metric-header">
                    <label class="metric-label">${name}</label>
                </div>
                <div class="metric-input">${previewHTML}</div>
            </div>
        `;

        // Make preview interactive for bool_number
        if (type === 'number' && displayMode === 'bool_number') {
            const previewCard = document.getElementById('preview-card');
            previewCard.querySelectorAll('.bool-btn[data-bool-number="bool"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    const parent = btn.closest('.bool-number-bool');
                    parent.querySelectorAll('.bool-btn').forEach(b => b.classList.remove('active', 'yes', 'no'));

                    const value = btn.dataset.value === 'true';
                    btn.classList.add('active', value ? 'yes' : 'no');

                    const numberSection = btn.closest('.bool-number-fields').querySelector('.bool-number-number');
                    if (numberSection) {
                        numberSection.classList.toggle('hidden', !value);
                    }
                });
            });
        }
    };

    // Attach event listeners
    document.getElementById('nm-name').addEventListener('input', updatePreview);
    document.getElementById('nm-cat').addEventListener('input', updatePreview);
    document.querySelectorAll('input[name="type"]').forEach(r => r.addEventListener('change', updatePreview));
    document.querySelectorAll('input[name="measurements_per_day"]').forEach(r => r.addEventListener('change', updatePreview));
    document.getElementById('nm-unit').addEventListener('input', updatePreview);
    document.getElementById('nm-min').addEventListener('input', updatePreview);
    document.getElementById('nm-max').addEventListener('input', updatePreview);
    document.getElementById('nm-step').addEventListener('input', updatePreview);
    document.querySelectorAll('input[name="display_mode"]').forEach(r => r.addEventListener('change', updatePreview));
    document.getElementById('nm-bool-label').addEventListener('input', updatePreview);
    document.getElementById('nm-number-label').addEventListener('input', updatePreview);

    updatePreview(); // Initial render

    document.getElementById('nm-cancel').onclick = () => overlay.remove();
    document.getElementById('nm-save').onclick = async () => {
        const name = document.getElementById('nm-name').value;
        const category = document.getElementById('nm-cat').value;

        if (!name || !category) {
            alert('Заполните название и категорию');
            return;
        }

        const measurementsPerDay = parseInt(document.querySelector('input[name="measurements_per_day"]:checked').value);

        // For multiple measurements, always use scale type
        // In edit mode, use existing type (it's disabled anyway)
        const type = isEdit
            ? existingMetric.type
            : (measurementsPerDay > 1 ? 'scale' : document.querySelector('input[name="type"]:checked').value);

        const config = {};
        if (type === 'scale') {
            config.min_value = 1;
            config.max_value = 5;
        } else if (type === 'number') {
            config.unit_label = document.getElementById('nm-unit').value;
            config.min_value = parseFloat(document.getElementById('nm-min').value) || 0;
            config.max_value = parseFloat(document.getElementById('nm-max').value) || 100;
            config.step = parseFloat(document.getElementById('nm-step').value) || 1;
            const displayMode = document.querySelector('input[name="display_mode"]:checked')?.value || 'number_only';
            config.display_mode = displayMode;
            if (displayMode === 'bool_number') {
                config.bool_label = document.getElementById('nm-bool-label').value || '';
                config.number_label = document.getElementById('nm-number-label').value || '';
            }
        }

        // Build measurement_labels for multi-measurement metrics
        let measurement_labels = [];
        if (measurementsPerDay === 3) {
            measurement_labels = ['Утро', 'День', 'Вечер'];
        }

        try {
            if (isEdit) {
                // Update existing metric (type excluded)
                await api.updateMetric(existingMetric.id, {
                    name,
                    category,
                    measurements_per_day: measurementsPerDay,
                    measurement_labels,
                    config
                });
            } else {
                // Generate slug from name (only for new metrics)
                const slug = name.toLowerCase()
                    .replace(/\s+/g, '_')
                    .replace(/[^a-z0-9_а-яё]/gi, '')
                    || 'metric_' + Date.now();

                // Create new metric
                await api.createMetric({
                    slug,
                    name,
                    category,
                    type,
                    measurements_per_day: measurementsPerDay,
                    measurement_labels,
                    config,
                });
            }

            overlay.remove();
            await loadMetrics();
            navigateTo('settings');
        } catch (error) {
            alert(`Ошибка ${isEdit ? 'обновления' : 'создания'} метрики: ` + error.message);
        }
    };
}

// Wrapper functions for compatibility
function showAddMetricModal() {
    showMetricModal('create');
}

function showEditMetricModal(metric) {
    showMetricModal('edit', metric);
}

// ─── Helpers ───
function formatDate(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' });
}

function formatValue(val, type) {
    if (!val) return '—';
    if (type === 'bool') return val.value ? 'Да' : 'Нет';
    if (type === 'time') return val.value || '—';
    if (type === 'scale') return val.value ?? '—';
    if (type === 'number') {
        if (val.bool_value !== undefined && val.bool_value !== null) {
            return val.bool_value ? (val.number_value ?? '—') : 'Нет';
        }
        return val.number_value ?? '—';
    }
    return '—';
}

function daysAgo(n) {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
}

function getTypeLabel(type) {
    const labels = {
        'bool': 'Да/Нет',
        'number': 'Число',
        'scale': 'Шкала 1-5',
        'time': 'Время',
    };
    return labels[type] || type;
}

function getFrequencyLabel(measurementsPerDay) {
    if (measurementsPerDay === 1) return 'Раз в день';
    if (measurementsPerDay === 3) return '3 раза в день';
    return `${measurementsPerDay} раз(а) в день`;
}
