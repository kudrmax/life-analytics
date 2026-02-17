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

    // Add clear button for daily metrics with entries
    const clearBtn = (m.frequency === 'daily' && entry)
        ? `<button class="metric-clear-btn" data-clear-entry="${entryId}" title="Очистить">&times;</button>`
        : '';

    return `<div class="metric-card ${filledClass}" data-metric-id="${m.metric_id}" data-entry-id="${entryId || ''}">
        <div class="metric-header">
            <label class="metric-label">${m.name}</label>
            ${clearBtn}
        </div>
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

    // Group entries by period
    const periods = { morning: null, day: null, evening: null };
    for (const e of m.entries) {
        const period = e.value.period;
        if (period && periods.hasOwnProperty(period)) {
            // Keep the latest entry for each period
            if (!periods[period] || e.id > periods[period].id) {
                periods[period] = e;
            }
        }
    }

    const periodLabels = {
        morning: 'Утро',
        day: 'День',
        evening: 'Вечер'
    };

    let html = '<div class="multiple-entry">';

    for (const [period, label] of Object.entries(periodLabels)) {
        const entry = periods[period];
        const currentValue = entry ? entry.value.value : null;
        const entryId = entry ? entry.id : '';
        const clearBtn = entry ? `<button class="period-clear-btn" data-clear-period-entry="${entryId}" title="Очистить">&times;</button>` : '';

        html += `<div class="period-section" data-period="${period}" data-period-entry-id="${entryId}">`;
        html += `<div class="period-header">`;
        html += `<label class="period-label">${label}</label>`;
        html += clearBtn;
        html += `</div>`;
        html += '<div class="scale-buttons">';
        for (let i = min; i <= max; i++) {
            const active = currentValue === i ? 'active' : '';
            html += `<button class="scale-btn ${active}" data-period-value="${i}" data-period="${period}">${i}</button>`;
        }
        html += '</div>';
        html += '</div>';
    }

    // Show summary if there are any entries
    if (m.summary && (periods.morning || periods.day || periods.evening)) {
        html += `<div class="summary-line">Среднее: ${m.summary.avg} | Мин: ${m.summary.min} | Макс: ${m.summary.max}</div>`;
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

            await saveDaily(metricId, entryId, { value: newValue });
            await renderTodayForm();
        } catch (error) {
            console.error('Error in number button handler:', error);
            alert('Ошибка: ' + error.message);
        }
        return;
    }

    // Period-based scale buttons (for multiple-frequency metrics)
    if (btn.dataset.periodValue && btn.dataset.period) {
        try {
            const period = btn.dataset.period;
            const value = parseInt(btn.dataset.periodValue);
            const periodSection = btn.closest('.period-section');
            const periodEntryId = periodSection ? periodSection.dataset.periodEntryId : '';

            console.log('Period button clicked:', { metricId, period, value, periodEntryId });

            if (periodEntryId) {
                // Update existing entry
                await api.updateEntry(parseInt(periodEntryId), {
                    value: { period, value }
                });
            } else {
                // Create new entry
                await api.createEntry({
                    metric_id: metricId,
                    date: currentDate,
                    timestamp: new Date().toISOString(),
                    value: { period, value },
                });
            }
            await renderTodayForm();
        } catch (error) {
            console.error('Error in period button handler:', error);
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
            const typeLabel = getTypeLabel(m.type);
            const freqLabel = getFrequencyLabel(m.frequency);
            html += `<div class="setting-row">
                <div class="setting-info">
                    <span class="setting-name ${m.enabled ? '' : 'disabled'}">${m.name}</span>
                    <span class="setting-type">${typeLabel} • ${freqLabel}</span>
                </div>
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
        <div class="modal modal-large">
            <h3>Создать метрику</h3>

            <div class="modal-content-split">
            <div class="modal-form">
                <label class="form-label">
                    <span class="label-text">Название</span>
                    <input id="nm-name" placeholder="Например: Экранное время" class="form-input">
                    <span class="label-hint">Как метрика будет отображаться</span>
                </label>

                <label class="form-label">
                    <span class="label-text">Категория</span>
                    <input id="nm-cat" placeholder="Например: Продуктивность" class="form-input">
                    <span class="label-hint">Для группировки метрик</span>
                </label>

                <div class="form-section" id="type-section">
                    <span class="label-text">Тип значения</span>
                    <div class="radio-group">
                        <label class="radio-option">
                            <input type="radio" name="type" value="boolean" checked>
                            <div class="radio-content">
                                <strong>Да/Нет</strong>
                                <span>Простой выбор (например: "Тренировка была?")</span>
                            </div>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="type" value="number">
                            <div class="radio-content">
                                <strong>Число</strong>
                                <span>Количество (например: "5 чашек кофе", "2.5 часа работы")</span>
                            </div>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="type" value="scale">
                            <div class="radio-content">
                                <strong>Шкала 1-5</strong>
                                <span>Оценка (например: "Качество сна: 4 из 5")</span>
                            </div>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="type" value="time">
                            <div class="radio-content">
                                <strong>Время</strong>
                                <span>Указать время (например: "Подъем в 07:30")</span>
                            </div>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="type" value="compound">
                            <div class="radio-content">
                                <strong>Составная (условная)</strong>
                                <span>Несколько полей с условиями (например: "Алкоголь: да/нет + количество порций")</span>
                            </div>
                        </label>
                    </div>
                </div>

                <div class="form-section" id="frequency-section">
                    <span class="label-text">Как часто заполнять</span>
                    <div class="radio-group">
                        <label class="radio-option">
                            <input type="radio" name="frequency" value="daily" checked>
                            <div class="radio-content">
                                <strong>Один раз в день</strong>
                                <span>Заполняется вечером при подведении итогов</span>
                            </div>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="frequency" value="multiple">
                            <div class="radio-content">
                                <strong>Три раза в день (оценка 1-5)</strong>
                                <span>Заполняется утром, днём и вечером. Автоматически использует шкалу 1-5 (для настроения, энергии, стресса)</span>
                            </div>
                        </label>
                    </div>
                </div>

                <div id="number-options" class="form-section" style="display: none;">
                    <span class="label-text">Настройки числа</span>
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

                <div id="compound-options" class="form-section" style="display: none;">
                    <span class="label-text">Выберите структуру</span>
                    <div class="compound-examples">
                        <button type="button" class="compound-example-btn" data-example="bool_number">
                            Да/Нет + Число
                        </button>
                        <button type="button" class="compound-example-btn" data-example="bool_enum">
                            Да/Нет + Варианты
                        </button>
                    </div>

                    <div id="compound-config-number" class="compound-config" style="display: none;">
                        <label class="form-label">
                            <span class="label-text">Текст вопроса</span>
                            <input id="compound-question-num" placeholder="Например: Употреблял алкоголь" class="form-input">
                        </label>
                        <div class="form-label">
                            <span class="label-text">Число появляется при выборе:</span>
                            <div class="radio-group-inline">
                                <label class="radio-inline">
                                    <input type="radio" name="compound-condition-num" value="true" checked>
                                    <span>Да</span>
                                </label>
                                <label class="radio-inline">
                                    <input type="radio" name="compound-condition-num" value="false">
                                    <span>Нет</span>
                                </label>
                            </div>
                        </div>
                        <label class="form-label">
                            <span class="label-text">Подпись числа</span>
                            <input id="compound-num-label" placeholder="Например: Количество порций" class="form-input">
                        </label>
                    </div>

                    <div id="compound-config-enum" class="compound-config" style="display: none;">
                        <label class="form-label">
                            <span class="label-text">Текст вопроса</span>
                            <input id="compound-question-enum" placeholder="Например: Была тренировка" class="form-input">
                        </label>
                        <div class="form-label">
                            <span class="label-text">Варианты появляются при выборе:</span>
                            <div class="radio-group-inline">
                                <label class="radio-inline">
                                    <input type="radio" name="compound-condition-enum" value="true" checked>
                                    <span>Да</span>
                                </label>
                                <label class="radio-inline">
                                    <input type="radio" name="compound-condition-enum" value="false">
                                    <span>Нет</span>
                                </label>
                            </div>
                        </div>
                        <label class="form-label">
                            <span class="label-text">Варианты выбора (через запятую)</span>
                            <input id="compound-enum-options" placeholder="кардио, силовая, растяжка, йога" class="form-input">
                            <span class="label-hint">Введите варианты через запятую</span>
                        </label>
                    </div>

                    <div class="label-hint">
                        💡 <strong>Совет:</strong> В превью справа можно кликать по кнопкам, чтобы увидеть как работает условная логика
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
                <button class="btn-primary" id="nm-save">Создать метрику</button>
                <button class="btn-small" id="nm-cancel">Отмена</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    // Compound configuration
    let currentCompoundType = null;

    const buildCompoundConfig = () => {
        if (currentCompoundType === 'bool_number') {
            const question = document.getElementById('compound-question-num').value || 'Было';
            const condition = document.querySelector('input[name="compound-condition-num"]:checked').value;
            const numLabel = document.getElementById('compound-num-label').value || 'Количество';
            return {
                fields: [
                    { name: 'has', type: 'boolean', label: question },
                    { name: 'amount', type: 'number', label: numLabel, condition: `has == ${condition}` }
                ]
            };
        } else if (currentCompoundType === 'bool_enum') {
            const question = document.getElementById('compound-question-enum').value || 'Было';
            const condition = document.querySelector('input[name="compound-condition-enum"]:checked').value;
            const optionsStr = document.getElementById('compound-enum-options').value || 'вариант 1, вариант 2, вариант 3';
            const options = optionsStr.split(',').map(s => s.trim()).filter(Boolean);
            return {
                fields: [
                    { name: 'has', type: 'boolean', label: question },
                    { name: 'type', type: 'enum', label: 'Тип', options, condition: `has == ${condition}` }
                ]
            };
        }
        return null;
    };

    // Update preview on any change
    const updatePreview = () => {
        const name = document.getElementById('nm-name').value || 'Название метрики';
        const frequency = document.querySelector('input[name="frequency"]:checked').value;

        // Get current type (or default to scale for multiple)
        let type;
        if (frequency === 'multiple') {
            type = 'scale';
            document.getElementById('type-section').style.display = 'none';
        } else {
            type = document.querySelector('input[name="type"]:checked').value;
            document.getElementById('type-section').style.display = 'block';
        }

        // Show/hide and enable/disable frequency options based on type
        const frequencySection = document.getElementById('frequency-section');
        const multipleOption = document.querySelector('input[name="frequency"][value="multiple"]');
        const multipleLabel = multipleOption.closest('.radio-option');

        if (frequency === 'daily') {
            // When editing type, check if multiple should be available
            if (type === 'scale') {
                // Scale can use multiple frequency
                multipleLabel.style.display = 'flex';
            } else {
                // Other types can only use daily frequency
                multipleLabel.style.display = 'none';
                // Make sure daily is selected
                document.querySelector('input[name="frequency"][value="daily"]').checked = true;
            }
        }

        // Show/hide options based on type
        const numberOpts = document.getElementById('number-options');
        const compoundOpts = document.getElementById('compound-options');
        numberOpts.style.display = (type === 'number' && frequency === 'daily') ? 'block' : 'none';
        compoundOpts.style.display = (type === 'compound' && frequency === 'daily') ? 'block' : 'none';

        // Build mock metric object
        const mockMetric = {
            metric_id: 'preview',
            name: name,
            type: type,
            frequency: frequency,
            config: {},
            entries: []
        };

        if (type === 'scale') {
            mockMetric.config.min = 1;
            mockMetric.config.max = 5;
        } else if (type === 'number') {
            mockMetric.config.label = document.getElementById('nm-unit').value;
            mockMetric.config.min = parseFloat(document.getElementById('nm-min').value) || 0;
            mockMetric.config.max = parseFloat(document.getElementById('nm-max').value) || 100;
            mockMetric.config.step = parseFloat(document.getElementById('nm-step').value) || 1;
        } else if (type === 'compound') {
            const compoundConfig = buildCompoundConfig();
            if (compoundConfig) {
                mockMetric.config.fields = compoundConfig.fields;
            }
        }

        // Render preview
        const preview = document.getElementById('metric-preview');
        let previewHTML = '';

        if (frequency === 'multiple') {
            previewHTML = renderMultipleInput(mockMetric);
        } else if (type === 'scale') {
            previewHTML = renderScale(mockMetric, null);
        } else if (type === 'boolean') {
            previewHTML = renderBoolean(mockMetric, null);
        } else if (type === 'number') {
            previewHTML = renderNumber(mockMetric, null);
        } else if (type === 'time') {
            previewHTML = renderTime(mockMetric, null);
        } else if (type === 'compound') {
            const compoundConfig = buildCompoundConfig();
            previewHTML = compoundConfig
                ? renderCompound(mockMetric, null)
                : '<div class="label-hint">Выберите структуру составной метрики</div>';
        }

        preview.innerHTML = `
            <div class="metric-card" id="preview-card">
                <div class="metric-header">
                    <label class="metric-label">${name}</label>
                </div>
                <div class="metric-input">${previewHTML}</div>
            </div>
        `;

        // Make preview interactive for compound metrics
        if (type === 'compound') {
            const previewCard = document.getElementById('preview-card');
            previewCard.querySelectorAll('.bool-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    const parent = btn.parentElement;
                    parent.querySelectorAll('.bool-btn').forEach(b => b.classList.remove('active', 'yes', 'no'));

                    const value = btn.dataset.value === 'true';
                    if (value) {
                        btn.classList.add('active', 'yes');
                    } else {
                        btn.classList.add('active', 'no');
                    }

                    // Show/hide conditional fields
                    const compoundField = btn.closest('.compound-fields');
                    if (compoundField) {
                        const condition = btn.dataset.compoundField;
                        const compoundConfig = buildCompoundConfig();
                        if (compoundConfig && compoundConfig.fields) {
                            compoundConfig.fields.forEach(field => {
                                if (field.condition) {
                                    const match = field.condition.match(/(\w+)\s*==\s*(true|false)/);
                                    if (match) {
                                        const condValue = match[2] === 'true';
                                        const condField = compoundField.querySelector(`[data-cfield="${field.name}"]`);
                                        if (condField) {
                                            condField.classList.toggle('hidden', value !== condValue);
                                        }
                                    }
                                }
                            });
                        }
                    }
                });
            });
        }
    };

    // Attach event listeners
    document.getElementById('nm-name').addEventListener('input', updatePreview);
    document.getElementById('nm-cat').addEventListener('input', updatePreview);
    document.querySelectorAll('input[name="type"]').forEach(r => r.addEventListener('change', updatePreview));
    document.querySelectorAll('input[name="frequency"]').forEach(r => r.addEventListener('change', updatePreview));
    document.getElementById('nm-unit').addEventListener('input', updatePreview);
    document.getElementById('nm-min').addEventListener('input', updatePreview);
    document.getElementById('nm-max').addEventListener('input', updatePreview);
    document.getElementById('nm-step').addEventListener('input', updatePreview);

    // Compound example buttons
    document.querySelectorAll('.compound-example-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const example = btn.dataset.example;
            currentCompoundType = example;

            // Show/hide config sections
            document.getElementById('compound-config-number').style.display = example === 'bool_number' ? 'block' : 'none';
            document.getElementById('compound-config-enum').style.display = example === 'bool_enum' ? 'block' : 'none';

            // Set active button
            document.querySelectorAll('.compound-example-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Set default values if empty
            if (example === 'bool_number') {
                if (!document.getElementById('compound-question-num').value) {
                    document.getElementById('compound-question-num').value = 'Употреблял алкоголь';
                    document.getElementById('compound-num-label').value = 'Количество порций';
                }
            } else if (example === 'bool_enum') {
                if (!document.getElementById('compound-question-enum').value) {
                    document.getElementById('compound-question-enum').value = 'Была тренировка';
                    document.getElementById('compound-enum-options').value = 'кардио, силовая, растяжка, йога';
                }
            }

            updatePreview();
        });
    });

    // Compound config inputs
    document.getElementById('compound-question-num').addEventListener('input', updatePreview);
    document.getElementById('compound-num-label').addEventListener('input', updatePreview);
    document.querySelectorAll('input[name="compound-condition-num"]').forEach(r => r.addEventListener('change', updatePreview));
    document.getElementById('compound-question-enum').addEventListener('input', updatePreview);
    document.getElementById('compound-enum-options').addEventListener('input', updatePreview);
    document.querySelectorAll('input[name="compound-condition-enum"]').forEach(r => r.addEventListener('change', updatePreview));

    updatePreview(); // Initial render

    document.getElementById('nm-cancel').onclick = () => overlay.remove();
    document.getElementById('nm-save').onclick = async () => {
        const name = document.getElementById('nm-name').value;
        const category = document.getElementById('nm-cat').value;

        if (!name || !category) {
            alert('Заполните название и категорию');
            return;
        }

        const frequency = document.querySelector('input[name="frequency"]:checked').value;

        // For multiple frequency, always use scale type
        const type = frequency === 'multiple' ? 'scale' : document.querySelector('input[name="type"]:checked').value;

        // Generate ID from name
        const id = name.toLowerCase()
            .replace(/\s+/g, '_')
            .replace(/[^a-z0-9_]/g, '')
            || 'metric_' + Date.now();

        const config = {};
        if (type === 'scale') {
            config.min = 1;
            config.max = 5;
        } else if (type === 'number') {
            config.label = document.getElementById('nm-unit').value;
            config.min = parseFloat(document.getElementById('nm-min').value) || 0;
            config.max = parseFloat(document.getElementById('nm-max').value) || 100;
            config.step = parseFloat(document.getElementById('nm-step').value) || 1;
        } else if (type === 'compound') {
            const compoundConfig = buildCompoundConfig();
            if (!compoundConfig) {
                alert('Настройте составную метрику');
                return;
            }
            config.fields = compoundConfig.fields;
        }

        try {
            await api.createMetric({
                id,
                name,
                category,
                type,
                frequency,
                config,
            });
            overlay.remove();
            await loadMetrics();
            navigateTo('settings');
        } catch (error) {
            alert('Ошибка создания метрики: ' + error.message);
        }
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

function getTypeLabel(type) {
    const labels = {
        'boolean': 'Да/Нет',
        'number': 'Число',
        'scale': 'Шкала 1-5',
        'time': 'Время',
        'enum': 'Варианты',
        'compound': 'Составная'
    };
    return labels[type] || type;
}

function getFrequencyLabel(frequency) {
    const labels = {
        'daily': 'Раз в день',
        'multiple': '3 раза в день'
    };
    return labels[frequency] || frequency;
}
