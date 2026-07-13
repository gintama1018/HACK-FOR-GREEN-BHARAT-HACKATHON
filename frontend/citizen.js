/**
 * InfraWatch Nexus — Citizens' Portal Logic (SPA Edition)
 * Multi-section dashboard with single persistent WebSocket connection.
 */

// ═══════════════════════════════════════════════════════════════════════════
// AUTH0 MODULE
// ═══════════════════════════════════════════════════════════════════════════
let _auth0Client = null;
let _authUser    = null;   // {name, email, picture, sub}
let _authToken   = null;   // access_token (in memory only — never localStorage)

async function _initAuth0() {
    if (typeof auth0 === 'undefined') {
        console.warn('[Auth0] SDK not loaded, running in offline mode.');
        return;
    }
    try {
        _auth0Client = await auth0.createAuth0Client({
            domain:        'dev-kklommsgij3qgkij.us.auth0.com',
            clientId:      'JUpaLQX0981B0A1FL4yQA7dFUHImqbPU',
            authorizationParams: { audience: 'https://infrawatch-nexus-api', scope: 'openid profile email' },
            cacheLocation: 'memory',
            useRefreshTokens: true,
        });
        if (location.search.includes('code=') && location.search.includes('state=')) {
            await _auth0Client.handleRedirectCallback();
            history.replaceState({}, document.title, location.pathname + location.hash);
        }
        const isAuth = await _auth0Client.isAuthenticated();
        if (isAuth) {
            _authUser  = await _auth0Client.getUser();
            _authToken = await _auth0Client.getTokenSilently({
                authorizationParams: { audience: 'https://infrawatch-nexus-api', scope: 'openid profile email' }
            });
            _renderAuthBtn(true);
        }
    } catch (e) {
        console.warn('[Auth0] Init failed (offline mode):', e.message);
    }
}

function _renderAuthBtn(loggedIn) {
    const btn = document.getElementById('authBtn');
    if (!btn) return;
    if (loggedIn && _authUser) {
        const name = _authUser.name || _authUser.email || 'User';
        const pic  = _authUser.picture
            ? `<img src="${_authUser.picture}" style="width:22px;height:22px;border-radius:50%;object-fit:cover;" />`
            : '\u{1F464}';
        btn.innerHTML = `${pic} ${name.split(' ')[0]}`;
        btn.style.background = 'linear-gradient(135deg,#6366F1,#8B5CF6)';
        btn.title = 'Logged in — Click to logout';
    } else {
        btn.innerHTML = '\u{1F464} Login';
        btn.style.background = '#0F172A';
        btn.title = 'Login with Auth0';
    }
    // Notify all listeners that auth state changed
    window.dispatchEvent(new CustomEvent('infrawatch:auth', { detail: { loggedIn: loggedIn } }));
}

async function handleAuthClick() {
    if (!_auth0Client) { alert('Auth0 not loaded yet. Please refresh.'); return; }
    const isAuth = await _auth0Client.isAuthenticated();
    if (isAuth) {
        _authUser  = null;
        _authToken = null;
        _renderAuthBtn(false);
        await _auth0Client.logout({ logoutParams: { returnTo: location.origin } });
    } else {
        await _auth0Client.loginWithRedirect({ authorizationParams: { redirect_uri: location.origin } });
    }
}

async function _authHeaders() {
    if (!_auth0Client) return {};
    try {
        _authToken = await _auth0Client.getTokenSilently({
            authorizationParams: { audience: 'https://infrawatch-nexus-api', scope: 'openid profile email' }
        });
        console.log('[Auth] Token obtained, length:', _authToken ? _authToken.length : 0);
        return { 'Authorization': 'Bearer ' + _authToken };
    } catch (e) {
        const errorMsg = e.message || e.error || e;
        // Suppress expected warnings for unauthenticated users
        if (!errorMsg.includes('Missing Refresh Token') && 
            !errorMsg.includes('login_required') && 
            !errorMsg.includes('consent_required')) {
            console.warn('[Auth] getTokenSilently failed:', errorMsg);
        }
        
        // if (e.error === 'login_required' || e.error === 'consent_required') {
        //     await _auth0Client.loginWithRedirect({ authorizationParams: { redirect_uri: location.origin } });
        // }
        return {};
    }
}

window.addEventListener('DOMContentLoaded', _initAuth0);

// ═══════════════════════════════════════════════════════════════════════════

const API_BASE = window.location.origin;
const WS_SCHEME = window.location.protocol === 'https:' ? 'wss' : 'ws';
const WS_URL = `${WS_SCHEME}://${window.location.host}/ws`;

let dashboard = null;
let _dashboardLastFetch = 0;
let _httpPollTimer = null;

async function _fetchDashboardFallback() {
    const now = Date.now();
    if (now - _dashboardLastFetch < 5000) return;
    _dashboardLastFetch = now;
    try {
        const resp = await fetch(`${API_BASE}/api/dashboard`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data || !data.timestamp) return;
        if (!dashboard || !dashboard.timestamp || data.timestamp > dashboard.timestamp) {
            dashboard = data;
            updateWardStatusPanel();
            updateRoadAlertsPanel();
            updateAlertBadge();
            updateStatsBar();
        }
    } catch (e) {
        console.warn('[HTTP fallback] Dashboard fetch failed:', e.message);
    }
}

function _startHttpPolling() {
    if (_httpPollTimer) return;
    _httpPollTimer = setInterval(_fetchDashboardFallback, 10000);
}

