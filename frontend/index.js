/**
 * InfraWatch Nexus — Frontend Logic
 * ==================================
 * Real-time dashboard powered by Pathway streaming.
 * No simulation. No fake data.
 */

// ═══════════════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════════════
let ws = null;
let dashboardState = null;
let configData = null;
let map = null;
let mapMarkers = [];
let activeLayer = 'waste';
let currentPage = 'command';

// ═══════════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', async () => {
    initRouter();
    await loadConfig();
    populateFormSelects();
    initMap();
    initForms();
    connectWebSocket();
    // Initial data fetch
    fetchDashboard();
});

// ═══════════════════════════════════════════════════════════════════════════
// ROUTER
// ═══════════════════════════════════════════════════════════════════════════
function initRouter() {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const page = link.dataset.page;
            navigateTo(page);
        });
    });
}

function navigateTo(page) {
    currentPage = page;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.getElementById(`page-${page}`).classList.add('active');
    document.getElementById(`nav-${page}`).classList.add('active');
    renderCurrentPage();
}

// ═══════════════════════════════════════════════════════════════════════════
// DATA
// ═══════════════════════════════════════════════════════════════════════════
async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        configData = await res.json();
    } catch (e) {
        console.error('Config load failed:', e);
    }
}

async function fetchDashboard() {
    try {
        const res = await fetch('/api/dashboard');
        dashboardState = await res.json();
        renderCurrentPage();
    } catch (e) {
        console.error('Dashboard fetch failed:', e);
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// WEBSOCKET
// ═══════════════════════════════════════════════════════════════════════════
function connectWebSocket() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
        document.getElementById('conn-status').textContent = 'Live';
        document.querySelector('.status-dot').classList.add('live');
    };

    ws.onmessage = (event) => {
        try {
            dashboardState = JSON.parse(event.data);
            renderCurrentPage();
        } catch (e) { }
    };

    ws.onclose = () => {
        document.getElementById('conn-status').textContent = 'Reconnecting...';
        document.querySelector('.status-dot').classList.remove('live');
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => ws.close();
}

// ═══════════════════════════════════════════════════════════════════════════
// RENDER DISPATCHER
// ═══════════════════════════════════════════════════════════════════════════
function renderCurrentPage() {
    if (!dashboardState) return;
    switch (currentPage) {
        case 'command': renderCommandCenter(); break;
        case 'waste': renderWastePage(); break;
        case 'road': renderRoadPage(); break;
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// PAGE 1: COMMAND CENTER
// ═══════════════════════════════════════════════════════════════════════════
function renderCommandCenter() {
    const d = dashboardState;

    // City indices
    document.getElementById('waste-index-val').textContent = d.city_waste_index;
    document.getElementById('waste-index-state').textContent = classifyState(d.city_waste_index);
    document.getElementById('waste-index-state').style.color = stateColor(classifyState(d.city_waste_index));

    document.getElementById('road-index-val').textContent = d.city_road_index;
    document.getElementById('road-index-state').textContent = classifyState(d.city_road_index);
    document.getElementById('road-index-state').style.color = stateColor(classifyState(d.city_road_index));

    document.getElementById('rainfall-val').textContent = d.rainfall_mm_hr || 0;

    // Data freshness bar
    renderFreshness(d.freshness || {});

    // Priority queue
    renderPriorityQueue(d.priority_queue || []);

    // Map
    updateMap();
}

function renderPriorityQueue(queue) {
    const list = document.getElementById('priority-list');
    document.getElementById('priority-count').textContent = queue.length;

    if (queue.length === 0) {
        list.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:13px;">All clear — no elevated risks</div>';
        return;
    }

    list.innerHTML = queue.map((item, i) => `
        <div class="priority-item" onclick="showAdvisory('${item.id}', '${item.type}')">
            <span class="priority-rank">${i + 1}</span>
            <span class="priority-type-tag ${item.type}">${item.type}</span>
            <div class="priority-info">
                <div class="priority-name">${item.name}</div>
            </div>
            <span class="priority-score" style="color:${item.color}">${item.risk_score}</span>
            <span class="priority-state-dot" style="background:${item.color}"></span>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════════════════════════════
// MAP (Leaflet)
// ═══════════════════════════════════════════════════════════════════════════
function initMap() {
    const center = configData?.city_center || { lat: 28.6139, lng: 77.2090 };
    map = L.map('map', {
        center: [center.lat, center.lng],
        zoom: 11,
        zoomControl: false,
        attributionControl: false,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 18,
    }).addTo(map);

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // Toggle buttons
    document.getElementById('toggle-waste').addEventListener('click', () => {
        activeLayer = 'waste';
        document.getElementById('toggle-waste').classList.add('active');
        document.getElementById('toggle-road').classList.remove('active');
        updateMap();
    });
    document.getElementById('toggle-road').addEventListener('click', () => {
        activeLayer = 'road';
        document.getElementById('toggle-road').classList.add('active');
        document.getElementById('toggle-waste').classList.remove('active');
        updateMap();
    });
}

function updateMap() {
    if (!map || !dashboardState) return;

    // Clear existing markers
    mapMarkers.forEach(m => m.remove());
    mapMarkers = [];

    if (activeLayer === 'waste') {
        (dashboardState.waste_risks || []).forEach(w => {
            const ward = configData?.wards?.[w.ward_id];
            if (!ward) return;
            const marker = L.circleMarker([ward.lat, ward.lng], {
                radius: 10 + (w.risk_score / 10),
                fillColor: w.color,
                fillOpacity: 0.6,
                color: w.color,
                weight: 2,
                opacity: 0.8,
            }).addTo(map);

            marker.bindTooltip(`
                <strong>${ward.name}</strong> (${w.ward_id})<br>
                Risk: <strong>${w.risk_score}</strong> — ${w.state}<br>
                Reports: ${w.report_count} | Overflow: ${w.avg_overflow}<br>
                Collection delay: ${w.collection_delay_hr}hr
            `, { className: 'dark-tooltip' });

            marker.on('click', () => showAdvisory(w.ward_id, 'waste'));
            mapMarkers.push(marker);
        });
    } else {
        (dashboardState.road_risks || []).forEach(r => {
            const seg = configData?.segments?.[r.segment_id];
            if (!seg) return;
            const marker = L.circleMarker([seg.lat, seg.lng], {
                radius: 8 + (r.risk_score / 12),
                fillColor: r.color,
                fillOpacity: 0.6,
                color: r.color,
                weight: 2,
                opacity: 0.8,
            }).addTo(map);

            marker.bindTooltip(`
                <strong>${seg.name}</strong> (${r.segment_id})<br>
                Risk: <strong>${r.risk_score}</strong> — ${r.state}<br>
                Reports: ${r.report_count} | Severity: ${r.avg_severity}
            `, { className: 'dark-tooltip' });

            marker.on('click', () => showAdvisory(r.segment_id, 'road'));
            mapMarkers.push(marker);
        });
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// PAGE 2: WASTE OPERATIONS
// ═══════════════════════════════════════════════════════════════════════════
function renderWastePage() {
    const grid = document.getElementById('ward-grid');
    const risks = dashboardState.waste_risks || [];

    grid.innerHTML = risks.map(w => `
        <div class="ward-card" onclick="showAdvisory('${w.ward_id}', 'waste')">
            <div class="card-state-bar" style="background:${w.color}"></div>
            <div class="card-header">
                <div>
                    <div class="card-title">${w.name}</div>
                    <div class="card-id">${w.ward_id} · ${w.zone}</div>
                </div>
                <div style="text-align:right;">
                    <div class="card-score" style="color:${w.color}">${w.risk_score}</div>
                    <div class="card-state-label" style="color:${w.color}">${w.state}</div>
                </div>
            </div>
            <div class="card-metrics">
                <div class="metric">
                    <div class="metric-label">Reports</div>
                    <div class="metric-value">${w.report_count}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Avg Overflow</div>
                    <div class="metric-value">${w.avg_overflow}/5</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Collection Delay</div>
                    <div class="metric-value">${w.collection_delay_hr}hr</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Active Vans</div>
                    <div class="metric-value">${w.active_vans}</div>
                </div>
            </div>
            <div class="card-action">
                <button class="action-btn">View Advisory →</button>
            </div>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════════════════════════════
// PAGE 3: ROAD MONITORING
// ═══════════════════════════════════════════════════════════════════════════
function renderRoadPage() {
    const grid = document.getElementById('segment-grid');
    const risks = dashboardState.road_risks || [];

    grid.innerHTML = risks.map(r => `
        <div class="segment-card" onclick="showAdvisory('${r.segment_id}', 'road')">
            <div class="card-state-bar" style="background:${r.color}"></div>
            <div class="card-header">
                <div>
                    <div class="card-title">${r.name}</div>
                    <div class="card-id">${r.segment_id} · ${r.type_road || 'Road'}</div>
                </div>
                <div style="text-align:right;">
                    <div class="card-score" style="color:${r.color}">${r.risk_score}</div>
                    <div class="card-state-label" style="color:${r.color}">${r.state}</div>
                </div>
            </div>
            <div class="card-metrics">
                <div class="metric">
                    <div class="metric-label">Reports</div>
                    <div class="metric-value">${r.report_count}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Avg Severity</div>
                    <div class="metric-value">${r.avg_severity}/5</div>
                </div>
            </div>
            <div class="card-action">
                <button class="action-btn">View Advisory →</button>
            </div>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════════════════════════════
// FORMS
// ═══════════════════════════════════════════════════════════════════════════
function populateFormSelects() {
    if (!configData) return;

    // Ward selects
    const wardOpts = Object.entries(configData.wards || {}).map(
        ([id, w]) => `<option value="${id}">${w.name} (${id})</option>`
    ).join('');

    const wasteWard = document.getElementById('waste-ward-select');
    if (wasteWard) wasteWard.innerHTML = '<option value="">Select Ward</option>' + wardOpts;
    const roadWard = document.getElementById('road-ward-select');
    if (roadWard) roadWard.innerHTML = '<option value="">Ward</option>' + wardOpts;

    // Segment select
    const segOpts = Object.entries(configData.segments || {}).map(
        ([id, s]) => `<option value="${id}" data-ward="${s.ward_id}">${s.name} (${id})</option>`
    ).join('');

    const roadSeg = document.getElementById('road-segment-select');
    if (roadSeg) {
        roadSeg.innerHTML = '<option value="">Select Segment</option>' + segOpts;
        // Auto-fill ward when segment is selected
        roadSeg.addEventListener('change', () => {
            const opt = roadSeg.options[roadSeg.selectedIndex];
            const wardId = opt?.dataset?.ward;
            if (wardId && roadWard) roadWard.value = wardId;
        });
    }
}

function initForms() {
    // Waste form
    document.getElementById('waste-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const data = {
            bin_id: form.bin_id.value,
            ward_id: form.ward_id.value,
            overflow_level: parseInt(form.overflow_level.value),
            reporter_type: form.reporter_type.value,
        };
        const status = document.getElementById('waste-form-status');
        try {
            const res = await fetch('/api/report/waste', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const result = await res.json();
            status.textContent = `✓ ${result.message}`;
            status.style.color = 'var(--normal)';
            form.reset();
        } catch (err) {
            status.textContent = '✗ Failed to submit';
            status.style.color = 'var(--critical)';
        }
    });

    // Road form
    document.getElementById('road-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const data = {
            segment_id: form.segment_id.value,
            ward_id: form.ward_id.value,
            issue_type: form.issue_type.value,
            severity: parseInt(form.severity.value),
        };
        const status = document.getElementById('road-form-status');
        try {
            const res = await fetch('/api/report/road', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const result = await res.json();
            status.textContent = `✓ ${result.message}`;
            status.style.color = 'var(--normal)';
            form.reset();
        } catch (err) {
            status.textContent = '✗ Failed to submit';
            status.style.color = 'var(--critical)';
        }
    });
}

// ═══════════════════════════════════════════════════════════════════════════
// ADVISORY MODAL
// ═══════════════════════════════════════════════════════════════════════════
async function showAdvisory(targetId, targetType) {
    const modal = document.getElementById('advisory-modal');
    const body = document.getElementById('advisory-body');
    modal.classList.add('visible');
    body.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px;">Loading advisory...</div>';

    try {
        const res = await fetch('/api/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: targetId, target_type: targetType }),
        });
        const data = await res.json();
        const a = data.advisory;

        // Build metrics table
        let metricsHtml = '';
        if (a.metrics) {
            metricsHtml = '<div class="advisory-metrics">' +
                Object.entries(a.metrics).map(([k, v]) =>
                    `<div class="metric"><div class="metric-label">${k.replace(/_/g, ' ')}</div><div class="metric-value">${v}</div></div>`
                ).join('') + '</div>';
        }

        body.innerHTML = `
            <h3>${a.target} — ${a.type}</h3>
            <div class="advisory-field">
                <div class="advisory-field-label">Risk Level</div>
                <div class="advisory-field-value" style="color:${stateColor(a.risk_level)}; font-weight:700;">
                    ${a.risk_level} (Score: ${a.risk_score})
                </div>
            </div>
            <div class="advisory-field">
                <div class="advisory-field-label">Urgency</div>
                <div class="advisory-field-value" style="font-weight:600;color:${urgencyColor(a.urgency)}">
                    ${a.urgency}
                </div>
            </div>
            <div class="advisory-field">
                <div class="advisory-field-label">Primary Factor</div>
                <div class="advisory-field-value">${a.primary_factor || 'No significant triggers.'}</div>
            </div>
            <div class="advisory-field">
                <div class="advisory-field-label">Recommended Action</div>
                <div class="advisory-field-value"><strong>${a.action}</strong></div>
            </div>
            <div class="advisory-field">
                <div class="advisory-field-label">Justification</div>
                <div class="advisory-field-value" style="font-size:13px;color:var(--text-secondary)">${a.justification}</div>
            </div>
            ${metricsHtml}
        `;
    } catch (err) {
        body.innerHTML = '<div style="color:var(--critical);">Failed to load advisory.</div>';
    }
}

function closeModal() {
    document.getElementById('advisory-modal').classList.remove('visible');
}

// Close modal on backdrop click
document.getElementById('advisory-modal')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
});

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════
function classifyState(score) {
    if (score < 30) return 'Normal';
    if (score < 55) return 'Elevated';
    if (score < 75) return 'Warning';
    return 'Critical';
}

function stateColor(state) {
    switch (state) {
        case 'Normal': return '#16A34A';
        case 'Elevated': return '#D97706';
        case 'Warning': return '#EA580C';
        case 'Critical': return '#DC2626';
        default: return '#6B7280';
    }
}

function urgencyColor(urgency) {
    switch (urgency) {
        case 'Immediate': return '#DC2626';
        case 'High': return '#EA580C';
        case 'Moderate': return '#D97706';
        case 'Low': return '#16A34A';
        default: return '#6B7280';
    }
}

function timeAgo(isoStr) {
    if (!isoStr) return 'Never';
    const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return `${Math.round(diff / 86400)}d ago`;
}

function renderFreshness(f) {
    let bar = document.getElementById('freshness-bar');
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'freshness-bar';
        bar.className = 'freshness-bar';
        const indexBar = document.querySelector('.index-bar');
        if (indexBar) indexBar.after(bar);
    }

    const pwStatus = f.pathway_status || 'waiting';
    const pwColor = pwStatus === 'streaming' ? '#16A34A' : '#D97706';
    const weatherSrc = f.weather_source === 'openweathermap' ? '☁ Live' : '⚠ Fallback';
    const weatherSrcColor = f.weather_source === 'openweathermap' ? '#06B6D4' : '#D97706';

    bar.innerHTML = `
        <span class="freshness-item">
            <span class="freshness-dot" style="background:${pwColor}"></span>
            Pathway: <strong>${pwStatus}</strong>
        </span>
        <span class="freshness-item">
            Weather: <strong style="color:${weatherSrcColor}">${weatherSrc}</strong>
            ${f.weather_last_update ? ' · ' + timeAgo(f.weather_last_update) : ''}
        </span>
        <span class="freshness-item">
            Last report: <strong>${f.last_report_ts ? timeAgo(f.last_report_ts) : 'None'}</strong>
        </span>
        ${f.engine_started_at ? `<span class="freshness-item">Engine up: <strong>${timeAgo(f.engine_started_at)}</strong></span>` : ''}
    `;
}
