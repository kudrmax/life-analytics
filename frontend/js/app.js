// ─── Constants ───
const TODOIST_ICON = '<svg viewBox="0 0 512 512" width="16" height="16" xmlns="http://www.w3.org/2000/svg"><rect width="512" height="512" rx="100" fill="#e44332"/><path d="M130 182l60 35 132-77 60 35" stroke="#fff" stroke-width="38" stroke-linecap="round" stroke-linejoin="round" fill="none"/><path d="M130 256l60 35 132-77 60 35" stroke="#fff" stroke-width="38" stroke-linecap="round" stroke-linejoin="round" fill="none"/><path d="M130 330l60 35 132-77 60 35" stroke="#fff" stroke-width="38" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>';
const AW_ICON = '<svg viewBox="0 0 100 100" width="16" height="16" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="48" fill="#6c5ce7"/><circle cx="50" cy="50" r="30" stroke="#fff" stroke-width="5" fill="none"/><path d="M50 28v22l16 10" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>';

// ─── Privacy Mode ───
const PRIVACY_KEY = 'la_privacy_mode';
function isPrivacyMode() { return localStorage.getItem(PRIVACY_KEY) === 'true'; }
function setPrivacyMode(on) { localStorage.setItem(PRIVACY_KEY, on ? 'true' : 'false'); }
const PRIVATE_MASK = '***';
const PRIVATE_ICON = '🔒';
function isMetricBlocked(m) { return m.private && isPrivacyMode(); }
function metricIconHtml(m) { const i = m.icon || ''; return i ? '<span class="metric-icon">' + i + '</span>' : ''; }
function metricLabelHtml(m) { return metricIconHtml(m) + m.name; }
function _pluralize(n, one, few, many) {
    const m = Math.abs(n) % 100;
    if (m >= 11 && m <= 19) return many;
    const d = m % 10;
    if (d === 1) return one;
    if (d >= 2 && d <= 4) return few;
    return many;
}

// ─── State ───
let currentDate = todayStr();
let metrics = [];
let currentPage = 'today';
let currentUser = null;
let isAuthenticated = false;
let corrPollInterval = null;
const corrPairData = new Map();
let _dependencyMetricIdsGlobal = new Set();
let _todayRenderVersion = 0;
let _historyRenderVersion = 0;
let _dayHeaderObserver = null;

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
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem(THEME_KEY, theme);
    const toggle = document.getElementById('theme-switch-input');
    if (toggle) toggle.checked = (theme === 'dark');
    const label = document.getElementById('theme-label');
    if (label) label.textContent = theme === 'light' ? 'Светлая тема' : 'Тёмная тема';
    const icon = document.getElementById('theme-icon-emoji');
    if (icon) icon.textContent = theme === 'light' ? '☀️' : '🌙';
}

function toggleTheme() {
    const currentTheme = localStorage.getItem(THEME_KEY) || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme);
}