function _stopHttpPolling() {
    if (_httpPollTimer) { clearInterval(_httpPollTimer); _httpPollTimer = null; }
}

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
let detectedPhotoUrl  = null;  // Vultr Object Storage URL from detect step
let _yoloData         = null;  // YOLO waste detection result
let selectedOverflow = 3;
let manualSelectedOverflow = 3;

// Recent reports tracker
let recentReports = [];

// ── ROUTE CACHING + MARKER HELPERS ─────────────────────────────────
// Provided by shared.js (loaded before this file):
//   - InfraRoute.fetchRoadPath(ri), InfraRoute.fetchMultiRoutes(ri)
//   - getMarkerStateClass(state), getMarkerSize(state), createDivIcon(stateClass, sizeClass)
//   - formatDistance(m), formatDuration(s), stateColor(state)
// Legacy wrappers for backward compatibility with inline calls:
const routeCache = {};
const multiRouteCache = {};
async function fetchMultiRoutes(ri) { return InfraRoute.fetchMultiRoutes(ri); }
async function fetchRoadPath(ri) { return InfraRoute.fetchRoadPath(ri); }

// ── INIT ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    initDashMap();
    initReportFlow();
    initSearch();
    connectWebSocket();
    setTimeout(_fetchDashboardFallback, 800); // Seed data before first WS message
});

// ── CONFIG ──────────────────────────────────────────────────────────
async function loadConfig() {
    try {
        const authHdr = await _authHeaders();
        const resp = await fetch(`${API_BASE}/api/config`, { headers: authHdr });
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

        // QR pre-fill: if page opened via /report?bin=MCD-DL-XXXX
        const _prefillBin = window._QR_PREFILL_BIN;
        if (_prefillBin && configData.dustbins[_prefillBin]) {
            const binInfo = configData.dustbins[_prefillBin];
            // 1. Set ward (triggers the change event which populates bin dropdown)
            manualWard.value = binInfo.ward_id;
            manualWard.dispatchEvent(new Event('change'));
            // 2. Set bin
            const binSel = document.getElementById('manualDustbin');
            binSel.value = _prefillBin;
            // 3. Switch to report tab and scroll panel into view
            switchSection('dashboard');
            setTimeout(() => {
                const ptab = document.querySelector('[data-ptab="ptab-report"]');
                if (ptab) switchPanelTab(ptab);
                const ovGrid = document.getElementById('manualOverflowGrid');
                if (ovGrid) ovGrid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                showToast('\u2705 QR स्कैन सफल — ' + _prefillBin + ' चुना गया', 'success');
            }, 300);
        }
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

    // Update bottom nav active state (mobile)
    document.querySelectorAll('.bottom-nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.section === name);
    });

    // Show/hide content sections
    document.querySelectorAll('.content-section').forEach(sec => {
        sec.classList.toggle('active', sec.id === `section-${name}`);
    });

    // Close mobile sidebar when navigating
    if (window.innerWidth <= 768) {
        closeSidebar();
    }

    // Initialize section-specific maps on first visit
    if (name === 'citymap' && !fullMap) {
        setTimeout(() => initFullMap(), 100);
    }

    // Invalidate map size when switching (Leaflet needs this)
    setTimeout(() => {
        if (name === 'dashboard' && dashMap) dashMap.invalidateSize();
        if (name === 'citymap' && fullMap) fullMap.invalidateSize();
    }, 150);

    // Render section data
    if (name === 'analytics') renderAnalyticsPage();
    if (name === 'alerts') renderAlertsPage();
}

