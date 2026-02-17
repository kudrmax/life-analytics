// ─── State ───
let currentDate = todayStr();
let metrics = [];
let currentPage = 'today';

function todayStr() {
    return new Date().toISOString().slice(0, 10);
}

// ─── Init ───
document.addEventListener('DOMContentLoaded', async () => {
    setupNav();
    await loadMetrics();
    navigateTo('today');
});

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
    document.querySelectorAll('[data-page]').forEach(b => b.classList.toggle('active', b.dataset.page === page));
    const main = document.getElementById('main');

    switch (page) {
        case 'today': renderToday(main); break;
        case 'history': renderHistory(main); break;
        case 'dashboard': renderDashboard(main); break;
        case 'settings': renderSettings(main); break;
    }
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
        if (m.source !== 'manual') continue;
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
    const isFilled = m.frequency === 'daily' && entry;
    const filledClass = isFilled ? 'filled' : '';

    let input = '';

    if (m.frequency === 'multiple') {
        // Show quick buttons + list of entries
        input = renderMultipleInput(m);
    } else if (m.type === 'scale') {
        input = renderScale(m, val);
    } else if (m.type === 'boolean') {
        input = renderBoolean(m, val);
    } else if (m.type === 'number') {
        input = renderNumber(m, val);
    } else if (m.type === 'time') {
        input = renderTime(m, val);
    } else if (m.type === 'compound') {
        input = renderCompound(m, val);
    }

    return `<div class="metric-card ${filledClass}" data-metric-id="${m.metric_id}" data-entry-id="${entryId || ''}">
        <label class="metric-label">${m.name}</label>
        <div class="metric-input">${input}</div>
    </div>`;
}

function renderScale(m, val) {
    const cfg = m.config;
    const min = cfg.min || 1;
    const max = cfg.max || 5;
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
    const current = val ? val.value : 0;
    const cfg = m.config;
    const step = cfg.step || 1;
    const min = cfg.min ?? 0;
    const max = cfg.max ?? 999;
    const label = cfg.label || '';
    return `<div class="number-input">
        <button class="number-btn" data-action="decrement" data-step="${step}" data-min="${min}">−</button>
        <input type="number" value="${current}" step="${step}" min="${min}" max="${max}" data-field="value">
        <span class="unit">${label}</span>
        <button class="number-btn" data-action="increment" data-step="${step}" data-max="${max}">+</button>
    </div>`;
}

function renderTime(m, val) {
    const current = val ? val.value : '';
    return `<input type="time" value="${current}" data-field="value" class="time-input">`;
}

function renderCompound(m, val) {
    const fields = m.config.fields || [];
    let html = '<div class="compound-fields">';
    for (const f of fields) {
        const fval = val ? val[f.name] : null;
        const conditionMet = !f.condition || evaluateCondition(f.condition, val);
        const hidden = conditionMet ? '' : 'hidden';

        html += `<div class="compound-field ${hidden}" data-condition="${f.condition || ''}" data-cfield="${f.name}">`;
        if (f.type === 'boolean') {
            html += `<div class="bool-buttons">
                <label class="field-label">${f.label}</label>
                <button class="bool-btn ${fval === true ? 'active yes' : ''}" data-value="true" data-compound-field="${f.name}">${'Да'}</button>
                <button class="bool-btn ${fval === false ? 'active no' : ''}" data-value="false" data-compound-field="${f.name}">${'Нет'}</button>
            </div>`;
        } else if (f.type === 'number') {
            html += `<label class="field-label">${f.label}</label>
                <input type="number" value="${fval ?? ''}" data-compound-field="${f.name}">`;
        } else if (f.type === 'enum') {
            html += `<label class="field-label">${f.label}</label><div class="enum-buttons">`;
            for (const opt of (f.options || [])) {
                html += `<button class="enum-btn ${fval === opt ? 'active' : ''}" data-value="${opt}" data-compound-field="${f.name}">${opt}</button>`;
            }
            html += '</div>';
        }
        html += '</div>';
    }
    html += '</div>';
    return html;
}

function renderMultipleInput(m) {
    const cfg = m.config;
    const min = cfg.min || 1;
    const max = cfg.max || 5;

    let html = '<div class="multiple-entry">';
    html += '<div class="scale-buttons quick-add">';
    for (let i = min; i <= max; i++) {
        html += `<button class="scale-btn" data-quick-value="${i}">${i}</button>`;
    }
    html += '</div>';

    // List existing entries
    if (m.entries.length > 0) {
        html += '<div class="entry-list">';
        for (const e of m.entries) {
            const time = e.timestamp.slice(11, 16);
            html += `<div class="entry-chip" data-entry-id="${e.id}">
                <span>${time}: ${e.value.value}</span>
                <button class="delete-entry" data-delete-entry="${e.id}">&times;</button>
            </div>`;
        }
        html += '</div>';
        if (m.summary) {
            html += `<div class="summary-line">Среднее: ${m.summary.avg} | Мин: ${m.summary.min} | Макс: ${m.summary.max}</div>`;
        }
    }
    html += '</div>';
    return html;
}

