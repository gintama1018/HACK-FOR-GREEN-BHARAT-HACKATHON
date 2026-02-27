/**
 * InfraWatch Nexus — Citizens' Portal Logic (SPA Edition)
 * Multi-section dashboard with single persistent WebSocket connection.
 */

const API_BASE = window.location.origin;
const WS_SCHEME = window.location.protocol === 'https:' ? 'wss' : 'ws';
const WS_URL = `${WS_SCHEME}://${window.location.host}/ws`;

let dashboard = null;
let configData = null;

// Map instances
let dashMap = null;
let fullMap = null;
let routeMap = null;
let markers = {};       // Dashboard map markers
let fullMarkers = {};   // Full map markers
let routeMarkers = {};  // Route map markers
let roadLines = [];
let fullRoadLines = [];
let routeLines = [];

// Report state
let detectedDustbinId = null;
let selectedOverflow = 3;
let manualSelectedOverflow = 3;

// Recent reports tracker
let recentReports = [];

// Route cache
const routeCache = {};

// ── OSRM ROUTING — MULTI-ROUTE ──────────────────────────────────────
const multiRouteCache = {};

async function fetchMultiRoutes(ri) {
    const cacheKey = `multi-${ri.from_lat},${ri.from_lng}-${ri.to_lat},${ri.to_lng}`;
    if (multiRouteCache[cacheKey]) return multiRouteCache[cacheKey];

    try {
        const url = `https://router.project-osrm.org/route/v1/driving/${ri.from_lng},${ri.from_lat};${ri.to_lng},${ri.to_lat}?overview=full&geometries=geojson&alternatives=true`;
        const resp = await fetch(url, { signal: AbortSignal.timeout(12000) });
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
        console.warn('OSRM multi-route retry next tick:', e.message);
    }

    // Fallback: straight line — NOT CACHED so it retries next WS update
    return [{ coords: [[ri.from_lat, ri.from_lng], [ri.to_lat, ri.to_lng]], distance: 0, duration: 0 }];
}

// Single-route fetch (used by zoomToAlert highlight)
async function fetchRoadPath(ri) {
    const cacheKey = `${ri.from_lat},${ri.from_lng}-${ri.to_lat},${ri.to_lng}`;
    if (routeCache[cacheKey]) return routeCache[cacheKey];

    try {
        const url = `https://router.project-osrm.org/route/v1/driving/${ri.from_lng},${ri.from_lat};${ri.to_lng},${ri.to_lat}?overview=full&geometries=geojson`;
        const resp = await fetch(url, { signal: AbortSignal.timeout(10000) });
        const data = await resp.json();

        if (data.routes && data.routes.length > 0) {
            const coords = data.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
            routeCache[cacheKey] = coords;
            return coords;
        }
    } catch (e) {
        console.warn('OSRM routing retry next tick:', e.message);
    }

    // Fallback: NOT CACHED — will retry on next call
    return [[ri.from_lat, ri.from_lng], [ri.to_lat, ri.to_lng]];
}

// ── MARKER HELPERS ──────────────────────────────────────────────────
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

// ── INIT ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    initDashMap();
    initReportFlow();
    connectWebSocket();
});

// ── CONFIG ──────────────────────────────────────────────────────────
async function loadConfig() {
    try {
        const resp = await fetch(`${API_BASE}/api/config`);
        configData = await resp.json();

        // Populate ward filter in topbar
        const wardFilter = document.getElementById('filterWard');
        for (const [wid, info] of Object.entries(configData.wards)) {
            wardFilter.innerHTML += `<option value="${wid}">${info.name} (${wid})</option>`;
        }

        // Populate manual form wards
        const manualWard = document.getElementById('manualWard');
        for (const [wid, info] of Object.entries(configData.wards)) {
            manualWard.innerHTML += `<option value="${wid}">${info.name} (${wid})</option>`;
        }

        manualWard.addEventListener('change', () => {
            const sel = document.getElementById('manualDustbin');
            sel.innerHTML = '<option value="">— Select Dustbin —</option>';
            for (const [did, info] of Object.entries(configData.dustbins)) {
                if (info.ward_id === manualWard.value) {
                    sel.innerHTML += `<option value="${did}">${did} — ${info.street}</option>`;
                }
            }
        });
    } catch (e) {
        showToast('Configuration failed to load.', 'error');
    }
}