// ─── Init ───
document.addEventListener('DOMContentLoaded', async () => {
    initTheme();
    setupNav();
    if (window.lucide) lucide.createIcons();
    await checkAuth();

    if (isAuthenticated) {
        const today = todayStr();
        await Promise.all([
            loadMetrics(),
            api.getDailySummary(today),
            api.cachedGet('/api/metrics'),
            api.awGetStatus(),
            api.getPrivacyMode().then(r => setPrivacyMode(r.privacy_mode)).catch(() => {}),
        ]);
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

    // Cleanup day header observer
    if (_dayHeaderObserver) { _dayHeaderObserver.disconnect(); _dayHeaderObserver = null; }
    // Cleanup polling
    if (corrPollInterval) { clearInterval(corrPollInterval); corrPollInterval = null; }
    // Cleanup correlation charts
    for (const [, c] of corrChartInstances) c.destroy();
    corrChartInstances.clear();

    // Hide nav for auth pages
    const nav = document.querySelector('nav');
    if (nav) {
        nav.style.display = (page === 'login' || page === 'register') ? 'none' : '';
    }

    const activePage = page === 'metric-detail' ? 'charts' : page === 'categories' ? 'settings' : page === 'insights' ? 'insights' : page;
    document.querySelectorAll('[data-page]').forEach(b => b.classList.toggle('active', b.dataset.page === activePage));
    const main = document.getElementById('main');

    switch (page) {
        case 'login': renderLogin(main); break;
        case 'register': renderRegister(main); break;
        case 'today': renderToday(main); break;
        case 'history': renderHistory(main); break;
        case 'charts': renderCharts(main); break;
        case 'analysis': renderAnalysis(main); break;
        case 'insights': renderInsights(main); break;
        case 'metric-detail': renderMetricDetail(main, params.metricId); break;
        case 'settings': renderSettings(main, params); break;
        case 'categories': renderCategoryManager(main); break;
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
            api.getPrivacyMode().then(r => setPrivacyMode(r.privacy_mode)).catch(() => {});
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
        <div class="today-actions" style="display:none">
            <button class="btn-small" id="today-edit-metrics">
                <i data-lucide="settings"></i> Редактировать метрики
            </button>
            <button class="btn-small" id="today-add-metric">
                <i data-lucide="plus"></i> Добавить метрику
            </button>
        </div>
    `;

    if (window.lucide) lucide.createIcons();

    // Sticky header shadow via IntersectionObserver
    if (_dayHeaderObserver) _dayHeaderObserver.disconnect();
    const sentinel = document.createElement('div');
    sentinel.className = 'day-header-sentinel';
    document.querySelector('.day-header').before(sentinel);
    _dayHeaderObserver = new IntersectionObserver(([e]) => {
        document.querySelector('.day-header')?.classList.toggle('scrolled', !e.isIntersecting);
    }, { threshold: 0 });
    _dayHeaderObserver.observe(sentinel);

    document.getElementById('prev-day').onclick = () => { changeDay(-1); };
    document.getElementById('next-day').onclick = () => { changeDay(1); };
    document.getElementById('go-today').onclick = () => { currentDate = todayStr(); renderTodayForm(true); };
    document.getElementById('today-add-metric').onclick = () => { navigateTo('settings', { openAddModal: true }); };
    document.getElementById('today-edit-metrics').onclick = () => { navigateTo('settings'); };

    // Swipe navigation for mobile
    const metricsForm = document.getElementById('metrics-form');
    let touchStartX = 0;
    let touchStartY = 0;
    metricsForm.addEventListener('touchstart', (e) => {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
    }, { passive: true });
    metricsForm.addEventListener('touchend', (e) => {
        const dx = e.changedTouches[0].clientX - touchStartX;
        const dy = e.changedTouches[0].clientY - touchStartY;
        if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
            changeDay(dx < 0 ? 1 : -1);
        }
    }, { passive: true });

    await renderTodayForm();
}

function changeDay(delta) {
    const d = new Date(currentDate);
    d.setDate(d.getDate() + delta);
    currentDate = d.toISOString().slice(0, 10);
    renderTodayForm(true, delta > 0 ? 'next' : 'prev');
}

async function renderTodayForm(preserveScroll = false, direction = null) {
    const _t0 = performance.now();
    const myVersion = ++_todayRenderVersion;
    document.getElementById('current-date-label').textContent = formatDate(currentDate);
    const goTodayBtn = document.getElementById('go-today');
    if (goTodayBtn) {
        goTodayBtn.style.display = (currentDate === todayStr()) ? 'none' : '';
    }
    const form = document.getElementById('metrics-form');
    const savedScrollY = preserveScroll ? window.scrollY : 0;

    if (preserveScroll && form.innerHTML && !form.querySelector('.loading-spinner')) {
        form.classList.add('loading-fade');
    } else {
        form.innerHTML = '<div class="loading-spinner"></div>';
    }
    let summary, awCard;
    [summary, awCard] = await Promise.all([
        api.getDailySummary(currentDate),
        (async () => {
            try {
                const awStatus = await api.awGetStatus();
                if (awStatus.enabled) {
                    const awSummary = await api.awGetSummary(currentDate);
                    return _renderAWSummaryCard(awSummary);
                }
            } catch (e) { /* AW not configured — skip */ }
            return '';
        })(),
    ]);
    if (myVersion !== _todayRenderVersion) return;

    // Load categories tree for grouping
    let categories = [];
    try { categories = await api.getCategories(); } catch(e) { console.warn('Failed to load categories', e); }

    // Build flat lookup: id -> category (including children)
    const catById = {};
    for (const c of categories) {
        catById[c.id] = c;
        for (const ch of (c.children || [])) catById[ch.id] = ch;
    }

    // Build metric name lookup and dependency tracking for conditions
    const metricNameById = {};
    _dependencyMetricIdsGlobal = new Set();
    for (const m of summary.metrics) {
        metricNameById[m.metric_id] = m.name;
        if (m.condition && m.condition.depends_on_metric_id) {
            _dependencyMetricIdsGlobal.add(m.condition.depends_on_metric_id);
        }
    }

    // Group metrics by category_id
    const metricsByCat = {};
    const uncategorized = [];
    for (const m of summary.metrics) {
        if (m.category_id && catById[m.category_id]) {
            if (!metricsByCat[m.category_id]) metricsByCat[m.category_id] = [];
            metricsByCat[m.category_id].push(m);
        } else {
            uncategorized.push(m);
        }
    }

    let html = '';
    const hasUserMetrics = summary.metrics.length > 0;

    if (!hasUserMetrics) {
        html += `<div class="empty-state">
            <div class="empty-state-icon"><i data-lucide="calendar-check"></i></div>
            <div class="empty-state-text">Вы пока не создали метрики, поэтому тут пусто</div>
            <button class="btn-primary" id="empty-create-metric">
                <i data-lucide="plus"></i> Создать метрику
            </button>
        </div>`;
    } else {
        html += `<h3 class="section-header">Ваши метрики <span class="corr-count">${new Set(summary.metrics.map(m => m.metric_id)).size}</span></h3>`;
        const hasCategories = categories.length > 0;

        for (const topCat of categories) {
            // Top-level: check if it or its children have metrics
            const topMetrics = metricsByCat[topCat.id] || [];
            const childrenWithMetrics = (topCat.children || []).filter(ch => (metricsByCat[ch.id] || []).length > 0);
            if (topMetrics.length === 0 && childrenWithMetrics.length === 0) continue;

            html += `<h2 class="fill-time-header">${topCat.name}</h2>`;
            if (topMetrics.length > 0) {
                html += `<div class="category">`;
                for (const m of topMetrics) html += renderMetricInput(m, metricNameById);
                html += '</div>';
            }
            for (const ch of (topCat.children || [])) {
                const chMetrics = metricsByCat[ch.id] || [];
                if (chMetrics.length === 0) continue;
                html += `<div class="category"><h3>${ch.name}</h3>`;
                for (const m of chMetrics) html += renderMetricInput(m, metricNameById);
                html += '</div>';
            }
        }
        if (uncategorized.length > 0) {
            if (hasCategories) html += `<h2 class="fill-time-header">Без категории</h2>`;
            html += `<div class="category">`;
            for (const m of uncategorized) html += renderMetricInput(m, metricNameById);
            html += '</div>';
        }
    }

    // Auto metrics section (collapsible)
    const autoMetrics = summary.auto_metrics || [];
    if (autoMetrics.length > 0) {
        const autoVisible = localStorage.getItem('la_auto_metrics_visible') === 'true';
        html += '<div class="auto-metrics-section">';
        html += `<div class="auto-metrics-header ${autoVisible ? 'expanded' : ''}" id="auto-metrics-toggle">
            <h3 class="section-header">Автоматические метрики</h3>
            <i data-lucide="chevron-down" class="auto-metrics-chevron"></i>
        </div>`;
        html += `<div class="auto-metrics-content" id="auto-metrics-content" style="display:${autoVisible ? 'block' : 'none'}">`;
        html += '<div class="auto-metrics-note">Вычисляются автоматически</div>';
        for (const am of autoMetrics) {
            const isBool = am.auto_type === 'nonzero';
            const isNoteCount = am.auto_type === 'note_count';
            let displayVal;
            if (isNoteCount) {
                displayVal = String(am.value);
            } else if (isBool) {
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
        html += '</div>'; // auto-metrics-content
        html += '</div>'; // auto-metrics-section
    }

    html += awCard;

    if (direction && preserveScroll) {
        const slideOut = direction === 'next' ? '-20px' : '20px';
        const slideIn  = direction === 'next' ? '20px' : '-20px';

        // Fade out
        form.style.transition = 'opacity 0.12s ease, transform 0.12s ease';
        form.style.opacity = '0';
        form.style.transform = `translateX(${slideOut})`;
        await new Promise(r => setTimeout(r, 120));

        if (myVersion !== _todayRenderVersion) return; // race check

        // Replace
        form.classList.remove('loading-fade');
        form.innerHTML = html;

        // Position for slide in
        form.style.transition = 'none';
        form.style.transform = `translateX(${slideIn})`;
        form.offsetHeight; // force reflow

        // Animate in
        form.style.transition = 'opacity 0.15s ease, transform 0.15s ease';
        form.style.opacity = '1';
        form.style.transform = 'translateX(0)';
        setTimeout(() => { form.style.transition = ''; form.style.transform = ''; }, 160);
    } else {
        form.classList.remove('loading-fade');
        form.innerHTML = html;
    }

    if (preserveScroll) {
        requestAnimationFrame(() => {
            const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
            window.scrollTo(0, Math.min(savedScrollY, Math.max(0, maxScroll)));
        });
    }

    if (window.lucide) lucide.createIcons();
    attachInputHandlers();

    // Empty state create button
    const emptyCreateBtn = document.getElementById('empty-create-metric');
    if (emptyCreateBtn) {
        emptyCreateBtn.addEventListener('click', () => {
            navigateTo('settings', { openAddModal: true });
        });
    }

    // Auto metrics toggle
    const autoToggle = document.getElementById('auto-metrics-toggle');
    if (autoToggle) {
        autoToggle.addEventListener('click', () => {
            const content = document.getElementById('auto-metrics-content');
            const isVisible = content.style.display !== 'none';
            content.style.display = isVisible ? 'none' : 'block';
            autoToggle.classList.toggle('expanded', !isVisible);
            localStorage.setItem('la_auto_metrics_visible', String(!isVisible));
        });
    }

    // Show/hide action buttons
    const actionsEl = document.querySelector('.today-actions');
    if (actionsEl) {
        actionsEl.style.display = hasUserMetrics ? '' : 'none';
    }

    // Update progress bar from backend
    const prog = summary.progress || {};
    const pct = prog.percent ?? 0;
    const filled = prog.filled ?? 0;
    const total = prog.total ?? 0;
    document.getElementById('progress-count').textContent = `${pct}%`;
    const progressFill = document.getElementById('progress-fill');
    progressFill.style.width = `${pct}%`;
    progressFill.classList.toggle('complete', filled === total && total > 0);

    // Preload adjacent days in background
    const prev = new Date(currentDate);
    prev.setDate(prev.getDate() - 1);
    api.getDailySummary(prev.toISOString().slice(0, 10));
    const next = new Date(currentDate);
    next.setDate(next.getDate() + 1);
    api.getDailySummary(next.toISOString().slice(0, 10));
    console.debug(`[render] today  ${(performance.now() - _t0).toFixed(0)}ms`);
}

function renderMetricInput(m, metricNameById) {
    // Private metric blocked in privacy mode
    if (isMetricBlocked(m)) {
        return `<div class="metric-card metric-private">
            <div class="metric-header"><label class="metric-label">${metricLabelHtml(m)}</label></div>
            <div class="metric-private-hint">Сначала отключите приватный режим</div>
        </div>`;
    }
    // Condition not met — show hint instead of input
    if (m.condition && !m.condition_met) {
        const depName = (metricNameById && metricNameById[m.condition.depends_on_metric_id]) || 'другую метрику';
        const hasEntry = !!(m.entry || (m.slots && m.slots.some(s => s.entry)));
        let currentValHtml = '';
        if (hasEntry) {
            let dv = '';
            if (m.entry && m.entry.display_value) dv = m.entry.display_value;
            else if (m.slots) {
                const parts = m.slots.filter(s => s.entry).map(s => `${s.label}: ${s.entry.display_value || s.entry.value}`);
                dv = parts.join(', ');
            }
            if (dv) currentValHtml = `<div class="condition-current-value">Текущее значение: ${dv}</div>`;
        }
        return `<div class="metric-card metric-condition-blocked" data-metric-id="${m.metric_id}" data-metric-type="${m.type}">
            <div class="metric-header"><label class="metric-label">${metricLabelHtml(m)}</label></div>
            <div class="condition-hint">Чтобы заполнить, сначала укажите «${depName}»</div>
            ${currentValHtml}
        </div>`;
    }
    // Integration metric — fetch button + standard card
    if (m.type === 'integration') {
        const entry = m.entry;
        const val = entry ? entry.value : null;
        const entryId = entry ? entry.id : null;
        const isFilled = val !== null && val !== undefined;
        const vt = m.value_type || 'number';
        let displayVal;
        if (!isFilled) {
            displayVal = '—';
        } else if (vt === 'bool') {
            displayVal = val ? 'Да' : 'Нет';
        } else {
            displayVal = String(val);
        }
        const btnLabel = isFilled ? 'Обновить' : 'Получить';
        const clearBtn = entry
            ? `<button class="metric-clear-btn" data-clear-entry="${entryId}" title="Очистить">&times;</button>`
            : '';
        let configHint = '';
        if (m.filter_name) configHint = `<span class="integration-hint">Фильтр: ${m.filter_name}</span>`;
        else if (m.filter_query) configHint = `<span class="integration-hint">Запрос: ${m.filter_query}</span>`;
        return `<div class="metric-card ${isFilled ? 'filled' : ''}" data-metric-id="${m.metric_id}" data-metric-type="integration" data-provider="${m.provider || ''}" data-entry-id="${entryId || ''}">
            <div class="metric-header">
                <label class="metric-label">${metricLabelHtml(m)}</label>
                ${clearBtn}
            </div>
            <div class="metric-input integration-input">
                <span class="computed-value ${isFilled ? '' : 'empty'}">${displayVal}</span>
                <button class="btn-small btn-fetch" data-action="fetch-integration" data-provider="${m.provider || 'todoist'}">${btnLabel}</button>
            </div>
            ${configHint}
        </div>`;
    }

    // Text metric — notes
    if (m.type === 'text') {
        const notes = m.notes || [];
        const noteCount = m.note_count || 0;
        const isFilled = noteCount > 0;
        let notesHtml = '';
        for (const n of notes) {
            const time = n.created_at ? new Date(n.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '';
            notesHtml += `<div class="note-item" data-note-id="${n.id}">
                <div class="note-text">${_escapeHtml(n.text)}</div>
                <div class="note-meta">
                    <span class="note-time">${time}</span>
                    <button class="btn-icon-tiny" data-action="edit-note" data-note-id="${n.id}" title="Редактировать"><i data-lucide="pencil"></i></button>
                    <button class="btn-icon-tiny btn-icon-danger" data-action="delete-note" data-note-id="${n.id}" title="Удалить"><i data-lucide="trash-2"></i></button>
                </div>
            </div>`;
        }
        return `<div class="metric-card ${isFilled ? 'filled' : ''}" data-metric-id="${m.metric_id}" data-metric-type="text">
            <div class="metric-header">
                <label class="metric-label">${metricLabelHtml(m)}</label>
                ${noteCount > 0 ? `<span class="note-count-badge">${noteCount}</span>` : ''}
            </div>
            <div class="notes-list">${notesHtml}</div>
            <div class="note-input-row">
                <textarea class="note-textarea" placeholder="Написать заметку..." rows="1"></textarea>
                <button class="btn-small btn-save-note" data-action="save-note">Сохранить</button>
            </div>
        </div>`;
    }

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
        } else if (rt === 'time' || rt === 'duration') {
            displayVal = String(val);
        } else if (rt === 'int') {
            displayVal = String(Math.round(val));
        } else {
            displayVal = typeof val === 'number' ? val.toFixed(2) : String(val);
        }
        return `<div class="metric-card ${isFilled ? 'filled' : ''}" data-metric-id="${m.metric_id}" data-metric-type="computed">
            <div class="metric-header">
                <label class="metric-label">${metricLabelHtml(m)}</label>
                <span class="computed-badge">формула</span>
            </div>
            <div class="computed-value ${isFilled ? '' : 'empty'}">${displayVal}</div>
        </div>`;
    }

    // Split single slot — render as regular card with composite name
    if (m.is_slot_split && m.slots && m.slots.length === 1) {
        const slot = m.slots[0];
        const entry = slot.entry;
        const val = entry ? entry.value : null;
        const entryId = entry ? entry.id : null;
        const isFilled = !!entry;
        const filledClass = isFilled ? 'filled' : '';

        let input;
        if (m.type === 'enum') input = renderEnum(val, m.enum_options, m.multi_select, !!entry);
        else if (m.type === 'time') input = renderTime(val);
        else if (m.type === 'duration') input = renderDuration(val);
        else if (m.type === 'number') input = renderNumber(val);
        else if (m.type === 'scale') {
            const sMin = (entry && entry.scale_min != null) ? entry.scale_min : m.scale_min;
            const sMax = (entry && entry.scale_max != null) ? entry.scale_max : m.scale_max;
            const sStep = (entry && entry.scale_step != null) ? entry.scale_step : m.scale_step;
            input = renderScale(val, sMin, sMax, sStep);
        }
        else input = renderBoolean(val);

        const clearBtn = entry
            ? `<button class="metric-clear-btn" data-clear-entry="${entryId}" title="Очистить">&times;</button>`
            : '';

        const slotBadge = `<span class="slot-badge">${slot.label}</span>`;
        const labelHtml = m.icon
            ? `<span class="metric-icon">${m.icon}</span> ${m.name}${slotBadge}`
            : `${m.name}${slotBadge}`;

        return `<div class="metric-card ${filledClass}" data-metric-id="${m.metric_id}" data-metric-type="${m.type}" data-entry-id="${entryId || ''}" data-slot-id="${slot.slot_id}">
            <div class="metric-header">
                <label class="metric-label">${labelHtml}</label>
                ${clearBtn}
            </div>
            <div class="metric-input">${input}</div>
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
            if (m.type === 'enum') input = renderEnum(val, m.enum_options, m.multi_select, !!entry);
            else if (m.type === 'time') input = renderTime(val);
            else if (m.type === 'duration') input = renderDuration(val);
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
                <label class="metric-label">${metricLabelHtml(m)}</label>
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
    if (m.type === 'enum') input = renderEnum(val, m.enum_options, m.multi_select, !!entry);
    else if (m.type === 'time') input = renderTime(val);
    else if (m.type === 'duration') input = renderDuration(val);
    else if (m.type === 'number') input = renderNumber(val);
    else if (m.type === 'scale') input = renderScale(val, m.scale_min, m.scale_max, m.scale_step);
    else input = renderBoolean(val);

    const clearBtn = entry
        ? `<button class="metric-clear-btn" data-clear-entry="${entryId}" title="Очистить">&times;</button>`
        : '';

    return `<div class="metric-card ${filledClass}" data-metric-id="${m.metric_id}" data-metric-type="${m.type}" data-entry-id="${entryId || ''}">
        <div class="metric-header">
            <label class="metric-label">${metricLabelHtml(m)}</label>
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

function formatDuration(minutes) {
    if (minutes === null || minutes === undefined) return '—';
    const m = typeof minutes === 'number' ? minutes : parseInt(minutes);
    if (isNaN(m)) return '—';
    return `${Math.floor(m / 60)}ч ${m % 60}м`;
}

function renderDuration(val) {
    if (val !== null && val !== undefined) {
        return `<button type="button" class="time-picker-btn has-value" data-action="pick-duration">${formatDuration(val)}</button>`;
    }
    return `<button type="button" class="time-picker-btn" data-action="pick-duration">Указать длительность</button>`;
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

function renderEnum(selectedIds, options, multiSelect, hasEntry) {
    let buttons = '';
    for (const opt of (options || [])) {
        const isSelected = selectedIds && Array.isArray(selectedIds) && selectedIds.includes(opt.id);
        buttons += `<button class="enum-btn ${isSelected ? 'active' : ''}" data-option-id="${opt.id}" data-value="${opt.id}">${opt.label}</button>`;
    }
    if (multiSelect) {
        const noneActive = hasEntry && Array.isArray(selectedIds) && selectedIds.length === 0;
        buttons += `<button class="enum-btn enum-btn-none ${noneActive ? 'active' : ''}" data-option-id="none">Ничего</button>`;
    }
    return `<div class="enum-buttons ${multiSelect ? 'multi' : 'single'}" data-multi-select="${multiSelect ? 'true' : 'false'}">${buttons}</div>`;
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
    const slotId = slotEl ? slotEl.dataset.slotId : (card.dataset.slotId || null);

    const raw = input.value.trim();
    if (raw === '') {
        if (entryId) {
            card.classList.remove('filled');
            if (slotEl) slotEl.dataset.entryId = '';
            else card.dataset.entryId = '';
            api.deleteEntry(parseInt(entryId)).then(() => {
                renderTodayForm();
            }).catch(err => {
                alert('Ошибка: ' + err.message);
                renderTodayForm();
            });
        }
        return;
    }

    const parsed = parseInt(raw);
    if (isNaN(parsed)) {
        input.value = '';
        return;
    }

    card.classList.add('filled');
    saveDaily(metricId, entryId, parsed, slotId).then(({ entryId: newId }) => {
        if (!newId) return;
        if (slotEl) slotEl.dataset.entryId = newId;
        else card.dataset.entryId = newId;
        _ensureClearButton(card, slotEl, newId);
        updateProgress();
    }).catch(err => {
        alert('Ошибка: ' + err.message);
        renderTodayForm();
    });
}

// ─── ActivityWatch UI helpers ───

function _awFormatDuration(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}ч ${m}м`;
    return `${m}м`;
}

function _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function _renderAWSummaryCard(awSummary) {
    let html = '<div class="aw-section">';
    html += `<h3 class="category-title"><span class="metric-icon">${AW_ICON}</span> Экранное время</h3>`;

    if (awSummary.synced) {
        const activeTime = _awFormatDuration(awSummary.active_seconds);
        const totalTime = _awFormatDuration(awSummary.total_seconds);
        const afkPct = awSummary.afk_percent;

        html += `<div class="aw-summary-card filled">
            <div class="aw-summary-stats">
                <div class="aw-stat"><div class="aw-stat-value">${activeTime}</div><div class="aw-stat-label">активное</div></div>
                <div class="aw-stat"><div class="aw-stat-value">${totalTime}</div><div class="aw-stat-label">всего</div></div>
                <div class="aw-stat"><div class="aw-stat-value">${afkPct}%</div><div class="aw-stat-label">AFK</div></div>
            </div>`;

        const topApps = awSummary.apps || [];
        if (topApps.length > 0) {
            html += '<div class="aw-top-apps">';
            for (const app of topApps) {
                const pct = app.percent;
                html += `<div class="aw-app-row">
                    <span class="aw-app-name">${_escapeHtml(app.app_name)}</span>
                    <span class="aw-app-dur">${_awFormatDuration(app.duration_seconds)}</span>
                    <div class="aw-app-bar"><div class="aw-app-bar-fill" style="width:${pct}%"></div></div>
                </div>`;
            }
            html += '</div>';
        }

        const topDomains = awSummary.domains || [];
        if (topDomains.length > 0) {
            html += '<div class="aw-top-apps" style="margin-top:8px"><div class="aw-stat-label" style="margin-bottom:4px">Сайты</div>';
            for (const d of topDomains) {
                const pct = d.percent;
                html += `<div class="aw-app-row">
                    <span class="aw-app-name">${_escapeHtml(d.domain)}</span>
                    <span class="aw-app-dur">${_awFormatDuration(d.duration_seconds)}</span>
                    <div class="aw-app-bar"><div class="aw-app-bar-fill" style="width:${pct}%"></div></div>
                </div>`;
            }
            html += '</div>';
        }

        html += `<button class="btn-small btn-fetch aw-sync-btn" data-action="aw-sync">Обновить</button>`;
        html += '</div>';
    } else {
        html += `<div class="aw-summary-card">
            <div class="aw-empty">Нет данных за этот день</div>
            <button class="btn-small btn-fetch aw-sync-btn" data-action="aw-sync">Синхронизировать</button>
        </div>`;
    }
    html += '</div>';
    return html;
}

function attachInputHandlers() {
    const form = document.getElementById('metrics-form');
    if (form.dataset.handlersAttached) return;
    form.dataset.handlersAttached = 'true';
    form.addEventListener('click', handleFormClick);
    form.addEventListener('change', handleNumberChange);
}

async function handleFormClick(e) {
    const btn = e.target.closest('[data-action]') || e.target;

    // ActivityWatch sync
    if (btn.dataset.action === 'aw-sync') {
        btn.disabled = true;
        const origText = btn.textContent;
        btn.textContent = 'Загрузка...';
        try {
            const awAvailable = await awClient.checkAvailable();
            if (!awAvailable) {
                alert('ActivityWatch не обнаружен. Убедитесь, что он запущен на вашем компьютере.');
                btn.disabled = false;
                btn.textContent = origText;
                return;
            }
            const { windowEvents, afkEvents, webEvents } = await awClient.fetchDayEvents(currentDate);
            await api.awSync(currentDate, windowEvents, afkEvents, webEvents);
            await renderTodayForm();
        } catch (error) {
            alert('Ошибка синхронизации ActivityWatch: ' + error.message);
            btn.disabled = false;
            btn.textContent = origText;
        }
        return;
    }

    // Save note
    if (btn.dataset.action === 'save-note') {
        const card = btn.closest('.metric-card');
        if (!card) return;
        const textarea = card.querySelector('.note-textarea');
        const text = textarea.value.trim();
        if (!text) return;
        btn.disabled = true;
        try {
            await api.createNote({ metric_id: parseInt(card.dataset.metricId), date: currentDate, text });
            await renderTodayForm();
        } catch (error) {
            alert('Ошибка: ' + error.message);
            btn.disabled = false;
        }
        return;
    }

    // Delete note
    if (btn.dataset.action === 'delete-note') {
        const noteId = parseInt(btn.dataset.noteId);
        try {
            await api.deleteNote(noteId);
            await renderTodayForm();
        } catch (error) {
            alert('Ошибка: ' + error.message);
        }
        return;
    }

    // Edit note — switch to inline editing
    if (btn.dataset.action === 'edit-note') {
        const noteId = btn.dataset.noteId;
        const noteItem = btn.closest('.note-item');
        if (!noteItem) return;
        const noteTextEl = noteItem.querySelector('.note-text');
        const currentText = noteTextEl.textContent;
        noteItem.innerHTML = `<textarea class="note-textarea note-edit-textarea" rows="2">${_escapeHtml(currentText)}</textarea>
            <div class="note-edit-actions">
                <button class="btn-small" data-action="save-edit-note" data-note-id="${noteId}">Сохранить</button>
                <button class="btn-small btn-secondary" data-action="cancel-edit-note">Отмена</button>
            </div>`;
        noteItem.querySelector('.note-edit-textarea').focus();
        return;
    }

    // Save edited note
    if (btn.dataset.action === 'save-edit-note') {
        const noteItem = btn.closest('.note-item');
        const textarea = noteItem.querySelector('.note-edit-textarea');
        const text = textarea.value.trim();
        if (!text) return;
        btn.disabled = true;
        try {
            await api.updateNote(parseInt(btn.dataset.noteId), { text });
            await renderTodayForm();
        } catch (error) {
            alert('Ошибка: ' + error.message);
            btn.disabled = false;
        }
        return;
    }

    // Cancel edit note
    if (btn.dataset.action === 'cancel-edit-note') {
        await renderTodayForm();
        return;
    }

    const card = btn.closest('.metric-card');
    if (!card) return;

    const metricId = card.dataset.metricId;
    const slotEl = btn.closest('.metric-slot');
    const entryId = slotEl ? slotEl.dataset.entryId : card.dataset.entryId;
    const slotId = slotEl ? slotEl.dataset.slotId : (card.dataset.slotId || null);

    // Integration fetch
    if (btn.dataset.action === 'fetch-integration') {
        const provider = btn.dataset.provider || 'todoist';
        btn.disabled = true;
        btn.textContent = 'Загрузка...';
        try {
            const result = await api.fetchIntegration(provider, currentDate, metricId);
            if (result && result.errors && result.errors.length > 0) {
                const msgs = result.errors.map(e => e.error).join('\n');
                alert('Некоторые метрики не обновились:\n' + msgs);
            }
            await renderTodayForm();
        } catch (error) {
            alert('Ошибка: ' + error.message);
            btn.disabled = false;
            btn.textContent = 'Получить';
        }
        return;
    }

    // Clear metric entry
    if (btn.dataset.clearEntry) {
        const clearEntryId = parseInt(btn.dataset.clearEntry);
        card.classList.remove('filled');
        if (slotEl) slotEl.dataset.entryId = '';
        else card.dataset.entryId = '';
        api.deleteEntry(clearEntryId).then(() => {
            renderTodayForm();
        }).catch(err => {
            alert('Ошибка при удалении: ' + err.message);
            renderTodayForm();
        });
        return;
    }

    // Boolean buttons
    if (btn.classList.contains('bool-btn')) {
        const boolVal = btn.dataset.value === 'true';
        const container = slotEl || card;
        container.querySelectorAll('.bool-btn').forEach(b => {
            b.classList.remove('active', 'yes', 'no');
        });
        btn.classList.add('active', boolVal ? 'yes' : 'no');
        card.classList.add('filled');
        saveDaily(metricId, entryId, boolVal, slotId).then(({ entryId: newId }) => {
            if (!newId) return;
            if (slotEl) slotEl.dataset.entryId = newId;
            else card.dataset.entryId = newId;
            _ensureClearButton(card, slotEl, newId);
            updateProgress();
        }).catch(err => {
            alert('Ошибка: ' + err.message);
            renderTodayForm();
        });
        return;
    }

    // Scale buttons
    if (btn.classList.contains('scale-btn')) {
        const container = slotEl || card;
        container.querySelectorAll('.scale-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        card.classList.add('filled');
        saveDaily(metricId, entryId, parseInt(btn.dataset.value), slotId).then(({ entryId: newId }) => {
            if (!newId) return;
            if (slotEl) slotEl.dataset.entryId = newId;
            else card.dataset.entryId = newId;
            _ensureClearButton(card, slotEl, newId);
            updateProgress();
        }).catch(err => {
            alert('Ошибка: ' + err.message);
            renderTodayForm();
        });
        return;
    }

    // Enum buttons
    if (btn.classList.contains('enum-btn')) {
        const container = slotEl || card;
        const enumContainer = container.querySelector('.enum-buttons');
        const isMulti = enumContainer?.dataset.multiSelect === 'true';
        const isNoneBtn = btn.dataset.optionId === 'none';

        if (isMulti) {
            if (isNoneBtn) {
                // "Ничего" — снять все обычные кнопки
                container.querySelectorAll('.enum-btn:not(.enum-btn-none)').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            } else {
                // Обычная кнопка — снять "Ничего"
                const noneBtn = container.querySelector('.enum-btn-none');
                if (noneBtn) noneBtn.classList.remove('active');
                btn.classList.toggle('active');
            }
        } else {
            container.querySelectorAll('.enum-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        }

        // Собрать выбранные option IDs (без "none")
        const activeIds = [];
        container.querySelectorAll('.enum-btn.active:not(.enum-btn-none)').forEach(b => {
            activeIds.push(parseInt(b.dataset.optionId));
        });

        const noneActive = container.querySelector('.enum-btn-none.active');

        if (activeIds.length === 0 && !noneActive) {
            // Single-select: нельзя снять кнопкой (только clear ×)
            return;
        }

        // activeIds может быть [] если нажата "Ничего" — это валидный ответ
        card.classList.add('filled');
        saveDaily(metricId, entryId, activeIds, slotId).then(({ entryId: newId }) => {
            if (!newId) return;
            if (slotEl) slotEl.dataset.entryId = newId;
            else card.dataset.entryId = newId;
            _ensureClearButton(card, slotEl, newId);
            updateProgress();
        }).catch(err => {
            alert('Ошибка: ' + err.message);
            renderTodayForm();
        });
        return;
    }

    // Number "=0" button
    if (btn.dataset.action === 'set-zero') {
        const container = slotEl || card;
        const input = container.querySelector('.number-value-input');
        input.value = 0;
        card.classList.add('filled');
        btn.remove();
        saveDaily(metricId, entryId, 0, slotId).then(({ entryId: newId }) => {
            if (!newId) return;
            if (slotEl) slotEl.dataset.entryId = newId;
            else card.dataset.entryId = newId;
            _ensureClearButton(card, slotEl, newId);
            updateProgress();
        }).catch(err => {
            alert('Ошибка: ' + err.message);
            renderTodayForm();
        });
        return;
    }

    // Number +/- buttons
    if (btn.classList.contains('number-btn')) {
        const container = slotEl || card;
        const input = container.querySelector('.number-value-input');
        let currentVal = input.value !== '' ? parseInt(input.value) : 0;
        if (isNaN(currentVal)) currentVal = 0;
        const newVal = currentVal + (btn.dataset.action === 'increment' ? 1 : -1);
        input.value = newVal;
        card.classList.add('filled');
        const zeroBtn = container.querySelector('.number-zero-btn');
        if (zeroBtn) zeroBtn.remove();
        saveDaily(metricId, entryId, newVal, slotId).then(({ entryId: newId }) => {
            if (!newId) return;
            if (slotEl) slotEl.dataset.entryId = newId;
            else card.dataset.entryId = newId;
            _ensureClearButton(card, slotEl, newId);
            updateProgress();
        }).catch(err => {
            alert('Ошибка: ' + err.message);
            renderTodayForm();
        });
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

    // Duration picker (reuses clock picker, converts HH:MM → minutes)
    const durTrigger = btn.closest('[data-action="pick-duration"]');
    if (durTrigger) {
        if (document.querySelector('.cp-overlay')) return;
        // Convert current minutes to HH:MM for picker
        let currentVal = '';
        if (durTrigger.classList.contains('has-value')) {
            const container = slotEl || card;
            const entry = container.dataset.entryId;
            // Parse from displayed text "Xч Yм"
            const text = durTrigger.textContent.trim();
            const match = text.match(/(\d+)ч\s*(\d+)м/);
            if (match) {
                currentVal = `${String(parseInt(match[1])).padStart(2, '0')}:${String(parseInt(match[2])).padStart(2, '0')}`;
            }
        }
        showClockPicker(currentVal, async (hhmmVal) => {
            try {
                const parts = hhmmVal.split(':').map(Number);
                const minutes = parts[0] * 60 + parts[1];
                await saveDaily(metricId, entryId, minutes, slotId);
                await renderTodayForm();
            } catch (error) {
                alert('Ошибка: ' + error.message);
            }
        });
        return;
    }
}

function _ensureClearButton(card, slotEl, entryId) {
    if (slotEl) {
        const header = slotEl.querySelector('.period-header');
        if (!header) return;
        let btn = header.querySelector('.period-clear-btn');
        if (btn) {
            btn.dataset.clearEntry = entryId;
        } else {
            btn = document.createElement('button');
            btn.className = 'period-clear-btn';
            btn.dataset.clearEntry = entryId;
            btn.title = 'Очистить';
            btn.innerHTML = '&times;';
            header.appendChild(btn);
        }
    } else {
        const header = card.querySelector('.metric-header');
        if (!header) return;
        let btn = header.querySelector('.metric-clear-btn');
        if (btn) {
            btn.dataset.clearEntry = entryId;
        } else {
            btn = document.createElement('button');
            btn.className = 'metric-clear-btn';
            btn.dataset.clearEntry = entryId;
            btn.title = 'Очистить';
            btn.innerHTML = '&times;';
            header.appendChild(btn);
        }
    }
}

const _savingKeys = new Set();

async function saveDaily(metricId, entryId, value, slotId) {
    const key = `${metricId}-${slotId || 'null'}`;
    let result;
    if (entryId) {
        await api.updateEntry(parseInt(entryId), { value });
        result = { entryId: parseInt(entryId) };
    } else {
        if (_savingKeys.has(key)) return {};
        _savingKeys.add(key);
        try {
            const payload = {
                metric_id: parseInt(metricId),
                date: currentDate,
                value,
            };
            if (slotId) payload.slot_id = parseInt(slotId);
            const res = await api.createEntry(payload);
            result = { entryId: res.id };
        } finally {
            _savingKeys.delete(key);
        }
    }
    // Re-render if this metric is a dependency for conditional metrics
    if (_dependencyMetricIdsGlobal.has(parseInt(metricId))) {
        setTimeout(() => renderTodayForm(true), 50);
    }
    return result;
}

function updateProgress() {
    const form = document.getElementById('metrics-form');
    let total = 0, filled = 0;
    form.querySelectorAll('.metric-card').forEach(card => {
        if (card.classList.contains('metric-condition-blocked')) return;
        const type = card.dataset.metricType;
        if (type === 'computed' || type === 'integration') return;
        if (type === 'text') {
            total++;
            if (card.querySelector('.note-item')) filled++;
            return;
        }
        const slots = card.querySelectorAll('.metric-slot');
        if (slots.length > 0) {
            slots.forEach(s => {
                total++;
                if (s.dataset.entryId) filled++;
            });
        } else {
            total++;
            if (card.dataset.entryId) filled++;
        }
    });
    const pct = total > 0 ? Math.round((filled / total) * 100) : 0;
    document.getElementById('progress-count').textContent = `${pct}%`;
    const bar = document.getElementById('progress-fill');
    bar.style.width = `${pct}%`;
    bar.classList.toggle('complete', filled === total && total > 0);
}

// ─── History Page ───
let historyDate = todayStr();

async function renderHistory(container) {
    if (metrics.length === 0) {
        container.innerHTML = `
            <div class="stats-header"><h2 class="stats-title">История</h2></div>
            <div class="empty-state">
                <div class="empty-state-icon"><i data-lucide="history"></i></div>
                <div class="empty-state-text">Вы пока не создали метрики, поэтому тут пусто</div>
                <button class="btn-primary" id="history-create-metric"><i data-lucide="plus"></i> Создать метрику</button>
            </div>
        `;
        if (window.lucide) lucide.createIcons();
        document.getElementById('history-create-metric').addEventListener('click', () => {
            navigateTo('settings', { openAddModal: true });
        });
        return;
    }

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
    const _t0 = performance.now();
    // Update header
    document.getElementById('hist-date-label').textContent = formatDate(historyDate);
    const goBtn = document.getElementById('hist-go-today');
    if (goBtn) goBtn.style.display = (historyDate === todayStr()) ? 'none' : '';

    // Render calendar for the month of historyDate
    renderCalendar(historyDate.slice(0, 7));

    // Load and show day detail + progress
    await showDayDetail(historyDate);
    console.debug(`[render] history  ${(performance.now() - _t0).toFixed(0)}ms`);
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
    const myVersion = ++_historyRenderVersion;
    const detail = document.getElementById('day-detail');
    detail.innerHTML = '<div class="loading-spinner"></div>';
    const summary = await api.getDailySummary(date);
    if (myVersion !== _historyRenderVersion) return;

    // Update progress bar from backend
    const prog = summary.progress || {};
    const pct = prog.percent ?? 0;
    const filled = prog.filled ?? 0;
    const total = prog.total ?? 0;
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
        const blocked = isMetricBlocked(m);
        if (m.type === 'text') {
            const notes = m.notes || [];
            if (notes.length === 0) continue;
            hasAny = true;
            for (const n of notes) {
                const time = n.created_at ? new Date(n.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '';
                const val = blocked ? PRIVATE_MASK : `${_escapeHtml(n.text)} <span class="note-time">${time}</span>`;
                html += `<div class="summary-row"><span class="summary-label">${metricLabelHtml(m)}</span><span class="summary-value">${val}</span></div>`;
            }
            continue;
        }
        if (m.slots && m.slots.length > 0) {
            const filledSlots = m.slots.filter(s => s.entry !== null);
            if (filledSlots.length === 0) continue;
            hasAny = true;
            for (const s of filledSlots) {
                const val = blocked ? PRIVATE_MASK : s.entry.display_value;
                html += `<div class="summary-row"><span class="summary-label">${metricLabelHtml(m)} — ${blocked ? PRIVATE_MASK : s.label}</span><span class="summary-value">${val}</span></div>`;
            }
        } else {
            if (!m.entry) continue;
            hasAny = true;
            const val = blocked ? PRIVATE_MASK : m.entry.display_value;
            html += `<div class="summary-row"><span class="summary-label">${metricLabelHtml(m)}</span><span class="summary-value">${val}</span></div>`;
        }
    }

    if (!hasAny) {
        html += `<div class="summary-row"><span class="summary-label" style="color:var(--text-dim)">Нет записей</span></div>`;
    }

    html += '</div>';
    detail.innerHTML = html;
}

// ─── Charts Page (Статистика) ───
async function renderCharts(container) {
    if (metrics.length === 0) {
        container.innerHTML = `
            <div class="stats-header"><h2 class="stats-title">Статистика</h2></div>
            <div class="empty-state">
                <div class="empty-state-icon"><i data-lucide="bar-chart-3"></i></div>
                <div class="empty-state-text">Вы пока не создали метрики, поэтому тут пусто</div>
                <button class="btn-primary" id="charts-create-metric"><i data-lucide="plus"></i> Создать метрику</button>
            </div>
        `;
        if (window.lucide) lucide.createIcons();
        document.getElementById('charts-create-metric').addEventListener('click', () => {
            navigateTo('settings', { openAddModal: true });
        });
        return;
    }

    const end = todayStr();
    const start = daysAgo(30);

    container.innerHTML = `
        <div class="stats-header">
            <h2 class="stats-title">Статистика</h2>
            <div class="stats-controls">
                <div id="charts-start-picker"></div>
                <span class="stats-dash">—</span>
                <div id="charts-end-picker"></div>
                <button class="btn-icon" id="charts-refresh" title="Обновить">
                    <i data-lucide="refresh-cw"></i>
                </button>
            </div>
        </div>
        <div id="trends-section"></div>
    `;

    if (window.lucide) lucide.createIcons();

    const chartsStartPicker = createDatePicker('charts-start-picker', start, () => {
        loadChartsTrends(chartsStartPicker.getValue(), chartsEndPicker.getValue());
    });
    const chartsEndPicker = createDatePicker('charts-end-picker', end, () => {
        loadChartsTrends(chartsStartPicker.getValue(), chartsEndPicker.getValue());
    });

    document.getElementById('charts-refresh').addEventListener('click', () => {
        loadChartsTrends(chartsStartPicker.getValue(), chartsEndPicker.getValue());
    });

    await loadChartsTrends(start, end);
}

async function loadChartsTrends(start, end) {
    const _t0 = performance.now();
    // Destroy previous trend charts
    trendChartInstances.forEach(c => c.destroy());
    trendChartInstances = [];

    const trendsEl = document.getElementById('trends-section');

    // Fetch all trends in parallel
    const [trendResults, awTrendPoints] = await Promise.all([
        Promise.all(metrics.map(m =>
            api.getTrends(m.id, start, end).then(t => ({ metric: m, trend: t }))
        )),
        (async () => {
            try {
                const awStatus = await api.awGetStatus();
                if (awStatus.enabled) {
                    const awTrends = await api.awGetTrends(start, end);
                    if (awTrends.points && awTrends.points.length > 0) return awTrends.points;
                }
            } catch (e) { /* AW not configured */ }
            return null;
        })(),
    ]);

    const trendData = [];
    const metricsWithCards = [];
    for (const { metric: m, trend } of trendResults) {
        const hasPoints = trend.points && trend.points.length > 0;
        const hasEnumSeries = trend.option_series && Object.keys(trend.option_series).length > 0;
        if (hasPoints || hasEnumSeries) {
            let cardHtml;
            if (isMetricBlocked(m)) {
                cardHtml = `<div class="trend-card-row metric-private" data-metric-id="${m.id}" style="cursor:pointer">
                    <div class="trend-card-header">
                        <h4>${metricIconHtml(m)}<span class="trend-metric-name">${m.name}</span></h4>
                    </div>
                    <div class="metric-private-hint">Сначала отключите приватный режим</div>
                </div>`;
            } else if (m.type === 'text') {
                const total = (trend.points || []).reduce((s, p) => s + (p.value || 0), 0);
                cardHtml = `<div class="trend-card-row" data-metric-id="${m.id}" style="cursor:pointer">
                    <div class="trend-card-header">
                        <h4>${metricIconHtml(m)}<span class="trend-metric-name">${m.name}</span></h4>
                        <i data-lucide="info" class="trend-info-icon"></i>
                    </div>
                    <div class="trend-text-count">${total} ${_pluralize(total, 'запись', 'записи', 'записей')}</div>
                </div>`;
            } else {
                trendData.push({ metric: m, points: trend.points || [], trend });
                cardHtml = `<div class="trend-card-row" data-metric-id="${m.id}" style="cursor:pointer">
                    <div class="trend-card-header">
                        <h4>${metricIconHtml(m)}<span class="trend-metric-name">${m.name}</span></h4>
                        <i data-lucide="info" class="trend-info-icon"></i>
                    </div>
                    <div class="trend-chart-container"><canvas id="trend-chart-${m.id}"></canvas></div>
                </div>`;
            }
            metricsWithCards.push({ metric: m, cardHtml });
        }
    }

    const awCardHtml = awTrendPoints ? `<div class="trend-card-row aw-trend-card">
        <div class="trend-card-header">
            <h4><span class="metric-icon">${AW_ICON}</span><span class="trend-metric-name">Экранное время</span></h4>
        </div>
        <div class="trend-chart-container"><canvas id="trend-chart-aw"></canvas></div>
    </div>` : '';

    // Load categories for grouping
    let categories = [];
    try { categories = await api.getCategories(); } catch(e) { console.warn('Failed to load categories', e); }

    let trendsHtml = '';
    const hasCategories = categories.length > 0;

    if (hasCategories) {
        const catById = {};
        for (const c of categories) {
            catById[c.id] = c;
            for (const ch of (c.children || [])) catById[ch.id] = ch;
        }
        const metricsByCat = {};
        const uncategorized = [];
        for (const item of metricsWithCards) {
            const catId = item.metric.category_id;
            if (catId && catById[catId]) {
                if (!metricsByCat[catId]) metricsByCat[catId] = [];
                metricsByCat[catId].push(item);
            } else {
                uncategorized.push(item);
            }
        }

        for (const topCat of categories) {
            const topItems = metricsByCat[topCat.id] || [];
            const childrenWithItems = (topCat.children || []).filter(ch => (metricsByCat[ch.id] || []).length > 0);
            if (topItems.length === 0 && childrenWithItems.length === 0) continue;

            trendsHtml += `<h2 class="fill-time-header">${topCat.name}</h2>`;
            if (topItems.length > 0) {
                trendsHtml += '<div class="trends-list">';
                for (const item of topItems) trendsHtml += item.cardHtml;
                trendsHtml += '</div>';
            }
            for (const ch of (topCat.children || [])) {
                const chItems = metricsByCat[ch.id] || [];
                if (chItems.length === 0) continue;
                trendsHtml += `<h3 class="fill-time-header">${ch.name}</h3>`;
                trendsHtml += '<div class="trends-list">';
                for (const item of chItems) trendsHtml += item.cardHtml;
                trendsHtml += '</div>';
            }
        }
        if (uncategorized.length > 0) {
            trendsHtml += '<h2 class="fill-time-header">Без категории</h2>';
            trendsHtml += '<div class="trends-list">';
            for (const item of uncategorized) trendsHtml += item.cardHtml;
            trendsHtml += '</div>';
        }
    } else {
        trendsHtml += '<div class="trends-list">';
        for (const item of metricsWithCards) trendsHtml += item.cardHtml;
        trendsHtml += '</div>';
    }

    if (awCardHtml) {
        trendsHtml += '<div class="trends-list">' + awCardHtml + '</div>';
    }

    trendsEl.innerHTML = trendsHtml;

    // Initialize Chart.js for each trend card
    const style = getComputedStyle(document.documentElement);
    const colors = {
        accent: style.getPropertyValue('--accent').trim(),
        green: style.getPropertyValue('--green').trim(),
        red: style.getPropertyValue('--red').trim(),
    };
    for (const { metric, points, trend: trendObj } of trendData) {
        const canvas = document.getElementById(`trend-chart-${metric.id}`);
        if (!canvas) continue;
        const mt = metric.type === 'computed' ? (metric.result_type || 'float') : metric.type === 'integration' ? (metric.value_type || 'number') : metric.type === 'text' ? 'number' : metric.type;
        if (mt === 'enum' && trendObj?.option_series) {
            const optColors = ['#6c8cff', '#4caf50', '#ff9800', '#e91e63', '#9c27b0', '#00bcd4', '#795548', '#607d8b'];
            const options = trendObj.options || [];
            const dates = Object.values(trendObj.option_series)[0]?.map(p => formatShortDate(p.date)) || [];
            const datasets = options.map((opt, idx) => ({
                label: opt.label,
                data: (trendObj.option_series[opt.label] || []).map(p => p.value),
                backgroundColor: optColors[idx % optColors.length] + 'cc',
                borderRadius: 3,
            }));
            trendChartInstances.push(new Chart(canvas.getContext('2d'), {
                type: 'bar',
                data: { labels: dates, datasets },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    interaction: { mode: null },
                    events: [],
                    scales: {
                        x: { stacked: true, display: false },
                        y: { stacked: true, display: false },
                    },
                },
            }));
        } else {
            const config = buildChartConfig(points, mt, colors, { compact: true });
            trendChartInstances.push(new Chart(canvas.getContext('2d'), config));
        }
    }

    // AW trend chart
    if (awTrendPoints) {
        const awCanvas = document.getElementById('trend-chart-aw');
        if (awCanvas) {
            const labels = awTrendPoints.map(p => p.date.slice(5));
            const activeData = awTrendPoints.map(p => p.active_hours);
            const afkData = awTrendPoints.map(p => p.afk_hours);
            const chart = new Chart(awCanvas.getContext('2d'), {
                type: 'bar',
                data: {
                    labels,
                    datasets: [
                        { label: 'Активное', data: activeData, backgroundColor: colors.accent + '99', borderRadius: 4 },
                        { label: 'AFK', data: afkData, backgroundColor: colors.red + '44', borderRadius: 4 },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { x: { stacked: true, display: false }, y: { stacked: true, display: false } },
                    plugins: { legend: { display: false } },
                },
            });
            trendChartInstances.push(chart);
        }
    }

    if (window.lucide) lucide.createIcons({ nameAttr: 'data-lucide' });

    // Attach click on entire card
    trendsEl.querySelectorAll('.trend-card-row[data-metric-id]').forEach(card => {
        card.addEventListener('click', () => {
            navigateTo('metric-detail', { metricId: parseInt(card.dataset.metricId) });
        });
    });

    console.debug(`[render] charts  ${(performance.now() - _t0).toFixed(0)}ms`);
}

// ─── Insights Page (Выводы) ───

async function renderInsights(container) {
    const _t0 = performance.now();
    container.innerHTML = '<div class="stats-header"><h2 class="stats-title">Выводы</h2></div><div style="color:var(--text-dim);font-size:13px;">Загрузка...</div>';

    let insightsData;
    try {
        insightsData = await api.getInsights();
    } catch (e) {
        container.innerHTML = '<div class="stats-header"><h2 class="stats-title">Выводы</h2></div><p style="color:var(--red)">Ошибка загрузки</p>';
        return;
    }

    let html = `
        <div class="stats-header">
            <h2 class="stats-title">Выводы</h2>
            <button class="btn-primary btn-sm" id="insight-add-btn"><i data-lucide="plus"></i> Добавить</button>
        </div>
    `;

    if (insightsData.length === 0) {
        html += `
            <div class="empty-state">
                <div class="empty-state-icon"><i data-lucide="lightbulb"></i></div>
                <div class="empty-state-text">Записывайте выводы о связях между метриками</div>
                <button class="btn-primary" id="insight-empty-add"><i data-lucide="plus"></i> Добавить вывод</button>
            </div>
        `;
    } else {
        html += '<div id="insights-list">';
        for (const insight of insightsData) {
            html += renderInsightCard(insight);
        }
        html += '</div>';
    }

    container.innerHTML = html;
    if (window.lucide) lucide.createIcons();

    // Event listeners
    const addBtn = document.getElementById('insight-add-btn');
    if (addBtn) addBtn.addEventListener('click', () => showInsightModal());

    const emptyAdd = document.getElementById('insight-empty-add');
    if (emptyAdd) emptyAdd.addEventListener('click', () => showInsightModal());

    // Event delegation for insight actions
    const list = document.getElementById('insights-list');
    if (list) {
        list.addEventListener('click', async (e) => {
            const editBtn = e.target.closest('.insight-edit-btn');
            if (editBtn) {
                const id = parseInt(editBtn.dataset.insightId);
                const insight = insightsData.find(ins => ins.id === id);
                if (insight) showInsightModal(insight);
                return;
            }

            const deleteBtn = e.target.closest('.insight-delete-btn');
            if (deleteBtn) {
                const id = parseInt(deleteBtn.dataset.insightId);
                if (confirm('Удалить вывод?')) {
                    await api.deleteInsight(id);
                    renderInsights(container);
                }
                return;
            }

            const corrBtn = e.target.closest('.insight-corr-btn');
            if (corrBtn) {
                toggleInsightCorrelations(corrBtn);
                return;
            }

            // Delegation for correlation detail buttons inside insight panels
            const detailBtn = e.target.closest('.corr-detail-btn');
            if (detailBtn) {
                e.stopPropagation();
                const d = corrPairData.get(detailBtn.dataset.pairId);
                if (d) toggleCorrDetail(detailBtn.dataset.pairId, d.mAId, d.mBId, d.lA, d.iA, d.lB, d.iB, d.pStart, d.pEnd);
                return;
            }
        });
    }

    console.debug(`[render] insights  ${(performance.now() - _t0).toFixed(0)}ms`);
}

function renderInsightCard(insight) {
    const metricTags = insight.metrics.map(m => {
        if (m.metric_id) {
            const icon = m.metric_icon ? `<span class="metric-icon">${m.metric_icon}</span>` : '';
            return `<span class="insight-metric-tag">${icon}${m.metric_name || 'Удалённая метрика'}</span>`;
        } else {
            return `<span class="insight-metric-tag custom">${m.custom_label || ''}</span>`;
        }
    }).join('');

    const realMetricIds = insight.metrics
        .filter(m => m.metric_id)
        .map(m => m.metric_id);
    const corrBtnHtml = realMetricIds.length >= 2
        ? `<button class="insight-corr-btn btn-icon-sm" data-metric-ids="${realMetricIds.join(',')}" title="Показать корреляции"><i data-lucide="info"></i></button>`
        : '';

    const textHtml = insight.text
        ? `<div class="insight-text">${insight.text.replace(/\n/g, '<br>')}</div>`
        : '';

    return `<div class="insight-card" data-insight-id="${insight.id}">
        <div class="insight-card-body">
            <div class="insight-metrics-col">${metricTags || '<span class="insight-no-metrics">Нет метрик</span>'}</div>
            <div class="insight-content-col">${textHtml}</div>
            <div class="insight-actions">
                ${corrBtnHtml}
                <button class="insight-edit-btn btn-icon-sm" data-insight-id="${insight.id}" title="Редактировать"><i data-lucide="pencil"></i></button>
                <button class="insight-delete-btn btn-icon-sm" data-insight-id="${insight.id}" title="Удалить"><i data-lucide="trash-2"></i></button>
            </div>
        </div>
        <div class="insight-corr-panel" id="insight-corr-${insight.id}" style="display:none"></div>
    </div>`;
}

async function showInsightModal(existing = null) {
    const isEdit = !!existing;
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    const initialMetrics = existing ? existing.metrics : [];

    function renderMetricRows(metricsArr) {
        return metricsArr.map((m, i) => {
            const isCustom = !m.metric_id;
            const selectHtml = `<select class="insight-metric-select" data-idx="${i}">
                <option value="">— Выберите метрику —</option>
                ${metrics.filter(mt => mt.enabled).map(mt =>
                    `<option value="${mt.id}" ${m.metric_id === mt.id ? 'selected' : ''}>${mt.icon || ''} ${mt.name}</option>`
                ).join('')}
                <option value="custom" ${isCustom && m.custom_label ? 'selected' : ''}>Произвольное название...</option>
            </select>`;
            const customInput = isCustom
                ? `<input type="text" class="insight-custom-input" data-idx="${i}" value="${m.custom_label || ''}" placeholder="Название">`
                : '';
            return `<div class="insight-metric-row">
                ${selectHtml}
                ${customInput}
                <button class="insight-metric-remove btn-icon-tiny btn-icon-danger" data-idx="${i}" title="Удалить"><i data-lucide="x"></i></button>
            </div>`;
        }).join('');
    }

    overlay.innerHTML = `
        <div class="modal">
            <h3>${isEdit ? 'Редактировать вывод' : 'Новый вывод'}</h3>
            <div class="modal-form">
                <div class="form-section">
                    <span class="label-text">Метрики</span>
                    <div id="insight-modal-metrics">${renderMetricRows(initialMetrics)}</div>
                    <button class="btn-small btn-sm" id="insight-add-metric" style="margin-top:4px"><i data-lucide="plus"></i> Добавить метрику</button>
                </div>
                <div class="form-section">
                    <span class="label-text">Текст вывода</span>
                    <textarea id="insight-modal-text" class="note-textarea" rows="4" placeholder="Опишите вывод о связи..." style="min-height:80px">${existing ? existing.text : ''}</textarea>
                </div>
            </div>
            <div class="modal-actions">
                <button class="btn-small" id="insight-modal-cancel">Отмена</button>
                <button class="btn-primary" id="insight-modal-save">${isEdit ? 'Сохранить' : 'Создать'}</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    if (window.lucide) lucide.createIcons();

    let modalMetrics = initialMetrics.map(m => ({
        metric_id: m.metric_id || null,
        custom_label: m.custom_label || null,
    }));

    function refreshRows() {
        const container = document.getElementById('insight-modal-metrics');
        container.innerHTML = renderMetricRows(modalMetrics.map((m, i) => ({
            metric_id: m.metric_id,
            custom_label: m.custom_label,
            metric_name: m.metric_id ? (metrics.find(mt => mt.id === m.metric_id) || {}).name : null,
            metric_icon: m.metric_id ? (metrics.find(mt => mt.id === m.metric_id) || {}).icon : null,
        })));
        if (window.lucide) lucide.createIcons();
        attachRowListeners();
    }

    function attachRowListeners() {
        const container = document.getElementById('insight-modal-metrics');
        container.querySelectorAll('.insight-metric-select').forEach(sel => {
            sel.addEventListener('change', () => {
                const idx = parseInt(sel.dataset.idx);
                if (sel.value === 'custom') {
                    modalMetrics[idx] = { metric_id: null, custom_label: '' };
                } else if (sel.value) {
                    modalMetrics[idx] = { metric_id: parseInt(sel.value), custom_label: null };
                } else {
                    modalMetrics[idx] = { metric_id: null, custom_label: null };
                }
                refreshRows();
            });
        });
        container.querySelectorAll('.insight-custom-input').forEach(inp => {
            inp.addEventListener('input', () => {
                const idx = parseInt(inp.dataset.idx);
                modalMetrics[idx].custom_label = inp.value;
            });
        });
        container.querySelectorAll('.insight-metric-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.idx);
                modalMetrics.splice(idx, 1);
                refreshRows();
            });
        });
    }

    attachRowListeners();

    document.getElementById('insight-add-metric').addEventListener('click', () => {
        modalMetrics.push({ metric_id: null, custom_label: null });
        refreshRows();
    });

    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.getElementById('insight-modal-cancel').addEventListener('click', () => overlay.remove());

    document.getElementById('insight-modal-save').addEventListener('click', async () => {
        const text = document.getElementById('insight-modal-text').value.trim();
        const metricsPayload = modalMetrics
            .filter(m => m.metric_id || (m.custom_label && m.custom_label.trim()))
            .map(m => ({
                metric_id: m.metric_id || null,
                custom_label: m.custom_label ? m.custom_label.trim() : null,
            }));

        try {
            if (isEdit) {
                await api.updateInsight(existing.id, { text, metrics: metricsPayload });
            } else {
                await api.createInsight({ text, metrics: metricsPayload });
            }
            overlay.remove();
            renderInsights(document.getElementById('main'));
        } catch (err) {
            alert('Ошибка: ' + err.message);
        }
    });
}

async function toggleInsightCorrelations(btn) {
    const metricIdsStr = btn.dataset.metricIds;
    const card = btn.closest('.insight-card');
    const panel = card.querySelector('.insight-corr-panel');

    if (panel.style.display !== 'none') {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
    }

    panel.style.display = '';
    panel.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:12px;">Загрузка корреляций...</div>';

    try {
        const reportData = await api.getCorrelationReport();
        if (!reportData.report) {
            panel.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:12px;">Нет рассчитанных отчётов. Сначала рассчитайте корреляции на странице «Анализ».</div>';
            return;
        }

        const report = reportData.report;
        const data = await api.getCorrelationPairs(report.id, { category: 'all', limit: 200, metric_ids: metricIdsStr });

        if (data.pairs.length === 0) {
            panel.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:12px;">Нет корреляций между этими метриками.</div>';
            return;
        }

        let html = '<div class="insight-corr-pairs">';
        for (const p of data.pairs) {
            html += renderCorrPair(p, report);
        }
        html += '</div>';
        panel.innerHTML = html;
    } catch (err) {
        panel.innerHTML = `<div style="color:var(--red);font-size:13px;padding:12px;">Ошибка: ${err.message}</div>`;
    }
}

// ─── Analysis Page (Анализ) ───
async function renderAnalysis(container) {
    if (metrics.length === 0) {
        container.innerHTML = `
            <div class="stats-header"><h2 class="stats-title">Анализ</h2></div>
            <div class="empty-state">
                <div class="empty-state-icon"><i data-lucide="scatter-chart"></i></div>
                <div class="empty-state-text">Вы пока не создали метрики, поэтому тут пусто</div>
                <button class="btn-primary" id="analysis-create-metric"><i data-lucide="plus"></i> Создать метрику</button>
            </div>
        `;
        if (window.lucide) lucide.createIcons();
        document.getElementById('analysis-create-metric').addEventListener('click', () => {
            navigateTo('settings', { openAddModal: true });
        });
        return;
    }

    const end = todayStr();
    const start = daysAgo(30);

    container.innerHTML = `
        <div class="stats-header">
            <h2 class="stats-title">Анализ</h2>
            <div class="stats-controls">
                <div id="analysis-start-picker"></div>
                <span class="stats-dash">—</span>
                <div id="analysis-end-picker"></div>
                <button class="btn-icon" id="analysis-refresh" title="Обновить">
                    <i data-lucide="refresh-cw"></i>
                </button>
            </div>
        </div>
        <div id="correlation-section"></div>
    `;

    if (window.lucide) lucide.createIcons();

    const analysisStartPicker = createDatePicker('analysis-start-picker', start, () => {
        loadAnalysisCorrelation(analysisStartPicker.getValue(), analysisEndPicker.getValue());
    });
    const analysisEndPicker = createDatePicker('analysis-end-picker', end, () => {
        loadAnalysisCorrelation(analysisStartPicker.getValue(), analysisEndPicker.getValue());
    });

    document.getElementById('analysis-refresh').addEventListener('click', () => {
        loadAnalysisCorrelation(analysisStartPicker.getValue(), analysisEndPicker.getValue());
    });

    await loadAnalysisCorrelation(start, end);
}

async function loadAnalysisCorrelation(start, end) {
    const _t0 = performance.now();
    const corrEl = document.getElementById('correlation-section');

    corrEl.innerHTML = `
        <div class="corr-header">
            <div class="corr-header-left">
                <h3>Корреляции</h3>
                <span class="corr-count" id="corr-count" style="display:none"></span>
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

    // Event delegation: one listener for all corr detail buttons
    document.getElementById('corr-reports').addEventListener('click', (e) => {
        const btn = e.target.closest('.corr-detail-btn');
        if (!btn) return;
        e.stopPropagation();
        const d = corrPairData.get(btn.dataset.pairId);
        if (d) toggleCorrDetail(btn.dataset.pairId, d.mAId, d.mBId, d.lA, d.iA, d.lB, d.iB, d.pStart, d.pEnd);
    });

    loadCorrelationReport(start, end);
    console.debug(`[render] analysis  ${(performance.now() - _t0).toFixed(0)}ms`);
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
                if (currentPage !== 'analysis') {
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
        countEl.textContent = data.report.counts.total;
        countEl.style.display = '';
    }

    const calcBtn = document.getElementById('corr-calc-all');
    if (calcBtn) {
        calcBtn.textContent = data.report ? 'Обновить' : 'Рассчитать';
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
            <h2>Как читать результаты</h2>
            <div class="corr-help">
                <p>Приложение попарно сравнило все ваши метрики и выявило, какие из них регулярно меняются синхронно.</p>

                <h3>Пример:</h3>
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
                <p>Число справа отражает силу связи (корреляцию) по шкале от 0 до 1. Чем оно выше, тем устойчивее закономерность. Слова под иконками указывают направление: например, если зарядка утром помечена как «да», а настроение — «выше», это означает, что в дни с зарядкой настроение у вас, как правило, лучше.</p>

                <h3>Первый раздел — надёжные корреляции.</h3>
                <p>Приложение проверило, не является ли каждое совпадение случайным, и включило сюда только те пары, где вероятность случайного совпадения очень мала (p-value &lt; 0.05). Иными словами, найденная связь, скорее всего, отражает реальную закономерность, а не случайность.</p>

                <h3>Второй раздел — возможно ненадёжные.</h3>
                <p>Доверительный интервал слишком широк — оценка силы связи неточная. Связь, вероятно, существует, но нужно больше данных чтобы понять насколько она сильная.</p>

                <h3>Третий раздел — ненадёжные.</h3>
                <p>Либо данных пока недостаточно для уверенного вывода, либо шанс случайного совпадения остаётся высоким — и найденная закономерность может ничего не отражать. Стоит понаблюдать дольше.</p>

                <p>Показатели сравниваются не только внутри одного дня, но и между соседними днями — чтобы выявлять закономерности вида «вчера было X → сегодня наблюдается Y»:</p>
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

                <p>Надёжность результатов возрастает с количеством заполненных дней. До 10 дней — ориентировочные данные, после 20 — выводы становятся достаточно обоснованными.</p>

                <p style="color:var(--text-dim);font-style:italic">Важно: наличие связи не означает причинно-следственной зависимости. Например, зарядка и хорошее настроение могут не влиять друг на друга напрямую — оба показателя могут просто зависеть от качества сна.</p>

                <p>Карточки помогают замечать закономерности, но объяснять их предстоит вам.</p>
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

function renderCorrMetricLabel(label, icon, slotLabel, hint, dayLabel) {
    const iconHtml = `<span class="metric-icon">${icon || ''}</span>`;
    const slotHtml = slotLabel ? `<span class="corr-slot-badge">${slotLabel}</span>` : '';
    const dayHtml = dayLabel ? `<div class="corr-day-label">${dayLabel}</div>` : '';
    return `${iconHtml}<div class="corr-metric-text">${dayHtml}<div class="corr-metric-name">${label}${slotHtml}</div><div class="corr-pair-hint">${hint}</div></div>`;
}

const _metricStatsCache = {};

async function fetchMetricStats(metricId, start, end) {
    const key = `${metricId}_${start}_${end}`;
    if (_metricStatsCache[key]) return _metricStatsCache[key];
    const data = await api.request('GET', `/api/analytics/metric-stats?metric_id=${metricId}&start=${start}&end=${end}`);
    _metricStatsCache[key] = data;
    return data;
}

function formatMetricStatsHtml(stats) {
    if (!stats || stats.error) return '<span class="corr-stats-na">нет данных</span>';
    return stats.display_stats.map(s =>
        `<span>${s.label}</span><span>${s.value}</span>`
    ).join('');
}

async function toggleCorrDetail(pairId, metricAId, metricBId, labelA, iconA, labelB, iconB, periodStart, periodEnd) {
    const panel = document.getElementById(pairId);
    panel.classList.toggle('open');
    if (!panel.classList.contains('open')) return;
    const statsEl = document.getElementById(pairId + '-stats');
    if (statsEl.dataset.loaded) return;
    statsEl.innerHTML = '<div style="color:var(--text-dim);font-size:12px;">Загрузка...</div>';
    const d = corrPairData.get(pairId);
    const promises = [
        metricAId ? fetchMetricStats(metricAId, periodStart, periodEnd).catch(() => null) : Promise.resolve(null),
        metricBId ? fetchMetricStats(metricBId, periodStart, periodEnd).catch(() => null) : Promise.resolve(null),
        d && d.dbPairId ? api.getCorrelationPairChart(d.dbPairId).catch(() => null) : Promise.resolve(null),
    ];
    const [statsA, statsB, chartData] = await Promise.all(promises);
    const blockA = `<div class="corr-stats-block"><div class="corr-stats-label">${iconA || ''} ${labelA}</div><div class="corr-detail-grid">${formatMetricStatsHtml(statsA)}</div></div>`;
    const blockB = `<div class="corr-stats-block"><div class="corr-stats-label">${iconB || ''} ${labelB}</div><div class="corr-detail-grid">${formatMetricStatsHtml(statsB)}</div></div>`;
    statsEl.innerHTML = `<div class="corr-stats-columns">${blockA}${blockB}</div>`;
    statsEl.dataset.loaded = '1';
    const chartWrap = document.getElementById(pairId + '-chart-wrap');
    if (chartData && chartData.dates && chartData.dates.length > 0 && chartWrap) {
        chartWrap.style.display = 'block';
        renderCorrPairChart(pairId, chartData);
    }
}

function renderCorrPair(p, report) {
    const r = p.correlation;
    const absR = Math.abs(r);
    const cls = absR > 0.7 ? 'strong' : absR > 0.3 ? 'medium' : 'weak';
    const isLagged = p.lag_days && p.lag_days > 0;

    const typeLeft = isLagged ? p.type_b : p.type_a;
    const typeRight = isLagged ? p.type_a : p.type_b;
    const wrapHint = (text, positive) => positive
        ? `<span class="corr-word-pos">${text}</span>`
        : `<span class="corr-word-neg">${text}</span>`;
    let hintA, hintB;
    if (isLagged) {
        hintA = wrapHint(p.hint_b, p.hint_b_positive);
        hintB = wrapHint(p.hint_a, p.hint_a_positive);
    } else {
        hintA = wrapHint(p.hint_a, p.hint_a_positive);
        hintB = wrapHint(p.hint_b, p.hint_b_positive);
    }
    const optLeft = isLagged ? (p.option_b || '') : (p.option_a || '');
    const optRight = isLagged ? (p.option_a || '') : (p.option_b || '');
    if (typeLeft === 'enum_bool' && optLeft) hintA = `<span class="corr-word-pos">✓ ${optLeft}</span>`;
    if (typeRight === 'enum_bool' && optRight) hintB = r > 0 ? `<span class="corr-word-pos">✓ ${optRight}</span>` : `<span class="corr-word-neg">✗ ${optRight}</span>`;

    const rawLabelA = isLagged ? p.label_b : p.label_a;
    const rawIconA = (isLagged ? p.icon_b : p.icon_a) || '';
    const rawLabelB = isLagged ? p.label_a : p.label_b;
    const rawIconB = (isLagged ? p.icon_a : p.icon_b) || '';
    const labelA = renderCorrMetricLabel(rawLabelA, rawIconA, isLagged ? p.slot_label_b : p.slot_label_a, hintA, isLagged ? 'вчера' : '');
    const labelB = renderCorrMetricLabel(rawLabelB, rawIconB, isLagged ? p.slot_label_a : p.slot_label_b, hintB, isLagged ? 'сегодня' : '');

    const pairId = `corr-detail-${p.pair_id}`;
    corrPairData.set(pairId, {
        mAId: isLagged ? p.metric_b_id : p.metric_a_id,
        mBId: isLagged ? p.metric_a_id : p.metric_b_id,
        lA: rawLabelA,
        lB: rawLabelB,
        iA: rawIconA,
        iB: rawIconB,
        pStart: report.period_start,
        pEnd: report.period_end,
        dbPairId: p.pair_id,
    });

    return `<div class="corr-pair-wrapper">
        <div class="corr-pair-row">
        <div class="corr-col-metric">${labelA}</div>
        <div class="corr-arrow">↔</div>
        <div class="corr-col-metric">${labelB}</div>
        <div class="corr-col-info">
            <div class="corr-pair-value ${cls}">${absR.toFixed(3)} <button class="corr-detail-btn" data-pair-id="${pairId}">i</button></div>
            <div class="corr-info-sub">${p.data_points} дн.</div>
        </div>
    </div>
    <div class="corr-detail-panel" id="${pairId}">
        <div class="corr-detail-grid">
            <span>Корреляция</span><span>${r > 0 ? '+' : ''}${r.toFixed(4)}</span>
            <span>p-value</span><span>${p.p_value !== null && p.p_value !== undefined ? p.p_value.toFixed(4) : '—'}</span>
            ${p.ci_lower != null ? `<span>95% доверительный интервал</span><span>[${p.ci_lower.toFixed(4)}, ${p.ci_upper.toFixed(4)}]</span>` : ''}
            <span>Дней данных</span><span>${p.data_points}</span>
            <span>Сдвиг</span><span>${isLagged ? p.lag_days + ' дн.' : 'нет'}</span>
            ${p.quality_issue_label ? `<span>Причина</span><span style="color:var(--yellow)">${p.quality_issue_label}</span>` : ''}
        </div>
        <div class="corr-detail-stats" id="${pairId}-stats"></div>
        <div class="corr-detail-chart-wrap" id="${pairId}-chart-wrap" style="display:none;"><canvas id="${pairId}-chart"></canvas></div>
    </div>
    </div>`;
}

function renderCorrelationReport(report, container) {
    const c = report.counts;
    if (c.total === 0) {
        container.innerHTML = '<p style="color:var(--text-dim);font-size:13px;">Нет данных для корреляций.</p>';
        return;
    }

    const sigTotal = c.sig_strong + c.sig_medium + c.sig_weak;
    let html = '<div class="corr-section">';
    html += '<h4>Надёжные корреляции <span class="corr-sig corr-sig-yes">p&lt;0.05</span></h4>';

    if (sigTotal > 0) {
        if (c.sig_strong > 0) {
            html += `<div class="corr-subsection-header">Сильная корреляция <span class="corr-cat-count">${c.sig_strong}</span></div>`;
            html += '<div class="corr-category-pairs" id="corr-cat-sig_strong"></div>';
        }
        if (c.sig_medium > 0) {
            html += `<div class="corr-subsection-header">Средняя корреляция <span class="corr-cat-count">${c.sig_medium}</span></div>`;
            html += '<div class="corr-category-pairs" id="corr-cat-sig_medium"></div>';
        }
        if (c.sig_weak > 0) {
            html += `<div class="corr-subsection-header">Слабая корреляция <span class="corr-cat-count">${c.sig_weak}</span></div>`;
            html += '<div class="corr-category-pairs" id="corr-cat-sig_weak"></div>';
        }
    } else {
        html += '<div class="corr-empty-notice">';
        html += '<p>Пока нет уверенных корреляций.</p>';
        html += '<p>Продолжайте заполнять метрики — нужно минимум 10 дней данных, чтобы увидеть закономерности.</p>';
        html += '</div>';
    }
    html += '</div>';

    if (c.maybe > 0) {
        html += '<details class="corr-section corr-section-low" id="corr-maybe-details">';
        html += `<summary><h4>Возможно ненадёжные <span class="corr-cat-count">${c.maybe}</span></h4></summary>`;
        html += '<div class="corr-category-pairs" id="corr-cat-maybe"></div>';
        html += '</details>';
    }

    if (c.insig > 0) {
        html += '<details class="corr-section corr-section-low" id="corr-insig-details">';
        html += `<summary><h4>Ненадёжные <span class="corr-cat-count">${c.insig}</span></h4></summary>`;
        html += '<div class="corr-category-pairs" id="corr-cat-insig"></div>';
        html += '</details>';
    }

    container.innerHTML = html;

    // Load significant categories
    const categoriesToLoad = ['sig_strong', 'sig_medium', 'sig_weak'].filter(cat => c[cat] > 0);
    for (const cat of categoriesToLoad) {
        const el = document.getElementById(`corr-cat-${cat}`);
        if (el) loadCategoryPairs(report.id, cat, el, report, 0);
    }

    // Lazy load maybe on <details> open
    const maybeDetails = document.getElementById('corr-maybe-details');
    if (maybeDetails) {
        maybeDetails.addEventListener('toggle', () => {
            if (!maybeDetails.open) return;
            const el = document.getElementById('corr-cat-maybe');
            if (el && !el.dataset.loaded) {
                el.dataset.loaded = '1';
                loadCategoryPairs(report.id, 'maybe', el, report, 0);
            }
        });
    }

    // Lazy load insig on <details> open
    const insigDetails = document.getElementById('corr-insig-details');
    if (insigDetails) {
        insigDetails.addEventListener('toggle', () => {
            if (!insigDetails.open) return;
            const el = document.getElementById('corr-cat-insig');
            if (el && !el.dataset.loaded) {
                el.dataset.loaded = '1';
                loadCategoryPairs(report.id, 'insig', el, report, 0);
            }
        });
    }
}

async function loadCategoryPairs(reportId, category, containerEl, report, offset) {
    const loader = document.createElement('div');
    loader.className = 'corr-loader';
    loader.innerHTML = '<div class="corr-loader-spinner"></div>';
    containerEl.appendChild(loader);

    try {
        const data = await api.getCorrelationPairs(reportId, { category, offset });
        loader.remove();

        let html = '';
        for (const p of data.pairs) html += renderCorrPair(p, report);
        containerEl.insertAdjacentHTML('beforeend', html);

        if (data.has_more) {
            const sentinel = document.createElement('div');
            sentinel.className = 'corr-scroll-sentinel';
            containerEl.appendChild(sentinel);

            const observer = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting) {
                    observer.disconnect();
                    sentinel.remove();
                    loadCategoryPairs(reportId, category, containerEl, report, offset + 50);
                }
            }, { rootMargin: '200px' });
            observer.observe(sentinel);
        }
    } catch (err) {
        loader.remove();
        containerEl.insertAdjacentHTML('beforeend', '<p style="color:var(--text-dim);font-size:13px;">Ошибка загрузки.</p>');
    }
}

// ─── Correlation Charts ───
const corrChartInstances = new Map();

function buildCorrYAxis(type, position, color, reverse) {
    const cfg = {
        position,
        grid: { display: position === 'left', color: 'rgba(128,128,128,0.1)' },
        ticks: { color },
        reverse,
    };
    if (type === 'bool' || type === 'enum_bool') {
        cfg.min = 0; cfg.max = 1;
        cfg.ticks.callback = v => v === 1 ? 'Да' : v === 0 ? 'Нет' : '';
        cfg.ticks.stepSize = 1;
    } else if (type === 'time') {
        cfg.min = 0; cfg.max = 1439;
        cfg.ticks.callback = v => minutesToHHMM(v);
        cfg.ticks.stepSize = 360;
    } else if (type === 'duration') {
        cfg.min = 0;
        cfg.ticks.callback = v => { const h = Math.floor(v / 60); const m = v % 60; return m === 0 ? `${h}ч` : `${h}ч ${m}м`; };
    } else if (type === 'scale') {
        cfg.min = 0; cfg.max = 100;
        cfg.ticks.callback = v => v + '%';
    }
    return cfg;
}

function formatCorrTooltip(value, type) {
    if (type === 'bool' || type === 'enum_bool') return value === 1 ? 'Да' : 'Нет';
    if (type === 'time') return minutesToHHMM(value);
    if (type === 'duration') { const h = Math.floor(value / 60); const m = Math.round(value % 60); return `${h}ч ${m}м`; }
    if (type === 'scale') return Math.round(value) + '%';
    return Math.round(value * 100) / 100;
}

function renderCorrPairChart(pairId, data) {
    if (corrChartInstances.has(pairId)) {
        corrChartInstances.get(pairId).destroy();
    }
    const canvas = document.getElementById(pairId + '-chart');
    if (!canvas) return;

    const style = getComputedStyle(document.documentElement);
    const colorA = style.getPropertyValue('--accent').trim();
    const colorB = '#ff9800';

    const d = corrPairData.get(pairId);
    const dispLabelA = data.label_a;
    const dispLabelB = data.label_b;

    const labels = data.dates.map(formatShortDate);
    const showPoints = data.dates.length <= 30;
    const isNeg = data.correlation < 0;
    const isLag = data.lag_days > 0;

    const scales = {
        yA: buildCorrYAxis(data.type_a, 'left', colorA, false),
        yB: buildCorrYAxis(data.type_b, 'right', colorB, isNeg),
        x: {
            ticks: { maxTicksLimit: 7, maxRotation: 0 },
            grid: { display: false },
        },
    };

    if (isLag && data.original_dates_b) {
        scales.x2 = {
            position: 'top',
            labels: data.original_dates_b.map(formatShortDate),
            ticks: { maxTicksLimit: 7, maxRotation: 0, color: colorB, font: { size: 10 } },
            grid: { display: false },
        };
    }

    const datasets = [
        {
            label: dispLabelA,
            data: data.values_a,
            borderColor: colorA,
            backgroundColor: colorA + '22',
            yAxisID: 'yA',
            tension: 0.3,
            pointRadius: showPoints ? 3 : 0,
            stepped: (data.type_a === 'bool' || data.type_a === 'enum_bool') ? 'middle' : false,
        },
        {
            label: dispLabelB,
            data: data.values_b,
            borderColor: colorB,
            backgroundColor: colorB + '22',
            yAxisID: 'yB',
            tension: 0.3,
            pointRadius: showPoints ? 3 : 0,
            stepped: (data.type_b === 'bool' || data.type_b === 'enum_bool') ? 'middle' : false,
        },
    ];

    const chart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, position: 'bottom', labels: { usePointStyle: true, boxWidth: 8, padding: 16 } },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const tp = ctx.datasetIndex === 0 ? data.type_a : data.type_b;
                            return `${ctx.dataset.label}: ${formatCorrTooltip(ctx.parsed.y, tp)}`;
                        },
                    },
                },
            },
            scales,
        },
    });
    corrChartInstances.set(pairId, chart);
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
    const chartType = (metricType === 'int' || metricType === 'float') ? 'number' : metricType === 'duration' ? 'duration' : metricType;
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
    } else if (chartType === 'duration') {
        yConfig.min = 0;
        yConfig.ticks = { callback: v => { const h = Math.floor(v / 60); const m = v % 60; return m === 0 ? `${h}ч` : `${h}ч ${m}м`; } };
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
    } else if (chartType === 'duration') {
        config.options.plugins.tooltip = {
            callbacks: { label: ctx => { const v = ctx.parsed.y; return `${Math.floor(v / 60)}ч ${Math.round(v % 60)}м`; } }
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
    const opLabels = {'+': '+', '-': '−', '*': '×', '/': '÷', '>': '>', '<': '<'};
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
    syncResultTypeWithComparison();
}

function syncResultTypeWithComparison() {
    const sel = document.getElementById('nm-result-type');
    if (!sel) return;
    const hasComp = formulaTokens.some(t => t.type === 'op' && (t.value === '>' || t.value === '<'));
    if (hasComp) {
        sel.value = 'bool';
        sel.disabled = true;
    } else {
        sel.disabled = false;
    }
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
    if (!metric) { navigateTo('charts'); return; }

    if (isMetricBlocked(metric)) {
        container.innerHTML = `
            <div class="detail-header">
                <button class="btn-small" id="detail-back"><i data-lucide="arrow-left"></i> Статистика</button>
                <h2>${metricLabelHtml(metric)}</h2>
            </div>
            <div class="metric-private-hint" style="text-align:center;padding:32px 0;">Сначала отключите приватный режим</div>
        `;
        if (window.lucide) lucide.createIcons();
        document.getElementById('detail-back').addEventListener('click', () => navigateTo('charts'));
        return;
    }

    const end = todayStr();
    const start = daysAgo(90);

    container.innerHTML = `
        <div class="detail-header">
            <button class="btn-small" id="detail-back"><i data-lucide="arrow-left"></i> Статистика</button>
            <h2>${metricLabelHtml(metric)}</h2>
        </div>
        <div class="detail-controls">
            <div id="detail-start-picker"></div>
            <span>—</span>
            <div id="detail-end-picker"></div>
            <button class="btn-small" id="detail-refresh">Обновить</button>
        </div>
        <div class="detail-chart-container"><canvas id="detail-chart"></canvas></div>
        <div id="detail-stats"></div>
        ${metric.type === 'text' ? '<div id="detail-notes-table"></div>' : ''}
    `;

    if (window.lucide) lucide.createIcons();

    const detailStartPicker = createDatePicker('detail-start-picker', start, () => {
        loadMetricDetail(metricId, metric, detailStartPicker.getValue(), detailEndPicker.getValue());
    });
    const detailEndPicker = createDatePicker('detail-end-picker', end, () => {
        loadMetricDetail(metricId, metric, detailStartPicker.getValue(), detailEndPicker.getValue());
    });

    document.getElementById('detail-back').addEventListener('click', () => navigateTo('charts'));
    document.getElementById('detail-refresh').addEventListener('click', () => {
        loadMetricDetail(metricId, metric, detailStartPicker.getValue(), detailEndPicker.getValue());
    });

    await loadMetricDetail(metricId, metric, start, end);
}

async function loadMetricDetail(metricId, metric, start, end) {
    const _t0 = performance.now();
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

    const mt = metric.type === 'computed' ? (metric.result_type || 'float') : metric.type === 'integration' ? (metric.value_type || 'number') : metric.type === 'text' ? 'number' : metric.type;

    if (mt === 'enum' && trend.option_series) {
        // Enum: stacked bar chart with per-option datasets
        const optColors = ['#6c8cff', '#4caf50', '#ff9800', '#e91e63', '#9c27b0', '#00bcd4', '#795548', '#607d8b'];
        const options = trend.options || [];
        const dates = Object.values(trend.option_series)[0]?.map(p => formatShortDate(p.date)) || [];
        const datasets = options.map((opt, idx) => ({
            label: opt.label,
            data: (trend.option_series[opt.label] || []).map(p => p.value),
            backgroundColor: optColors[idx % optColors.length] + 'cc',
            borderRadius: 3,
        }));
        detailChartInstance = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: { labels: dates, datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: true, position: 'bottom' } },
                scales: {
                    x: { stacked: true, ticks: { maxTicksLimit: 7, maxRotation: 0 }, grid: { display: false } },
                    y: { stacked: true, ticks: { stepSize: 1 } },
                },
            },
        });
    } else {
        const points = trend.points || [];
        const chartConfig = buildChartConfig(points, mt, colors);
        detailChartInstance = new Chart(canvas.getContext('2d'), chartConfig);
    }

    // Render stats (use result_type for computed)
    const statsType = metric.type === 'computed' ? (metric.result_type || 'float') : metric.type === 'integration' ? (metric.value_type || 'number') : metric.type;
    renderDetailStats(stats, statsType);

    // Notes table for text metrics
    if (metric.type === 'text') {
        const notesTableEl = document.getElementById('detail-notes-table');
        if (notesTableEl) {
            try {
                const notes = await api.listNotes(metricId, start, end);
                if (notes.length > 0) {
                    let tableHtml = '<h3>Заметки</h3>';
                    tableHtml += '<button class="btn-small" id="copy-notes-btn"><i data-lucide="copy"></i> Копировать</button>';
                    tableHtml += '<table class="notes-table"><thead><tr><th>Дата</th><th>Время</th><th>Заметка</th></tr></thead><tbody>';
                    for (const n of notes) {
                        const time = n.created_at ? new Date(n.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '';
                        tableHtml += `<tr><td>${n.date}</td><td>${time}</td><td>${_escapeHtml(n.text)}</td></tr>`;
                    }
                    tableHtml += '</tbody></table>';
                    notesTableEl.innerHTML = tableHtml;
                    if (window.lucide) lucide.createIcons();
                    document.getElementById('copy-notes-btn')?.addEventListener('click', async () => {
                        const lines = ['| Дата | Время | Заметка |', '|---|---|---|'];
                        for (const n of notes) {
                            const time = n.created_at ? new Date(n.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '';
                            lines.push(`| ${n.date} | ${time} | ${n.text} |`);
                        }
                        const text = lines.join('\n');
                        try {
                            if (navigator.clipboard && navigator.clipboard.writeText) {
                                await navigator.clipboard.writeText(text);
                            } else {
                                const ta = document.createElement('textarea');
                                ta.value = text;
                                ta.style.position = 'fixed';
                                ta.style.opacity = '0';
                                document.body.appendChild(ta);
                                ta.select();
                                document.execCommand('copy');
                                document.body.removeChild(ta);
                            }
                            const cbtn = document.getElementById('copy-notes-btn');
                            if (cbtn) { cbtn.textContent = 'Скопировано!'; setTimeout(() => { cbtn.innerHTML = '<i data-lucide="copy"></i> Копировать'; if (window.lucide) lucide.createIcons(); }, 1500); }
                        } catch (err) {
                            console.warn('Copy failed', err);
                            alert('Не удалось скопировать. Попробуйте выделить текст вручную.');
                        }
                    });
                }
            } catch (e) { console.warn('Failed to load notes', e); }
        }
    }

    console.debug(`[render] metric-detail(${metricId})  ${(performance.now() - _t0).toFixed(0)}ms`);
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
    } else if (metricType === 'duration') {
        cards += `
            <div class="stat-card"><div class="stat-value">${stats.average}</div><div class="stat-label">Среднее</div></div>
            <div class="stat-card"><div class="stat-value">${stats.min}</div><div class="stat-label">Мин</div></div>
            <div class="stat-card"><div class="stat-value">${stats.max}</div><div class="stat-label">Макс</div></div>
            ${stats.median !== undefined ? `<div class="stat-card"><div class="stat-value">${stats.median}</div><div class="stat-label">Медиана</div></div>` : ''}
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
    } else if (metricType === 'text') {
        cards += `
            <div class="stat-card"><div class="stat-value">${stats.total_notes || 0}</div><div class="stat-label">Всего заметок</div></div>
            <div class="stat-card"><div class="stat-value">${stats.average_per_day || 0}</div><div class="stat-label">Среднее/день</div></div>
            <div class="stat-card"><div class="stat-value">${stats.max_per_day || 0}</div><div class="stat-label">Макс/день</div></div>
        `;
    } else if (metricType === 'enum') {
        if (stats.most_common) {
            cards += `<div class="stat-card"><div class="stat-value">${stats.most_common}</div><div class="stat-label">Чаще всего</div></div>`;
        }
        if (stats.option_stats) {
            for (const os of stats.option_stats) {
                cards += `<div class="stat-card"><div class="stat-value">${os.percent}%</div><div class="stat-label">${os.label}</div></div>`;
            }
        }
    }

    el.innerHTML = `<h3>Статистика</h3><div class="detail-stats-grid">${cards}</div>`;
}

// ─── Settings Page ───
async function renderSettings(container, { archiveOpen = false, openAddModal = false } = {}) {
    const _t0 = performance.now();
    container.innerHTML = '<div class="loading-spinner"></div>';
    const allMetrics = await api.cachedGet('/api/metrics');
    let html = '<div class="settings-header">';
    html += `<div class="user-info"><i data-lucide="user"></i><span>${localStorage.getItem('la_username') || 'Unknown'}</span></div>`;
    html += '<button class="btn-small btn-logout" id="logout-btn"><i data-lucide="log-out"></i><span>Выйти</span></button>';
    html += '</div>';

    const currentTheme = localStorage.getItem(THEME_KEY) || 'dark';
    const isLight = currentTheme === 'light';
    html += '<div class="theme-row">';
    html += `<span class="theme-row-label"><span id="theme-icon-emoji">${isLight ? '☀️' : '🌙'}</span> <span id="theme-label">${isLight ? 'Светлая тема' : 'Тёмная тема'}</span></span>`;
    html += `<label class="theme-switch"><input type="checkbox" id="theme-switch-input" ${isLight ? '' : 'checked'}><span class="slider"></span></label>`;
    html += '</div>';

    const privacyOn = isPrivacyMode();
    html += '<div class="theme-row">';
    html += `<span class="theme-row-label">🔒 <span>Приватный режим</span></span>`;
    html += `<label class="theme-switch"><input type="checkbox" id="privacy-switch-input" ${privacyOn ? 'checked' : ''}><span class="slider"></span></label>`;
    html += '</div>';

    html += `<h2>Настройки метрик <span class="corr-count">${allMetrics.filter(m => m.enabled).length}</span></h2>`;
    html += '<div class="settings-actions">';
    html += '<button class="btn-primary" id="add-metric"><i data-lucide="plus"></i> Новая метрика</button>';
    html += '<button class="btn-small" id="manage-categories-btn"><i data-lucide="folders"></i> Категории</button>';
    html += '<button class="btn-small" id="export-btn"><i data-lucide="download"></i> Экспорт</button>';
    html += '<button class="btn-small" id="import-btn"><i data-lucide="upload"></i> Импорт</button>';
    html += '</div>';
    html += '<input type="file" id="import-file" accept=".zip" style="display:none">';

    const activeMetrics = allMetrics.filter(m => m.enabled);
    const archivedMetrics = allMetrics.filter(m => !m.enabled);

    if (allMetrics.length === 0) {
        html += `<div class="empty-state">
            <div class="empty-state-icon"><i data-lucide="settings"></i></div>
            <div class="empty-state-text">Вы пока не создали метрики, поэтому тут пусто</div>
        </div>`;
    } else {
        // Load categories for grouping
        let settingsCategories = [];
        try { settingsCategories = await api.getCategories(); } catch(e) {}
        const settingsCatById = {};
        for (const c of settingsCategories) {
            settingsCatById[c.id] = c;
            for (const ch of (c.children || [])) settingsCatById[ch.id] = ch;
        }
        const settingsMetricsByCat = {};
        const settingsUncategorized = [];
        for (const m of activeMetrics) {
            if (m.slots && m.slots.length >= 2) {
                // Group slots by category_id
                const slotsByCat = {};
                for (const s of m.slots) {
                    const key = s.category_id != null ? String(s.category_id) : 'null';
                    if (!slotsByCat[key]) slotsByCat[key] = [];
                    slotsByCat[key].push(s);
                }

                const uniqueCats = Object.keys(slotsByCat);
                if (uniqueCats.length === 1) {
                    // All slots in one category — single row as before
                    const catId = m.slots[0].category_id;
                    if (catId && settingsCatById[catId]) {
                        if (!settingsMetricsByCat[catId]) settingsMetricsByCat[catId] = [];
                        settingsMetricsByCat[catId].push(m);
                    } else {
                        settingsUncategorized.push(m);
                    }
                } else {
                    // Slots in different categories — split into view items
                    for (const [key, catSlots] of Object.entries(slotsByCat)) {
                        const catId = key === 'null' ? null : parseInt(key);
                        const viewItem = { ...m, _displaySlots: catSlots };
                        if (catId && settingsCatById[catId]) {
                            if (!settingsMetricsByCat[catId]) settingsMetricsByCat[catId] = [];
                            settingsMetricsByCat[catId].push(viewItem);
                        } else {
                            settingsUncategorized.push(viewItem);
                        }
                    }
                }
                continue;
            }
            if (m.category_id && settingsCatById[m.category_id]) {
                if (!settingsMetricsByCat[m.category_id]) settingsMetricsByCat[m.category_id] = [];
                settingsMetricsByCat[m.category_id].push(m);
            } else {
                settingsUncategorized.push(m);
            }
        }
        const hasSettingsCategories = settingsCategories.length > 0;

        // Build metric name map for condition display
        const settingsMetricNameMap = {};
        for (const m of activeMetrics) settingsMetricNameMap[m.id] = m.name;

        function renderSettingRow(m) {
            const displaySlots = m._displaySlots || m.slots || [];
            const slotIds = displaySlots.map(s => s.id).join(',');
            const slotsBadge = displaySlots.length > 1
                ? `<span class="setting-slots">${displaySlots.length}x</span>`
                : displaySlots.length === 1
                    ? `<span class="setting-slots">${displaySlots[0].label}</span>`
                    : (m.slots && m.slots.length > 0)
                        ? `<span class="setting-slots">${m.slots.length}x</span>`
                        : '';
            const condBadge = m.condition_metric_id
                ? `<span class="setting-condition" title="Зависит от: ${settingsMetricNameMap[m.condition_metric_id] || '?'}"><i data-lucide="git-branch"></i></span>` : '';
            const typeIcon = (m.type === 'time' ? '<i data-lucide="clock"></i> Время'
                : m.type === 'duration' ? '<i data-lucide="timer"></i> Длительность'
                : m.type === 'number' ? '<i data-lucide="hash"></i> Число'
                : m.type === 'scale' ? '<i data-lucide="sliders-horizontal"></i> Шкала'
                : m.type === 'enum' ? '<i data-lucide="list"></i> Варианты'
                : m.type === 'text' ? '<i data-lucide="file-text"></i> Заметка'
                : m.type === 'computed' ? '<i data-lucide="calculator"></i> Формула'
                : m.type === 'integration' ? (m.provider === 'activitywatch' ? '<i data-lucide="monitor"></i> ActivityWatch' : '<i data-lucide="list-checks"></i> Todoist')
                : '<i data-lucide="toggle-left"></i> Да/Нет') + slotsBadge + condBadge;
            return `<div class="setting-row" data-metric-id="${m.id}"${slotIds ? ` data-slot-ids="${slotIds}"` : ''}>
                <span class="drag-handle">⠿</span>
                <div class="setting-info">
                    <span class="setting-name">${metricLabelHtml(m)}</span>
                    <span class="setting-type">${typeIcon}</span>
                </div>
                <div class="setting-actions">
                    ${(m.type === 'scale' || m.type === 'bool') ? `<button class="btn-icon convert-btn" data-metric="${m.id}" title="Конвертировать"><i data-lucide="repeat-2"></i></button>` : ''}
                    <button class="btn-icon edit-btn" data-metric="${m.id}"><i data-lucide="pencil"></i></button>
                    <button class="btn-icon archive-btn" data-metric="${m.id}"><i data-lucide="archive"></i></button>
                    <button class="btn-icon delete-btn btn-icon-danger" data-metric="${m.id}"><i data-lucide="trash-2"></i></button>
                </div>
            </div>`;
        }

        for (const topCat of settingsCategories) {
            const topMetrics = settingsMetricsByCat[topCat.id] || [];
            html += `<h2 class="fill-time-header">${topCat.name}</h2>`;
            html += `<div class="category" data-category-id="${topCat.id}">`;
            for (const m of topMetrics) html += renderSettingRow(m);
            html += '</div>';
            for (const ch of (topCat.children || [])) {
                const chMetrics = settingsMetricsByCat[ch.id] || [];
                html += `<div class="category" data-category-id="${ch.id}"><h3>${ch.name}</h3>`;
                for (const m of chMetrics) html += renderSettingRow(m);
                html += '</div>';
            }
        }
        if (settingsUncategorized.length > 0 || !hasSettingsCategories) {
            if (hasSettingsCategories) html += `<h2 class="fill-time-header">Без категории</h2>`;
            html += `<div class="category" data-category-id="">`;
            for (const m of settingsUncategorized) html += renderSettingRow(m);
            html += '</div>';
        }
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
                : m.type === 'duration' ? '<i data-lucide="timer"></i> Длительность'
                : m.type === 'number' ? '<i data-lucide="hash"></i> Число'
                : m.type === 'scale' ? '<i data-lucide="sliders-horizontal"></i> Шкала'
                : m.type === 'text' ? '<i data-lucide="file-text"></i> Заметка'
                : m.type === 'computed' ? '<i data-lucide="calculator"></i> Формула'
                : m.type === 'integration' ? '<span class="metric-icon">' + TODOIST_ICON + '</span> Todoist'
                : '<i data-lucide="toggle-left"></i> Да/Нет') + slotsBadge;
            html += `<div class="setting-row archived-row">
                <div class="setting-info">
                    <span class="setting-name archived">${metricLabelHtml(m)}</span>
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
    // Integrations section
    html += '<div class="integrations-section"><h2>Интеграции</h2>';
    html += '<p class="integrations-description">Сторонние интеграции позволяют автоматически получать данные из других приложений</p>';
    html += '<div id="integrations-list"><div class="integration-status"><span class="text-dim">Загрузка...</span></div></div>';
    html += '</div>';

    container.innerHTML = html;
    if (window.lucide) lucide.createIcons();

    // Theme toggle
    const themeSwitch = document.getElementById('theme-switch-input');
    if (themeSwitch) {
        themeSwitch.addEventListener('change', toggleTheme);
    }

    const privacySwitch = document.getElementById('privacy-switch-input');
    if (privacySwitch) {
        privacySwitch.addEventListener('change', async () => {
            try {
                await api.setPrivacyMode(privacySwitch.checked);
                setPrivacyMode(privacySwitch.checked);
            } catch (e) {
                console.error('Failed to set privacy mode:', e);
                privacySwitch.checked = !privacySwitch.checked;
            }
            renderSettings(container, { archiveOpen });
        });
    }

    // Load integrations status
    _loadIntegrationsSection();

    document.getElementById('logout-btn').addEventListener('click', () => {
        api.logout();
        isAuthenticated = false;
        currentUser = null;
        navigateTo('login');
    });

    document.getElementById('add-metric').addEventListener('click', showAddMetricModal);

    // Manage categories button
    document.getElementById('manage-categories-btn')?.addEventListener('click', () => {
        navigateTo('categories');
    });

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

    // Convert button listeners
    container.querySelectorAll('.convert-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const metricId = btn.dataset.metric;
            const metric = allMetrics.find(m => m.id === parseInt(metricId));
            if (metric) showConvertModal(metric);
        });
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
            if (!confirm('Архивировать метрику?')) return;
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
    setupMetricDragDrop(container);
    console.debug(`[render] settings  ${(performance.now() - _t0).toFixed(0)}ms`);
}