function evaluateCondition(condition, val) {
    if (!condition || !val) return false;
    // Simple "field == true/false" parser
    const match = condition.match(/^(\w+)\s*==\s*(true|false)$/);
    if (match) {
        return val[match[1]] === (match[2] === 'true');
    }
    return true;
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

            await saveDaily(metricId, entryId, { value: newValue });
            await renderTodayForm();
        } catch (error) {
            console.error('Error in number button handler:', error);
            alert('Ошибка: ' + error.message);
        }
        return;
    }

    // Quick add for multiple-frequency
    if (btn.dataset.quickValue) {
        try {
            console.log('Quick add detected:', { metricId, value: btn.dataset.quickValue });
            const result = await api.createEntry({
                metric_id: metricId,
                date: currentDate,
                timestamp: new Date().toISOString(),
                value: { value: parseInt(btn.dataset.quickValue) },
            });
            console.log('Quick add result:', result);
            await renderTodayForm();
        } catch (error) {
            console.error('Error in quick add:', error);
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

            if (btn.dataset.compoundField) {
                // Compound field
                const currentVal = await getCurrentValue(metricId, entryId);
                currentVal[btn.dataset.compoundField] = boolVal;
                // Reset conditional fields if needed
                await saveDaily(metricId, entryId, currentVal);
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

    // Enum buttons
    if (btn.classList.contains('enum-btn')) {
        try {
            console.log('Enum button clicked');
            const currentVal = await getCurrentValue(metricId, entryId);
            currentVal[btn.dataset.compoundField] = btn.dataset.value;
            await saveDaily(metricId, entryId, currentVal);
            await renderTodayForm();
        } catch (error) {
            console.error('Error in enum handler:', error);
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

    if (input.dataset.compoundField) {
        const currentVal = await getCurrentValue(metricId, entryId);
        currentVal[input.dataset.compoundField] = input.type === 'number' ? parseFloat(input.value) : input.value;
        await saveDaily(metricId, entryId, currentVal);
    } else if (input.dataset.field === 'value') {
        let v = input.value;
        if (input.type === 'number') v = parseFloat(v);
        await saveDaily(metricId, entryId, { value: v });
    }
}

async function getCurrentValue(metricId, entryId) {
    if (entryId) {
        const entries = await api.getEntries(currentDate, metricId);
        if (entries.length > 0) return entries[0].value;
    }
    return {};
}

async function saveDaily(metricId, entryId, value) {
    console.log('saveDaily called:', { metricId, entryId, value, currentDate });
    try {
        if (entryId) {
            const result = await api.updateEntry(parseInt(entryId), { value });
            console.log('Update result:', result);
        } else {
            const result = await api.createEntry({
                metric_id: metricId,
                date: currentDate,
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
        if (m.frequency === 'multiple' && m.summary) {
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
    const scaleMetrics = metrics.filter(m => ['scale', 'number', 'boolean'].includes(m.type));
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
    let html = '<h2>Настройки метрик</h2>';
    html += '<button class="btn-primary" id="add-metric">+ Новая метрика</button>';

    const categories = {};
    for (const m of allMetrics) {
        categories[m.category] = categories[m.category] || [];
        categories[m.category].push(m);
    }

    for (const [cat, items] of Object.entries(categories)) {
        html += `<div class="category"><h3>${cat}</h3>`;
        for (const m of items) {
            html += `<div class="setting-row">
                <span class="setting-name ${m.enabled ? '' : 'disabled'}">${m.name}</span>
                <span class="setting-type">${m.type} | ${m.frequency} | ${m.source}</span>
                <div class="setting-actions">
                    <button class="btn-icon toggle-btn" data-metric="${m.id}" data-enabled="${m.enabled}">${m.enabled ? '&#x2714;' : '&#x2716;'}</button>
                    <button class="btn-icon delete-btn" data-metric="${m.id}">&times;</button>
                </div>
            </div>`;
        }
        html += '</div>';
    }
    container.innerHTML = html;

    document.getElementById('add-metric').addEventListener('click', showAddMetricModal);

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

function showAddMetricModal() {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal">
            <h3>Новая метрика</h3>
            <label>ID <input id="nm-id" placeholder="my_metric"></label>
            <label>Название <input id="nm-name" placeholder="Моя метрика"></label>
            <label>Категория <input id="nm-cat" placeholder="Категория"></label>
            <label>Тип <select id="nm-type">
                <option value="boolean">boolean</option>
                <option value="number">number</option>
                <option value="scale">scale</option>
                <option value="time">time</option>
            </select></label>
            <label>Частота <select id="nm-freq">
                <option value="daily">daily</option>
                <option value="multiple">multiple</option>
            </select></label>
            <div class="modal-actions">
                <button class="btn-primary" id="nm-save">Создать</button>
                <button class="btn-small" id="nm-cancel">Отмена</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    document.getElementById('nm-cancel').onclick = () => overlay.remove();
    document.getElementById('nm-save').onclick = async () => {
        const type = document.getElementById('nm-type').value;
        const config = {};
        if (type === 'scale') { config.min = 1; config.max = 5; }

        await api.createMetric({
            id: document.getElementById('nm-id').value,
            name: document.getElementById('nm-name').value,
            category: document.getElementById('nm-cat').value,
            type,
            frequency: document.getElementById('nm-freq').value,
            config,
        });
        overlay.remove();
        await loadMetrics();
        navigateTo('settings');
    };
}

// ─── Helpers ───
function formatDate(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' });
}

function formatValue(val, type) {
    if (!val) return '—';
    if (type === 'boolean') return val.value ? 'Да' : 'Нет';
    if (type === 'time') return val.value || '—';
    if (type === 'scale' || type === 'number') return val.value ?? '—';
    // compound
    return Object.entries(val).map(([k, v]) => {
        if (typeof v === 'boolean') return v ? k : '';
        return `${v}`;
    }).filter(Boolean).join(', ') || '—';
}

function daysAgo(n) {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
}
