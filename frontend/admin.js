/**
 * InfraWatch Nexus — Admin Portal Logic
 * Command center. Road issue reporting, van collection, priority queue.
 * Strictly stateless visualization of WebSocket array.
 */

const API_BASE = window.location.origin;
const WS_SCHEME = window.location.protocol === 'https:' ? 'wss' : 'ws';
const WS_URL = `${WS_SCHEME}://${window.location.host}/ws`;

let dashboard = null;
let configData = null;
let map = null;
let markers = {};
let roadLines = [];
let authToken = localStorage.getItem('infrawatch_admin_token') || '';
let roadSeverity = 3;
let ws = null;

// Route cache to avoid redundant OSRM API calls
const routeCache = {};

/**
 * Fetch actual road path between two GPS points using OSRM.
 * Falls back to straight line if routing API fails.
 */
async function fetchRoadPath(ri) {
    const cacheKey = `${ri.from_lat},${ri.from_lng}-${ri.to_lat},${ri.to_lng}`;
    if (routeCache[cacheKey]) return routeCache[cacheKey];

    try {
        const url = `https://router.project-osrm.org/route/v1/driving/${ri.from_lng},${ri.from_lat};${ri.to_lng},${ri.to_lat}?overview=full&geometries=geojson`;
        const resp = await fetch(url, { signal: AbortSignal.timeout(4000) });
        const data = await resp.json();

        if (data.routes && data.routes.length > 0) {
            const coords = data.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
            routeCache[cacheKey] = coords;
            return coords;
        }
    } catch (e) {
        console.warn('OSRM routing failed, using straight line fallback:', e.message);
    }

    const fallback = [[ri.from_lat, ri.from_lng], [ri.to_lat, ri.to_lng]];
    routeCache[cacheKey] = fallback;
    return fallback;
}

// ── INIT ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    if (!authToken) document.getElementById('authOverlay').classList.remove('hidden');
    else { document.getElementById('authOverlay').classList.add('hidden'); await bootstrap(); }

    document.getElementById('btnAuth').addEventListener('click', handleAuth);
    document.getElementById('authTokenInput').addEventListener('keydown', e => { if (e.key === 'Enter') handleAuth(); });
    document.getElementById('btnLogout').addEventListener('click', () => {
        localStorage.removeItem('infrawatch_admin_token');
        authToken = '';
        document.getElementById('authOverlay').classList.remove('hidden');
    });

    document.getElementById('btnDemo').addEventListener('click', async () => {
        if (!confirm("🚨 Warning: This will inject multiple severe reports into Ward 12 to demonstrate the auto-triage escalation matrix. Continue?")) return;

        const btn = document.getElementById('btnDemo');
        const originalText = btn.innerHTML;
        btn.innerHTML = 'INJECTING...';

        try {
            const res = await fetch('/api/demo/simulate-crisis', {
                method: 'POST',
                headers: authHeader()
            });
            const data = await res.json();
            if (res.ok) {
                showToast(data.message, 'success');
            } else {
                showToast(data.error || "Simulation failed.", 'error');
            }
        } catch (e) {
            showToast("Network error during simulation.", 'error');
        } finally {
            btn.innerHTML = originalText;
        }
    });
});

async function bootstrap() {
    await loadConfig();
    initTabs();
    initMap();
    initForms();
    connectWebSocket();
}

// ── AUTH ────────────────────────────────────────────────────────────
function handleAuth() {
    const input = document.getElementById('authTokenInput').value.trim();
    if (!input) { document.getElementById('authError').textContent = 'Token required.'; return; }
    authToken = input;
    localStorage.setItem('infrawatch_admin_token', authToken);
    document.getElementById('authOverlay').classList.add('hidden');
    bootstrap();
}

function authHeader() { return { 'Authorization': `Bearer ${authToken}` }; }

// ── CONFIG ──────────────────────────────────────────────────────────
async function loadConfig() {
    try {
        const resp = await fetch(`${API_BASE}/api/config`);
        configData = await resp.json();

        // Populate Wards
        const wardSelects = ['vanWard', 'roadWard'];
        wardSelects.forEach(id => {
            const el = document.getElementById(id);
            el.innerHTML = '<option value="">— Select Ward —</option>';
            for (const [wid, info] of Object.entries(configData.wards)) {
                el.innerHTML += `<option value="${wid}">${info.name} (${wid})</option>`;
            }
        });

        // Event Listeners for dependent dustbin selects
        document.getElementById('vanWard').addEventListener('change', e => populateDustbins('vanDustbin', e.target.value));
        document.getElementById('roadWard').addEventListener('change', e => {
            populateDustbins('roadFrom', e.target.value);
            populateDustbins('roadTo', e.target.value);
        });

    } catch (e) { showToast('Config Load Failure', 'error'); }
}

function populateDustbins(selectId, wardId) {
    const sel = document.getElementById(selectId);
    sel.innerHTML = '<option value="">— Select Dustbin —</option>';
    if (!wardId || !configData) return;
    for (const [did, info] of Object.entries(configData.dustbins)) {
        if (info.ward_id === wardId) {
            sel.innerHTML += `<option value="${did}">${did} — ${info.street}</option>`;
        }
    }
}