function setupMetricDragDrop(container) {
    let dragRow = null;
    let clone = null;
    let startX = 0, startY = 0;
    let offsetX = 0, offsetY = 0;
    let isDragging = false;
    const DRAG_THRESHOLD = 5;

    function getDropTarget(y) {
        const rows = container.querySelectorAll('.setting-row[data-metric-id]:not(.dragging)');
        let closest = null;
        let closestDist = Infinity;
        let insertBefore = true;
        for (const row of rows) {
            const rect = row.getBoundingClientRect();
            const mid = rect.top + rect.height / 2;
            const dist = Math.abs(y - mid);
            if (dist < closestDist) {
                closestDist = dist;
                closest = row;
                insertBefore = y < mid;
            }
        }
        return { target: closest, before: insertBefore };
    }

    function clearIndicators() {
        container.querySelectorAll('.drag-over-before, .drag-over-after').forEach(el => {
            el.classList.remove('drag-over-before', 'drag-over-after');
        });
    }

    function collectOrder() {
        const items = [];
        const rows = container.querySelectorAll('.setting-row[data-metric-id]');
        rows.forEach((row, index) => {
            const catDiv = row.closest('.category[data-category-id]');
            const catIdStr = catDiv ? catDiv.dataset.categoryId : '';
            const catId = catIdStr && !isNaN(parseInt(catIdStr)) ? parseInt(catIdStr) : null;
            const metricId = parseInt(row.dataset.metricId);
            const slotIdsAttr = row.dataset.slotIds;

            if (slotIdsAttr) {
                // Split metric — send per-slot items
                const slotIds = slotIdsAttr.split(',').map(Number);
                for (const slotId of slotIds) {
                    items.push({
                        id: metricId,
                        sort_order: index * 10,
                        category_id: catId,
                        slot_id: slotId,
                    });
                }
            } else {
                items.push({
                    id: metricId,
                    sort_order: index * 10,
                    category_id: catId,
                });
            }
        });
        return items;
    }

    container.addEventListener('pointerdown', (e) => {
        const handle = e.target.closest('.drag-handle');
        if (!handle) return;
        const row = handle.closest('.setting-row[data-metric-id]');
        if (!row) return;

        e.preventDefault();
        dragRow = row;
        startX = e.clientX;
        startY = e.clientY;
        isDragging = false;

        handle.setPointerCapture(e.pointerId);
    });

    container.addEventListener('pointermove', (e) => {
        if (!dragRow) return;

        if (!isDragging) {
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
            isDragging = true;

            // Create clone, remember cursor offset relative to element
            const rect = dragRow.getBoundingClientRect();
            offsetX = startX - rect.left;
            offsetY = startY - rect.top;
            clone = dragRow.cloneNode(true);
            clone.className = 'setting-row drag-clone';
            clone.style.width = rect.width + 'px';
            clone.style.left = rect.left + 'px';
            clone.style.top = rect.top + 'px';
            document.body.appendChild(clone);

            dragRow.classList.add('dragging');
        }

        if (clone) {
            clone.style.left = (e.clientX - offsetX) + 'px';
            clone.style.top = (e.clientY - offsetY) + 'px';
        }

        clearIndicators();
        const { target, before } = getDropTarget(e.clientY);
        if (target) {
            target.classList.add(before ? 'drag-over-before' : 'drag-over-after');
        }
    });

    container.addEventListener('pointerup', async (e) => {
        if (!dragRow) return;

        clearIndicators();

        if (isDragging) {
            const { target, before } = getDropTarget(e.clientY);

            if (target && target !== dragRow) {
                // Move DOM element to new position
                const targetParent = target.parentElement;
                if (before) {
                    targetParent.insertBefore(dragRow, target);
                } else {
                    targetParent.insertBefore(dragRow, target.nextSibling);
                }
            }

            // Remove clone
            if (clone) {
                clone.remove();
                clone = null;
            }
            dragRow.classList.remove('dragging');

            // Remove empty category divs and orphaned headers
            container.querySelectorAll('.category[data-category-id]').forEach(catDiv => {
                if (!catDiv.querySelector('.setting-row[data-metric-id]')) {
                    const prev = catDiv.previousElementSibling;
                    catDiv.remove();
                    if (prev && prev.classList.contains('fill-time-header')) {
                        const next = prev.nextElementSibling;
                        if (!next || !next.classList.contains('category') || next.classList.contains('archive-section')) {
                            prev.remove();
                        }
                    }
                }
            });

            // Save new order to server
            const items = collectOrder();
            try {
                await api.reorderMetrics(items);
            } catch (err) {
                console.error('Reorder failed:', err);
            }
        }

        dragRow = null;
        isDragging = false;
    });

    container.addEventListener('pointercancel', () => {
        if (clone) {
            clone.remove();
            clone = null;
        }
        if (dragRow) {
            dragRow.classList.remove('dragging');
        }
        clearIndicators();
        dragRow = null;
        isDragging = false;
    });
}

