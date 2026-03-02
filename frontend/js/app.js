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
    const entry = m.entry;
    const val = entry ? entry.value : null;
    const entryId = entry ? entry.id : null;

    const isFilled = !!entry;
    const filledClass = isFilled ? 'filled' : '';

    const input = m.type === 'time' ? renderTime(val) : renderBoolean(val);

    const clearBtn = entry
        ? `<button class="metric-clear-btn" data-clear-entry="${entryId}" title="Очистить">&times;</button>`
        : '';

    return `<div class="metric-card ${filledClass}" data-metric-id="${m.metric_id}" data-metric-type="${m.type}" data-entry-id="${entryId || ''}">
        <div class="metric-header">
            <label class="metric-label">${m.name}</label>
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

function renderTime(val) {
    return `<input type="time" class="time-input" value="${val || ''}">`;
}

// ─── Event Handlers ───
function attachInputHandlers() {
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
            await saveDaily(metricId, entryId, boolVal);
            await renderTodayForm();
        } catch (error) {
            alert('Ошибка: ' + error.message);
        }
        return;
    }
}

async function handleFormChange(e) {
    const input = e.target;
    if (!input.classList.contains('time-input')) return;

    const card = input.closest('.metric-card');
    if (!card) return;

    const metricId = card.dataset.metricId;
    const entryId = card.dataset.entryId;
    const value = input.value; // "HH:MM"

    if (!value) return;

    try {
        await saveDaily(metricId, entryId, value);
        await renderTodayForm();
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

async function saveDaily(metricId, entryId, value) {
    if (entryId) {
        await api.updateEntry(parseInt(entryId), { value });
    } else {
        await api.createEntry({
            metric_id: parseInt(metricId),
            date: currentDate,
            value,
        });
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

    const firstDay = (new Date(year, month - 1, 1).getDay() + 6) % 7;
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
        if (!m.entry) continue;
        let valStr;
        if (m.type === 'time') {
            valStr = m.entry.value || '—';
        } else {
            valStr = m.entry.value ? 'Да' : 'Нет';
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

    // Trends — show for all bool metrics (True=1, False=0)
    const trendsEl = document.getElementById('trends-section');
    let trendsHtml = '<h3>Тренды</h3><div class="trends">';
    for (const m of metrics) {
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
    let corrHtml = '<h3>Корреляции</h3><div class="corr-controls">';
    corrHtml += `<select id="corr-a">${metrics.map(m => `<option value="${m.id}">${m.name}</option>`).join('')}</select>`;
    corrHtml += ` vs `;
    corrHtml += `<select id="corr-b">${metrics.map(m => `<option value="${m.id}">${m.name}</option>`).join('')}</select>`;
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
async function renderSettings(container) {
    const allMetrics = await api.getMetrics(false);
    let html = '<div class="settings-header">';
    html += `<div class="user-info">Пользователь: ${localStorage.getItem('la_username') || 'Unknown'}</div>`;
    html += '<button class="btn-small" id="logout-btn">Выйти</button>';
    html += '</div>';
    html += '<h2>Настройки метрик</h2>';
    html += '<div class="settings-actions">';
    html += '<button class="btn-primary" id="add-metric">+ Новая метрика</button>';
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
            html += `<div class="setting-row">
                <div class="setting-info">
                    <span class="setting-name ${m.enabled ? '' : 'disabled'}">${m.name}</span>
                    <span class="setting-type">${m.type === 'time' ? 'Время' : 'Да/Нет'}</span>
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

    container.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const metricId = btn.dataset.metric;
            const currentEnabled = btn.dataset.enabled === 'true';
            const newEnabled = !currentEnabled;
            try {
                await api.updateMetric(metricId, { enabled: newEnabled });
                await renderSettings(container);
            } catch (error) {
                alert('Ошибка: ' + error.message);
            }
        });
    });

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

    function previewInputHtml(type) {
        if (type === 'time') {
            return `<input type="time" class="time-input" value="">`;
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
                    <span class="label-hint">Как метрика будет отображаться</span>
                </label>

                <label class="form-label">
                    <span class="label-text">Категория</span>
                    <input id="nm-cat" placeholder="Например: Утро" class="form-input" value="${existingMetric?.category || ''}">
                    <span class="label-hint">Для группировки метрик</span>
                </label>

                ${isEdit ? `
                <div class="form-section" id="nm-type-section">
                    ${typeHintHtml(currentType)}
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
                    </div>
                </div>
                `}
            </div>

            <div class="modal-preview-column">
                <div class="preview-sticky">
                    <span class="label-text">Превью</span>
                    <div id="metric-preview" class="metric-preview">
                        <div class="metric-card" id="preview-card">
                            <div class="metric-header">
                                <label class="metric-label">${existingMetric?.name || 'Название метрики'}</label>
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

    // Update preview on name change
    document.getElementById('nm-name').addEventListener('input', () => {
        const name = document.getElementById('nm-name').value || 'Название метрики';
        const label = document.querySelector('#preview-card .metric-label');
        if (label) label.textContent = name;
    });

    // Type selector change (only in create mode)
    if (!isEdit) {
        overlay.querySelectorAll('input[name="nm-type"]').forEach(radio => {
            radio.addEventListener('change', () => {
                const selectedType = overlay.querySelector('input[name="nm-type"]:checked').value;
                document.getElementById('preview-input').innerHTML = previewInputHtml(selectedType);
                setupPreviewInteractions();
            });
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
    }
    setupPreviewInteractions();

    document.getElementById('nm-cancel').onclick = () => overlay.remove();
    document.getElementById('nm-save').onclick = async () => {
        const name = document.getElementById('nm-name').value;
        const category = document.getElementById('nm-cat').value;

        if (!name || !category) {
            alert('Заполните название и категорию');
            return;
        }

        try {
            if (isEdit) {
                await api.updateMetric(existingMetric.id, { name, category });
            } else {
                const typeRadio = overlay.querySelector('input[name="nm-type"]:checked');
                const selectedType = typeRadio ? typeRadio.value : 'bool';

                const slug = name.toLowerCase()
                    .replace(/\s+/g, '_')
                    .replace(/[^a-z0-9_а-яё]/gi, '')
                    || 'metric_' + Date.now();

                await api.createMetric({
                    slug,
                    name,
                    category,
                    type: selectedType,
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

function daysAgo(n) {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
}