// ── TABS ────────────────────────────────────────────────────────────
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(btn.dataset.tab).classList.add('active');
        });
    });
}

// ── MAP ─────────────────────────────────────────────────────────────
function initMap() {
    const center = configData?.city_center || { lat: 28.6139, lng: 77.2090 };
    map = L.map('map', { center: [center.lat, center.lng], zoom: 11 });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '© CARTO', maxZoom: 19
    }).addTo(map);

    if (configData?.dustbins) {
        for (const [did, info] of Object.entries(configData.dustbins)) {
            const marker = L.circleMarker([info.lat, info.lng], {
                radius: 6, fillColor: '#64748B', color: '#0F172A', weight: 2, fillOpacity: 0.9
            }).addTo(map);
            marker.bindPopup(`<b>${did}</b><br>${info.street}`);
            markers[did] = marker;
        }
    }
}

function updateMap() {
    if (!dashboard) return;

    for (const ds of (dashboard.dustbin_states || [])) {
        const marker = markers[ds.dustbin_id];
        if (!marker) continue;

        let radius = 6;
        if (ds.state === 'Critical') radius = 10;
        else if (ds.state === 'Escalated') radius = 8;
        else if (ds.state === 'Reported') radius = 7;

        marker.setStyle({ fillColor: ds.color || '#16A34A', radius });
        marker.setPopupContent(`
            <div style="font-family: var(--font);">
                <b>${ds.dustbin_id}</b><br>
                <span style="font-size:11px; color:var(--text-muted);">${ds.street}</span><br>
                <div style="color:${ds.color}; font-weight:700; font-size:11px; margin-top:4px;">● ${ds.state.toUpperCase()}</div>
                ${ds.report_count > 0 ? `<div style="font-size:10px; margin-top:4px;">Reports: ${ds.report_count}</div>` : ''}
            </div>
        `);
    }

    roadLines.forEach(l => map.removeLayer(l));
    roadLines = [];

    for (const ri of (dashboard.road_issues || [])) {
        fetchRoadPath(ri).then(coords => {
            const line = L.polyline(
                coords,
                { color: '#EA580C', weight: 5, dashArray: '6,6', opacity: 0.85 }
            ).addTo(map);
            line.bindPopup(`<b>🚧 ${ri.issue_type.toUpperCase()}</b><br>Severity: ${ri.severity}/5<br><span style="font-size:10px;color:#888;">Route-mapped path</span>`);
            roadLines.push(line);
        });
    }
}

// ── FORMS ───────────────────────────────────────────────────────────
function initForms() {
    // Road Severity
    document.getElementById('roadSevGrid').addEventListener('click', e => {
        if (!e.target.classList.contains('sev-btn')) return;
        document.querySelectorAll('.sev-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        roadSeverity = parseInt(e.target.dataset.val);
    });

    // Submit Van
    document.getElementById('btnCollectionConfirm').addEventListener('click', async () => {
        const btn = document.getElementById('btnCollectionConfirm');
        const did = document.getElementById('vanDustbin').value;
        if (!did) return showToast('Select Dustbin ID', 'error');

        btn.disabled = true;
        btn.textContent = 'Processing...';
        try {
            const resp = await fetch(`${API_BASE}/api/van/collection`, {
                method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader() },
                body: JSON.stringify({ dustbin_id: did })
            });
            const result = await resp.json();
            if (resp.ok) showToast('Collection Confirmed.', 'success');
            else if (resp.status === 401) { showAuthModal(); showToast('Auth Token Expired', 'error'); }
            else showToast(result.error, 'error');
        } catch (e) { showToast('Network Failure', 'error'); }
        btn.disabled = false;
        btn.textContent = 'Mark as Cleared';
    });

    // Submit Road
    document.getElementById('btnRoadSubmit').addEventListener('click', async () => {
        const btn = document.getElementById('btnRoadSubmit');
        const from = document.getElementById('roadFrom').value;
        const to = document.getElementById('roadTo').value;
        const type = document.getElementById('roadType').value;
        if (!from || !to) return showToast('Select both Origin and Destination IDs', 'error');
        if (from === to) return showToast('Origin and Destination must differ', 'error');

        btn.disabled = true;
        btn.textContent = 'Verifying...';
        try {
            const resp = await fetch(`${API_BASE}/api/report/road-issue`, {
                method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader() },
                body: JSON.stringify({ from_dustbin: from, to_dustbin: to, issue_type: type, severity: roadSeverity })
            });
            if (resp.ok) showToast('Road Alert Broadcasted.', 'success');
            else if (resp.status === 401) { showAuthModal(); showToast('Auth Token Expired', 'error'); }
            else showToast('Submission rejected', 'error');
        } catch (e) { showToast('Network Failure', 'error'); }
        btn.disabled = false;
        btn.textContent = 'Submit Road Issue';
    });
}

