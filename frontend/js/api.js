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
        const res = await fetch(`${API_BASE}${path}`, opts);

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
        if (cached !== undefined) return Promise.resolve(cached);
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
};