async function renderCategoryManager(container) {
    let categories = [];
    try { categories = await api.getCategories(); } catch(e) {}

    let html = '<div class="cat-manager-header">';
    html += '<button class="btn-icon" id="cat-back-btn"><i data-lucide="arrow-left"></i></button>';
    html += '<h2>Категории</h2>';
    html += '<button class="btn-small btn-primary" id="cat-add-btn"><i data-lucide="plus"></i> Добавить</button>';
    html += '</div>';

    html += '<div id="cat-list">';
    if (categories.length === 0) {
        html += '<div class="empty-state"><div class="empty-state-text">Нет категорий</div></div>';
    } else {
        for (const cat of categories) {
            html += `<div class="cat-item" data-cat-id="${cat.id}" data-parent-id="">
                <span class="drag-handle">⠿</span>
                <span class="cat-item-name">${cat.name}</span>
                <div class="cat-item-actions">
                    <button class="btn-icon cat-edit" data-cat-id="${cat.id}"><i data-lucide="pencil"></i></button>
                    <button class="btn-icon btn-icon-danger cat-del" data-cat-id="${cat.id}"><i data-lucide="trash-2"></i></button>
                </div>
            </div>`;
            for (const ch of (cat.children || [])) {
                html += `<div class="cat-item cat-item-child" data-cat-id="${ch.id}" data-parent-id="${cat.id}">
                    <span class="drag-handle">⠿</span>
                    <span class="cat-item-name">${ch.name}</span>
                    <div class="cat-item-actions">
                        <button class="btn-icon cat-edit" data-cat-id="${ch.id}"><i data-lucide="pencil"></i></button>
                        <button class="btn-icon btn-icon-danger cat-del" data-cat-id="${ch.id}"><i data-lucide="trash-2"></i></button>
                    </div>
                </div>`;
            }
        }
    }
    html += '</div>';
    container.innerHTML = html;
    if (window.lucide) lucide.createIcons();

    document.getElementById('cat-back-btn').addEventListener('click', () => navigateTo('settings'));

    document.getElementById('cat-add-btn').addEventListener('click', async () => {
        const name = prompt('Название категории:');
        if (!name || !name.trim()) return;
        try {
            await api.createCategory({ name: name.trim() });
            await renderCategoryManager(container);
        } catch (e) { alert('Ошибка: ' + e.message); }
    });

    container.querySelectorAll('.cat-edit').forEach(btn => {
        btn.addEventListener('click', async () => {
            const catId = parseInt(btn.dataset.catId);
            const nameEl = btn.closest('.cat-item').querySelector('.cat-item-name');
            const currentName = nameEl?.textContent?.trim() || '';
            const newName = prompt('Новое название:', currentName);
            if (!newName || !newName.trim() || newName.trim() === currentName) return;
            try {
                await api.updateCategory(catId, { name: newName.trim() });
                await renderCategoryManager(container);
            } catch (e) { alert('Ошибка: ' + e.message); }
        });
    });

    container.querySelectorAll('.cat-del').forEach(btn => {
        btn.addEventListener('click', async () => {
            const catId = parseInt(btn.dataset.catId);
            if (!confirm('Удалить категорию? Подкатегории будут удалены. Метрики сохранятся без категории.')) return;
            try {
                await api.deleteCategory(catId);
                await renderCategoryManager(container);
            } catch (e) { alert('Ошибка: ' + e.message); }
        });
    });

    setupCategoryDragDrop(container);
}