// ── SECTION SWITCHING ───────────────────────────────────────────────
function switchSection(name) {
    // Update sidebar active state
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.section === name);
    });

    // Show/hide content sections
    document.querySelectorAll('.content-section').forEach(sec => {
        sec.classList.toggle('active', sec.id === `section-${name}`);
    });

    // Initialize section-specific maps on first visit
    if (name === 'citymap' && !fullMap) {
        setTimeout(() => initFullMap(), 100);
    }
    if (name === 'routeplanner' && !routeMap) {
        setTimeout(() => initRouteMap(), 100);
    }

    // Invalidate map size when switching (Leaflet needs this)
    setTimeout(() => {
        if (name === 'dashboard' && dashMap) dashMap.invalidateSize();
        if (name === 'citymap' && fullMap) fullMap.invalidateSize();
        if (name === 'routeplanner' && routeMap) routeMap.invalidateSize();
    }, 150);

    // Render section data
    if (name === 'analytics') renderAnalyticsPage();
    if (name === 'alerts') renderAlertsPage();
    if (name === 'routeplanner') renderRoutePage();
}

function switchPanelTab(btn) {
    document.querySelectorAll('.ptab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.ptab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.ptab).classList.add('active');
}

// ── MAPS ────────────────────────────────────────────────────────────
function createMapInstance(containerId, zoom = 12) {
    const center = configData?.city_center || { lat: 28.6139, lng: 77.2090 };
    const map = L.map(containerId, { center: [center.lat, center.lng], zoom });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '© CARTO', maxZoom: 19
    }).addTo(map);

    return map;
}

function addDustbinMarkers(map, markerStore) {
    if (!configData?.dustbins) return;
    for (const [did, info] of Object.entries(configData.dustbins)) {
        const icon = createDivIcon('marker-clear', 'marker-sm');
        const marker = L.marker([info.lat, info.lng], { icon }).addTo(map);
        marker.bindPopup(`<b>${did}</b><br>${info.street}`);
        markerStore[did] = marker;
    }
}

function initDashMap() {
    dashMap = createMapInstance('dashMap', 11);
    addDustbinMarkers(dashMap, markers);
}

function initFullMap() {
    fullMap = createMapInstance('fullMap', 12);
    addDustbinMarkers(fullMap, fullMarkers);
    updateFullMap();
}

function initRouteMap() {
    routeMap = createMapInstance('routeMap', 12);
    addDustbinMarkers(routeMap, routeMarkers);
}

// ── MAP UPDATES ─────────────────────────────────────────────────────
function updateMarkers(markerStore, dustbinStates) {
    for (const ds of dustbinStates) {
        const marker = markerStore[ds.dustbin_id];
        if (!marker) continue;

        const stateClass = getMarkerStateClass(ds.state);
        const sizeClass = getMarkerSize(ds.state);
        marker.setIcon(createDivIcon(stateClass, sizeClass));

        marker.setPopupContent(`
            <div style="font-family: 'Inter', sans-serif;">
                <b style="font-size: 14px;">${ds.dustbin_id}</b><br>
                <div style="font-size: 11px; color: #94A3B8; margin-bottom: 6px;">${ds.street} (${ds.ward_id})</div>
                <div style="background: ${ds.color}20; border: 1px solid ${ds.color}50; color: ${ds.color}; padding: 4px 8px; border-radius: 4px; display: inline-block; font-weight: 600; font-size: 11px;">
                    ● ${ds.state.toUpperCase()}
                </div>
                ${ds.report_count > 0 ? `<div style="margin-top: 6px; font-size: 12px; font-weight: 500;">Reports: ${ds.report_count} | Overflow: ${ds.max_overflow}/5</div>` : ''}
            </div>
        `);
    }
}

function drawRoadLines(map, lineStore, roadIssues) {
    lineStore.forEach(l => map.removeLayer(l));
    lineStore.length = 0;

    for (const ri of (roadIssues || [])) {
        fetchMultiRoutes(ri).then(routes => {
            if (!routes || routes.length === 0) return;

            // Draw ALTERNATIVE routes first (behind, yellow)
            for (let i = routes.length - 1; i >= 1; i--) {
                const altLine = L.polyline(routes[i].coords, {
                    color: '#FBBF24',    // Yellow
                    weight: 3,
                    dashArray: '4,8',
                    opacity: 0.65
                }).addTo(map);
                const distKm = (routes[i].distance / 1000).toFixed(1);
                const timeMin = Math.round(routes[i].duration / 60);
                altLine.bindPopup(
                    `<b>⚠️ ALTERNATIVE APPROACH</b><br>` +
                    `Route to hazard zone<br>` +
                    `<span style="font-size:11px;color:#94A3B8;">Distance: ${distKm} km · ~${timeMin} min</span>`
                );
                lineStore.push(altLine);
            }

            // Draw MAIN hazard route on top (red, thick)
            const mainLine = L.polyline(routes[0].coords, {
                color: '#EF4444',    // Red
                weight: 5,
                dashArray: '8,6',
                opacity: 0.9
            }).addTo(map);
            const mainDistKm = (routes[0].distance / 1000).toFixed(1);
            mainLine.bindPopup(
                `<b>🔴 MAIN HAZARD ROUTE</b><br>` +
                `🚧 ${ri.issue_type.toUpperCase()} — Severity ${ri.severity}/5<br>` +
                `<span style="font-size:11px;color:#94A3B8;">${ri.from_dustbin} → ${ri.to_dustbin} · ${mainDistKm} km</span>`
            );
            lineStore.push(mainLine);
        });
    }
}