// ── MOBILE QUICK REPORT ──────────────────────────────────────────────
function quickReport() {
    // On mobile, scroll to report form on dashboard
    if (window.innerWidth <= 768) {
        switchSection('dashboard');
        setTimeout(() => {
            const reportPanel = document.getElementById('ptab-report');
            if (reportPanel) {
                reportPanel.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }, 100);
    } else {
        // Desktop: open sidebar
        switchSection('dashboard');
    }
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

async function drawRoadLines(map, lineStore, roadIssues) {
    lineStore.forEach(l => map.removeLayer(l));
    lineStore.length = 0;

    for (const ri of (roadIssues || [])) {
        // Sleep to respect OSRM public API rate limits (avoid timeouts)
        await new Promise(r => setTimeout(r, 200));
        
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
        d.state === 'Critical' || d.state === 'Escalated' || d.state === 'Reported'
    ).length;
    const critical = states.filter(d => d.state === 'Critical').length;
    const clear = states.filter(d => d.state === 'Clear').length;
    const collectionRate = total > 0 ? Math.round((clear / total) * 100) : 0;

    document.getElementById('statTotalBins').textContent = total;
    document.getElementById('statOverflowing').textContent = overflowing;
    document.getElementById('statCollection').textContent = `${collectionRate}%`;
    const statBarEl = document.getElementById('statBar');
    if (statBarEl) statBarEl.style.width = `${collectionRate}%`;

    // High priority label
    const hpEl = document.getElementById('statHighPriority');
    if (hpEl) hpEl.textContent = critical > 0 ? `${critical} Critical` : '● High Priority';

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

async function loadLeaderboard() {
    const container = document.getElementById('leaderboardList');
    if (!container) return;
    container.innerHTML = '<div style="color:#64748B;font-size:13px;text-align:center;padding:16px;">Loading...</div>';
    try {
        const resp = await fetch(`${API_BASE}/api/leaderboard`);
        if (!resp.ok) throw new Error('Failed');
        const data = await resp.json();
        const leaders = data.leaderboard || [];
        if (!leaders.length) {
            container.innerHTML = '<div style="color:#64748B;font-size:13px;text-align:center;padding:16px;">No reporters yet. Be the first!</div>';
            return;
        }
        const medals = ['\uD83E\uDD47','\uD83E\uDD48','\uD83E\uDD49'];
        container.innerHTML = leaders.map((l, i) => `
            <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;background:${i===0?'rgba(99,102,241,0.08)':'#F8FAFC'};border-radius:12px;border:1px solid ${i===0?'rgba(99,102,241,0.2)':'#E2E8F0'}">
                <span style="font-size:22px;min-width:28px">${medals[i] || `#${i+1}`}</span>
                <div style="flex:1">
                    <div style="font-weight:700;font-size:13px;color:#0F172A">${l.reporter_name || 'Anonymous'}</div>
                    <div style="font-size:11px;color:#64748B">${l.report_count} reports resolved</div>
                </div>
                <div style="text-align:right">
                    <div style="font-weight:800;font-size:14px;color:#6366F1">${l.total_points} pts</div>
                    <div style="font-size:11px;color:#10B981;font-weight:600">\u20B9${l.total_rupees}</div>
                </div>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<div style="color:#64748B;font-size:13px;text-align:center;padding:16px;">Could not load leaderboard.</div>';
    }
}

function updateRoadAlertsPanel() {
    const container = document.getElementById('roadAlertsList');
    const roads = dashboard?.road_issues || [];
    if (!roads.length) { container.innerHTML = '<div class="recent-empty">No active road alerts</div>'; return; }

    container.innerHTML = roads.map(ri => `
        <div class="alert-item" style="cursor:pointer;" onclick='zoomToRoadIssue(${JSON.stringify({ event_id: ri.event_id, from_lat: ri.from_lat, from_lng: ri.from_lng, to_lat: ri.to_lat, to_lng: ri.to_lng, issue_type: ri.issue_type, severity: ri.severity, from_dustbin: ri.from_dustbin, to_dustbin: ri.to_dustbin })})'>
            <span class="alert-icon">🚧</span>
            <div class="alert-info">
                <div class="alert-name">${ri.issue_type?.toUpperCase() || 'UNKNOWN'}</div>
                <div class="alert-sub">${ri.from_dustbin} → ${ri.to_dustbin} · Severity ${ri.severity}/5 · <span style="color:var(--accent);font-weight:700;">↗ LOCATE</span></div>
            </div>
        </div>
    `).join('');
}

function zoomToRoadIssue(ri) {
    // Zoom the dashboard map to this road issue and draw highlight
    if (!dashMap) return;

    // Guard against missing/zero coordinates (dustbin not in registry)
    if (!ri.from_lat || !ri.from_lng || !ri.to_lat || !ri.to_lng) {
        console.warn('[zoomToRoadIssue] Missing coordinates for', ri.event_id);
        return;
    }

    // Remove previous highlight
    if (citizenHighlightLine) { dashMap.removeLayer(citizenHighlightLine); citizenHighlightLine = null; }

    // Zoom to fit both endpoints
    const bounds = L.latLngBounds(
        [ri.from_lat, ri.from_lng],
        [ri.to_lat, ri.to_lng]
    );
    dashMap.flyToBounds(bounds.pad(0.3), { duration: 1.2 });

    // Draw OSRM-routed gold highlight line
    fetchRoadPath(ri).then(coords => {
        if (citizenHighlightLine) dashMap.removeLayer(citizenHighlightLine);
        citizenHighlightLine = L.polyline(coords, {
            color: '#FFD700', weight: 8, opacity: 1, dashArray: null
        }).addTo(dashMap);
        citizenHighlightLine.bindPopup(
            `<b>🎯 SELECTED: ${ri.issue_type.toUpperCase()}</b><br>Severity: ${ri.severity}/5`
        ).openPopup();

        // Fade to normal after 5 seconds
        setTimeout(() => {
            if (citizenHighlightLine) {
                citizenHighlightLine.setStyle({ color: '#EA580C', weight: 5, opacity: 0.85, dashArray: '6,6' });
            }
        }, 5000);
    });
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
// ── SEARCH FUNCTIONALITY ─────────────────────────────────────────────
function initSearch() {
    const searchInput = document.getElementById('searchLocation');
    const datalist = document.getElementById('searchSuggestions');
    if (!searchInput) return;

    // Populate autocomplete suggestions
    if (datalist && configData) {
        let optionsHtml = '';
        for (const [wid, info] of Object.entries(configData.wards)) {
            optionsHtml += `<option value="${info.name} (${wid})"></option>`;
        }
        for (const [did, info] of Object.entries(configData.dustbins)) {
            optionsHtml += `<option value="${did} — ${info.street}"></option>`;
        }
        datalist.innerHTML = optionsHtml;
    }

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            triggerSearch(searchInput.value.trim());
        }
    });

    searchInput.addEventListener('input', () => {
        const val = searchInput.value.trim();
        if (val.includes('(W') || val.includes(' — ')) {
            triggerSearch(val);
        }
    });
}

function triggerSearch(val) {
    if (!val) return;
    let searchVal = val;
    let idMatch = val.match(/\((W\d+)\)/);
    if (idMatch) {
        searchVal = idMatch[1];
    } else {
        let binMatch = val.split(' — ');
        if (binMatch.length > 0) searchVal = binMatch[0].trim();
    }

    const query = searchVal.toLowerCase();

    // 1. Search exact dustbin ID
    const exactBin = Object.keys(configData.dustbins).find(id => id.toLowerCase() === query);
    if (exactBin) {
        const info = configData.dustbins[exactBin];
        dashMap.setView([info.lat, info.lng], 16);
        if (markers[exactBin]) markers[exactBin].openPopup();
        showToast(`📍 Located Dustbin: ${exactBin}`, 'success');
        return;
    }

    // 2. Search exact Ward ID / Name
    const matchingWard = Object.entries(configData.wards).find(([id, info]) => 
        id.toLowerCase() === query || info.name.toLowerCase().includes(query)
    );
    if (matchingWard) {
        const [wid, info] = matchingWard;
        dashMap.setView([info.lat, info.lng], 14);
        showToast(`📍 Centered on Ward: ${info.name}`, 'success');
        return;
    }

    // 3. Search partial dustbin ID or street name
    const partialBin = Object.entries(configData.dustbins).find(([id, info]) => 
        id.toLowerCase().includes(query) || info.street.toLowerCase().includes(query)
    );
    if (partialBin) {
        const [bid, info] = partialBin;
        dashMap.setView([info.lat, info.lng], 16);
        if (markers[bid]) markers[bid].openPopup();
        showToast(`📍 Located Dustbin: ${bid} (${info.street})`, 'success');
        return;
    }

    showToast('No matching dustbin, ward, or street found.', 'error');
}


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
        // Fire YOLO analysis in background immediately after file chosen
        _yoloData = null;
        const badge = document.getElementById('yoloBadge');
        if (badge) { badge.style.display = 'flex'; badge.style.background = '#F1F5F9'; badge.style.color = '#64748B'; badge.innerHTML = '⏳ AI analysing image...'; }
        const fd = new FormData();
        fd.append('file', f);
        fetch(`${API_BASE}/api/report/analyze-waste`, { method: 'POST', body: fd })
            .then(r => r.json())
            .then(d => {
                _yoloData = d;
                // Replace the preview with the annotated (bounding-box) image if available
                if (d.annotated_image && photoPreview) {
                    photoPreview.src = d.annotated_image;
                }
                if (!badge) return;
                if (!d.available) { badge.style.display = 'none'; return; }
                const classesHtml = (d.waste_classes && d.waste_classes.length)
                    ? ` &nbsp;<span style="opacity:0.75;font-size:10px;">🏷 ${d.waste_classes.join(', ')}</span>` : '';
                if (d.waste_detected && d.confidence >= 0.55) {
                    badge.style.cssText = 'display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:10px 14px;border-radius:10px;font-size:12px;font-weight:700;background:#DCFCE7;color:#15803D;margin-bottom:16px;';
                    badge.innerHTML = `🤖 <b>${d.label}</b> &nbsp; <span style="background:#15803D;color:#fff;border-radius:6px;padding:2px 8px;">${Math.round(d.confidence*100)}%</span>${classesHtml}`;
                } else if (d.waste_detected) {
                    badge.style.cssText = 'display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:10px 14px;border-radius:10px;font-size:12px;font-weight:700;background:#FEF9C3;color:#854D0E;margin-bottom:16px;';
                    badge.innerHTML = `🤖 <b>${d.label}</b> &nbsp; <span style="background:#A16207;color:#fff;border-radius:6px;padding:2px 8px;">${Math.round(d.confidence*100)}%</span>${classesHtml}`;
                } else {
                    badge.style.cssText = 'display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:10px;font-size:12px;font-weight:700;background:#FEE2E2;color:#B91C1C;margin-bottom:16px;';
                    badge.innerHTML = `🤖 <b>${d.label}</b> &nbsp; <span style="opacity:0.7;font-size:11px;">Please verify manually</span>`;
                }
            })
            .catch(() => { if (badge) badge.style.display = 'none'; });
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
            const resp = await fetch(`${API_BASE}/api/report/dustbin/detect`, {
                method: 'POST',
                headers: { ...(await _authHeaders()) },  // Auth0 token for user-tagged photo storage
                body: formData
            });
            const data = await resp.json();

            if (data.dustbin_id || data.detected_id) {
                detectedDustbinId = data.dustbin_id || data.detected_id;
                detectedPhotoUrl  = data.photo_url || null;  // Vultr URL (null if no Vultr keys)
                document.getElementById('detectedId').textContent = detectedDustbinId;
                document.getElementById('detectedStreet').textContent = data.street || '';
                document.getElementById('detectionResult').classList.remove('hidden');
                if (detectedPhotoUrl) console.log('[Vultr] Evidence stored:', detectedPhotoUrl);
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
        await submitReport(detectedDustbinId, selectedOverflow, detectedPhotoUrl);
    });

    // Submit manual report
    document.getElementById('btnManualSubmit').addEventListener('click', async () => {
        const did = document.getElementById('manualDustbin').value;
        if (!did) { showToast('Select a dustbin.', 'error'); return; }
        await submitReport(did, manualSelectedOverflow);
    });
}