function setupCategoryDragDrop(container) {
    let dragItem = null;
    let clone = null;
    let startX = 0, startY = 0;
    let offsetX = 0, offsetY = 0;
    let isDragging = false;
    let nestingLevel = 0; // 0 = top-level, 1 = child
    const DRAG_THRESHOLD = 5;
    const NEST_THRESHOLD = 40;

    function getDropTarget(y) {
        const items = container.querySelectorAll('.cat-item:not(.dragging)');
        let closest = null;
        let closestDist = Infinity;
        let insertBefore = true;
        for (const item of items) {
            const rect = item.getBoundingClientRect();
            const mid = rect.top + rect.height / 2;
            const dist = Math.abs(y - mid);
            if (dist < closestDist) {
                closestDist = dist;
                closest = item;
                insertBefore = y < mid;
            }
        }
        return { target: closest, before: insertBefore };
    }

    function clearIndicators() {
        container.querySelectorAll('.drag-over-before, .drag-over-after').forEach(el => {
            el.classList.remove('drag-over-before', 'drag-over-after');
        });
    }

    function collectCategoryOrder() {
        const items = [];
        const catItems = container.querySelectorAll('.cat-item');
        let lastTopId = null;
        let topOrder = 0;
        let childOrder = 0;
        for (const el of catItems) {
            const id = parseInt(el.dataset.catId);
            const isChild = el.classList.contains('cat-item-child');
            if (isChild && lastTopId) {
                items.push({ id, sort_order: childOrder * 10, parent_id: lastTopId });
                childOrder++;
            } else {
                lastTopId = id;
                childOrder = 0;
                items.push({ id, sort_order: topOrder * 10, parent_id: null });
                topOrder++;
            }
        }
        return items;
    }

    // Check if making this item a child is valid (it must not itself have children)
    function hasChildren(catId) {
        const items = container.querySelectorAll('.cat-item');
        let found = false;
        for (const el of items) {
            if (found) {
                if (el.dataset.parentId === String(catId)) return true;
                if (!el.classList.contains('cat-item-child')) return false;
            }
            if (parseInt(el.dataset.catId) === catId) found = true;
        }
        return false;
    }

    container.addEventListener('pointerdown', (e) => {
        const handle = e.target.closest('.drag-handle');
        if (!handle) return;
        const item = handle.closest('.cat-item');
        if (!item) return;

        e.preventDefault();
        dragItem = item;
        startX = e.clientX;
        startY = e.clientY;
        isDragging = false;
        nestingLevel = item.classList.contains('cat-item-child') ? 1 : 0;

        handle.setPointerCapture(e.pointerId);
    });

    container.addEventListener('pointermove', (e) => {
        if (!dragItem) return;

        if (!isDragging) {
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
            isDragging = true;

            const rect = dragItem.getBoundingClientRect();
            offsetX = startX - rect.left;
            offsetY = startY - rect.top;
            clone = dragItem.cloneNode(true);
            clone.className = 'cat-item drag-clone';
            clone.style.width = rect.width + 'px';
            clone.style.left = rect.left + 'px';
            clone.style.top = rect.top + 'px';
            document.body.appendChild(clone);
            dragItem.classList.add('dragging');
        }

        if (clone) {
            clone.style.left = (e.clientX - offsetX) + 'px';
            clone.style.top = (e.clientY - offsetY) + 'px';
        }

        // Determine nesting from horizontal offset
        const deltaX = e.clientX - startX;
        const prevNesting = nestingLevel;
        if (deltaX > NEST_THRESHOLD && nestingLevel === 0) {
            nestingLevel = 1;
        } else if (deltaX < -NEST_THRESHOLD && nestingLevel === 1) {
            nestingLevel = 0;
        }
        if (nestingLevel !== prevNesting && clone) {
            clone.classList.toggle('cat-item-child', nestingLevel === 1);
        }

        clearIndicators();
        const { target, before } = getDropTarget(e.clientY);
        if (target) {
            target.classList.add(before ? 'drag-over-before' : 'drag-over-after');
        }
    });

    container.addEventListener('pointerup', async (e) => {
        if (!dragItem) return;
        clearIndicators();

        if (isDragging) {
            const { target, before } = getDropTarget(e.clientY);
            const catId = parseInt(dragItem.dataset.catId);

            // Don't allow nesting if item has children
            if (nestingLevel === 1 && hasChildren(catId)) {
                nestingLevel = 0;
            }

            if (target && target !== dragItem) {
                const parent = target.parentElement;
                if (before) {
                    parent.insertBefore(dragItem, target);
                } else {
                    parent.insertBefore(dragItem, target.nextSibling);
                }
            }

            // Apply nesting class
            if (nestingLevel === 1) {
                dragItem.classList.add('cat-item-child');
            } else {
                dragItem.classList.remove('cat-item-child');
            }

            if (clone) { clone.remove(); clone = null; }
            dragItem.classList.remove('dragging');

            // Ensure first item is always top-level
            const firstItem = container.querySelector('.cat-item');
            if (firstItem) firstItem.classList.remove('cat-item-child');

            const items = collectCategoryOrder();
            try {
                await api.reorderCategories(items);
            } catch (err) {
                console.error('Category reorder failed:', err);
            }
        }

        dragItem = null;
        isDragging = false;
        nestingLevel = 0;
    });

    container.addEventListener('pointercancel', () => {
        if (clone) { clone.remove(); clone = null; }
        if (dragItem) dragItem.classList.remove('dragging');
        clearIndicators();
        dragItem = null;
        isDragging = false;
        nestingLevel = 0;
    });
}

