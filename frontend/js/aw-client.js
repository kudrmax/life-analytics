/**
 * ActivityWatch local client.
 * Fetches data directly from ActivityWatch running on user's machine (localhost:5600).
 */
const awClient = {
    baseUrl: 'http://localhost:5600',

    setUrl(url) {
        this.baseUrl = url.replace(/\/$/, '');
    },

    async checkAvailable() {
        try {
            const resp = await fetch(`${this.baseUrl}/api/0/info`, {
                signal: AbortSignal.timeout(3000),
            });
            return resp.ok;
        } catch {
            return false;
        }
    },

    async getBuckets() {
        const resp = await fetch(`${this.baseUrl}/api/0/buckets/`);
        if (!resp.ok) throw new Error('Failed to fetch ActivityWatch buckets');
        return resp.json();
    },

    async getEvents(bucketId, start, end) {
        const params = new URLSearchParams({ start, end, limit: '-1' });
        const resp = await fetch(
            `${this.baseUrl}/api/0/buckets/${encodeURIComponent(bucketId)}/events?${params}`
        );
        if (!resp.ok) throw new Error(`Failed to fetch events from ${bucketId}`);
        return resp.json();
    },

    /**
     * Fetch all relevant events for a given date.
     * Returns { windowEvents, afkEvents, webEvents }.
     */
    async fetchDayEvents(dateStr) {
        const start = `${dateStr}T00:00:00`;
        const end = `${dateStr}T23:59:59.999`;

        const buckets = await this.getBuckets();
        const bucketIds = Object.keys(buckets);

        const windowBucket = bucketIds.find(id => id.startsWith('aw-watcher-window'));
        const afkBucket = bucketIds.find(id => id.startsWith('aw-watcher-afk'));
        const webBuckets = bucketIds.filter(id => id.startsWith('aw-watcher-web'));

        if (!windowBucket || !afkBucket) {
            throw new Error('ActivityWatch window/afk watchers not found. Is ActivityWatch running with watchers?');
        }

        const [windowEvents, afkEvents] = await Promise.all([
            this.getEvents(windowBucket, start, end),
            this.getEvents(afkBucket, start, end),
        ]);

        let webEvents = [];
        for (const wb of webBuckets) {
            const events = await this.getEvents(wb, start, end);
            webEvents = webEvents.concat(events);
        }

        return {
            windowEvents,
            afkEvents,
            webEvents: webEvents.length > 0 ? webEvents : null,
        };
    },
};