async function submitReport(dustbinId, overflow, photoUrl) {
    // Get Auth0 token if user is logged in (defined in citizen.js Auth0 module)
    const authHdrs = await _authHeaders();
    try {
        const resp = await fetch(`${API_BASE}/api/report/dustbin/confirm`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHdrs },
            body: JSON.stringify({
                dustbin_id:       dustbinId,
                overflow_level:   overflow,
                photo_url:        photoUrl || null,
                ai_verified:      _yoloData?.waste_detected ?? null,
                yolo_confidence:  _yoloData?.confidence     ?? null,
                detected_objects: _yoloData?.waste_classes  ?? null,
            })
        });

        if (resp.ok) {
            const data = await resp.json();
            showToast(`Report submitted for ${dustbinId}!`, 'success');
            addRecentReport(dustbinId);

            // Reward preview badge for logged-in users
            if (_authUser && data.reward_points) {
                const rewardBadge = document.getElementById('rewardPreviewBadge') || _createRewardBadge();
                rewardBadge.textContent = `🏆 +${data.reward_points} civic points earned when resolved!`;
                rewardBadge.style.display = 'block';
                setTimeout(() => { rewardBadge.style.display = 'none'; }, 6000);
                // Refresh My Rewards card
                _loadMyRewards();
            }

            // ElevenLabs Hindi voice confirmation
            const speakMsg = 'आपकी शिकायत सफलतापूर्वक दर्ज हो गई!';
            if (typeof _aiSpeak === 'function') _aiSpeak(speakMsg);

            // Reset form
            document.getElementById('detectionResult').classList.add('hidden');
            document.getElementById('photoPreview').classList.add('hidden');
            document.getElementById('uploadZone').style.display = '';
            const badge = document.getElementById('yoloBadge');
            if (badge) badge.style.display = 'none';
            detectedDustbinId = null;
            detectedPhotoUrl  = null;
            _yoloData         = null;
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
let seedGenerated = false;     // Track if initial seed events were created
let heartbeatInterval = null;  // Periodic status heartbeat

// Generate initial events from current state on first load
function generateSeedEvents(data) {
    const events = [];
    const now = new Date().toLocaleTimeString();
    const states = data.dustbin_states || [];
    const roads = data.road_issues || [];

    // System boot event
    events.push({
        type: 'info', icon: '⚡',
        text: `InfraWatch connected — Monitoring ${states.length} dustbins across Delhi NCR`,
        time: now, priority: 0
    });

    // Report existing road issues
    for (const ri of roads) {
        events.push({
            type: 'road', icon: '🚧',
            text: `Active ${ri.issue_type}: ${ri.from_dustbin} → ${ri.to_dustbin} (Severity ${ri.severity}/5)`,
            time: now, priority: 1
        });
    }

    // Report critical/escalated dustbins
    const critical = states.filter(d => d.state === 'Critical');
    const escalated = states.filter(d => d.state === 'Escalated');
    const reported = states.filter(d => d.state === 'Reported');

    for (const ds of critical) {
        events.push({
            type: 'critical', icon: '🔴',
            text: `${ds.dustbin_id} is CRITICAL — ${ds.report_count || 0} reports on ${ds.street}`,
            time: now, priority: 3,
            pushTitle: '🚨 CRITICAL ALERT',
            pushBody: `${ds.dustbin_id} (${ds.street}) is Critical`
        });
    }

    for (const ds of escalated) {
        events.push({
            type: 'warning', icon: '🟡',
            text: `${ds.dustbin_id} is ${ds.state} — ${ds.report_count || 0} reports on ${ds.street}`,
            time: now, priority: 2
        });
    }

    if (reported.length > 0) {
        events.push({
            type: 'info', icon: '📢',
            text: `${reported.length} dustbin${reported.length > 1 ? 's' : ''} with pending civic reports`,
            time: now, priority: 1
        });
    }

    // Summary stats
    const clear = states.filter(d => d.state === 'Clear').length;
    const rate = states.length > 0 ? Math.round((clear / states.length) * 100) : 0;
    events.push({
        type: 'success', icon: '📊',
        text: `City collection rate: ${rate}% · ${clear}/${states.length} bins clear · ${roads.length} road alerts active`,
        time: now, priority: 0
    });

    return events;
}

// Periodic heartbeat to show system is alive
function startHeartbeat() {
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    heartbeatInterval = setInterval(() => {
        if (!dashboard) return;
        const now = new Date().toLocaleTimeString();
        const states = dashboard.dustbin_states || [];
        const clear = states.filter(d => d.state === 'Clear').length;
        const critical = states.filter(d => d.state === 'Critical').length;
        const escalated = states.filter(d => d.state === 'Escalated').length;
        const roads = (dashboard.road_issues || []).length;
        const rate = states.length > 0 ? Math.round((clear / states.length) * 100) : 0;

        addFeedEvent({
            type: 'info', icon: '📡',
            text: `System pulse — Collection: ${rate}% · Critical: ${critical} · Escalated: ${escalated} · Road alerts: ${roads}`,
            time: now, priority: 0
        });
    }, 30000); // Every 30 seconds
}

function detectStateChanges(newDashboard) {
    if (!previousState) return []; // First message — handled by seed generator

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
                events.push({
                    type: 'success', icon: '✅',
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
                type: 'info', icon: '📢',
                text: `${newCount} new civic report${newCount > 1 ? 's' : ''} for ${ds.dustbin_id} on ${ds.street}`,
                time: now, priority: 1
            });
        }
    }

    // ── NEW ROAD ISSUES ───────────────────────────────────────────────
    const prevRoadIds = new Set((previousState.road_issues || []).map(r => r.event_id));
    for (const ri of (newDashboard.road_issues || [])) {
        if (!prevRoadIds.has(ri.event_id)) {
            events.push({
                type: 'road', icon: '🚧',
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

    // ElevenLabs proactive voice alert for critical civic events (post-seed only)
    if (event.priority >= 3 && seedGenerated && typeof _aiSpeak === 'function') {
        const parts = event.text.split(' ');
        const binId = parts[0] || 'डस्टबिन';
        _aiSpeak(`चेतावनी! ${binId} क्रिटिकल स्तर पर पहुंच गया। तुरंत कार्रवाई आवश्यक है।`);
    }

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
                tag: `infrawatch-${Date.now()}`,
                requireInteraction: event.priority >= 3
            });
            notif.onclick = () => { window.focus(); notif.close(); };
        } catch (e) { /* Silent fail for unsupported contexts */ }
    }
}