async function _loadIntegrationsSection() {
    const listEl = document.getElementById('integrations-list');
    if (!listEl) return;
    try {
        const integrations = await api.listIntegrations();
        if (integrations.length === 0) {
            // Нет доступных интеграций на сервере — скрываем секцию
            const section = listEl.closest('.integrations-section');
            if (section) section.style.display = 'none';
            return;
        }

        let html = '';

        // Todoist
        const todoist = integrations.find(i => i.provider === 'todoist');
        if (todoist) {
            if (todoist.enabled) {
                html += `<div class="integration-card">
                    <div class="integration-status">
                        <span class="integration-provider"><span class="metric-icon">${TODOIST_ICON}</span> Todoist подключён</span>
                        <button class="btn-small btn-danger" id="disconnect-todoist"><i data-lucide="unplug"></i> Отключить</button>
                    </div>
                    <div class="integration-note">Отслеживание выполненных и отфильтрованных задач из Todoist</div>
                </div>`;
            } else {
                html += `<div class="integration-card">
                    <div class="integration-status">
                        <span class="integration-provider"><span class="metric-icon">${TODOIST_ICON}</span> Todoist</span>
                        <button class="btn-primary btn-small" id="connect-todoist"><i data-lucide="plug"></i> Подключить</button>
                    </div>
                    <div class="integration-note">Отслеживание выполненных и отфильтрованных задач из Todoist</div>
                </div>`;
            }
        }

        // ActivityWatch
        const aw = integrations.find(i => i.provider === 'activitywatch');
        if (aw) {
            if (aw.enabled) {
                html += `<div class="integration-card">
                    <div class="integration-status">
                        <span class="integration-provider"><span class="metric-icon">${AW_ICON}</span> ActivityWatch подключён</span>
                        <button class="btn-small btn-danger" id="disconnect-aw"><i data-lucide="unplug"></i> Отключить</button>
                    </div>
                    <div class="integration-note">Экранное время с вашего компьютера</div>
                    <div id="aw-connection-check" class="aw-connection-check"><span class="text-dim">Проверяю доступность...</span></div>
                    <div id="aw-categories-section" class="aw-categories-section">
                        <div class="aw-categories-header">
                            <span class="label-text">Категории приложений</span>
                            <button class="btn-small" id="aw-add-category"><i data-lucide="plus"></i> Категория</button>
                        </div>
                        <div id="aw-categories-list" class="aw-categories-list"><span class="text-dim">Загрузка...</span></div>
                    </div>
                </div>`;
            } else {
                html += `<div class="integration-card">
                    <div class="integration-status">
                        <span class="integration-provider"><span class="metric-icon">${AW_ICON}</span> ActivityWatch</span>
                        <button class="btn-primary btn-small" id="connect-aw"><i data-lucide="plug"></i> Подключить</button>
                    </div>
                    <div class="integration-note">Экранное время с вашего компьютера. Требуется <a href="https://activitywatch.net/" target="_blank">ActivityWatch</a>.</div>
                </div>`;
            }
        }

        listEl.innerHTML = html;
        if (window.lucide) lucide.createIcons();

        // Todoist handlers
        if (todoist && todoist.enabled) {
            document.getElementById('disconnect-todoist')?.addEventListener('click', async () => {
                if (!confirm('Отключить Todoist? Метрика будет архивирована, данные сохранятся.')) return;
                try {
                    await api.disconnectIntegration('todoist');
                    await loadMetrics();
                    navigateTo('settings');
                } catch (error) { alert('Ошибка: ' + error.message); }
            });
        } else if (todoist) {
            document.getElementById('connect-todoist')?.addEventListener('click', async () => {
                try {
                    const { url } = await api.getTodoistAuthUrl();
                    window.location.href = url;
                } catch (error) { alert('Ошибка: ' + error.message); }
            });
        }

        // ActivityWatch handlers
        if (aw && aw.enabled) {
            document.getElementById('disconnect-aw')?.addEventListener('click', async () => {
                if (!confirm('Отключить ActivityWatch? Данные сохранятся.')) return;
                try {
                    await api.awDisable();
                    navigateTo('settings');
                } catch (error) { alert('Ошибка: ' + error.message); }
            });
            // Check AW availability
            const checkEl = document.getElementById('aw-connection-check');
            if (checkEl) {
                const available = await awClient.checkAvailable();
                checkEl.innerHTML = available
                    ? '<span style="color:var(--green)"><i data-lucide="wifi"></i> ActivityWatch доступен</span>'
                    : '<span style="color:var(--red)"><i data-lucide="wifi-off"></i> ActivityWatch недоступен — убедитесь, что он запущен</span>';
                if (window.lucide) lucide.createIcons();
            }
            // Load categories UI
            _loadAWCategories();
            document.getElementById('aw-add-category')?.addEventListener('click', async () => {
                const name = prompt('Название категории:');
                if (!name || !name.trim()) return;
                const color = '#' + Math.floor(Math.random()*16777215).toString(16).padStart(6, '0');
                try {
                    await api.awCreateCategory(name.trim(), color);
                    _loadAWCategories();
                } catch (error) { alert('Ошибка: ' + error.message); }
            });
        } else if (aw) {
            document.getElementById('connect-aw')?.addEventListener('click', async () => {
                await api.awEnable();
                navigateTo('settings');
            });
        }
    } catch (error) {
        listEl.innerHTML = '<div class="integration-status"><span class="text-dim">Не удалось загрузить</span></div>';
    }
}

// Track which category sections are expanded
const _awExpandedSections = new Set();

async function _loadAWCategories() {
    const container = document.getElementById('aw-categories-list');
    if (!container) return;
    try {
        const [categories, apps] = await Promise.all([
            api.awGetCategories(),
            api.awGetApps(),
        ]);

        const appsByCategory = {};
        const uncategorized = [];
        for (const app of apps) {
            if (app.category_id) {
                if (!appsByCategory[app.category_id]) appsByCategory[app.category_id] = [];
                appsByCategory[app.category_id].push(app);
            } else {
                uncategorized.push(app);
            }
        }

        let html = '';
        for (const cat of categories) {
            const catApps = appsByCategory[cat.id] || [];
            const sectionKey = `aw-cat-${cat.id}`;
            const isOpen = _awExpandedSections.has(sectionKey);
            html += `<div class="aw-category-item" data-cat-id="${cat.id}">
                <div class="aw-category-header" data-toggle="${sectionKey}">
                    <span class="aw-category-color" style="background:${cat.color}"></span>
                    <span class="aw-category-name">${cat.name}</span>
                    <span class="aw-category-count">${catApps.length}</span>
                    <button class="btn-icon aw-cat-edit" data-cat-id="${cat.id}" title="Редактировать"><i data-lucide="pencil"></i></button>
                    <button class="btn-icon aw-cat-delete" data-cat-id="${cat.id}" title="Удалить"><i data-lucide="trash-2"></i></button>
                    <i data-lucide="chevron-down" class="aw-cat-chevron"></i>
                </div>
                <div class="aw-category-apps" id="${sectionKey}" style="display:${isOpen ? 'block' : 'none'}">
                    ${catApps.length === 0 ? '<span class="text-dim">Нет приложений</span>' :
                        catApps.map(a => `<div class="aw-app-item">
                            <span>${a.app_name}</span>
                            <button class="btn-icon aw-app-remove" data-app="${encodeURIComponent(a.app_name)}" title="Убрать из категории"><i data-lucide="x"></i></button>
                        </div>`).join('')}
                </div>
            </div>`;
        }

        if (uncategorized.length > 0) {
            const isOpen = _awExpandedSections.has('aw-cat-uncat');
            html += `<div class="aw-category-item aw-uncategorized">
                <div class="aw-category-header" data-toggle="aw-cat-uncat">
                    <span class="aw-category-color" style="background:var(--text-dim)"></span>
                    <span class="aw-category-name">Без категории</span>
                    <span class="aw-category-count">${uncategorized.length}</span>
                    <i data-lucide="chevron-down" class="aw-cat-chevron"></i>
                </div>
                <div class="aw-category-apps" id="aw-cat-uncat" style="display:${isOpen ? 'block' : 'none'}">
                    ${uncategorized.map(a => `<div class="aw-app-item">
                        <span>${a.app_name}</span>
                        <select class="aw-app-assign" data-app="${encodeURIComponent(a.app_name)}">
                            <option value="">Назначить...</option>
                            ${categories.map(c => `<option value="${c.id}">${c.name}</option>`).join('')}
                        </select>
                    </div>`).join('')}
                </div>
            </div>`;
        }

        if (!html) {
            html = '<span class="text-dim">Нет категорий. Синхронизируйте данные и создайте категории.</span>';
        }

        container.innerHTML = html;
        if (window.lucide) lucide.createIcons();

        // Toggle category expand
        container.querySelectorAll('[data-toggle]').forEach(header => {
            header.addEventListener('click', (e) => {
                if (e.target.closest('button') || e.target.closest('select')) return;
                const sectionKey = header.dataset.toggle;
                const target = document.getElementById(sectionKey);
                if (!target) return;
                const nowOpen = target.style.display === 'none';
                target.style.display = nowOpen ? 'block' : 'none';
                if (nowOpen) _awExpandedSections.add(sectionKey);
                else _awExpandedSections.delete(sectionKey);
            });
        });

        // Delete category
        container.querySelectorAll('.aw-cat-delete').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!confirm('Удалить категорию? Приложения станут некатегоризированными.')) return;
                try {
                    await api.awDeleteCategory(parseInt(btn.dataset.catId));
                    _loadAWCategories();
                } catch (error) { alert('Ошибка: ' + error.message); }
            });
        });

        // Edit category
        container.querySelectorAll('.aw-cat-edit').forEach(btn => {
            btn.addEventListener('click', async () => {
                const catId = parseInt(btn.dataset.catId);
                const cat = categories.find(c => c.id === catId);
                if (!cat) return;
                const newName = prompt('Новое название:', cat.name);
                if (!newName || !newName.trim() || newName.trim() === cat.name) return;
                try {
                    await api.awUpdateCategory(catId, { name: newName.trim() });
                    _loadAWCategories();
                } catch (error) { alert('Ошибка: ' + error.message); }
            });
        });

        // Remove app from category
        container.querySelectorAll('.aw-app-remove').forEach(btn => {
            btn.addEventListener('click', async () => {
                const appName = decodeURIComponent(btn.dataset.app);
                try {
                    await api.awSetAppCategory(appName, null);
                    _loadAWCategories();
                } catch (error) { alert('Ошибка: ' + error.message); }
            });
        });

        // Assign app to category
        container.querySelectorAll('.aw-app-assign').forEach(select => {
            select.addEventListener('change', async () => {
                const appName = decodeURIComponent(select.dataset.app);
                const categoryId = select.value ? parseInt(select.value) : null;
                if (!categoryId) return;
                try {
                    await api.awSetAppCategory(appName, categoryId);
                    _loadAWCategories();
                } catch (error) { alert('Ошибка: ' + error.message); }
            });
        });
    } catch (error) {
        container.innerHTML = '<span class="text-dim">Не удалось загрузить категории</span>';
    }
}