// Track road issue state for smart redraw
let lastRoadHash = '';
let lastFullRoadHash = '';
let lastRoadDrawTime = 0;
const ROAD_REDRAW_INTERVAL = 10000; // Retry every 10s if routes not cached

function getRoadHash(roadIssues) {
    return (roadIssues || []).map(r => r.event_id).sort().join(',');
}

function allRoutesCached(roadIssues) {
    return (roadIssues || []).every(ri => {
        const key = `multi-${ri.from_lat},${ri.from_lng}-${ri.to_lat},${ri.to_lng}`;
        return multiRouteCache[key];
    });
}

function updateDashMap() {
    if (!dashboard) return;
    updateMarkers(markers, dashboard.dustbin_states || []);

    const newHash = getRoadHash(dashboard.road_issues);
    const now = Date.now();
    const needsRetry = !allRoutesCached(dashboard.road_issues) && (now - lastRoadDrawTime > ROAD_REDRAW_INTERVAL);

    if (newHash !== lastRoadHash || needsRetry) {
        lastRoadHash = newHash;
        lastRoadDrawTime = now;
        drawRoadLines(dashMap, roadLines, dashboard.road_issues);
    }
}

function updateFullMap() {
    if (!dashboard || !fullMap) return;
    updateMarkers(fullMarkers, dashboard.dustbin_states || []);

    const newHash = getRoadHash(dashboard.road_issues);
    const now = Date.now();
    const needsRetry = !allRoutesCached(dashboard.road_issues) && (now - lastRoadDrawTime > ROAD_REDRAW_INTERVAL);

    if (newHash !== lastFullRoadHash || needsRetry) {
        lastFullRoadHash = newHash;
        drawRoadLines(fullMap, fullRoadLines, dashboard.road_issues);
    }
}

// ── STATS BAR ───────────────────────────────────────────────────────
function updateStatsBar() {
    if (!dashboard) return;

    const states = dashboard.dustbin_states || [];
    const total = states.length || 72;
    const overflowing = states.filter(d =>
        d.state === 'Critical' || d.state === 'Escalated'
    ).length;
    const clear = states.filter(d => d.state === 'Clear').length;
    const collectionRate = total > 0 ? Math.round((clear / total) * 100) : 0;

    document.getElementById('statTotalBins').textContent = total;
    document.getElementById('statOverflowing').textContent = overflowing;
    document.getElementById('statCollection').textContent = `${collectionRate}%`;
    document.getElementById('statBar').style.width = `${collectionRate}%`;

    // Truck count from van events
    const trucks = dashboard.active_vans || 0;
    document.getElementById('statTrucks').textContent = trucks;
}

// ── DASHBOARD PANELS ────────────────────────────────────────────────
function updateWardStatusPanel() {
    const container = document.getElementById('wardStatusList');
    const wards = dashboard?.ward_risks || [];
    if (!wards.length) { container.innerHTML = '<div class="recent-empty">No ward data yet</div>'; return; }

    container.innerHTML = [...wards].sort((a, b) => b.risk_score - a.risk_score).map(w => `
        <div class="ward-item">
            <span>${w.name} <span style="color:var(--text-muted);font-size:10px;">(${w.ward_id})</span></span>
            <span class="ward-score" style="color:${w.color}">${w.risk_score}</span>
        </div>
    `).join('');
}

function updateRoadAlertsPanel() {
    const container = document.getElementById('roadAlertsList');
    const roads = dashboard?.road_issues || [];
    if (!roads.length) { container.innerHTML = '<div class="recent-empty">No active road alerts</div>'; return; }

    container.innerHTML = roads.map(ri => `
        <div class="alert-item">
            <span class="alert-icon">🚧</span>
            <div class="alert-info">
                <div class="alert-name">${ri.issue_type?.toUpperCase() || 'UNKNOWN'}</div>
                <div class="alert-sub">${ri.from_dustbin} → ${ri.to_dustbin} · Severity ${ri.severity}/5</div>
            </div>
        </div>
    `).join('');
}