function processStateChanges(newDashboard) {
    // Generate seed events on FIRST WebSocket message
    if (!seedGenerated) {
        seedGenerated = true;
        const seedEvents = generateSeedEvents(newDashboard);
        // Add seed events in reverse so they appear chronologically (oldest first)
        for (const event of seedEvents.reverse()) {
            addFeedEvent(event);
        }
        startHeartbeat();
        updateAlertBadge();
        return;
    }

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
let _wsRetries = 0;  // module-scope: persists across reconnect calls
function connectWebSocket() {
    const statusEl = document.getElementById('wsStatus');

    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        _stopHttpPolling(); // WS is back, stop HTTP polling
        _wsRetries = 0;  // Reset backoff on successful connection
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
        _wsRetries++;
        const delay = Math.min(30000, 1000 * Math.pow(2, _wsRetries)) + Math.random() * 1000;
        setTimeout(connectWebSocket, delay);
        _startHttpPolling(); // WS dropped — begin HTTP polling as fallback
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

// ── MOBILE SIDEBAR TOGGLE ─────────────────────────────────────────────
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    sidebar.classList.toggle('active');
    overlay.classList.toggle('active');
}

function closeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    sidebar.classList.remove('active');
    overlay.classList.remove('active');
}

// Close sidebar when navigating on mobile
document.addEventListener('DOMContentLoaded', function() {
    // Sidebar nav items
    const navItems = document.querySelectorAll('.nav-item[data-section]');
    navItems.forEach(item => {
        item.addEventListener('click', function() {
            if (window.innerWidth <= 768) {
                closeSidebar();
            }
        });
    });

    // Also close when clicking overlay
    const overlay = document.getElementById('sidebarOverlay');
    if (overlay) {
        overlay.addEventListener('click', closeSidebar);
    }
});

