const API_BASE = window.API_BASE || 'http://localhost:8000';

const api = {
    async request(method, path, body = null) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(`${API_BASE}${path}`, opts);
        if (res.status === 204) return null;
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || JSON.stringify(err));
        }
        return res.json();
    },

    // Metrics
    getMetrics(enabledOnly = false) {
        const q = enabledOnly ? '?enabled_only=true' : '';
        return this.request('GET', `/api/metrics${q}`);
    },
    createMetric(data) {
        return this.request('POST', '/api/metrics', data);
    },
    updateMetric(id, data) {
        return this.request('PATCH', `/api/metrics/${id}`, data);
    },
    deleteMetric(id) {
        return this.request('DELETE', `/api/metrics/${id}`);
    },

    // Entries
    getEntries(date, metricId = null) {
        let q = `?date=${date}`;
        if (metricId) q += `&metric_id=${metricId}`;
        return this.request('GET', `/api/entries${q}`);
    },
    createEntry(data) {
        return this.request('POST', '/api/entries', data);
    },
    updateEntry(id, data) {
        return this.request('PUT', `/api/entries/${id}`, data);
    },
    deleteEntry(id) {
        return this.request('DELETE', `/api/entries/${id}`);
    },

    // Daily
    getDailySummary(date) {
        return this.request('GET', `/api/daily/${date}`);
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
};