// ── UI RENDERERS ────────────────────────────────────────────────────
function renderQueue() {
    const list = document.getElementById('priorityList');
    const queue = dashboard?.priority_queue || [];
    document.getElementById('queueCount').textContent = `${queue.length} Tasks`;

    if (queue.length === 0) { list.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 12px;">Queue Clear</div>'; return; }

    list.innerHTML = queue.map((q, i) => `
        <div class="queue-row">
            <div class="q-rank">#${i + 1}</div>
            <div class="q-info">
                <div class="q-id">${q.type === 'waste' ? '🗑️' : '🚧'} ${q.name}</div>
                <div class="q-sub" style="color:${q.color}">${q.state} • ${q.ward_id}</div>
            </div>
            <div class="q-score" style="color:${q.color}">${q.risk_score}</div>
        </div>
    `).join('');
}

function renderAnalytics() {
    const list = document.getElementById('wardOverview');
    const wards = dashboard?.ward_risks || [];
    if (wards.length === 0) return;

    list.innerHTML = [...wards].sort((a, b) => b.risk_score - a.risk_score).map(w => `
        <div class="ward-row">
            <span>${w.name} (${w.ward_id})</span>
            <span style="color:${w.color}; font-weight:700;">${w.risk_score}</span>
        </div>
    `).join('');
}

// ── WEBSOCKET ───────────────────────────────────────────────────────
function connectWebSocket() {
    const statusEl = document.getElementById('wsStatus');
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        statusEl.textContent = '● CONNECTED';
        statusEl.className = 'badge live';
    };

    ws.onmessage = (event) => {
        dashboard = JSON.parse(event.data);
        document.getElementById('weatherBadge').textContent = `🌧 ${dashboard.rainfall_mm_hr || 0}mm/hr`;
        updateMap();
        renderQueue();
        renderAnalytics();
    };

    ws.onclose = () => {
        statusEl.textContent = '● OFFLINE';
        statusEl.className = 'badge dead';
        setTimeout(connectWebSocket, 4000);
    };
    ws.onerror = () => ws.close();
}

function showToast(msg, type = 'info') {
    const c = document.getElementById('toastContainer');
    const t = document.createElement('div');
    t.className = 'toast';
    t.innerHTML = `<span style="color: ${type === 'error' ? 'var(--danger)' : 'var(--success)'}; font-weight: 800; margin-right: 8px;">${type === 'error' ? '!' : '✓'}</span> ${msg}`;
    if (type === 'error') t.style.borderLeft = '4px solid var(--danger)';
    if (type === 'success') t.style.borderLeft = '4px solid var(--success)';
    c.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}

// ── PREDICTIVE RISK FORECAST ───────────────────────────────────────
async function loadForecast() {
    const container = document.getElementById('forecastContainer');
    const btn = document.getElementById('btnLoadForecast');
    btn.innerHTML = 'Loading...';
    btn.disabled = true;

    try {
        const resp = await fetch(`${API_BASE}/api/forecast`);
        const data = await resp.json();

        if (!data.forecast || data.forecast.length === 0) {
            container.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">No forecast data available.</div>';
            return;
        }

        let html = '';
        for (const day of data.forecast) {
            html += `<div style="margin-bottom: 16px; padding: 12px; background: rgba(30,27,75,0.5); border-radius: 8px; border-left: 3px solid ${day.weather_severity >= 0.5 ? '#ef4444' : day.weather_severity >= 0.2 ? '#eab308' : '#10b981'};">`;
            html += `<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">`;
            html += `<strong style="font-size: 13px;">${day.date}</strong>`;
            html += `<span style="font-size: 11px; color: var(--text-muted);">${day.condition} · ${day.total_precip_mm}mm · ${day.max_wind_kph}kph</span>`;
            html += `</div>`;

            // Top 5 wards by risk
            const topWards = day.wards.slice(0, 5);
            for (const w of topWards) {
                const riskColor = w.risk_level === 'CRITICAL' ? '#ef4444' : w.risk_level === 'ELEVATED' ? '#eab308' : '#10b981';
                const barWidth = Math.max(5, Math.round(w.predicted_risk * 100));
                html += `<div style="display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 11px;">`;
                html += `<span style="width: 50px; flex-shrink: 0; color: var(--text-muted);">${w.ward_id}</span>`;
                html += `<div style="flex: 1; height: 6px; background: rgba(255,255,255,0.05); border-radius: 3px;">`;
                html += `<div style="width: ${barWidth}%; height: 100%; background: ${riskColor}; border-radius: 3px; transition: width 0.5s;"></div>`;
                html += `</div>`;
                html += `<span style="width: 60px; text-align: right; font-weight: 700; color: ${riskColor}; font-size: 10px;">${w.risk_level}</span>`;
                html += `</div>`;
            }
            html += `</div>`;
        }

        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<div style="padding:16px;text-align:center;color:var(--danger);">Failed to load forecast.</div>';
    } finally {
        btn.innerHTML = 'Refresh Forecast';
        btn.disabled = false;
    }
}

// Wire the forecast button
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('btnLoadForecast');
    if (btn) btn.addEventListener('click', loadForecast);
});