// Handle window resize
window.addEventListener('resize', function() {
    if (window.innerWidth > 768) {
        closeSidebar();
    }
});


// ═══════════════════════════════════════════════════════════════════════════
// ELEVENLABS VOICE AI
// ═══════════════════════════════════════════════════════════════════════════

async function _getElevenLabsKey() {
    try {
        if (configData && configData.elevenlabs_key) return configData.elevenlabs_key;
        const authHdr = await _authHeaders();
        const resp = await fetch(`${API_BASE}/api/config`, { headers: authHdr });
        const cfg = await resp.json();
        if (cfg.elevenlabs_key) {
            if (configData) configData.elevenlabs_key = cfg.elevenlabs_key;
            return cfg.elevenlabs_key;
        }
    } catch (e) { /* silent */ }
    return '';
}

async function _aiSpeak(text, onDone) {
    // Silently fail if no key or TTS unavailable — must not break callers
    try {
        if (window._aiAudio) { window._aiAudio.pause(); window._aiAudio = null; }
        const statusEl = document.getElementById('aiSpeakStatus');
        if (statusEl) statusEl.style.display = 'block';

        const key = await _getElevenLabsKey();
        if (!key) {
            if (statusEl) statusEl.style.display = 'none';
            if (onDone) onDone();
            return;
        }

        const voiceId = (configData && configData.elevenlabs_voice_id) || '56k72tYpS6hbRADdszYg';
        const speakText = text.trim().substring(0, 350);

        const resp = await fetch(
            `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`,
            {
                method: 'POST',
                headers: { 'xi-api-key': key, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: speakText,
                    model_id: 'eleven_multilingual_v2',
                    voice_settings: { stability: 0.5, similarity_boost: 0.75 },
                }),
            }
        );
        if (!resp.ok) {
            if (statusEl) statusEl.style.display = 'none';
            if (onDone) onDone();
            return;
        }

        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        window._aiAudio = new Audio(url);
        window._aiAudio.onended = () => {
            URL.revokeObjectURL(url);
            if (statusEl) statusEl.style.display = 'none';
            window._aiAudio = null;
            if (onDone) onDone();
        };
        window._aiAudio.onerror = () => {
            URL.revokeObjectURL(url);
            if (statusEl) statusEl.style.display = 'none';
            window._aiAudio = null;
            if (onDone) onDone();
        };
        await window._aiAudio.play();
    } catch (e) {
        console.warn('[ElevenLabs] TTS failed:', e.message);
        const statusEl = document.getElementById('aiSpeakStatus');
        if (statusEl) statusEl.style.display = 'none';
        if (onDone) onDone();
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// CIVIC REWARDS — My Rewards Card
// ═══════════════════════════════════════════════════════════════════════════

function _createRewardBadge() {
    const badge = document.createElement('div');
    badge.id = 'rewardPreviewBadge';
    badge.style.cssText = [
        'display:none', 'position:fixed', 'bottom:90px', 'right:24px',
        'background:linear-gradient(135deg,#6366F1,#8B5CF6)',
        'color:#fff', 'padding:10px 18px', 'border-radius:12px',
        'font-weight:700', 'font-size:14px', 'z-index:9000',
        'box-shadow:0 4px 20px rgba(99,102,241,0.4)',
        'animation:fadeSlideUp 0.4s ease',
    ].join(';');
    document.body.appendChild(badge);
    return badge;
}

async function _loadMyRewards() {
    if (!_authUser) return;
    const card = document.getElementById('myRewardsCard');
    if (!card) return;
    card.innerHTML = '<div style="color:#94A3B8;font-size:13px;padding:8px 0">Loading rewards...</div>';
    try {
        const authHdr = await _authHeaders();
        const resp = await fetch(`${API_BASE}/api/rewards/my`, { headers: authHdr });
        if (!resp.ok) { card.innerHTML = ''; return; }
        const d = await resp.json();
        const pct = Math.min(100, (d.total_points / 500) * 100).toFixed(0);
        card.innerHTML = `
            <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px">
                <div style="flex:1;min-width:80px;background:#0F172A;border-radius:8px;padding:10px;text-align:center">
                    <div style="font-size:22px;font-weight:800;color:#6366F1">${d.total_points}</div>
                    <div style="font-size:11px;color:#64748B">Points</div>
                </div>
                <div style="flex:1;min-width:80px;background:#0F172A;border-radius:8px;padding:10px;text-align:center">
                    <div style="font-size:20px;font-weight:800;color:#10B981">₹${d.pending_rupees}</div>
                    <div style="font-size:11px;color:#64748B">Pending</div>
                </div>
                <div style="flex:1;min-width:80px;background:#0F172A;border-radius:8px;padding:10px;text-align:center">
                    <div style="font-size:20px;font-weight:800;color:#F59E0B">${d.reports_resolved}</div>
                    <div style="font-size:11px;color:#64748B">Resolved</div>
                </div>
            </div>
            <div style="margin-bottom:10px">
                <div style="display:flex;justify-content:space-between;font-size:12px;color:#64748B;margin-bottom:4px">
                    <span>Level Progress</span><span>${d.total_points}/500 pts</span>
                </div>
                <div style="background:#1E293B;border-radius:4px;height:6px;overflow:hidden">
                    <div style="width:${pct}%;height:100%;background:linear-gradient(90deg,#6366F1,#8B5CF6);transition:width 0.5s ease"></div>
                </div>
            </div>
            ${d.reward_history.length ? `
            <div style="font-size:12px;color:#64748B;margin-bottom:6px">Recent Resolved Reports</div>
            ${d.reward_history.slice(0, 5).map(h => `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #1E293B;font-size:12px">
                    <span style="color:#CBD5E1">${h.dustbin_id} (lvl ${h.overflow_level})</span>
                    <span style="color:#10B981;font-weight:700">+${h.points}pts / ₹${h.rupees}</span>
                </div>
            `).join('')}` : '<div style="color:#64748B;font-size:12px">No resolved reports yet. Keep reporting!</div>'}
        `;
    } catch (e) {
        card.innerHTML = '<div style="color:#64748B;font-size:12px">Could not load rewards data.</div>';
    }
}

function _initRewardsCard() {
    if (!_authUser) return;
    // Find the report section to inject after it
    const reportSection = document.getElementById('ptab-report');
    if (!reportSection) return;
    if (document.getElementById('myRewardsSection')) return;  // Guard

    const section = document.createElement('div');
    section.id = 'myRewardsSection';
    section.style.cssText = 'margin-top:16px;background:#1A2332;border-radius:12px;overflow:hidden;border:1px solid #2D3748';
    section.innerHTML = `
        <div onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.rw-chevron').textContent=this.nextElementSibling.classList.contains('hidden')?'▶':'▼'"
            style="padding:12px 16px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;user-select:none">
            <span style="font-weight:700;color:#E2E8F0;font-size:14px">🏆 My Civic Rewards</span>
            <span class="rw-chevron" style="color:#6366F1;font-size:12px">▶</span>
        </div>
        <div class="hidden" style="padding:0 16px 16px 16px">
            <div id="myRewardsCard"></div>
        </div>
    `;
    reportSection.after(section);
    _loadMyRewards();
}


// ═══════════════════════════════════════════════════════════════════════════
// AI CHATBOT WIDGET
// ═══════════════════════════════════════════════════════════════════════════

let _chatHistory = [];
let _lastReplayText = '';

function _initChatbot() {
    // Guard: only inject once
    if (document.getElementById('infraChatBtn')) return;

    // Floating button
    const btn = document.createElement('button');
    btn.id = 'infraChatBtn';
    btn.textContent = '🤖';
    btn.title = 'InfraWatch AI Assistant';
    btn.style.cssText = [
        'position:fixed', 'bottom:24px', 'right:24px', 'z-index:9100',
        'width:52px', 'height:52px', 'border-radius:50%', 'border:none',
        'background:linear-gradient(135deg,#6366F1,#8B5CF6)',
        'color:#fff', 'font-size:22px', 'cursor:pointer',
        'box-shadow:0 4px 20px rgba(99,102,241,0.5)',
        'display:none',   // Hidden until auth check
        'align-items:center', 'justify-content:center',
        'transition:transform 0.2s ease',
    ].join(';');
    btn.addEventListener('mouseenter', () => { btn.style.transform = 'scale(1.1)'; });
    btn.addEventListener('mouseleave', () => { btn.style.transform = 'scale(1.0)'; });

    // Panel
    const panel = document.createElement('div');
    panel.id = 'infraChatPanel';
    panel.style.cssText = [
        'position:fixed', 'bottom:86px', 'right:24px', 'z-index:9100',
        'width:320px', 'max-height:480px', 'display:none', 'flex-direction:column',
        'background:#0F172A', 'border:1px solid #2D3748', 'border-radius:16px',
        'overflow:hidden', 'box-shadow:0 8px 40px rgba(0,0,0,0.5)',
        'font-family:Inter,sans-serif',
    ].join(';');
    panel.innerHTML = `
        <div style="background:linear-gradient(135deg,#6366F1,#8B5CF6);padding:12px 16px;display:flex;align-items:center;justify-content:space-between">
            <span style="font-weight:700;color:#fff;font-size:14px">🤖 InfraWatch AI</span>
            <button id="infraChatClose" style="background:none;border:none;color:#fff;font-size:18px;cursor:pointer;line-height:1">×</button>
        </div>
        <div id="infraChatHistory" style="flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;min-height:200px;max-height:300px"></div>
        <div style="padding:8px;border-top:1px solid #1E293B;display:flex;gap:6px">
            <input id="infraChatInput" type="text" placeholder="Ask about your reports..." style="flex:1;background:#1E293B;border:1px solid #374151;border-radius:8px;padding:8px 10px;color:#E2E8F0;font-size:13px;outline:none"/>
            <button id="infraChatSend" style="background:#6366F1;border:none;border-radius:8px;padding:8px 12px;color:#fff;cursor:pointer;font-weight:700">➤</button>
            <button id="infraChatReplay" title="Replay last response" style="background:#1E293B;border:1px solid #374151;border-radius:8px;padding:8px 10px;color:#94A3B8;cursor:pointer">🔊</button>
        </div>
    `;
    document.body.appendChild(btn);
    document.body.appendChild(panel);

    // Show/hide panel
    btn.addEventListener('click', () => {
        const showing = panel.style.display === 'flex';
        panel.style.display = showing ? 'none' : 'flex';
        if (!showing && _chatHistory.length === 0) _chatSendWelcome();
    });
    document.getElementById('infraChatClose').addEventListener('click', () => { panel.style.display = 'none'; });

    // Send on button click or Enter
    document.getElementById('infraChatSend').addEventListener('click', _chatSend);
    document.getElementById('infraChatInput').addEventListener('keydown', e => { if (e.key === 'Enter') _chatSend(); });

    // Voice replay
    document.getElementById('infraChatReplay').addEventListener('click', () => {
        if (_lastReplayText) _aiSpeak(_lastReplayText);
    });

    // Show button when logged in
    if (_authUser) { btn.style.display = 'flex'; }

    // Watch for auth changes
    window.addEventListener('infrawatch:auth', () => {
        btn.style.display = _authUser ? 'flex' : 'none';
    });
}

function _appendChatBubble(text, isUser) {
    const history = document.getElementById('infraChatHistory');
    if (!history) return;
    const bubble = document.createElement('div');
    bubble.style.cssText = [
        `align-self:${isUser ? 'flex-end' : 'flex-start'}`,
        `background:${isUser ? 'linear-gradient(135deg,#6366F1,#8B5CF6)' : '#1E293B'}`,
        'color:#E2E8F0', 'padding:8px 12px', 'border-radius:12px',
        `border-radius:${isUser ? '12px 12px 2px 12px' : '12px 12px 12px 2px'}`,
        'max-width:85%', 'font-size:13px', 'line-height:1.5',
        'white-space:pre-wrap', 'word-break:break-word',
    ].join(';');
    bubble.textContent = text;
    history.appendChild(bubble);
    history.scrollTop = history.scrollHeight;
}

function _showChatTyping() {
    const history = document.getElementById('infraChatHistory');
    if (!history) return;
    const typing = document.createElement('div');
    typing.id = 'infraChatTyping';
    typing.style.cssText = 'align-self:flex-start;background:#1E293B;border-radius:12px 12px 12px 2px;padding:10px 14px;color:#94A3B8;font-size:20px;letter-spacing:4px';
    typing.textContent = '···';
    typing.style.animation = 'pulse 1.2s ease infinite';
    history.appendChild(typing);
    history.scrollTop = history.scrollHeight;
    return typing;
}

function _chatSendWelcome() {
    const name = (_authUser && (_authUser.name || _authUser.email || '').split('@')[0]) || 'Citizen';
    const welcome = `नमस्ते ${name}! मैं InfraWatch AI हूँ। आप अपनी शिकायतों का status पूछ सकते हैं।\n\nHi ${name}! Ask me about your reports or city conditions.`;
    _appendChatBubble(welcome, false);
    _lastReplayText = welcome;
}

async function _chatSend() {
    const input = document.getElementById('infraChatInput');
    if (!input) return;
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';

    _appendChatBubble(msg, true);
    _chatHistory.push({ role: 'user', text: msg });

    const typing = _showChatTyping();

    try {
        const authHdr = await _authHeaders();
        const body = { message: msg, user_sub: _authUser ? _authUser.sub : '' };
        const resp = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { ...authHdr, 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (typing) typing.remove();

        if (resp.ok) {
            const data = await resp.json();
            const answer = data.answer || 'Sorry, I could not process that.';
            _appendChatBubble(answer, false);
            _chatHistory.push({ role: 'ai', text: answer });
            if (data.speak) {
                _lastReplayText = data.speak;
                _aiSpeak(data.speak);
            }
        } else {
            _appendChatBubble('Service temporarily unavailable. Please try again.', false);
        }
    } catch (e) {
        if (typing) typing.remove();
        _appendChatBubble('Network error. Check your connection.', false);
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// INIT: Wire up rewards + chatbot after Auth0 loads
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    // Always init chatbot widget structure immediately — button visibility is
    // controlled inside _initChatbot via the infrawatch:auth event it listens for.
    _initChatbot();

    // If Auth0 has already resolved synchronously (e.g. token cached), init rewards now
    if (_authUser) {
        _initRewardsCard();
    }

    // Also listen for the auth event in case Auth0 resolves after DOMContentLoaded
    window.addEventListener('infrawatch:auth', () => {
        if (_authUser && typeof _initRewardsCard === 'function') {
            _initRewardsCard();
        }
    });
});

