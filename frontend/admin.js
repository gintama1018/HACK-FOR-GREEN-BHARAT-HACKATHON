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
// sessionStorage: token lost on tab close — XSS cannot persist it across sessions
let authToken = sessionStorage.getItem('infrawatch_admin_token') || '';
let _wsRetries = 0;
let roadSeverity = 3;
let ws = null;

// Route cache + OSRM routing provided by shared.js:
//   InfraRoute.fetchRoadPath(ri), InfraRoute.fetchMultiRoutes(ri)
const routeCache = {};
const multiRouteCache = {};
async function fetchMultiRoutes(ri) { return InfraRoute.fetchMultiRoutes(ri); }
async function fetchRoadPath(ri) { return InfraRoute.fetchRoadPath(ri); }

// ── INIT ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    if (!authToken) document.getElementById('authOverlay').classList.remove('hidden');
    else { document.getElementById('authOverlay').classList.add('hidden'); await bootstrap(); }

    document.getElementById('btnAuth').addEventListener('click', handleAuth);
    document.getElementById('authTokenInput').addEventListener('keydown', e => { if (e.key === 'Enter') handleAuth(); });
    document.getElementById('btnLogout').addEventListener('click', () => {
        sessionStorage.removeItem('infrawatch_admin_token');
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
    setTimeout(populateClearDropdowns, 1000); // Give dashboard a second to load
}

// ── AUTH ────────────────────────────────────────────────────────────
function handleAuth() {
    const input = document.getElementById('authTokenInput').value.trim();
    if (!input) { document.getElementById('authError').textContent = 'Token required.'; return; }
    authToken = input;
    sessionStorage.setItem('infrawatch_admin_token', authToken);
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
        const wardSelects = ['roadWard'];
        wardSelects.forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            el.innerHTML = '<option value="">— Select Ward —</option>';
            for (const [wid, info] of Object.entries(configData.wards)) {
                el.innerHTML += `<option value="${wid}">${info.name} (${wid})</option>`;
            }
        });

        // Event Listeners for dependent dustbin selects
        document.getElementById('roadWard').addEventListener('change', e => {
            populateDustbins('roadFrom', e.target.value);
            populateDustbins('roadTo', e.target.value);
        });

        // Clear Issues Handlers
        document.getElementById('btnClearDustbin')?.addEventListener('click', clearDustbin);
        document.getElementById('btnClearRoad')?.addEventListener('click', clearRoad);

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
// Marker helpers provided by shared.js:
//   getMarkerStateClass(state), getMarkerSize(state), createDivIcon(stateClass, sizeClass)

function initMap() {
    if (map) return;
    const center = configData?.city_center || { lat: 28.6139, lng: 77.2090 };
    map = L.map('map', { center: [center.lat, center.lng], zoom: 11 });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '© CARTO', maxZoom: 19
    }).addTo(map);

    if (configData?.dustbins) {
        for (const [did, info] of Object.entries(configData.dustbins)) {
            const icon = createDivIcon('marker-clear', 'marker-sm');
            const marker = L.marker([info.lat, info.lng], { icon }).addTo(map);
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

        const stateClass = getMarkerStateClass(ds.state);
        const sizeClass = getMarkerSize(ds.state);
        const icon = createDivIcon(stateClass, sizeClass);
        marker.setIcon(icon);
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
        fetchMultiRoutes(ri).then(routes => {
            if (!routes || routes.length === 0) return;

            // Draw ALTERNATIVE approach routes first (yellow, behind)
            for (let i = routes.length - 1; i >= 1; i--) {
                const altLine = L.polyline(routes[i].coords, {
                    color: '#FBBF24', weight: 3, dashArray: '4,8', opacity: 0.6
                }).addTo(map);
                const distKm = (routes[i].distance / 1000).toFixed(1);
                const timeMin = Math.round(routes[i].duration / 60);
                altLine.bindPopup(
                    `<b>⚠️ ALTERNATIVE APPROACH</b><br>Route to hazard zone<br>` +
                    `<span style="font-size:10px;color:#888;">Distance: ${distKm} km · ~${timeMin} min</span>`
                );
                roadLines.push(altLine);
            }

            // Draw MAIN hazard route on top (red, thick)
            const mainLine = L.polyline(routes[0].coords, {
                color: '#EF4444', weight: 5, dashArray: '8,6', opacity: 0.9
            }).addTo(map);
            const mainDistKm = (routes[0].distance / 1000).toFixed(1);
            mainLine.bindPopup(
                `<b>🔴 MAIN HAZARD ROUTE</b><br>` +
                `🚧 ${ri.issue_type.toUpperCase()} — Severity ${ri.severity}/5<br>` +
                `<span style="font-size:10px;color:#888;">${ri.from_dustbin} → ${ri.to_dustbin} · ${mainDistKm} km</span>`
            );
            roadLines.push(mainLine);
        });
    }
}