function updateAlertBadge() {
    const count = (dashboard?.priority_queue || []).length;
    const badge = document.getElementById('alertBadge');
    badge.textContent = count;
    badge.style.display = count > 0 ? 'inline' : 'none';
}

// ── WARD ANALYTICS PAGE ─────────────────────────────────────────────
function renderAnalyticsPage() {
    const grid = document.getElementById('analyticsGrid');
    const wards = dashboard?.ward_risks || [];
    if (!wards.length) { grid.innerHTML = '<div class="reports-empty">No analytics data yet. Submit reports to generate ward-level data.</div>'; return; }

    grid.innerHTML = [...wards].sort((a, b) => b.risk_score - a.risk_score).map(w => {
        const barColor = w.risk_score >= 60 ? 'var(--danger)' : w.risk_score >= 30 ? 'var(--warning)' : 'var(--success)';
        return `
            <div class="analytics-card">
                <div class="analytics-card-header">
                    <span class="analytics-ward-name">${w.name}</span>
                    <span class="analytics-score" style="color:${w.color};background:${w.color}15;">${w.risk_score}</span>
                </div>
                <div style="font-size:11px;color:var(--text-secondary);">${w.ward_id} · ${w.dustbin_count || 6} dustbins</div>
                <div class="analytics-bar">
                    <div class="analytics-bar-fill" style="width:${w.risk_score}%;background:${barColor};"></div>
                </div>
                <div class="analytics-meta">
                    <span>Risk Level: ${w.risk_score >= 60 ? '🔴 Critical' : w.risk_score >= 30 ? '🟡 Elevated' : '🟢 Normal'}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ── ALERTS PAGE ─────────────────────────────────────────────────────
function renderAlertsPage() {
    const container = document.getElementById('alertsContainer');
    const queue = dashboard?.priority_queue || [];
    if (!queue.length) { container.innerHTML = '<div class="reports-empty">No active alerts. System is operating normally.</div>'; return; }

    container.innerHTML = queue.map((q, i) => {
        const iconBg = q.type === 'waste' ? `${q.color}20` : '#FFEDD5';
        return `
            <div class="alert-card" style="border-left:4px solid ${q.color};cursor:pointer;" onclick='zoomToAlert(${JSON.stringify(q)})'>
                <div class="alert-card-rank">#${i + 1}</div>
                <div class="alert-card-icon" style="background:${iconBg};">
                    ${q.type === 'waste' ? '🗑️' : '🚧'}
                </div>
                <div class="alert-card-info">
                    <div class="alert-card-name">${q.name}</div>
                    <div class="alert-card-sub">${q.state} · ${q.ward_id} · <span style="color:var(--accent);font-weight:700;">↗ CLICK TO LOCATE</span></div>
                </div>
                <div class="alert-card-score" style="color:${q.color};">${q.risk_score}</div>
            </div>
        `;
    }).join('');
}

let citizenHighlightLine = null;  // Track active highlight on citizen map

function zoomToAlert(item) {
    // Switch to Dashboard and zoom the map
    switchSection('dashboard');

    setTimeout(() => {
        if (!dashMap) return;

        // Remove previous highlight
        if (citizenHighlightLine) { dashMap.removeLayer(citizenHighlightLine); citizenHighlightLine = null; }

        if (item.type === 'waste') {
            // Zoom to the dustbin marker
            const info = configData?.dustbins[item.id];
            if (!info) return;

            dashMap.flyTo([info.lat, info.lng], 17, { duration: 1.2 });

            // Flash the marker white → then revert
            const marker = markers[item.id];
            if (marker) {
                const flashIcon = L.divIcon({
                    className: '',
                    html: `<div class="marker-icon marker-xl" style="background:#fff;box-shadow:0 0 24px rgba(255,255,255,0.9);">🗑️</div>`,
                    iconSize: [42, 42], iconAnchor: [21, 21], popupAnchor: [0, -21]
                });
                marker.setIcon(flashIcon);
                marker.openPopup();
                setTimeout(() => {
                    const stateClass = getMarkerStateClass(item.state);
                    marker.setIcon(createDivIcon(stateClass, 'marker-lg'));
                }, 2000);
            }
        } else if (item.type === 'road') {
            // Look up the full road_issue data from dashboard (has coordinates)
            const roadIssues = dashboard?.road_issues || [];
            const ri = roadIssues.find(r => r.event_id === item.id);

            if (!ri) {
                // Fallback: zoom to ward center
                const wardInfo = configData?.wards?.[item.ward_id];
                if (wardInfo) dashMap.flyTo([wardInfo.lat, wardInfo.lng], 15, { duration: 1.2 });
                return;
            }

            // Zoom to fit both dustbin endpoints
            const bounds = L.latLngBounds(
                [ri.from_lat, ri.from_lng],
                [ri.to_lat, ri.to_lng]
            );
            dashMap.flyToBounds(bounds.pad(0.3), { duration: 1.2 });

            // Draw OSRM-routed highlight line (gold, thick, pulsing)
            fetchRoadPath(ri).then(coords => {
                if (citizenHighlightLine) dashMap.removeLayer(citizenHighlightLine);
                citizenHighlightLine = L.polyline(coords, {
                    color: '#FFD700', weight: 8, opacity: 1, dashArray: null
                }).addTo(dashMap);
                citizenHighlightLine.bindPopup(
                    `<b>🎯 SELECTED: ${ri.issue_type.toUpperCase()}</b><br>Severity: ${ri.severity}/5`
                ).openPopup();

                // Fade to normal orange after 5 seconds
                setTimeout(() => {
                    if (citizenHighlightLine) {
                        citizenHighlightLine.setStyle({ color: '#EA580C', weight: 5, opacity: 0.85, dashArray: '6,6' });
                    }
                }, 5000);
            });
        }
    }, 250);
}

// ── ROUTE PLANNER PAGE ──────────────────────────────────────────────
function renderRoutePage() {
    const stopsContainer = document.getElementById('routeStops');
    const statsContainer = document.getElementById('routeStats');
    const queue = (dashboard?.priority_queue || []).filter(q => q.type === 'waste');

    if (!queue.length) {
        stopsContainer.innerHTML = '<div class="recent-empty">No priority stops to route.</div>';
        statsContainer.innerHTML = '';
        return;
    }

    const topStops = queue.slice(0, 8);
    stopsContainer.innerHTML = topStops.map((q, i) => `
        <div class="route-stop">
            <div class="route-stop-num">${i + 1}</div>
            <div style="flex:1;">
                <div style="font-weight:600;">${q.id}</div>
                <div style="font-size:10px;color:var(--text-muted);">${q.ward_id} · ${q.state}</div>
            </div>
            <span style="font-weight:700;color:${q.color};">${q.risk_score}</span>
        </div>
    `).join('');

    statsContainer.innerHTML = `
        <div style="font-weight:600;margin-bottom:8px;">Route Summary</div>
        <div>Priority Stops: <strong>${topStops.length}</strong></div>
        <div>Estimated Time: <strong>${topStops.length * 8} min</strong></div>
        <div>Coverage: <strong>${new Set(topStops.map(q => q.ward_id)).size} wards</strong></div>
    `;

    // Draw route on map
    if (routeMap) {
        routeLines.forEach(l => routeMap.removeLayer(l));
        routeLines = [];

        // Connect stops with OSRM-routed lines
        for (let i = 0; i < topStops.length - 1; i++) {
            const fromInfo = configData?.dustbins[topStops[i].id];
            const toInfo = configData?.dustbins[topStops[i + 1].id];
            if (!fromInfo || !toInfo) continue;

            const ri = { from_lat: fromInfo.lat, from_lng: fromInfo.lng, to_lat: toInfo.lat, to_lng: toInfo.lng };
            fetchRoadPath(ri).then(coords => {
                const line = L.polyline(coords, {
                    color: '#2563EB', weight: 4, opacity: 0.9
                }).addTo(routeMap);
                routeLines.push(line);
            });
        }

        // Zoom to fit all stops
        const stopCoords = topStops
            .map(q => configData?.dustbins[q.id])
            .filter(Boolean)
            .map(d => [d.lat, d.lng]);
        if (stopCoords.length > 1) {
            routeMap.flyToBounds(L.latLngBounds(stopCoords).pad(0.2));
        }
    }
}

// Wire generate route button
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('btnGenerateRoute');
    if (btn) btn.addEventListener('click', renderRoutePage);
});

// ── REPORT FLOW ─────────────────────────────────────────────────────
function initReportFlow() {
    const photoInput = document.getElementById('photoInput');
    const photoPreview = document.getElementById('photoPreview');
    const btnDetect = document.getElementById('btnDetect');
    const btnManual = document.getElementById('btnManual');
    const uploadZone = document.getElementById('uploadZone');

    // File handling
    const handleFile = (f) => {
        if (!f) return;
        const reader = new FileReader();
        reader.onload = (e) => {
            photoPreview.src = e.target.result;
            photoPreview.classList.remove('hidden');
            uploadZone.style.display = 'none';
        };
        reader.readAsDataURL(f);
    };

    uploadZone.addEventListener('click', () => photoInput.click());
    photoInput.addEventListener('change', () => handleFile(photoInput.files[0]));

    // Drag and drop
    uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.style.borderColor = 'var(--accent)'; });
    uploadZone.addEventListener('dragleave', () => { uploadZone.style.borderColor = 'var(--border)'; });
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.style.borderColor = 'var(--border)';
        if (e.dataTransfer.files.length) {
            photoInput.files = e.dataTransfer.files;
            handleFile(e.dataTransfer.files[0]);
        }
    });

    // AI Detection
    btnDetect.addEventListener('click', async () => {
        if (!photoInput.files.length) { showToast('Upload a photo first.', 'error'); return; }

        btnDetect.disabled = true;
        btnDetect.innerHTML = '<span class="btn-icon">⏳</span> Detecting...';

        try {
            const formData = new FormData();
            formData.append('file', photoInput.files[0]);
            const resp = await fetch(`${API_BASE}/api/report/dustbin/detect`, { method: 'POST', body: formData });
            const data = await resp.json();

            if (data.dustbin_id) {
                detectedDustbinId = data.dustbin_id;
                document.getElementById('detectedId').textContent = data.dustbin_id;
                document.getElementById('detectedStreet').textContent = data.street || '';
                document.getElementById('detectionResult').classList.remove('hidden');
            } else {
                showToast(data.message || 'Detection failed. Try manual.', 'error');
            }
        } catch (e) {
            showToast('Detection failed. Try manual.', 'error');
        }

        btnDetect.disabled = false;
        btnDetect.innerHTML = '<span class="btn-icon">🔍</span> Extract Nearest ID';
    });

    // Manual mode
    btnManual.addEventListener('click', () => {
        document.getElementById('manualForm').classList.toggle('hidden');
    });

    // Overflow selectors
    document.getElementById('overflowGrid').addEventListener('click', (e) => {
        if (!e.target.classList.contains('ov-btn')) return;
        document.querySelectorAll('#overflowGrid .ov-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        selectedOverflow = parseInt(e.target.dataset.val);
    });

    document.getElementById('manualOverflowGrid').addEventListener('click', (e) => {
        if (!e.target.classList.contains('ov-btn')) return;
        document.querySelectorAll('#manualOverflowGrid .ov-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        manualSelectedOverflow = parseInt(e.target.dataset.val);
    });

    // Confirm AI detection
    document.getElementById('btnConfirm').addEventListener('click', async () => {
        if (!detectedDustbinId) return;
        await submitReport(detectedDustbinId, selectedOverflow);
    });

    // Submit manual report
    document.getElementById('btnManualSubmit').addEventListener('click', async () => {
        const did = document.getElementById('manualDustbin').value;
        if (!did) { showToast('Select a dustbin.', 'error'); return; }
        await submitReport(did, manualSelectedOverflow);
    });
}

async function submitReport(dustbinId, overflow) {
    try {
        const resp = await fetch(`${API_BASE}/api/report/dustbin/confirm`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dustbin_id: dustbinId, overflow_level: overflow })
        });

        if (resp.ok) {
            showToast(`Report submitted for ${dustbinId}!`, 'success');
            addRecentReport(dustbinId);

            // Reset form
            document.getElementById('detectionResult').classList.add('hidden');
            document.getElementById('photoPreview').classList.add('hidden');
            document.getElementById('uploadZone').style.display = '';
            detectedDustbinId = null;
        } else {
            const err = await resp.json();
            showToast(err.detail || 'Submission failed.', 'error');
        }
    } catch (e) {
        showToast('Network error.', 'error');
    }
}

function addRecentReport(dustbinId) {
    const info = configData?.dustbins[dustbinId];
    recentReports.unshift({
        id: dustbinId,
        street: info?.street || '',
        time: new Date().toLocaleTimeString(),
        status: 'Reported'
    });

    const list = document.getElementById('recentList');
    list.innerHTML = recentReports.slice(0, 5).map(r => `
        <div class="recent-item">
            <div class="recent-thumb">🗑️</div>
            <div class="recent-info">
                <div class="recent-id">${r.id}</div>
                <div class="recent-street">${r.street} · ${r.time}</div>
            </div>
            <span class="recent-status" style="background:#DBEAFE;color:#1E40AF;">● ${r.status}</span>
        </div>
    `).join('');
}

// ── LIVE EVENT STREAMING ENGINE ─────────────────────────────────────
let previousState = null;      // Previous WebSocket snapshot for diffing
let liveEvents = [];           // All detected events
const MAX_FEED_EVENTS = 50;    // Keep last 50 events in memory

function detectStateChanges(newDashboard) {
    if (!previousState) return; // First message — no diff possible

    const events = [];
    const now = new Date().toLocaleTimeString();

    // ── DUSTBIN STATE CHANGES ─────────────────────────────────────────
    const prevStates = {};
    for (const ds of (previousState.dustbin_states || [])) {
        prevStates[ds.dustbin_id] = ds;
    }

    for (const ds of (newDashboard.dustbin_states || [])) {
        const prev = prevStates[ds.dustbin_id];
        if (!prev) continue;

        // Escalation detection
        if (prev.state !== ds.state) {
            const severity = { 'Clear': 0, 'Reported': 1, 'Escalated': 2, 'Critical': 3 };
            const prevSev = severity[prev.state] ?? 0;
            const newSev = severity[ds.state] ?? 0;

            if (newSev > prevSev) {
                // Escalated UP
                const isCritical = ds.state === 'Critical';
                events.push({
                    type: isCritical ? 'critical' : 'warning',
                    icon: isCritical ? '🔴' : '🟡',
                    text: `${ds.dustbin_id} escalated to ${ds.state.toUpperCase()}! ${ds.report_count} reports on ${ds.street}`,
                    time: now,
                    pushTitle: isCritical ? '🚨 CRITICAL ALERT' : '⚠️ Escalation',
                    pushBody: `${ds.dustbin_id} (${ds.street}) is now ${ds.state}`,
                    priority: isCritical ? 3 : 2
                });
            } else if (newSev < prevSev) {
                // De-escalated (collection happened)
                events.push({
                    type: 'success',
                    icon: '✅',
                    text: `${ds.dustbin_id} resolved → ${ds.state}. Collection complete on ${ds.street}`,
                    time: now,
                    pushTitle: '✅ Area Cleared',
                    pushBody: `${ds.dustbin_id} (${ds.street}) has been collected`,
                    priority: 1
                });
            }
        }

        // New reports detected
        if (ds.report_count > (prev.report_count || 0)) {
            const newCount = ds.report_count - (prev.report_count || 0);
            events.push({
                type: 'info',
                icon: '📢',
                text: `${newCount} new civic report${newCount > 1 ? 's' : ''} for ${ds.dustbin_id} on ${ds.street}`,
                time: now,
                priority: 1
            });
        }
    }

    // ── NEW ROAD ISSUES ───────────────────────────────────────────────
    const prevRoadIds = new Set((previousState.road_issues || []).map(r => r.event_id));
    for (const ri of (newDashboard.road_issues || [])) {
        if (!prevRoadIds.has(ri.event_id)) {
            events.push({
                type: 'road',
                icon: '🚧',
                text: `New ${ri.issue_type} reported: ${ri.from_dustbin} → ${ri.to_dustbin} (Severity ${ri.severity}/5)`,
                time: now,
                pushTitle: '🚧 Road Hazard Alert',
                pushBody: `${ri.issue_type}: ${ri.from_dustbin} → ${ri.to_dustbin}`,
                priority: 2
            });
        }
    }

    return events;
}

function addFeedEvent(event) {
    liveEvents.unshift(event);
    if (liveEvents.length > MAX_FEED_EVENTS) liveEvents.pop();

    const feed = document.getElementById('liveFeed');
    if (!feed) return;

    // Remove empty placeholder
    const empty = feed.querySelector('.feed-empty');
    if (empty) empty.remove();

    // Create event card
    const el = document.createElement('div');
    el.className = `feed-event ${event.type}`;
    el.innerHTML = `
        <span class="feed-event-icon">${event.icon}</span>
        <div class="feed-event-body">
            <div class="feed-event-text">${event.text}</div>
            <div class="feed-event-time">${event.time}</div>
        </div>
    `;

    // Prepend (newest first)
    feed.prepend(el);

    // Trim old events from DOM
    while (feed.children.length > MAX_FEED_EVENTS) {
        feed.lastChild.remove();
    }

    // Update count
    const countEl = document.getElementById('feedCount');
    if (countEl) countEl.textContent = `${liveEvents.length} events`;
}

function firePushNotification(event) {
    // In-app push toast (always works)
    const toast = document.createElement('div');
    toast.className = 'push-toast';
    toast.innerHTML = `
        <span class="push-icon">${event.icon}</span>
        <div class="push-body">
            <div class="push-title">${event.pushTitle || 'InfraWatch Alert'}</div>
            <div class="push-msg">${event.pushBody || event.text}</div>
        </div>
        <button class="push-close" onclick="this.parentElement.remove()">✕</button>
    `;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 6000);

    // Browser native push notification (works even when tab is minimized)
    if ('Notification' in window && Notification.permission === 'granted') {
        try {
            const notif = new Notification(event.pushTitle || 'InfraWatch Alert', {
                body: event.pushBody || event.text,
                icon: '⚡',
                badge: '⚡',
                tag: `infrawatch-${Date.now()}`,
                requireInteraction: event.priority >= 3
            });
            notif.onclick = () => { window.focus(); notif.close(); };
        } catch (e) { /* Silent fail for unsupported contexts */ }
    }
}

function processStateChanges(newDashboard) {
    const events = detectStateChanges(newDashboard);
    if (!events || events.length === 0) return;

    for (const event of events) {
        addFeedEvent(event);

        // Fire push notification for important events (priority >= 2)
        if (event.priority >= 2 && event.pushTitle) {
            firePushNotification(event);
        }
    }

    // Update alert badge with new event count
    updateAlertBadge();
}

// ── WEBSOCKET ───────────────────────────────────────────────────────
function connectWebSocket() {
    const statusEl = document.getElementById('wsStatus');
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        statusEl.textContent = '● Live';
        statusEl.className = 'status-badge live';
        const diagEl = document.getElementById('settingsWsStatus');
        if (diagEl) diagEl.textContent = 'Connected';

        // Auto-request notification permission on first connect
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }
    };

    ws.onmessage = (event) => {
        const newDashboard = JSON.parse(event.data);

        // ── STATE CHANGE DETECTION (the Uber magic) ──────────────────
        processStateChanges(newDashboard);
        previousState = JSON.parse(JSON.stringify(newDashboard)); // Deep clone for next diff
        dashboard = newDashboard;

        // Update topbar
        document.getElementById('rainBadge').textContent = `🌧 ${dashboard.rainfall_mm_hr || 0}mm`;
        document.getElementById('wasteIndex').textContent = `Waste: ${dashboard.city_waste_index || 0}`;

        // Update all active views
        updateDashMap();
        updateStatsBar();
        updateWardStatusPanel();
        updateRoadAlertsPanel();
        updateAlertBadge();

        // Update full map if it exists
        if (fullMap) updateFullMap();

        // Update settings diagnostics
        const lastEl = document.getElementById('settingsLastUpdate');
        if (lastEl) lastEl.textContent = new Date().toLocaleTimeString();
    };

    ws.onclose = () => {
        statusEl.textContent = '● Offline';
        statusEl.className = 'status-badge dead';
        setTimeout(connectWebSocket, 4000);
    };

    ws.onerror = () => ws.close();
}

// ── SETTINGS HELPERS ────────────────────────────────────────────────
function changeMapTheme(theme) {
    const tileUrl = theme === 'light'
        ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
        : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';

    [dashMap, fullMap, routeMap].forEach(map => {
        if (!map) return;
        map.eachLayer(layer => {
            if (layer instanceof L.TileLayer) map.removeLayer(layer);
        });
        L.tileLayer(tileUrl, { attribution: '© CARTO', maxZoom: 19 }).addTo(map);
    });

    showToast(`Map theme set to ${theme} mode.`, 'success');
}

function requestNotifPermission() {
    if ('Notification' in window) {
        Notification.requestPermission().then(perm => {
            showToast(perm === 'granted' ? 'Notifications enabled!' : 'Notifications blocked.', perm === 'granted' ? 'success' : 'error');
        });
    } else {
        showToast('Notifications not supported in this browser.', 'error');
    }
}

// ── TOAST ───────────────────────────────────────────────────────────
function showToast(msg, type = 'info') {
    const c = document.getElementById('toastContainer');
    const t = document.createElement('div');
    t.className = 'toast';
    const color = type === 'error' ? 'var(--danger)' : 'var(--success)';
    t.innerHTML = `<span style="color: ${color}; font-weight: 800; margin-right: 8px;">${type === 'error' ? '✗' : '✓'}</span> ${msg}`;
    if (type === 'error') t.style.borderLeft = '4px solid var(--danger)';
    if (type === 'success') t.style.borderLeft = '4px solid var(--success)';
    c.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}
