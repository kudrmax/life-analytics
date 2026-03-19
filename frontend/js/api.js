const API_BASE = window.API_BASE || '';

// Token management
const TOKEN_KEY = 'la_auth_token';
const USERNAME_KEY = 'la_username';

function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}

function setToken(token, username) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USERNAME_KEY, username);
}

function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USERNAME_KEY);
}

// Response cache
const _responseCache = new Map();

function getCached(url, maxAgeMs) {
    const entry = _responseCache.get(url);
    if (entry && Date.now() - entry.time < maxAgeMs) return entry.data;
    return undefined;
}

function setCache(url, data) {
    _responseCache.set(url, { data, time: Date.now() });
}

function invalidateCache(...patterns) {
    for (const key of _responseCache.keys()) {
        if (patterns.some(p => key.includes(p))) _responseCache.delete(key);
    }
}

const api = {
    API_BASE,
    async request(method, path, body = null) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };

        const token = getToken();
        if (token) {
            opts.headers['Authorization'] = `Bearer ${token}`;
        }

        if (body) opts.body = JSON.stringify(body);
        const _t0 = performance.now();
        const res = await fetch(`${API_BASE}${path}`, opts);
        console.debug(`[api] ${method} ${path} -> ${res.status}  ${(performance.now() - _t0).toFixed(0)}ms`);

        if (res.status === 401) {
            clearToken();
            if (window.navigateTo) {
                window.navigateTo('login');
            }
            throw new Error('Session expired');
        }

        if (res.status === 204) return null;
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || JSON.stringify(err));
        }
        return res.json();
    },

    cachedGet(path, maxAgeMs = 120_000) {
        const cached = getCached(path, maxAgeMs);
        if (cached !== undefined) {
            console.debug(`[api] cache HIT  ${path}`);
            return Promise.resolve(cached);
        }
        console.debug(`[api] cache MISS ${path}`);
        return this.request('GET', path).then(data => {
            setCache(path, data);
            return data;
        });
    },

    // Auth
    register(username, password) {
        return this.request('POST', '/api/auth/register', { username, password });
    },
    login(username, password) {
        return this.request('POST', '/api/auth/login', { username, password });
    },
    getCurrentUser() {
        return this.request('GET', '/api/auth/me');
    },
    getPrivacyMode() {
        return this.request('GET', '/api/auth/privacy-mode');
    },
    async setPrivacyMode(enabled) {
        const result = await this.request('PUT', '/api/auth/privacy-mode', { enabled });
        _responseCache.clear();
        return result;
    },
    logout() {
        clearToken();
    },
    setToken,
    getToken,
    clearToken,

    // Metrics
    getMetrics(enabledOnly = false) {
        const q = enabledOnly ? '?enabled_only=true' : '';
        return this.request('GET', `/api/metrics${q}`);
    },
    async createMetric(data) {
        const result = await this.request('POST', '/api/metrics', data);
        invalidateCache('/api/metrics', '/api/daily/');
        return result;
    },
    async updateMetric(id, data) {
        const result = await this.request('PATCH', `/api/metrics/${id}`, data);
        invalidateCache('/api/metrics', '/api/daily/');
        return result;
    },
    async deleteMetric(id) {
        const result = await this.request('DELETE', `/api/metrics/${id}`);
        invalidateCache('/api/metrics', '/api/daily/');
        return result;
    },
    async reorderMetrics(items) {
        const result = await this.request('POST', '/api/metrics/reorder', items);
        invalidateCache('/api/metrics', '/api/daily/');
        return result;
    },
    convertPreview(metricId, targetType) {
        return this.request('GET', `/api/metrics/${metricId}/convert/preview?target_type=${targetType}`);
    },
    async convertMetric(metricId, data) {
        const result = await this.request('POST', `/api/metrics/${metricId}/convert`, data);
        invalidateCache('/api/metrics', '/api/daily/', '/api/entries');
        return result;
    },

    // Entries
    getEntries(date, metricId = null) {
        let q = `?date=${date}`;
        if (metricId) q += `&metric_id=${metricId}`;
        return this.request('GET', `/api/entries${q}`);
    },
    async createEntry(data) {
        const result = await this.request('POST', '/api/entries', data);
        invalidateCache('/api/daily/', '/api/entries');
        return result;
    },
    async updateEntry(id, data) {
        const result = await this.request('PUT', `/api/entries/${id}`, data);
        invalidateCache('/api/daily/', '/api/entries');
        return result;
    },
    async deleteEntry(id) {
        const result = await this.request('DELETE', `/api/entries/${id}`);
        invalidateCache('/api/daily/', '/api/entries');
        return result;
    },

    // Daily
    getDailySummary(date) {
        return this.cachedGet(`/api/daily/${date}`);
    },

    // Analytics
    getTrends(metricId, start, end) {
        return this.request('GET', `/api/analytics/trends?metric_id=${metricId}&start=${start}&end=${end}`);
    },
    getCorrelations(a, b, start, end) {
        return this.request('GET', `/api/analytics/correlations?metric_a=${a}&metric_b=${b}&start=${start}&end=${end}`);
    },
    getStreaks() {
        return this.request('GET', '/api/analytics/streaks');
    },
    getMetricStats(metricId, start, end) {
        return this.request('GET', `/api/analytics/metric-stats?metric_id=${metricId}&start=${start}&end=${end}`);
    },

    // Correlation reports
    createCorrelationReport(start, end) {
        return this.request('POST', '/api/analytics/correlation-report', { start, end });
    },
    getCorrelationReport() {
        return this.request('GET', '/api/analytics/correlation-report');
    },
    getCorrelationPairs(reportId, { category = 'all', offset = 0, limit = 50, metric_ids = null } = {}) {
        const params = new URLSearchParams({ category, offset, limit });
        if (metric_ids) params.set('metric_ids', metric_ids);
        return this.request('GET', `/api/analytics/correlation-report/${reportId}/pairs?${params}`);
    },
    getCorrelationPairChart(pairId) {
        return this.request('GET', `/api/analytics/correlation-pair-chart?pair_id=${pairId}`);
    },

    // Integrations
    listIntegrations() {
        return this.request('GET', '/api/integrations');
    },
    getTodoistAuthUrl() {
        return this.request('GET', '/api/integrations/todoist/auth-url');
    },
    async disconnectIntegration(provider) {
        const result = await this.request('DELETE', `/api/integrations/${provider}/disconnect`);
        invalidateCache('/api/integrations');
        return result;
    },
    async fetchIntegration(provider, date = null, metricId = null) {
        const params = [];
        if (date) params.push(`date=${date}`);
        if (metricId) params.push(`metric_id=${metricId}`);
        const q = params.length ? '?' + params.join('&') : '';
        const result = await this.request('POST', `/api/integrations/${provider}/fetch${q}`);
        invalidateCache('/api/daily/');
        return result;
    },
    getTodoistAvailableMetrics() {
        return this.request('GET', '/api/integrations/todoist/available-metrics');
    },

    // ActivityWatch
    awGetStatus() {
        return this.cachedGet('/api/integrations/activitywatch/status', 300_000);
    },
    async awEnable() {
        const result = await this.request('POST', '/api/integrations/activitywatch/enable');
        invalidateCache('/api/integrations/activitywatch');
        return result;
    },
    async awDisable() {
        const result = await this.request('DELETE', '/api/integrations/activitywatch/disable');
        invalidateCache('/api/integrations/activitywatch');
        return result;
    },
    async awSync(date, windowEvents, afkEvents, webEvents = null) {
        const body = { date, window_events: windowEvents, afk_events: afkEvents };
        if (webEvents) body.web_events = webEvents;
        const result = await this.request('POST', '/api/integrations/activitywatch/sync', body);
        invalidateCache('/api/integrations/activitywatch');
        return result;
    },
    awGetSummary(date) {
        return this.cachedGet(`/api/integrations/activitywatch/summary?date=${date}`);
    },
    awGetTrends(start, end) {
        return this.request('GET', `/api/integrations/activitywatch/trends?start=${start}&end=${end}`);
    },

    // ActivityWatch Categories
    awGetCategories() {
        return this.request('GET', '/api/integrations/activitywatch/categories');
    },
    async awCreateCategory(name, color) {
        const result = await this.request('POST', '/api/integrations/activitywatch/categories', { name, color });
        invalidateCache('/api/integrations/activitywatch/categories');
        return result;
    },
    async awUpdateCategory(id, data) {
        const result = await this.request('PUT', `/api/integrations/activitywatch/categories/${id}`, data);
        invalidateCache('/api/integrations/activitywatch/categories');
        return result;
    },
    async awDeleteCategory(id) {
        const result = await this.request('DELETE', `/api/integrations/activitywatch/categories/${id}`);
        invalidateCache('/api/integrations/activitywatch/categories');
        return result;
    },
    awGetApps() {
        return this.request('GET', '/api/integrations/activitywatch/apps');
    },
    async awSetAppCategory(appName, categoryId) {
        const result = await this.request('PUT', `/api/integrations/activitywatch/apps/${encodeURIComponent(appName)}/category`, { category_id: categoryId });
        invalidateCache('/api/integrations/activitywatch/apps');
        return result;
    },
    async awBatchSetCategory(appNames, categoryId) {
        const result = await this.request('PUT', '/api/integrations/activitywatch/apps/batch-category', { app_names: appNames, category_id: categoryId });
        invalidateCache('/api/integrations/activitywatch/apps');
        return result;
    },
    awGetAvailableMetrics() {
        return this.request('GET', '/api/integrations/activitywatch/available-metrics');
    },

    // Notes (text metrics)
    async createNote(data) {
        const result = await this.request('POST', '/api/notes', data);
        invalidateCache('/api/daily/');
        return result;
    },
    async updateNote(id, data) {
        const result = await this.request('PUT', `/api/notes/${id}`, data);
        invalidateCache('/api/daily/');
        return result;
    },
    async deleteNote(id) {
        const result = await this.request('DELETE', `/api/notes/${id}`);
        invalidateCache('/api/daily/');
        return result;
    },
    listNotes(metricId, start, end) {
        return this.request('GET', `/api/notes?metric_id=${metricId}&start=${start}&end=${end}`);
    },

    // Insights
    getInsights() {
        return this.request('GET', '/api/insights');
    },
    async createInsight(data) {
        const result = await this.request('POST', '/api/insights', data);
        invalidateCache('/api/insights');
        return result;
    },
    async updateInsight(id, data) {
        const result = await this.request('PUT', `/api/insights/${id}`, data);
        invalidateCache('/api/insights');
        return result;
    },
    async deleteInsight(id) {
        const result = await this.request('DELETE', `/api/insights/${id}`);
        invalidateCache('/api/insights');
        return result;
    },

    // Slots (Время замера)
    getSlots() {
        return this.cachedGet('/api/slots');
    },
    async createSlot(data) {
        const result = await this.request('POST', '/api/slots', data);
        invalidateCache('/api/slots');
        return result;
    },
    async updateSlot(id, data) {
        const result = await this.request('PATCH', `/api/slots/${id}`, data);
        invalidateCache('/api/slots');
        return result;
    },
    async deleteSlot(id) {
        const result = await this.request('DELETE', `/api/slots/${id}`);
        invalidateCache('/api/slots', '/api/metrics', '/api/daily/');
        return result;
    },
    async reorderSlots(items) {
        const result = await this.request('POST', '/api/slots/reorder', items);
        invalidateCache('/api/slots');
        return result;
    },

    // Categories
    getCategories() {
        return this.cachedGet('/api/categories');
    },
    async createCategory(data) {
        const result = await this.request('POST', '/api/categories', data);
        invalidateCache('/api/categories');
        return result;
    },
    async updateCategory(id, data) {
        const result = await this.request('PATCH', `/api/categories/${id}`, data);
        invalidateCache('/api/categories');
        return result;
    },
    async deleteCategory(id) {
        const result = await this.request('DELETE', `/api/categories/${id}`);
        invalidateCache('/api/categories', '/api/metrics', '/api/daily/');
        return result;
    },
    async reorderCategories(items) {
        const result = await this.request('POST', '/api/categories/reorder', items);
        invalidateCache('/api/categories');
        return result;
    },
};