// ── FORMS ───────────────────────────────────────────────────────────
function initForms() {
    // Road Severity
    document.getElementById('roadSevGrid')?.addEventListener('click', e => {
        if (!e.target.classList.contains('sev-btn')) return;
        document.querySelectorAll('.sev-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        roadSeverity = parseInt(e.target.dataset.val);
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

// ── CLEAR ISSUES LOGIC ──────────────────────────────────────────────
function populateClearDropdowns() {
    if (!dashboard) return;

    // Dustbins with active reports/escalations
    const dSel = document.getElementById('clearDustbinSelect');
    if (!dSel) return;
    const currentDustbin = dSel.value;
    dSel.innerHTML = '<option value="">— Select Dustbin —</option>';

    const activeDustbins = (dashboard.dustbin_states || []).filter(d => d.state !== 'Clear' && d.state !== 'Cleared');
    activeDustbins.sort((a, b) => b.report_count - a.report_count);
    for (const d of activeDustbins) {
        dSel.innerHTML += `<option value="${d.dustbin_id}">${d.dustbin_id} (${d.state})</option>`;
    }
    if (currentDustbin && activeDustbins.some(d => d.dustbin_id === currentDustbin)) {
        dSel.value = currentDustbin;
    }

    // Active road issues
    const rSel = document.getElementById('clearRoadSelect');
    if (!rSel) return;
    const currentRoad = rSel.value;
    rSel.innerHTML = '<option value="">— Select Road Issue —</option>';

    const activeRoads = dashboard.road_issues || [];
    for (const r of activeRoads) {
        rSel.innerHTML += `<option value="${r.event_id}">${r.issue_type.toUpperCase()}: ${r.from_dustbin} → ${r.to_dustbin}</option>`;
    }
    if (currentRoad && activeRoads.some(r => r.event_id === currentRoad)) {
        rSel.value = currentRoad;
    }
}

async function clearDustbin() {
    const btn = document.getElementById('btnClearDustbin');
    const did = document.getElementById('clearDustbinSelect').value;

    if (!did) { showToast('Select a dustbin to clear.', 'error'); return; }

    btn.disabled = true;
    btn.innerHTML = 'Submitting...';

    try {
        const resp = await fetch(`${API_BASE}/api/van/collection`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...authHeader()
            },
            body: JSON.stringify({ dustbin_id: did })
        });
        const data = await resp.json();
        if (resp.ok) {
            showToast('✅ Dustbin marked as collected.', 'success');
            document.getElementById('clearDustbinSelect').value = '';
        } else {
            if (resp.status === 401) { showAuthModal(); showToast('Auth Token Expired', 'error'); }
            showToast(data.error || 'Failed to clear dustbin.', 'error');
        }
    } catch (e) {
        showToast('Network error.', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = 'Mark as Collected';
    }
}

async function clearRoad() {
    const btn = document.getElementById('btnClearRoad');
    const eid = document.getElementById('clearRoadSelect').value;

    if (!eid) { showToast('Select a road issue to clear.', 'error'); return; }

    btn.disabled = true;
    btn.innerHTML = 'Submitting...';

    try {
        const resp = await fetch(`${API_BASE}/api/van/clear-road`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...authHeader()
            },
            body: JSON.stringify({ event_id: eid })
        });
        const data = await resp.json();
        if (resp.ok) {
            showToast('✅ Road issue marked as resolved.', 'success');
            document.getElementById('clearRoadSelect').value = '';
        } else {
            if (resp.status === 401) { showAuthModal(); showToast('Auth Token Expired', 'error'); }
            showToast(data.error || 'Failed to clear road.', 'error');
        }
    } catch (e) {
        showToast('Network error.', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = 'Mark as Resolved';
    }
}

// ── UI RENDERERS ────────────────────────────────────────────────────
let highlightLine = null;  // Track active highlight

function renderQueue() {
    const list = document.getElementById('priorityList');
    const queue = dashboard?.priority_queue || [];
    document.getElementById('queueCount').textContent = `${queue.length} Tasks`;

    if (queue.length === 0) { list.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 12px;">Queue Clear</div>'; return; }

    list.innerHTML = queue.map((q, i) => {
        const aiBadge = (q.type === 'waste' && q.ai_verified_count > 0)
            ? `<span style="background:#DCFCE7;color:#15803D;border-radius:4px;padding:1px 5px;font-size:9px;font-weight:700;margin-left:4px;">\ud83e\udde0 AI ${Math.round((q.ai_avg_confidence||0)*100)}%</span>`
            : '';
        const escalateBtn = (q.type === 'waste')
            ? `<button onclick="escalateWhatsApp(event,'${q.id}')" title="Escalate via WhatsApp" style="background:rgba(37,211,102,0.12);border:1px solid rgba(37,211,102,0.35);color:#25D166;border-radius:5px;padding:2px 7px;font-size:9px;font-weight:700;cursor:pointer;margin-left:4px;">🚨 WA</button>`
            : '';
        return `<div class="queue-row" style="cursor:pointer;" onclick="zoomToItem(${i})" title="Click to zoom to location">
            <div class="q-rank">#${i + 1}</div>
            <div class="q-info">
                <div class="q-id">${q.type === 'waste' ? '\ud83d\uddd1\ufe0f' : '\ud83d\udea7'} ${q.name}${aiBadge}${escalateBtn}</div>
                <div class="q-sub" style="color:${q.color}">${q.state} \u2022 ${q.ward_id} \u2022 <span style="font-size:9px;opacity:0.6;">\ud83d\udccd click to locate</span></div>
            </div>
            <div class="q-score" style="color:${q.color}">${q.risk_score}</div>
        </div>`;
    }).join('');
}

async function escalateWhatsApp(evt, dustbinId) {
    evt.stopPropagation();
    const token = localStorage.getItem('adminToken') || '';
    try {
        const resp = await fetch(`${API_BASE}/api/whatsapp-escalate/${encodeURIComponent(dustbinId)}`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        const data = await resp.json();
        if (resp.ok && data.wa_link) {
            window.open(data.wa_link, '_blank');
        } else {
            showToast(data.error || 'Escalation failed', 'error');
        }
    } catch (e) {
        showToast('Network error', 'error');
    }
}

function zoomToItem(index) {
    if (!dashboard || !configData) return;
    const queue = dashboard.priority_queue || [];
    const item = queue[index];
    if (!item) return;

    // Remove previous highlight
    if (highlightLine) { map.removeLayer(highlightLine); highlightLine = null; }

    if (item.type === 'waste') {
        // Zoom to the single dustbin
        const info = configData.dustbins[item.id];
        if (!info) return;
        map.flyTo([info.lat, info.lng], 17, { duration: 1.2 });

        // Pulse the marker
        const marker = markers[item.id];
        if (marker) {
            // Flash white highlight
            const flashIcon = L.divIcon({
                className: '',
                html: `<div class="marker-icon marker-xl" style="background:#fff;box-shadow:0 2px 6px rgba(0,0,0,0.2);">🗑️</div>`,
                iconSize: [42, 42], iconAnchor: [21, 21], popupAnchor: [0, -21]
            });
            marker.setIcon(flashIcon);
            marker.openPopup();
            setTimeout(() => {
                const stateClass = getMarkerStateClass(item.state);
                marker.setIcon(createDivIcon(stateClass, 'marker-lg'));
            }, 1500);
        }
    } else if (item.type === 'road') {
        // Extract dustbin IDs from road issue data
        const roadIssues = dashboard.road_issues || [];
        const ri = roadIssues.find(r => r.event_id === item.id);
        if (!ri) {
            // Fallback: zoom to ward center
            const wardInfo = configData.wards?.[item.ward_id];
            if (wardInfo) map.flyTo([wardInfo.lat, wardInfo.lng], 15, { duration: 1.2 });
            return;
        }

        // Zoom to fit both dustbin points
        const bounds = L.latLngBounds(
            [ri.from_lat, ri.from_lng],
            [ri.to_lat, ri.to_lng]
        );
        map.flyToBounds(bounds.pad(0.3), { duration: 1.2 });

        // Draw a bright highlight over the OSRM-routed path
        fetchRoadPath(ri).then(coords => {
            if (highlightLine) map.removeLayer(highlightLine);
            highlightLine = L.polyline(coords, {
                color: '#FFD700', weight: 8, opacity: 1, dashArray: null,
                className: 'highlight-pulse'
            }).addTo(map);
            highlightLine.bindPopup(`<b>🎯 SELECTED: ${ri.issue_type.toUpperCase()}</b><br>Severity: ${ri.severity}/5`).openPopup();

            // Fade highlight after 5 seconds
            setTimeout(() => {
                if (highlightLine) {
                    highlightLine.setStyle({ color: '#EA580C', weight: 5, opacity: 0.85, dashArray: '6,6' });
                }
            }, 5000);
        });
    }
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
        populateClearDropdowns(); // Update the CLEAR ISSUES dropdowns dynamically
    };

    ws.onopen = () => {
        _wsRetries = 0;  // Reset backoff on successful connection
        statusEl.textContent = '● CONNECTED';
        statusEl.className = 'badge live';
    };

    ws.onclose = () => {
        statusEl.textContent = '● OFFLINE';
        statusEl.className = 'badge dead';
        _wsRetries++;
        const delay = Math.min(30000, 1000 * Math.pow(2, _wsRetries)) + Math.random() * 1000;
        setTimeout(connectWebSocket, delay);
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

// ── AI WASTE HEATMAP ──────────────────────────────────────────────
async function renderAIHeatmap() {
    const chartEl   = document.getElementById('aiWasteChart');
    const summaryEl = document.getElementById('aiSummaryBar');
    const recentEl  = document.getElementById('aiRecentList');
    if (!chartEl) return;

    let events = [];
    try {
        const r = await fetch(`${API_BASE}/api/waste-events`);
        events = await r.json();
    } catch (e) {
        chartEl.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:12px;">Failed to load AI data.</div>';
        return;
    }

    // Filter reports that have YOLO data
    const aiReports  = events.filter(e => e.ai_verified !== undefined);
    const verified   = aiReports.filter(e => e.ai_verified === true);
    const confidence = verified.length ? (verified.reduce((s, e) => s + (e.yolo_confidence || 0), 0) / verified.length * 100).toFixed(0) : 0;

    // Summary stats bar
    summaryEl.innerHTML = [
        { label: 'AI Reports',   value: aiReports.length,  color: '#6366F1' },
        { label: 'Verified',     value: verified.length,   color: '#22C55E' },
        { label: 'Avg Conf.',    value: `${confidence}%`,  color: '#F59E0B' },
        { label: 'False Positives', value: aiReports.length - verified.length, color: '#EF4444' },
    ].map(s => `<div style="flex:1;min-width:70px;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 10px;text-align:center;">
        <div style="font-size:18px;font-weight:800;color:${s.color};">${s.value}</div>
        <div style="font-size:9px;color:var(--text-muted);margin-top:2px;text-transform:uppercase;">${s.label}</div>
    </div>`).join('');

    // Aggregate detected_objects across all AI reports → class counts
    const classCounts = {};
    for (const e of verified) {
        for (const cls of (e.detected_objects || [])) {
            classCounts[cls] = (classCounts[cls] || 0) + 1;
        }
    }

    // Ward-level AI confidence heatmap
    const wardAI = {};   // ward_id → { count, totalConf, classes: {} }
    for (const e of aiReports) {
        const wid = e.ward_id || 'Unknown';
        if (!wardAI[wid]) wardAI[wid] = { count: 0, totalConf: 0, classes: {} };
        wardAI[wid].count++;
        wardAI[wid].totalConf += e.yolo_confidence || 0;
        for (const cls of (e.detected_objects || [])) {
            wardAI[wid].classes[cls] = (wardAI[wid].classes[cls] || 0) + 1;
        }
    }

    const sortedWards = Object.entries(wardAI).sort((a, b) => b[1].count - a[1].count);

    if (sortedWards.length === 0) {
        chartEl.innerHTML = `<div style="font-size:12px;color:var(--text-muted);padding:20px;text-align:center;">
            No AI-verified reports yet.<br>Submit a report with a photo to see the heatmap.
        </div>`;
    } else {
        const maxCount = Math.max(...sortedWards.map(([,v]) => v.count));
        chartEl.innerHTML = sortedWards.map(([wid, v]) => {
            const avgConf = v.count ? (v.totalConf / v.count * 100).toFixed(0) : 0;
            const barW    = Math.max(4, Math.round(v.count / maxCount * 100));
            const topClasses = Object.entries(v.classes).sort((a,b) => b[1]-a[1]).slice(0,3)
                .map(([c,n]) => `<span style="background:rgba(239,68,68,0.15);color:#EF4444;border-radius:4px;padding:1px 5px;font-size:9px;">${c}×${n}</span>`).join('');
            return `<div style="margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                    <span style="font-size:11px;font-weight:600;">${wid}</span>
                    <span style="font-size:10px;color:var(--text-muted);">${v.count} reports · ${avgConf}% avg conf</span>
                </div>
                <div style="background:var(--border);border-radius:4px;height:8px;overflow:hidden;">
                    <div style="width:${barW}%;height:100%;background:linear-gradient(90deg,#6366F1,#EF4444);border-radius:4px;transition:width 0.6s;"></div>
                </div>
                <div style="margin-top:3px;display:flex;gap:4px;flex-wrap:wrap;">${topClasses}</div>
            </div>`;
        }).join('');
    }

    // Object type frequency chart
    const sortedClasses = Object.entries(classCounts).sort((a,b) => b[1]-a[1]).slice(0,10);
    if (sortedClasses.length > 0) {
        const maxC = sortedClasses[0][1];
        chartEl.innerHTML += `<div style="margin-top:14px;border-top:1px solid var(--border);padding-top:12px;">
            <div style="font-size:11px;font-weight:700;color:var(--text-muted);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.05em;">Detected Waste Types</div>
            ${sortedClasses.map(([cls,n]) => `<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;">
                <span style="width:80px;font-size:10px;text-align:right;color:var(--text-muted);">${cls}</span>
                <div style="flex:1;background:var(--border);border-radius:3px;height:6px;">
                    <div style="width:${Math.round(n/maxC*100)}%;height:100%;background:#6366F1;border-radius:3px;"></div>
                </div>
                <span style="font-size:10px;font-weight:700;width:20px;">${n}</span>
            </div>`).join('')}
        </div>`;
    }

    // Recent AI-verified list
    const recent = [...aiReports].reverse().slice(0, 8);
    recentEl.innerHTML = recent.length === 0
        ? '<div style="font-size:11px;color:var(--text-muted);padding:8px;">No entries yet.</div>'
        : recent.map(e => {
            const badge = e.ai_verified
                ? `<span style="background:#DCFCE7;color:#15803D;border-radius:4px;padding:1px 6px;font-size:9px;font-weight:700;">✔ Verified</span>`
                : `<span style="background:#FEE2E2;color:#B91C1C;border-radius:4px;padding:1px 6px;font-size:9px;font-weight:700;">✘ No Waste</span>`;
            const conf = e.yolo_confidence != null ? ` ${Math.round(e.yolo_confidence*100)}%` : '';
            const objs = (e.detected_objects || []).join(', ');
            return `<div style="display:flex;flex-direction:column;gap:2px;padding:6px 0;border-bottom:1px solid var(--border);">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:11px;font-weight:600;">${e.dustbin_id}</span>
                    <span style="display:flex;gap:4px;align-items:center;">${badge}<span style="font-size:10px;color:var(--text-muted);">${conf}</span></span>
                </div>
                ${objs ? `<div style="font-size:9px;color:#6366F1;">\ud83c\udff7 ${objs}</div>` : ''}
            </div>`;
        }).join('');
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

    const rtiBtn = document.getElementById('btnLoadRTI');
    if (rtiBtn) rtiBtn.addEventListener('click', loadRTIAdmin);
});

// ── RTI ADMIN LIST ──────────────────────────────────────────────────────
async function loadRTIAdmin() {
    const el = document.getElementById('rtiAdminList');
    if (!el) return;
    el.innerHTML = '<div style="padding:12px;font-size:12px;color:var(--text-muted);">Loading…</div>';
    try {
        const r = await fetch(`${API_BASE}/api/rti`);
        const rtis = await r.json();
        if (!rtis.length) {
            el.innerHTML = '<div style="padding:16px;text-align:center;font-size:12px;color:var(--text-muted);">No RTI drafts yet.<br>They auto-appear when critical alerts remain unresolved &gt;72h.</div>';
            return;
        }
        el.innerHTML = rtis.map(ri => {
            const d = ri.rti_data || {};
            const dateStr = (ri.generated_at || '').slice(0,16).replace('T', ' ');
            return `<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                    <span style="font-size:10px;font-weight:700;color:var(--accent);font-family:monospace;">${ri.rti_id}</span>
                    <span style="font-size:10px;color:var(--text-muted);">${dateStr}</span>
                </div>
                <div style="font-size:11px;font-weight:600;margin-bottom:4px;">${d.subject || 'RTI Draft'}</div>
                <div style="font-size:10px;color:var(--text-muted);">Dustbin: ${ri.dustbin_id || '—'} · Ward: ${ri.ward_id || '—'}</div>
                <a href="/transparency" target="_blank" style="display:inline-block;margin-top:8px;font-size:10px;color:var(--accent);text-decoration:none;">View on transparency portal ↗</a>
            </div>`;
        }).join('');
    } catch (e) {
        el.innerHTML = '<div style="padding:12px;font-size:12px;color:var(--danger);">Failed to load RTI data.</div>';
    }
}