async function showConvertModal(metric) {
    const CONVERSIONS = { scale: ['scale'], bool: ['enum'] };
    const TYPE_LABELS = { scale: 'Шкала', bool: 'Да/Нет', enum: 'Варианты' };
    const allowed = CONVERSIONS[metric.type] || [];
    if (!allowed.length) return;

    const targetType = allowed[0]; // MVP: single target per source type
    let preview;
    try {
        preview = await api.convertPreview(metric.id, targetType);
    } catch (err) {
        alert('Ошибка загрузки preview: ' + err.message);
        return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    function renderModal() {
        const sourceLabel = TYPE_LABELS[metric.type] || metric.type;
        const targetLabel = TYPE_LABELS[targetType] || targetType;
        let scaleInfo = '';
        if (metric.type === 'scale') {
            scaleInfo = ` (${metric.scale_min}–${metric.scale_max})`;
        }

        let configHtml = '';
        let mappingHtml = '';

        if (metric.type === 'scale' && targetType === 'scale') {
            configHtml = `
                <div class="convert-config">
                    <h4>Новая конфигурация</h4>
                    <div class="convert-config-row">
                        <label>Мин: <input type="number" id="conv-scale-min" value="${metric.scale_min}" class="input-small"></label>
                        <label>Макс: <input type="number" id="conv-scale-max" value="${metric.scale_max}" class="input-small"></label>
                        <label>Шаг: <input type="number" id="conv-scale-step" value="${metric.scale_step}" min="1" class="input-small"></label>
                    </div>
                </div>`;

            mappingHtml = buildScaleMappingHtml(preview);
        } else if (metric.type === 'bool' && targetType === 'enum') {
            configHtml = `
                <div class="convert-config">
                    <h4>Опции для нового типа "Варианты"</h4>
                    <div class="convert-enum-options">
                        <div class="enum-options-list" id="conv-enum-options-list"></div>
                        <button type="button" class="btn-add-slot" id="conv-add-enum-option">+ Добавить вариант</button>
                    </div>
                </div>`;

            mappingHtml = buildBoolMappingHtml(preview);
        }

        overlay.innerHTML = `
            <div class="modal">
                <h3>Конвертация: ${metric.icon ? `<span class="metric-icon">${metric.icon}</span> ` : ''}${metric.name}</h3>
                <div class="convert-warning">⚠ Рекомендуем сделать экспорт данных перед конвертацией</div>
                <div class="convert-type-info">
                    <span>Текущий тип: <strong>${sourceLabel}${scaleInfo}</strong></span>
                    <span>→ Целевой тип: <strong>${targetLabel}</strong></span>
                </div>
                ${configHtml}
                <div class="convert-mapping-section">
                    <h4>Маппинг значений</h4>
                    ${preview.entries_by_value.length === 0 ? '<p class="text-dim">Нет записей для конвертации</p>' : ''}
                    <div id="convert-mapping-table">${mappingHtml}</div>
                </div>
                <div class="convert-impact" id="convert-impact"></div>
                <div class="modal-actions">
                    <button class="btn btn-secondary" id="conv-cancel">Отмена</button>
                    <button class="btn btn-primary" id="conv-submit">Конвертировать</button>
                </div>
            </div>`;

        if (window.lucide) lucide.createIcons();
        updateImpact();
        attachConvertListeners();
    }

    function buildScaleMappingHtml(preview) {
        if (!preview.entries_by_value.length) return '';
        const newMin = parseInt(document.getElementById('conv-scale-min')?.value ?? metric.scale_min);
        const newMax = parseInt(document.getElementById('conv-scale-max')?.value ?? metric.scale_max);
        const newStep = parseInt(document.getElementById('conv-scale-step')?.value ?? metric.scale_step);

        const newValues = [];
        for (let v = newMin; v <= newMax; v += newStep) newValues.push(v);

        let html = '<table class="convert-mapping-table"><thead><tr><th>Старое</th><th>Записей</th><th>→ Новое</th></tr></thead><tbody>';
        for (const entry of preview.entries_by_value) {
            const options = ['<option value="__delete__">Удалить</option>']
                .concat(newValues.map(v => {
                    const sel = v === parseInt(entry.value) ? ' selected' : '';
                    return `<option value="${v}"${sel}>${v}</option>`;
                }));
            html += `<tr>
                <td>${entry.display}</td>
                <td>${entry.count}</td>
                <td><select class="convert-select" data-old="${entry.value}">${options.join('')}</select></td>
            </tr>`;
        }
        html += '</tbody></table>';
        return html;
    }

    function getConvEnumOptions() {
        const inputs = overlay.querySelectorAll('#conv-enum-options-list .enum-option-input');
        return Array.from(inputs).map(inp => inp.value.trim()).filter(Boolean);
    }

    function addConvEnumOption(label = '') {
        const list = overlay.querySelector('#conv-enum-options-list');
        if (!list) return;
        const row = document.createElement('div');
        row.className = 'enum-option-row';
        row.innerHTML = `<input type="text" class="form-input enum-option-input" placeholder="Название варианта" value="${label}">
            <button type="button" class="btn-remove-slot">&times;</button>`;
        list.appendChild(row);
        row.querySelector('.btn-remove-slot').onclick = () => { row.remove(); rebuildMappingSelects(); };
        row.querySelector('.enum-option-input').addEventListener('input', rebuildMappingSelects);
    }

    function rebuildMappingSelects() {
        const table = document.getElementById('convert-mapping-table');
        if (!table) return;
        // Save current selections
        const saved = {};
        overlay.querySelectorAll('.convert-select').forEach(sel => {
            saved[sel.dataset.old] = sel.value;
        });
        table.innerHTML = buildBoolMappingHtml(preview);
        // Restore selections where possible
        overlay.querySelectorAll('.convert-select').forEach(sel => {
            const prev = saved[sel.dataset.old];
            if (prev !== undefined) {
                const optExists = Array.from(sel.options).some(o => o.value === prev);
                if (optExists) sel.value = prev;
            }
        });
        updateImpact();
        attachMappingListeners();
    }

    function buildBoolMappingHtml(preview) {
        if (!preview.entries_by_value.length) return '';
        const enumOpts = getConvEnumOptions();

        let html = '<table class="convert-mapping-table"><thead><tr><th>Старое</th><th>Записей</th><th>→ Новое</th></tr></thead><tbody>';
        for (const entry of preview.entries_by_value) {
            const defaultLabel = entry.value === 'true' ? 'Да' : 'Нет';
            const options = ['<option value="__delete__">Удалить</option>']
                .concat(enumOpts.map(opt => {
                    const sel = opt === defaultLabel ? ' selected' : '';
                    return `<option value="${opt}"${sel}>${opt}</option>`;
                }));
            html += `<tr>
                <td>${entry.display}</td>
                <td>${entry.count}</td>
                <td><select class="convert-select" data-old="${entry.value}">${options.join('')}</select></td>
            </tr>`;
        }
        html += '</tbody></table>';
        return html;
    }

    function updateImpact() {
        const selects = overlay.querySelectorAll('.convert-select');
        let toConvert = 0, toDelete = 0;
        for (const sel of selects) {
            const entry = preview.entries_by_value.find(e => e.value === sel.dataset.old);
            if (!entry) continue;
            if (sel.value === '__delete__') toDelete += entry.count;
            else toConvert += entry.count;
        }
        const el = document.getElementById('convert-impact');
        if (el) {
            el.innerHTML = `Будет изменено: <strong>${toConvert}</strong> | Удалено: <strong>${toDelete}</strong>`;
        }
    }

    function attachConvertListeners() {
        // Cancel
        overlay.querySelector('#conv-cancel')?.addEventListener('click', () => overlay.remove());
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

        // Config change → rebuild mapping
        if (metric.type === 'scale') {
            for (const id of ['conv-scale-min', 'conv-scale-max', 'conv-scale-step']) {
                overlay.querySelector(`#${id}`)?.addEventListener('change', () => {
                    const table = document.getElementById('convert-mapping-table');
                    if (table) { table.innerHTML = buildScaleMappingHtml(preview); updateImpact(); attachMappingListeners(); }
                });
            }
        } else if (metric.type === 'bool') {
            // Pre-fill default options
            addConvEnumOption('Нет');
            addConvEnumOption('Да');
            // Add button
            overlay.querySelector('#conv-add-enum-option')?.addEventListener('click', () => {
                addConvEnumOption('');
                rebuildMappingSelects();
            });
        }

        attachMappingListeners();

        // Submit
        overlay.querySelector('#conv-submit')?.addEventListener('click', handleConvert);
    }

    function attachMappingListeners() {
        overlay.querySelectorAll('.convert-select').forEach(sel => {
            sel.addEventListener('change', updateImpact);
        });
    }

    async function handleConvert() {
        const mapping = {};
        overlay.querySelectorAll('.convert-select').forEach(sel => {
            mapping[sel.dataset.old] = sel.value === '__delete__' ? null : sel.value;
        });

        const body = { target_type: targetType, value_mapping: mapping };

        if (metric.type === 'scale' && targetType === 'scale') {
            body.scale_min = parseInt(overlay.querySelector('#conv-scale-min').value);
            body.scale_max = parseInt(overlay.querySelector('#conv-scale-max').value);
            body.scale_step = parseInt(overlay.querySelector('#conv-scale-step').value);
        } else if (metric.type === 'bool' && targetType === 'enum') {
            const enumOpts = getConvEnumOptions();
            if (enumOpts.length < 2) {
                alert('Нужно минимум 2 варианта');
                return;
            }
            const uniqueOpts = new Set(enumOpts.map(o => o.toLowerCase()));
            if (uniqueOpts.size !== enumOpts.length) {
                alert('Названия вариантов должны быть уникальными');
                return;
            }
            body.enum_options = enumOpts;
            body.multi_select = false;
        }

        if (!confirm('Это необратимая операция. Продолжить?')) return;

        const submitBtn = overlay.querySelector('#conv-submit');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Конвертация...';

        try {
            const result = await api.convertMetric(metric.id, body);
            alert(`Готово! Изменено: ${result.converted}, удалено: ${result.deleted}`);
            overlay.remove();
            await loadMetrics();
            const container = document.getElementById('page-content');
            if (container) renderSettings(container);
        } catch (err) {
            alert('Ошибка конвертации: ' + err.message);
            submitBtn.disabled = false;
            submitBtn.textContent = 'Конвертировать';
        }
    }

    document.body.appendChild(overlay);
    renderModal();
}


async function showMetricModal(mode = 'create', existingMetric = null) {
    const isEdit = mode === 'edit';
    const title = isEdit ? 'Редактировать метрику' : 'Создать метрику';
    const buttonText = isEdit ? 'Сохранить изменения' : 'Создать метрику';
    const currentType = existingMetric?.type || 'bool';

    // Fetch integration data for create mode
    let todoistConnected = false;
    let todoistAvailableMetrics = [];
    let awConnected = false;
    let awAvailableMetrics = [];
    let awCategories = [];
    let awApps = [];
    if (!isEdit) {
        try {
            const [integrations, todoistMetrics, awMetrics] = await Promise.all([
                api.listIntegrations().catch(() => []),
                api.getTodoistAvailableMetrics().catch(() => []),
                api.awGetAvailableMetrics().catch(() => []),
            ]);
            const todoist = integrations.find(i => i.provider === 'todoist');
            todoistConnected = !!(todoist && todoist.enabled);
            todoistAvailableMetrics = todoistMetrics;
            const aw = integrations.find(i => i.provider === 'activitywatch');
            awConnected = !!(aw && aw.enabled);
            awAvailableMetrics = awMetrics;
            if (awConnected) {
                [awCategories, awApps] = await Promise.all([
                    api.awGetCategories().catch(() => []),
                    api.awGetApps().catch(() => []),
                ]);
            }
        } catch { /* ignore */ }
    }

    function getScaleParams() {
        const minEl = document.getElementById('nm-scale-min');
        const maxEl = document.getElementById('nm-scale-max');
        const stepEl = document.getElementById('nm-scale-step');
        return {
            min: minEl && minEl.value !== '' ? parseInt(minEl.value) : (existingMetric?.scale_min ?? 1),
            max: maxEl && maxEl.value !== '' ? parseInt(maxEl.value) : (existingMetric?.scale_max ?? 5),
            step: stepEl && stepEl.value !== '' ? parseInt(stepEl.value) : (existingMetric?.scale_step ?? 1),
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
        if (type === 'enum') {
            const optInputs = overlay ? overlay.querySelectorAll('.enum-option-input') : [];
            const labels = Array.from(optInputs).map(i => i.value.trim()).filter(v => v !== '');
            if (labels.length === 0) {
                return '<div class="enum-buttons single"><button class="enum-btn">Вариант 1</button><button class="enum-btn">Вариант 2</button></div>';
            }
            const isMulti = document.getElementById('nm-multi-select')?.checked;
            return `<div class="enum-buttons ${isMulti ? 'multi' : 'single'}">${labels.map(l => `<button class="enum-btn">${l}</button>`).join('')}</div>`;
        }
        if (type === 'text') {
            return `<textarea class="note-textarea" placeholder="Написать заметку..." rows="2" disabled></textarea>`;
        }
        if (type === 'computed') {
            return `<div class="computed-value empty">= ?</div>`;
        }
        if (type === 'integration') {
            return `<div class="computed-value empty">—</div>
                <button type="button" class="btn-small btn-fetch" disabled>Получить</button>`;
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
        if (type === 'duration') {
            return `<span class="label-text">Тип: Длительность</span>
                    <span class="label-hint">Продолжительность (сон, тренировка, чтение)</span>`;
        }
        if (type === 'number') {
            return `<span class="label-text">Тип: Число</span>
                    <span class="label-hint">Целое число с кнопками +/−</span>`;
        }
        if (type === 'scale') {
            return `<span class="label-text">Тип: Шкала</span>
                    <span class="label-hint">Оценка по шкале с настраиваемым диапазоном</span>`;
        }
        if (type === 'enum') {
            return `<span class="label-text">Тип: Варианты</span>
                    <span class="label-hint">Выбор из заданного списка вариантов</span>`;
        }
        if (type === 'text') {
            return `<span class="label-text">Тип: Заметка</span>
                    <span class="label-hint">Текстовые заметки, можно добавлять несколько в день</span>`;
        }
        if (type === 'computed') {
            return `<span class="label-text">Тип: Формула</span>
                    <span class="label-hint">Вычисляется автоматически из других метрик</span>`;
        }
        if (type === 'integration') {
            return `<span class="label-text">Тип: Интеграция</span>
                    <span class="label-hint">Данные получаются из внешнего сервиса</span>`;
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
                <div class="form-label">
                    <span class="label-text">Название</span>
                    <input id="nm-name" placeholder="Например: Зарядка" class="form-input" value="${existingMetric?.name || ''}">
                </div>

                <div class="form-label" ${isEdit && currentType === 'integration' ? 'style="display:none"' : ''}>
                    <span class="label-text">Иконка</span>
                    <div class="emoji-picker-wrapper">
                        <button type="button" class="emoji-trigger-btn ${existingMetric?.icon ? 'has-icon' : ''}" id="nm-icon-btn">${existingMetric?.icon || '<i data-lucide="smile-plus"></i>'}</button>
                        <button type="button" class="emoji-clear-btn" id="nm-icon-clear" style="display:${existingMetric?.icon ? 'inline' : 'none'}">&times;</button>
                        <input type="hidden" id="nm-icon" value="${existingMetric?.icon || ''}">
                    </div>
                </div>

                <div class="form-label">
                    <span class="label-text">Категория <span class="label-optional">(необязательно)</span></span>
                    <select id="nm-category-id" class="form-input">
                        <option value="">Без категории</option>
                    </select>
                </div>

                <label class="enum-multi-select-label">
                    <input type="checkbox" id="nm-private" ${existingMetric?.private ? 'checked' : ''}> 🔒 Приватная метрика
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
                ${currentType === 'enum' ? `
                <div class="form-section" id="nm-enum-config" style="display: flex">
                    <span class="label-text">Варианты</span>
                    <div class="enum-options-list" id="nm-enum-options"></div>
                    <button type="button" class="btn-add-slot" id="nm-add-enum-option">+ Добавить вариант</button>
                    <label class="enum-multi-select-label">
                        <input type="checkbox" id="nm-multi-select" ${existingMetric?.multi_select ? 'checked' : ''}> Можно выбрать несколько
                    </label>
                    <span class="label-hint">Минимум 2 варианта</span>
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
                            <button type="button" class="formula-op-btn" data-op=">">&gt;</button>
                            <button type="button" class="formula-op-btn" data-op="<">&lt;</button>
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
                            <option value="duration" ${existingMetric?.result_type === 'duration' ? 'selected' : ''}>Длительность</option>
                        </select>
                    </div>
                    <span class="label-hint">Поддерживаются +, −, ×, ÷, >, < и скобки. Время можно комбинировать с длительностью.</span>
                </div>
                ` : ''}
                ${currentType !== 'computed' && currentType !== 'integration' && currentType !== 'text' ? `
                <div class="form-section" id="nm-slots-section">
                    <span class="label-text">Сколько раз в день замерять?</span>
                    <div class="slots-choice-grid">
                        <label class="slots-choice-card ${!existingMetric?.slots?.length ? 'selected' : ''}" data-slots="single">
                            <input type="radio" name="nm-slots-mode" value="single" ${!existingMetric?.slots?.length ? 'checked' : ''}>
                            <div class="slots-choice-icon"><i data-lucide="circle-dot"></i></div>
                            <span class="slots-choice-title">Один раз</span>
                        </label>
                        <label class="slots-choice-card ${existingMetric?.slots?.length ? 'selected' : ''}" data-slots="multiple">
                            <input type="radio" name="nm-slots-mode" value="multiple" ${existingMetric?.slots?.length ? 'checked' : ''}>
                            <div class="slots-choice-icon"><i data-lucide="list"></i></div>
                            <span class="slots-choice-title">Несколько раз</span>
                        </label>
                    </div>
                    <div class="slots-config" id="nm-slots-config" style="display:${existingMetric?.slots?.length ? 'flex' : 'none'}">
                        <div class="slot-labels-list" id="nm-slot-labels"></div>
                        <button type="button" class="btn-add-slot" id="nm-add-slot">+ Добавить замер</button>
                        <span class="label-hint">Названия замеров можно переименовать</span>
                    </div>
                </div>
                ` : ''}
                ` : `
                <div class="form-section" id="nm-type-section">
                    <span class="label-text">Тип метрики</span>
                    <span class="label-hint">Как вы будете записывать значение</span>
                    <div class="type-cards-grid">
                        <div class="type-card ${currentType === 'bool' ? 'selected' : ''}">
                            <input type="radio" name="nm-type" value="bool" ${currentType === 'bool' ? 'checked' : ''}>
                            <div class="type-card-icon"><i data-lucide="check-circle"></i></div>
                            <div class="type-card-info"><div class="type-card-name">Да / Нет</div><div class="type-card-desc">Было или нет</div></div>
                        </div>
                        <div class="type-card ${currentType === 'enum' ? 'selected' : ''}">
                            <input type="radio" name="nm-type" value="enum" ${currentType === 'enum' ? 'checked' : ''}>
                            <div class="type-card-icon"><i data-lucide="list"></i></div>
                            <div class="type-card-info"><div class="type-card-name">Варианты</div><div class="type-card-desc">Выбор из списка</div></div>
                        </div>
                        <div class="type-card ${currentType === 'number' ? 'selected' : ''}">
                            <input type="radio" name="nm-type" value="number" ${currentType === 'number' ? 'checked' : ''}>
                            <div class="type-card-icon"><i data-lucide="hash"></i></div>
                            <div class="type-card-info"><div class="type-card-name">Число</div><div class="type-card-desc">Целое значение</div></div>
                        </div>
                        <div class="type-card ${currentType === 'scale' ? 'selected' : ''}">
                            <input type="radio" name="nm-type" value="scale" ${currentType === 'scale' ? 'checked' : ''}>
                            <div class="type-card-icon"><i data-lucide="sliders-horizontal"></i></div>
                            <div class="type-card-info"><div class="type-card-name">Шкала</div><div class="type-card-desc">Оценка от 1 до N</div></div>
                        </div>
                        <div class="type-card ${currentType === 'time' ? 'selected' : ''}">
                            <input type="radio" name="nm-type" value="time" ${currentType === 'time' ? 'checked' : ''}>
                            <div class="type-card-icon"><i data-lucide="clock"></i></div>
                            <div class="type-card-info"><div class="type-card-name">Время</div><div class="type-card-desc">Часы и минуты</div></div>
                        </div>
                        <div class="type-card ${currentType === 'duration' ? 'selected' : ''}">
                            <input type="radio" name="nm-type" value="duration" ${currentType === 'duration' ? 'checked' : ''}>
                            <div class="type-card-icon"><i data-lucide="timer"></i></div>
                            <div class="type-card-info"><div class="type-card-name">Длительность</div><div class="type-card-desc">Часы и минуты (сколько)</div></div>
                        </div>
                        <div class="type-card ${currentType === 'text' ? 'selected' : ''}">
                            <input type="radio" name="nm-type" value="text" ${currentType === 'text' ? 'checked' : ''}>
                            <div class="type-card-icon"><i data-lucide="file-text"></i></div>
                            <div class="type-card-info"><div class="type-card-name">Заметка</div><div class="type-card-desc">Текст, несколько в день</div></div>
                        </div>
                        <div class="type-card ${currentType === 'computed' ? 'selected' : ''}">
                            <input type="radio" name="nm-type" value="computed" ${currentType === 'computed' ? 'checked' : ''}>
                            <div class="type-card-icon"><i data-lucide="calculator"></i></div>
                            <div class="type-card-info"><div class="type-card-name">Формула</div><div class="type-card-desc">Вычисляется из других метрик</div></div>
                        </div>
                        ${todoistConnected ? `<div class="type-card">
                            <input type="radio" name="nm-type" value="integration-todoist">
                            <div class="type-card-icon"><i data-lucide="list-checks"></i></div>
                            <div class="type-card-info"><div class="type-card-name">Todoist</div><div class="type-card-desc">Количество задач</div></div>
                        </div>` : ''}
                        ${awConnected ? `<div class="type-card">
                            <input type="radio" name="nm-type" value="integration-activitywatch">
                            <div class="type-card-icon"><i data-lucide="monitor"></i></div>
                            <div class="type-card-info"><div class="type-card-name">ActivityWatch</div><div class="type-card-desc">Экранное время</div></div>
                        </div>` : ''}
                    </div>
                </div>
                <div class="form-section" id="nm-integration-config" style="display: none">
                    <span class="label-text">Метрика Todoist</span>
                    <select id="nm-integration-metric" class="form-input">
                        ${todoistAvailableMetrics.map(m => `<option value="${m.key}" data-config-fields="${(m.config_fields || []).join(',')}">${m.name}</option>`).join('')}
                    </select>
                    <div id="nm-integration-fields"></div>
                </div>
                <div class="form-section" id="nm-aw-config" style="display: none">
                    <span class="label-text">Метрика ActivityWatch</span>
                    <select id="nm-aw-metric" class="form-input">
                        ${awAvailableMetrics.map(m => `<option value="${m.key}" data-config-fields="${(m.config_fields || []).join(',')}">${m.name}${m.description ? ' — ' + m.description : ''}</option>`).join('')}
                    </select>
                    <div id="nm-aw-fields"></div>
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
                <div class="form-section" id="nm-enum-config" style="display: ${currentType === 'enum' ? 'flex' : 'none'}">
                    <span class="label-text">Варианты</span>
                    <div class="enum-options-list" id="nm-enum-options"></div>
                    <button type="button" class="btn-add-slot" id="nm-add-enum-option">+ Добавить вариант</button>
                    <label class="enum-multi-select-label">
                        <input type="checkbox" id="nm-multi-select"> Можно выбрать несколько
                    </label>
                    <span class="label-hint">Минимум 2 варианта</span>
                </div>
                <div class="form-section" id="nm-computed-config" style="display: ${currentType === 'computed' ? 'block' : 'none'}">
                    <span class="label-text">Формула</span>
                    <div class="formula-empty-warning" id="nm-formula-empty-warning" style="display: none">
                        Чтобы использовать формулы, вам нужно сначала добавить минимум одну метрику другого типа.
                    </div>
                    <div id="nm-formula-builder">
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
                            <button type="button" class="formula-op-btn" data-op=">">&gt;</button>
                            <button type="button" class="formula-op-btn" data-op="<">&lt;</button>
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
                            <option value="duration">Длительность</option>
                        </select>
                    </div>
                    <span class="label-hint">Поддерживаются +, −, ×, ÷, >, < и скобки. Время можно комбинировать с длительностью.</span>
                    </div>
                </div>
                <div class="form-section" id="nm-slots-section" style="display: ${currentType === 'computed' || currentType === 'integration' || currentType === 'text' ? 'none' : ''}">
                    <span class="label-text">Сколько раз в день замерять?</span>
                    <div class="slots-choice-grid">
                        <label class="slots-choice-card selected" data-slots="single">
                            <input type="radio" name="nm-slots-mode" value="single" checked>
                            <div class="slots-choice-icon"><i data-lucide="circle-dot"></i></div>
                            <span class="slots-choice-title">Один раз</span>
                        </label>
                        <label class="slots-choice-card" data-slots="multiple">
                            <input type="radio" name="nm-slots-mode" value="multiple">
                            <div class="slots-choice-icon"><i data-lucide="list"></i></div>
                            <span class="slots-choice-title">Несколько раз</span>
                        </label>
                    </div>
                    <div class="slots-config" id="nm-slots-config" style="display:none">
                        <div class="slot-labels-list" id="nm-slot-labels"></div>
                        <button type="button" class="btn-add-slot" id="nm-add-slot">+ Добавить замер</button>
                        <span class="label-hint">Названия замеров можно переименовать</span>
                    </div>
                </div>
                `}
                <div class="form-section" id="nm-condition-section" style="display: ${currentType === 'computed' || currentType === 'integration' ? 'none' : ''}">
                    <span class="label-text">Условие показа <span class="label-optional">(необязательно)</span></span>
                    <span class="label-hint">Метрика будет доступна для заполнения только при выполнении условия</span>
                    <select id="nm-condition-metric" class="form-input">
                        <option value="">Без условия</option>
                    </select>
                    <div id="nm-condition-type-row" style="display:${existingMetric?.condition_metric_id ? 'flex' : 'none'}" class="condition-type-row">
                        <select id="nm-condition-type" class="form-input">
                            <option value="filled" ${existingMetric?.condition_type === 'filled' ? 'selected' : ''}>Заполнена</option>
                            <option value="equals" ${existingMetric?.condition_type === 'equals' ? 'selected' : ''}>Равна</option>
                            <option value="not_equals" ${existingMetric?.condition_type === 'not_equals' ? 'selected' : ''}>Не равна</option>
                        </select>
                        <div id="nm-condition-value-container"></div>
                    </div>
                </div>
            </div>

            <div class="modal-preview-column">
                <div class="preview-sticky">
                    <div class="preview-label-desktop">Превью</div>
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

            <div class="modal-bottom-sticky">
                <div class="modal-preview-inline" id="preview-inline">
                    <div class="preview-label">Превью</div>
                    <div id="metric-preview-inline" class="metric-preview">
                        <div class="metric-card" id="preview-card-inline">
                            <div class="metric-header">
                                <label class="metric-label">${existingMetric?.icon ? '<span class="metric-icon">' + existingMetric.icon + '</span>' : ''}${existingMetric?.name || 'Название метрики'}</label>
                            </div>
                            <div class="metric-input">${previewInputHtml(currentType)}</div>
                        </div>
                    </div>
                </div>
                <div class="modal-actions">
                    <button class="btn-primary" id="nm-save">${buttonText}</button>
                    <button class="btn-small" id="nm-cancel">Отмена</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    if (window.lucide) lucide.createIcons();

    // ─── Populate category select ───
    let modalCategories = [];
    (async () => {
        try {
            modalCategories = await api.getCategories();
            const sel = document.getElementById('nm-category-id');
            if (!sel) return;
            for (const c of modalCategories) {
                const opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = c.name;
                if (existingMetric?.category_id === c.id) opt.selected = true;
                sel.appendChild(opt);
                for (const ch of (c.children || [])) {
                    const chOpt = document.createElement('option');
                    chOpt.value = ch.id;
                    chOpt.textContent = `  └ ${ch.name}`;
                    if (existingMetric?.category_id === ch.id) chOpt.selected = true;
                    sel.appendChild(chOpt);
                }
            }
            // Refresh slot category selects rendered before categories loaded
            const slotListEl = document.getElementById('nm-slot-labels');
            if (slotListEl) {
                slotListEl.querySelectorAll('.slot-category-select').forEach(selEl => {
                    const currentCatId = selEl.dataset.categoryId ? parseInt(selEl.dataset.categoryId) : null;
                    selEl.innerHTML = _buildCategoryOptions(currentCatId);
                });
            }
        } catch(e) { console.warn('Failed to load categories for modal', e); }
    })();

    // ─── Condition section setup ───
    (async () => {
        try {
            const condMetricSel = document.getElementById('nm-condition-metric');
            const condTypeRow = document.getElementById('nm-condition-type-row');
            const condTypeSel = document.getElementById('nm-condition-type');
            const condValueContainer = document.getElementById('nm-condition-value-container');
            if (!condMetricSel) return;

            // Populate condition metric select from available metrics
            const availableForCondition = metrics.filter(m =>
                m.type !== 'computed' && m.type !== 'text' && m.enabled &&
                (!existingMetric || m.id !== existingMetric.id)
            );
            for (const m of availableForCondition) {
                const opt = document.createElement('option');
                opt.value = m.id;
                opt.textContent = (m.icon ? m.icon + ' ' : '') + m.name;
                opt.dataset.metricType = m.type;
                opt.dataset.metricData = JSON.stringify({
                    type: m.type, scale_min: m.scale_min, scale_max: m.scale_max,
                    scale_step: m.scale_step, enum_options: m.enum_options,
                });
                if (existingMetric?.condition_metric_id === m.id) opt.selected = true;
                condMetricSel.appendChild(opt);
            }

            function renderConditionValueInput() {
                if (!condValueContainer) return;
                const condType = condTypeSel.value;
                if (condType === 'filled') {
                    condValueContainer.innerHTML = '';
                    return;
                }
                const selOpt = condMetricSel.selectedOptions[0];
                if (!selOpt || !selOpt.value) { condValueContainer.innerHTML = ''; return; }
                let mData;
                try { mData = JSON.parse(selOpt.dataset.metricData); } catch { return; }

                const existingVal = existingMetric?.condition_value;

                if (mData.type === 'bool') {
                    const isTrue = existingVal === true;
                    const isFalse = existingVal === false;
                    condValueContainer.innerHTML = `<div class="condition-value-buttons">
                        <button type="button" class="cond-val-btn ${isTrue ? 'active' : ''}" data-cond-val="true">Да</button>
                        <button type="button" class="cond-val-btn ${isFalse ? 'active' : ''}" data-cond-val="false">Нет</button>
                    </div>`;
                    condValueContainer.querySelectorAll('.cond-val-btn').forEach(b => {
                        b.addEventListener('click', () => {
                            condValueContainer.querySelectorAll('.cond-val-btn').forEach(x => x.classList.remove('active'));
                            b.classList.add('active');
                        });
                    });
                } else if (mData.type === 'enum' && mData.enum_options) {
                    const selIds = Array.isArray(existingVal) ? existingVal : [];
                    condValueContainer.innerHTML = `<div class="condition-value-buttons enum">${
                        mData.enum_options.map(o =>
                            `<button type="button" class="cond-val-btn ${selIds.includes(o.id) ? 'active' : ''}" data-cond-val="${o.id}">${o.label}</button>`
                        ).join('')
                    }</div>`;
                    condValueContainer.querySelectorAll('.cond-val-btn').forEach(b => {
                        b.addEventListener('click', () => b.classList.toggle('active'));
                    });
                } else if (mData.type === 'scale') {
                    const numVal = typeof existingVal === 'number' ? existingVal : '';
                    condValueContainer.innerHTML = `<input type="number" id="nm-condition-value-num" class="form-input-small" value="${numVal}" placeholder="Значение" min="${mData.scale_min || 0}" max="${mData.scale_max || 10}" step="${mData.scale_step || 1}">`;
                } else {
                    const numVal = typeof existingVal === 'number' ? existingVal : '';
                    condValueContainer.innerHTML = `<input type="number" id="nm-condition-value-num" class="form-input-small" value="${numVal}" placeholder="Значение">`;
                }
            }

            condMetricSel.addEventListener('change', () => {
                const hasSelection = !!condMetricSel.value;
                condTypeRow.style.display = hasSelection ? 'flex' : 'none';
                if (hasSelection) renderConditionValueInput();
                else condValueContainer.innerHTML = '';
            });
            condTypeSel.addEventListener('change', renderConditionValueInput);

            // Init if editing with existing condition
            if (existingMetric?.condition_metric_id) {
                condTypeRow.style.display = 'flex';
                renderConditionValueInput();
            }
        } catch(e) { console.warn('Failed to setup condition section', e); }
    })();

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
        // Click on card selects the radio (since we use div instead of label)
        overlay.querySelectorAll('.type-card').forEach(card => {
            card.addEventListener('click', () => {
                const radio = card.querySelector('input[type="radio"]');
                if (radio) { radio.checked = true; radio.dispatchEvent(new Event('change')); }
            });
        });
        overlay.querySelectorAll('input[name="nm-type"]').forEach(radio => {
            radio.addEventListener('change', () => {
                // Update card selection visual
                overlay.querySelectorAll('.type-card').forEach(c => c.classList.remove('selected'));
                const card = radio.closest('.type-card');
                if (card) card.classList.add('selected');

                const selectedType = getCurrentType();
                const selectedProvider = getCurrentProvider();
                const scaleConfig = document.getElementById('nm-scale-config');
                const enumConfig = document.getElementById('nm-enum-config');
                const computedConfig = document.getElementById('nm-computed-config');
                const integrationConfig = document.getElementById('nm-integration-config');
                const awConfig = document.getElementById('nm-aw-config');
                const slotsSection = document.getElementById('nm-slots-section');
                const emojiWrapper = overlay.querySelector('.emoji-picker-wrapper');
                if (scaleConfig) scaleConfig.style.display = selectedType === 'scale' ? 'flex' : 'none';
                if (enumConfig) enumConfig.style.display = selectedType === 'enum' ? 'flex' : 'none';
                if (computedConfig) computedConfig.style.display = selectedType === 'computed' ? 'block' : 'none';
                if (integrationConfig) integrationConfig.style.display = (selectedType === 'integration' && selectedProvider === 'todoist') ? 'block' : 'none';
                if (awConfig) awConfig.style.display = (selectedType === 'integration' && selectedProvider === 'activitywatch') ? 'block' : 'none';
                if (slotsSection) slotsSection.style.display = (selectedType === 'computed' || selectedType === 'integration' || selectedType === 'text') ? 'none' : '';
                if (emojiWrapper) emojiWrapper.style.display = selectedType === 'integration' ? 'none' : '';
                const condSection = document.getElementById('nm-condition-section');
                if (condSection) condSection.style.display = (selectedType === 'computed' || selectedType === 'integration') ? 'none' : '';
                if (selectedType === 'computed') {
                    const availableMetrics = metrics.filter(m => m.type !== 'computed' && m.enabled);
                    const warning = document.getElementById('nm-formula-empty-warning');
                    const builder = document.getElementById('nm-formula-builder');
                    if (availableMetrics.length === 0) {
                        if (warning) warning.style.display = 'block';
                        if (builder) builder.style.display = 'none';
                    } else {
                        if (warning) warning.style.display = 'none';
                        if (builder) builder.style.display = '';
                        formulaTokens = [];
                        formulaBuilderInitialized = false;
                        renderFormulaTokens();
                        populateFormulaMetricSelect();
                        setupFormulaBuilderHandlers(overlay);
                    }
                }
                updatePreview();
            });
        });

        // Integration metric select — show config fields
        const integrationMetricSelect = overlay.querySelector('#nm-integration-metric');
        if (integrationMetricSelect) {
            const renderIntegrationFields = () => {
                const fieldsContainer = document.getElementById('nm-integration-fields');
                if (!fieldsContainer) return;
                const selected = integrationMetricSelect.selectedOptions[0];
                const configFields = (selected?.dataset.configFields || '').split(',').filter(Boolean);
                let html = '';
                if (configFields.includes('filter_name')) {
                    html = `<label class="form-label">
                        <span class="label-text">Название фильтра в Todoist</span>
                        <input id="nm-filter-name" placeholder="Например: Работа" class="form-input">
                    </label>
                    <span class="label-hint">Имя фильтра из вашего Todoist (регистр не важен)</span>`;
                } else if (configFields.includes('filter_query')) {
                    html = `<label class="form-label">
                        <span class="label-text">Поисковый запрос (filter query)</span>
                        <input id="nm-filter-query" placeholder="Например: today & @work" class="form-input">
                    </label>
                    <span class="label-hint">Любой <a href="https://todoist.com/help/articles/introduction-to-filters-V98wIH" target="_blank">запрос Todoist</a></span>`;
                }
                fieldsContainer.innerHTML = html;
            };
            integrationMetricSelect.addEventListener('change', renderIntegrationFields);
            renderIntegrationFields();
        }

        // AW metric select — show config fields
        const awMetricSelect = overlay.querySelector('#nm-aw-metric');
        if (awMetricSelect) {
            const renderAwFields = () => {
                const fieldsContainer = document.getElementById('nm-aw-fields');
                if (!fieldsContainer) return;
                const selected = awMetricSelect.selectedOptions[0];
                const configFields = (selected?.dataset.configFields || '').split(',').filter(Boolean);
                let html = '';
                if (configFields.includes('activitywatch_category_id')) {
                    html = `<label class="form-label">
                        <span class="label-text">Категория AW</span>
                        <select id="nm-aw-category-id" class="form-input">
                            ${awCategories.map(c => `<option value="${c.id}">${c.name}</option>`).join('')}
                        </select>
                    </label>`;
                } else if (configFields.includes('app_name')) {
                    html = `<label class="form-label">
                        <span class="label-text">Приложение</span>
                        <select id="nm-aw-app-name" class="form-input">
                            ${awApps.map(a => `<option value="${a.app_name}">${a.app_name}</option>`).join('')}
                        </select>
                    </label>`;
                }
                fieldsContainer.innerHTML = html;
            };
            awMetricSelect.addEventListener('change', renderAwFields);
            renderAwFields();
        }

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

    // ─── Slot management (declared early — updatePreview references slotList) ───
    const slotList = document.getElementById('nm-slot-labels');
    const addSlotBtn = document.getElementById('nm-add-slot');
    const slotsConfig = document.getElementById('nm-slots-config');

    // ─── Enum option management ───
    const enumOptionsList = document.getElementById('nm-enum-options');
    const addEnumOptionBtn = document.getElementById('nm-add-enum-option');

    function addEnumOptionField(label = '', optionId = null) {
        const row = document.createElement('div');
        row.className = 'enum-option-row';
        row.draggable = true;
        if (optionId) row.dataset.optionId = optionId;
        row.innerHTML = `<span class="drag-handle">⠿</span>
            <input type="text" class="form-input enum-option-input" placeholder="Название варианта" value="${label}">
            <button type="button" class="btn-remove-slot">&times;</button>`;
        enumOptionsList.appendChild(row);
        row.querySelector('.btn-remove-slot').onclick = () => { row.remove(); updatePreview(); };
        row.querySelector('.enum-option-input').addEventListener('input', updatePreview);
        // Drag & drop
        row.addEventListener('dragstart', (e) => {
            e.dataTransfer.effectAllowed = 'move';
            row.classList.add('dragging');
        });
        row.addEventListener('dragend', () => {
            row.classList.remove('dragging');
            updatePreview();
        });
        row.addEventListener('dragover', (e) => {
            e.preventDefault();
            const dragging = enumOptionsList.querySelector('.dragging');
            if (dragging && dragging !== row) {
                const rect = row.getBoundingClientRect();
                const mid = rect.top + rect.height / 2;
                if (e.clientY < mid) {
                    enumOptionsList.insertBefore(dragging, row);
                } else {
                    enumOptionsList.insertBefore(dragging, row.nextSibling);
                }
            }
        });
    }

    if (addEnumOptionBtn) {
        addEnumOptionBtn.onclick = () => { addEnumOptionField(''); updatePreview(); };
    }

    // Pre-fill enum options in edit mode
    if (isEdit && currentType === 'enum' && existingMetric?.enum_options) {
        for (const opt of existingMetric.enum_options) {
            addEnumOptionField(opt.label, opt.id);
        }
        // Multi-select checkbox listener for preview
        const multiSelectCb = document.getElementById('nm-multi-select');
        if (multiSelectCb) multiSelectCb.addEventListener('change', updatePreview);
        updatePreview();
    }
    // Create mode: auto-add 2 empty options when enum is selected
    if (!isEdit) {
        const multiSelectCb = document.getElementById('nm-multi-select');
        if (multiSelectCb) multiSelectCb.addEventListener('change', updatePreview);
        // Watch for type change to auto-populate
        overlay.querySelectorAll('input[name="nm-type"]').forEach(radio => {
            radio.addEventListener('change', () => {
                if (radio.value === 'enum' && enumOptionsList && enumOptionsList.children.length === 0) {
                    addEnumOptionField('');
                    addEnumOptionField('');
                }
            });
        });
    }

    function setupPreviewInteractions() {
        document.querySelectorAll('#preview-card .bool-btn, #preview-card-inline .bool-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const buttons = btn.parentElement.querySelectorAll('.bool-btn');
                buttons.forEach(b => b.classList.remove('active', 'yes', 'no'));
                const isYes = btn.dataset.value === 'true';
                btn.classList.add('active', isYes ? 'yes' : 'no');
            });
        });
        document.querySelectorAll('#preview-card .scale-btn, #preview-card-inline .scale-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const buttons = btn.parentElement.querySelectorAll('.scale-btn');
                buttons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        });
        document.querySelectorAll('#preview-card .enum-btn, #preview-card-inline .enum-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const container = btn.parentElement;
                const isMulti = container.classList.contains('multi');
                if (isMulti) {
                    btn.classList.toggle('active');
                } else {
                    container.querySelectorAll('.enum-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                }
            });
        });
    }

    function getCurrentType() {
        if (isEdit) return currentType;
        const raw = overlay.querySelector('input[name="nm-type"]:checked')?.value || 'bool';
        return raw.startsWith('integration') ? 'integration' : raw;
    }

    function getCurrentProvider() {
        if (isEdit) return existingMetric?.provider || '';
        const raw = overlay.querySelector('input[name="nm-type"]:checked')?.value || '';
        if (raw === 'integration-todoist') return 'todoist';
        if (raw === 'integration-activitywatch') return 'activitywatch';
        return '';
    }

    function updatePreview() {
        const type = getCurrentType();
        const rawName = document.getElementById('nm-name').value || 'Название метрики';
        const provider = getCurrentProvider();
        let icon;
        if (type === 'integration') {
            icon = provider === 'activitywatch' ? AW_ICON : TODOIST_ICON;
        } else {
            icon = document.getElementById('nm-icon').value;
        }
        const name = (icon ? '<span class="metric-icon">' + icon + '</span>' : '') + rawName;
        const slotInputs = slotList ? slotList.querySelectorAll('.slot-label-input') : [];
        const labels = Array.from(slotInputs).map(i => i.value.trim()).filter(v => v !== '');

        let cardHtml;
        if (labels.length >= 2) {
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
            cardHtml = `<div class="metric-header">
                    <label class="metric-label">${name}</label>
                </div>${slotsHtml}`;
        } else {
            cardHtml = `<div class="metric-header">
                    <label class="metric-label">${name}</label>
                </div>
                <div class="metric-input" id="preview-input">${previewInputHtml(type)}</div>`;
        }

        // Update both preview containers (desktop column + mobile inline)
        const previewCard = document.getElementById('preview-card');
        if (previewCard) previewCard.innerHTML = cardHtml;
        const previewCardInline = document.getElementById('preview-card-inline');
        if (previewCardInline) previewCardInline.innerHTML = cardHtml;

        setupPreviewInteractions();
    }

    setupPreviewInteractions();

    // ─── Slots choice cards ───
    overlay.querySelectorAll('input[name="nm-slots-mode"]').forEach(radio => {
        radio.addEventListener('change', () => {
            overlay.querySelectorAll('.slots-choice-card').forEach(c => c.classList.remove('selected'));
            const card = radio.closest('.slots-choice-card');
            if (card) card.classList.add('selected');

            if (radio.value === 'multiple') {
                if (slotsConfig) slotsConfig.style.display = 'flex';
                // Auto-add 3 default slots if empty
                if (slotList && slotList.querySelectorAll('.slot-label-row').length === 0) {
                    ['Утро', 'День', 'Вечер'].forEach(l => addSlotField(l));
                }
            } else {
                if (slotsConfig) slotsConfig.style.display = 'none';
                // Clear slots
                if (slotList) slotList.innerHTML = '';
            }
            updatePreview();
        });
    });

    function _buildCategoryOptions(selectedCatId) {
        let html = '<option value="">Без категории</option>';
        for (const c of modalCategories) {
            html += `<option value="${c.id}" ${selectedCatId === c.id ? 'selected' : ''}>${c.name}</option>`;
            for (const ch of (c.children || [])) {
                html += `<option value="${ch.id}" ${selectedCatId === ch.id ? 'selected' : ''}>  └ ${ch.name}</option>`;
            }
        }
        return html;
    }

    function addSlotField(label = '', categoryId = null) {
        const row = document.createElement('div');
        row.className = 'slot-label-row';
        row.draggable = true;
        row.innerHTML = `<span class="drag-handle">⠿</span>
            <input type="text" class="form-input slot-label-input" placeholder="Например: Утро" value="${label}">
            <select class="form-select slot-category-select" data-category-id="${categoryId || ''}">${_buildCategoryOptions(categoryId)}</select>
            <button type="button" class="btn-remove-slot">&times;</button>`;
        slotList.appendChild(row);
        row.querySelector('.btn-remove-slot').onclick = () => { row.remove(); updatePreview(); };
        row.querySelector('.slot-label-input').addEventListener('input', updatePreview);
        // Drag & drop (same pattern as addEnumOptionField)
        row.addEventListener('dragstart', (e) => {
            e.dataTransfer.effectAllowed = 'move';
            row.classList.add('dragging');
        });
        row.addEventListener('dragend', () => {
            row.classList.remove('dragging');
            updatePreview();
        });
        row.addEventListener('dragover', (e) => {
            e.preventDefault();
            const dragging = slotList.querySelector('.dragging');
            if (dragging && dragging !== row) {
                const rect = row.getBoundingClientRect();
                const mid = rect.top + rect.height / 2;
                if (e.clientY < mid) {
                    slotList.insertBefore(dragging, row);
                } else {
                    slotList.insertBefore(dragging, row.nextSibling);
                }
            }
        });
    }

    if (addSlotBtn) {
        addSlotBtn.onclick = () => { addSlotField(''); updatePreview(); };
        // Pre-fill slots in edit mode
        if (isEdit && existingMetric?.slots) {
            for (const s of existingMetric.slots) {
                addSlotField(s.label, s.category_id);
            }
            updatePreview();
        }
    }

    function getSlotLabels() {
        const inputs = slotList ? slotList.querySelectorAll('.slot-label-input') : [];
        return Array.from(inputs).map(i => i.value.trim()).filter(v => v !== '');
    }

    function getSlotConfigs() {
        if (!slotList) return [];
        const rows = slotList.querySelectorAll('.slot-label-row');
        const configs = [];
        for (const row of rows) {
            const label = row.querySelector('.slot-label-input').value.trim();
            if (!label) continue;
            const catSelect = row.querySelector('.slot-category-select');
            const catId = catSelect && catSelect.value ? parseInt(catSelect.value) : null;
            configs.push({ label, category_id: catId });
        }
        return configs;
    }

    document.getElementById('nm-cancel').onclick = () => overlay.remove();
    function _collectConditionData() {
        const condMetricSel = document.getElementById('nm-condition-metric');
        const condTypeSel = document.getElementById('nm-condition-type');
        if (!condMetricSel || !condMetricSel.value) return { remove: true };
        const condType = condTypeSel ? condTypeSel.value : 'filled';
        let condValue = null;
        if (condType !== 'filled') {
            const condValueContainer = document.getElementById('nm-condition-value-container');
            if (condValueContainer) {
                const activeButtons = condValueContainer.querySelectorAll('.cond-val-btn.active');
                if (activeButtons.length > 0) {
                    const selOpt = condMetricSel.selectedOptions[0];
                    let mData;
                    try { mData = JSON.parse(selOpt.dataset.metricData); } catch { mData = {}; }
                    if (mData.type === 'bool') {
                        condValue = activeButtons[0].dataset.condVal === 'true';
                    } else if (mData.type === 'enum') {
                        condValue = Array.from(activeButtons).map(b => parseInt(b.dataset.condVal));
                    }
                } else {
                    const numInput = condValueContainer.querySelector('#nm-condition-value-num');
                    if (numInput && numInput.value !== '') condValue = parseInt(numInput.value);
                }
            }
        }
        return { metric_id: parseInt(condMetricSel.value), type: condType, value: condValue };
    }

    document.getElementById('nm-save').onclick = async () => {
        const name = document.getElementById('nm-name').value;
        const categorySelect = document.getElementById('nm-category-id');
        const categoryIdVal = categorySelect ? categorySelect.value : '';

        if (!name) {
            alert('Заполните название');
            return;
        }

        try {
            const slotLabels = getSlotLabels();
            const slotConfigs = getSlotConfigs();

            if (isEdit) {
                const icon = existingMetric.type === 'integration' ? undefined : document.getElementById('nm-icon').value;
                const privateCb = document.getElementById('nm-private');
                const hasSlotConfigs = slotConfigs.length >= 2;
                const updateData = { name, category_id: hasSlotConfigs ? 0 : (categoryIdVal ? parseInt(categoryIdVal) : 0), private: privateCb ? privateCb.checked : false };
                if (icon !== undefined) updateData.icon = icon;
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
                if (existingMetric.type === 'enum') {
                    const multiSelectCb = document.getElementById('nm-multi-select');
                    updateData.multi_select = multiSelectCb ? multiSelectCb.checked : false;
                    // Collect enum options with their IDs (existing) or without (new)
                    const optRows = enumOptionsList ? enumOptionsList.querySelectorAll('.enum-option-row') : [];
                    const opts = [];
                    Array.from(optRows).forEach(row => {
                        const label = row.querySelector('.enum-option-input').value.trim();
                        if (!label) return;
                        const entry = { label };
                        if (row.dataset.optionId) entry.id = parseInt(row.dataset.optionId);
                        opts.push(entry);
                    });
                    if (opts.length < 2) {
                        alert('Нужно минимум 2 варианта');
                        return;
                    }
                    updateData.enum_options = opts;
                }
                // Send slot_configs if user configured slots (not for computed/integration)
                if (existingMetric.type !== 'computed' && existingMetric.type !== 'integration') {
                    if (slotConfigs.length >= 2) {
                        updateData.slot_configs = slotConfigs;
                    } else if (slotLabels.length === 0 && (!existingMetric.slots || existingMetric.slots.length === 0)) {
                        // No slots before, no slots now — don't send
                    } else if (slotLabels.length < 2 && existingMetric.slots && existingMetric.slots.length > 0) {
                        alert('Нельзя уменьшить количество замеров меньше 2. Удалите все поля, чтобы не менять настройку.');
                        return;
                    }
                }
                // Condition data
                const condData = _collectConditionData();
                if (condData.remove) {
                    updateData.remove_condition = true;
                } else {
                    updateData.condition_metric_id = condData.metric_id;
                    updateData.condition_type = condData.type;
                    updateData.condition_value = condData.value;
                }
                await api.updateMetric(existingMetric.id, updateData);
            } else {
                const selectedType = getCurrentType();

                const icon = document.getElementById('nm-icon').value;
                const privateCb = document.getElementById('nm-private');
                const createData = { name, icon, type: selectedType, private: privateCb ? privateCb.checked : false };
                if (categoryIdVal) createData.category_id = parseInt(categoryIdVal);

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

                if (selectedType === 'enum') {
                    const optRows = enumOptionsList ? enumOptionsList.querySelectorAll('.enum-option-row') : [];
                    const labels = [];
                    optRows.forEach(row => {
                        const label = row.querySelector('.enum-option-input').value.trim();
                        if (label) labels.push(label);
                    });
                    if (labels.length < 2) {
                        alert('Нужно минимум 2 варианта');
                        return;
                    }
                    const uniqueLabels = new Set(labels);
                    if (uniqueLabels.size !== labels.length) {
                        alert('Названия вариантов должны быть уникальными');
                        return;
                    }
                    createData.enum_options = labels;
                    const multiSelectCb = document.getElementById('nm-multi-select');
                    createData.multi_select = multiSelectCb ? multiSelectCb.checked : false;
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

                if (selectedType === 'integration') {
                    const intProvider = getCurrentProvider();

                    if (intProvider === 'todoist') {
                        const metricSelect = document.getElementById('nm-integration-metric');
                        if (!metricSelect || !metricSelect.value) {
                            alert('Выберите метрику Todoist');
                            return;
                        }
                        createData.provider = 'todoist';
                        createData.metric_key = metricSelect.value;
                        if (metricSelect.value === 'filter_tasks_count') {
                            const filterNameEl = document.getElementById('nm-filter-name');
                            if (!filterNameEl || !filterNameEl.value.trim()) {
                                alert('Укажите название фильтра');
                                return;
                            }
                            createData.filter_name = filterNameEl.value.trim();
                        }
                        if (metricSelect.value === 'query_tasks_count') {
                            const filterQueryEl = document.getElementById('nm-filter-query');
                            if (!filterQueryEl || !filterQueryEl.value.trim()) {
                                alert('Укажите поисковый запрос');
                                return;
                            }
                            createData.filter_query = filterQueryEl.value.trim();
                        }
                    } else if (intProvider === 'activitywatch') {
                        const awSelect = document.getElementById('nm-aw-metric');
                        if (!awSelect || !awSelect.value) {
                            alert('Выберите метрику ActivityWatch');
                            return;
                        }
                        createData.provider = 'activitywatch';
                        createData.metric_key = awSelect.value;
                        if (awSelect.value === 'category_time') {
                            const catEl = document.getElementById('nm-aw-category-id');
                            if (!catEl || !catEl.value) {
                                alert('Выберите категорию');
                                return;
                            }
                            createData.activitywatch_category_id = parseInt(catEl.value);
                        }
                        if (awSelect.value === 'app_time') {
                            const appEl = document.getElementById('nm-aw-app-name');
                            if (!appEl || !appEl.value) {
                                alert('Выберите приложение');
                                return;
                            }
                            createData.app_name = appEl.value;
                        }
                    }
                }

                if (!['computed', 'integration'].includes(selectedType) && slotConfigs.length >= 2) {
                    createData.slot_configs = slotConfigs;
                    // Defensive rule: category on slots, not metric
                    delete createData.category_id;
                }

                // Condition data
                const condData = _collectConditionData();
                if (!condData.remove) {
                    createData.condition_metric_id = condData.metric_id;
                    createData.condition_type = condData.type;
                    createData.condition_value = condData.value;
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

async function showAddMetricModal() {
    await showMetricModal('create');
}

async function showEditMetricModal(metric) {
    await showMetricModal('edit', metric);
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

// ─── Date Picker ───
const MONTHS_RU = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const DAY_NAMES_SHORT = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];

function createDatePicker(containerId, initialValue, onChange) {
    const container = document.getElementById(containerId);
    if (!container) return null;

    let currentValue = initialValue;
    let viewYear, viewMonth; // 1-based month
    {
        const parts = initialValue.split('-');
        viewYear = parseInt(parts[0]);
        viewMonth = parseInt(parts[1]);
    }

    function fmtBtn(dateStr) {
        const [, m, d] = dateStr.split('-');
        return `${d}.${m}`;
    }

    // Build DOM
    container.classList.add('date-picker');
    const btn = document.createElement('button');
    btn.className = 'date-picker-btn';
    btn.type = 'button';
    btn.textContent = fmtBtn(currentValue);

    const dropdown = document.createElement('div');
    dropdown.className = 'date-picker-dropdown';

    container.appendChild(btn);
    container.appendChild(dropdown);

    function renderDropdown() {
        const daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
        const firstDay = (new Date(viewYear, viewMonth - 1, 1).getDay() + 6) % 7;
        const today = todayStr();

        let html = `<div class="date-picker-nav">
            <button type="button" class="date-picker-nav-btn" data-dp-prev><i data-lucide="chevron-left"></i></button>
            <span class="date-picker-nav-title">${MONTHS_RU[viewMonth - 1]} ${viewYear}</span>
            <button type="button" class="date-picker-nav-btn" data-dp-next><i data-lucide="chevron-right"></i></button>
        </div><div class="date-picker-grid">`;

        html += DAY_NAMES_SHORT.map(d => `<div class="cal-header">${d}</div>`).join('');
        for (let i = 0; i < firstDay; i++) html += '<div class="cal-empty"></div>';

        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = `${viewYear}-${String(viewMonth).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
            const cls = [
                'cal-day',
                dateStr === today ? 'today' : '',
                dateStr === currentValue ? 'selected' : ''
            ].filter(Boolean).join(' ');
            html += `<div class="${cls}" data-dp-date="${dateStr}">${d}</div>`;
        }
        html += '</div>';
        dropdown.innerHTML = html;
        if (window.lucide) lucide.createIcons({ nodes: [dropdown] });

        dropdown.querySelector('[data-dp-prev]').addEventListener('click', (e) => {
            e.stopPropagation();
            viewMonth--;
            if (viewMonth < 1) { viewMonth = 12; viewYear--; }
            renderDropdown();
        });
        dropdown.querySelector('[data-dp-next]').addEventListener('click', (e) => {
            e.stopPropagation();
            viewMonth++;
            if (viewMonth > 12) { viewMonth = 1; viewYear++; }
            renderDropdown();
        });
        dropdown.querySelectorAll('[data-dp-date]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                currentValue = el.dataset.dpDate;
                const [, m] = currentValue.split('-');
                viewYear = parseInt(currentValue.split('-')[0]);
                viewMonth = parseInt(m);
                btn.textContent = fmtBtn(currentValue);
                close();
                if (onChange) onChange(currentValue);
            });
        });
    }

    function alignDropdown() {
        dropdown.classList.remove('align-left', 'align-right');
        requestAnimationFrame(() => {
            const rect = dropdown.getBoundingClientRect();
            if (rect.left < 4) {
                dropdown.classList.add('align-left');
            } else if (rect.right > window.innerWidth - 4) {
                dropdown.classList.add('align-right');
            }
        });
    }

    function open() {
        // Close all other open date pickers
        document.querySelectorAll('.date-picker-dropdown.open').forEach(d => d.classList.remove('open'));
        renderDropdown();
        dropdown.classList.add('open');
        alignDropdown();
    }

    function close() {
        dropdown.classList.remove('open');
    }

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (dropdown.classList.contains('open')) {
            close();
        } else {
            open();
        }
    });

    dropdown.addEventListener('click', (e) => e.stopPropagation());

    const outsideHandler = () => close();
    document.addEventListener('click', outsideHandler);

    return {
        getValue() { return currentValue; },
        setValue(dateStr) {
            currentValue = dateStr;
            const parts = dateStr.split('-');
            viewYear = parseInt(parts[0]);
            viewMonth = parseInt(parts[1]);
            btn.textContent = fmtBtn(currentValue);
        },
        destroy() {
            document.removeEventListener('click', outsideHandler);
            container.innerHTML = '';
            container.classList.remove('date-picker');
        }
    };
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
