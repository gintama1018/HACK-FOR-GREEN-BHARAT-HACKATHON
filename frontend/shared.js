/**
 * InfraWatch Nexus — Shared Frontend Utilities
 * ===============================================
 * Common functions used by both citizen.js and admin.js.
 * Eliminates code duplication across portals.
 */

// ═══════════════════════════════════════════════════════════════════════════
// ROUTE CACHING
// ═══════════════════════════════════════════════════════════════════════════
const InfraRoute = (() => {
    const routeCache = {};
    const multiRouteCache = {};

    /**
     * Fetch a single OSRM route between two points.
     * Returns array of [lat, lng] pairs.
     */
    async function fetchRoadPath(ri) {
        const cacheKey = `${ri.from_lat},${ri.from_lng}-${ri.to_lat},${ri.to_lng}`;
        if (routeCache[cacheKey]) return routeCache[cacheKey];

        try {
            const url = `https://router.project-osrm.org/route/v1/driving/${ri.from_lng},${ri.from_lat};${ri.to_lng},${ri.to_lat}?overview=full&geometries=geojson`;
            const resp = await fetch(url, { signal: AbortSignal.timeout(2000) });
            const data = await resp.json();

            if (data.routes && data.routes.length > 0) {
                const coords = data.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
                routeCache[cacheKey] = coords;
                return coords;
            }
        } catch (e) {
            console.warn('OSRM routing fallback active:', e.message);
        }

        const fallback = [[ri.from_lat, ri.from_lng], [ri.to_lat, ri.to_lng]];
        routeCache[cacheKey] = fallback;
        return fallback;
    }

    /**
     * Fetch multiple routes (main + alternatives) from OSRM.
     * Returns array of {coords, distance, duration}.
     */
    async function fetchMultiRoutes(ri) {
        const cacheKey = `multi-${ri.from_lat},${ri.from_lng}-${ri.to_lat},${ri.to_lng}`;
        if (multiRouteCache[cacheKey]) return multiRouteCache[cacheKey];

        try {
            const url = `https://router.project-osrm.org/route/v1/driving/${ri.from_lng},${ri.from_lat};${ri.to_lng},${ri.to_lat}?overview=full&geometries=geojson&alternatives=true`;
            const resp = await fetch(url, { signal: AbortSignal.timeout(2000) });
            const data = await resp.json();

            if (data.routes && data.routes.length > 0) {
                const routes = data.routes.map(route => ({
                    coords: route.geometry.coordinates.map(c => [c[1], c[0]]),
                    distance: route.distance,
                    duration: route.duration
                }));
                multiRouteCache[cacheKey] = routes;
                return routes;
            }
        } catch (e) {
            console.warn('OSRM multi-route fallback active:', e.message);
        }

        const fallback = [{ coords: [[ri.from_lat, ri.from_lng], [ri.to_lat, ri.to_lng]], distance: 0, duration: 0 }];
        multiRouteCache[cacheKey] = fallback;
        return fallback;
    }

    return { fetchRoadPath, fetchMultiRoutes };
})();


// ═══════════════════════════════════════════════════════════════════════════
// MARKER UTILITIES
// ═══════════════════════════════════════════════════════════════════════════

function getMarkerStateClass(state) {
    switch (state?.toLowerCase()) {
        case 'critical': return 'marker-critical';
        case 'escalated': return 'marker-escalated';
        case 'reported': return 'marker-reported';
        case 'cleared': return 'marker-cleared';
        default: return 'marker-clear';
    }
}

function getMarkerSize(state) {
    switch (state?.toLowerCase()) {
        case 'critical': return 'marker-xl';
        case 'escalated': return 'marker-lg';
        case 'reported': return 'marker-md';
        default: return 'marker-sm';
    }
}

function createDivIcon(stateClass, sizeClass) {
    const size = sizeClass === 'marker-xl' ? 42 : sizeClass === 'marker-lg' ? 34 : sizeClass === 'marker-md' ? 28 : 22;
    return L.divIcon({
        className: '',
        html: `<div class="marker-icon ${stateClass} ${sizeClass}">🗑️</div>`,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
        popupAnchor: [0, -size / 2]
    });
}


// ═══════════════════════════════════════════════════════════════════════════
// FORMATTING UTILITIES
// ═══════════════════════════════════════════════════════════════════════════

function formatDistance(meters) {
    if (meters >= 1000) return `${(meters / 1000).toFixed(1)} km`;
    return `${Math.round(meters)} m`;
}

function formatDuration(seconds) {
    const mins = Math.round(seconds / 60);
    if (mins >= 60) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
    return `${mins} min`;
}

function stateColor(state) {
    const colors = {
        'Critical': '#DC2626', 'Escalated': '#EA580C',
        'Reported': '#D97706', 'Cleared': '#06B6D4',
        'Warning': '#EF4444', 'Elevated': '#F59E0B',
        'Normal': '#16A34A', 'Clear': '#16A34A'
    };
    return colors[state] || '#6B7280';
}
