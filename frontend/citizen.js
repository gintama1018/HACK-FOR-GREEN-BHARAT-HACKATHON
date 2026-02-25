/**
 * InfraWatch Nexus — Citizens' Portal Logic
 * Strictly stateless. Always replaces state from Socket.
 */

const API_BASE = window.location.origin;
const WS_URL = `ws://${window.location.host}/ws`;

let dashboard = null;
let map = null;
let markers = {};
let roadLines = [];
let configData = null;

let detectedDustbinId = null;
let selectedOverflow = 3;
let manualSelectedOverflow = 3;

document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    initTabs();
    initMap();
    initReportFlow();
    connectWebSocket();
});

// ── CONFIG ──────────────────────────────────────────────────────────
async function loadConfig() {
    try {
        const resp = await fetch(`${API_BASE}/api/config`);
        configData = await resp.json();

        const manualWard = document.getElementById('manualWard');
        manualWard.innerHTML = '<option value="">— Select Ward —</option>';
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
        showToast('System configuration failed to load.', 'error');
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
    map = L.map('map', {
        center: [center.lat, center.lng],
        zoom: 11,
        zoomControl: true,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '© CARTO',
        maxZoom: 19,
    }).addTo(map);

    if (configData?.dustbins) {
        for (const [did, info] of Object.entries(configData.dustbins)) {
            const marker = L.circleMarker([info.lat, info.lng], {
                radius: 6,
                fillColor: '#64748B', // Default gray before WS load
                color: '#0F172A',
                weight: 2,
                fillOpacity: 0.9,
            }).addTo(map);

            marker.bindPopup(`<b>${did}</b><br>${info.street}<br>Loading State...`);
            markers[did] = marker;
        }
    }
}

function updateMap() {
    if (!dashboard?.dustbin_states) return;

    for (const ds of dashboard.dustbin_states) {
        const marker = markers[ds.dustbin_id];
        if (!marker) continue;

        let radius = 6;
        if (ds.state === 'Critical') radius = 10;
        else if (ds.state === 'Escalated') radius = 8;
        else if (ds.state === 'Reported') radius = 7;

        marker.setStyle({
            fillColor: ds.color || '#16A34A',
            radius: radius,
        });

        marker.setPopupContent(`
            <div style="font-family: 'Inter', sans-serif;">
                <b style="font-size: 14px;">${ds.dustbin_id}</b><br>
                <div style="font-size: 11px; color: #94A3B8; margin-bottom: 6px;">${ds.street} (${ds.ward_id})</div>
                <div style="background: ${ds.color}20; border: 1px solid ${ds.color}50; color: ${ds.color}; padding: 4px 8px; border-radius: 4px; display: inline-block; font-weight: 600; font-size: 11px;">
                    ● ${ds.state.toUpperCase()}
                </div>
                ${ds.report_count > 0 ? `<div style="margin-top: 6px; font-size: 12px; font-weight: 500;">Civic Reports: ${ds.report_count} | Max Overflow: ${ds.max_overflow}/5</div>` : ''}
            </div>
        `);
    }

    // Road Lines
    roadLines.forEach(line => map.removeLayer(line));
    roadLines = [];

    if (dashboard.road_issues) {
        for (const ri of dashboard.road_issues) {
            const line = L.polyline(
                [[ri.from_lat, ri.from_lng], [ri.to_lat, ri.to_lng]],
                { color: '#EA580C', weight: 4, dashArray: '6,6', opacity: 0.8 }
            ).addTo(map);

            line.bindPopup(`
                <b>🚧 ACTIVE ROAD ISSUE</b><br>
                ${ri.issue_type.toUpperCase()}<br>
                Severity: ${ri.severity}/5
            `);
            roadLines.push(line);
        }
    }
}

// ── REPORT FLOW ─────────────────────────────────────────────────────
function initReportFlow() {
    // Buttons & Elements
    const photoInput = document.getElementById('photoInput');
    const photoPreview = document.getElementById('photoPreview');
    const btnDetect = document.getElementById('btnDetect');
    const btnManual = document.getElementById('btnManual');

    // AI Step (File Selection & Display)
    const handleFile = (f) => {
        if (!f) return;

        // Force file into input if it came from drag and drop
        const dt = new DataTransfer();
        dt.items.add(f);
        photoInput.files = dt.files;

        const reader = new FileReader();
        reader.onload = ev => {
            photoPreview.src = ev.target.result;
            photoPreview.hidden = false;
            btnDetect.hidden = false;
        };
        reader.readAsDataURL(f);
    };

    photoInput.addEventListener('change', (e) => handleFile(e.target.files[0]));

    // Drag and Drop implementation
    const uploadArea = document.querySelector('.upload-area');
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });
    function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }

    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => uploadArea.style.borderColor = 'var(--accent)', false);
    });
    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => uploadArea.style.borderColor = 'var(--border)', false);
    });

    uploadArea.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        handleFile(dt.files[0]);
    }, false);

    btnDetect.addEventListener('click', async () => {
        if (!photoInput.files || photoInput.files.length === 0) {
            showToast('No file attached.', 'error');
            return;
        }

        btnDetect.disabled = true;
        btnDetect.textContent = 'Processing Image Array...';

        try {
            const formData = new FormData();
            formData.append('file', photoInput.files[0]);
            const resp = await fetch(`${API_BASE}/api/report/dustbin/detect`, { method: 'POST', body: formData });

            if (!resp.ok) {
                // If 422 happens, we catch it gracefully
                const errText = await resp.text();
                throw new Error(`HTTP ${resp.status}: ${errText}`);
            }

            const result = await resp.json();

            if (result.fallback || !result.detected_id) {
                showToast(result.message || 'ID Extraction Failed. Bypassing to Manual.', 'error');
                showFlowStep('step3');
            } else {
                detectedDustbinId = result.detected_id;
                document.getElementById('detectedId').textContent = result.detected_id;
                document.getElementById('detectedStreet').textContent = result.street || '';
                showFlowStep('step2');
            }
        } catch (e) {
            showToast('Vision API Error', 'error');
            showFlowStep('step3');
        } finally {
            btnDetect.disabled = false;
            btnDetect.textContent = '🔍 Extract Nearest ID';
        }
    });

    btnManual.addEventListener('click', () => showFlowStep('step3'));

    // Severity Grids
    const setupSevGrid = (gridId, isManual) => {
        const grid = document.getElementById(gridId);
        grid.addEventListener('click', e => {
            if (!e.target.classList.contains('sev-btn')) return;
            grid.querySelectorAll('.sev-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            if (isManual) manualSelectedOverflow = parseInt(e.target.dataset.val);
            else selectedOverflow = parseInt(e.target.dataset.val);
        });
    };
    setupSevGrid('overflowGrid', false);
    setupSevGrid('manualOverflowGrid', true);

    // Submissions
    document.getElementById('btnSubmitReport').addEventListener('click', () => submitReport(detectedDustbinId, selectedOverflow));
    document.getElementById('btnSubmitManual').addEventListener('click', () => {
        const did = document.getElementById('manualDustbin').value;
        if (!did) return showToast('Error: Empty Dustbin ID', 'error');
        submitReport(did, manualSelectedOverflow);
    });

    // Back & Reset
    const resetTo1 = () => {
        photoInput.value = '';
        photoPreview.hidden = true;
        photoPreview.src = '';
        btnDetect.hidden = true;
        detectedDustbinId = null;
        showFlowStep('step1');
    };
    document.getElementById('btnBackStep2').addEventListener('click', resetTo1);
    document.getElementById('btnBackManual').addEventListener('click', resetTo1);
    document.getElementById('btnNewReport').addEventListener('click', resetTo1);
}

function showFlowStep(id) {
    document.querySelectorAll('.flow-step').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
}

async function submitReport(did, level) {
    document.querySelectorAll('.btn-primary').forEach(b => b.disabled = true);
    try {
        const resp = await fetch(`${API_BASE}/api/report/dustbin/confirm`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dustbin_id: did, overflow_level: level }),
        });
        const result = await resp.json();
        if (resp.ok) {
            showToast('Payload Accepted. State Transition Initialized.', 'success');
            showFlowStep('step4');
        } else {
            showToast(`Rejected: ${result.error}`, 'error');
        }
    } catch (e) {
        showToast('Network Transmission Failure.', 'error');
    } finally {
        document.querySelectorAll('.btn-primary').forEach(b => b.disabled = false);
    }
}

// ── LISTS ───────────────────────────────────────────────────────────
function renderLists() {
    if (!dashboard) return;

    // Ward Status
    const wards = dashboard.ward_risks || [];
    const wardContainer = document.getElementById('wardListContainer');
    if (wards.length === 0) {
        wardContainer.innerHTML = '<p class="empty-state">System idle.</p>';
    } else {
        const sorted = [...wards].sort((a, b) => b.risk_score - a.risk_score);
        wardContainer.innerHTML = sorted.map(w => `
            <div class="list-item">
                <div>
                    <div class="list-item-title">${w.name} (${w.ward_id})</div>
                    <div class="list-item-sub">${w.bins_reported} bins flagged | ${w.active_vans} vans deployed</div>
                </div>
                <div style="text-align: right;">
                    <div class="list-value" style="color: ${w.color}">${w.risk_score}</div>
                    <div style="font-size: 10px; font-weight: 700; text-transform: uppercase; color: ${w.color}">${w.state}</div>
                </div>
            </div>
        `).join('');
    }

    // Road Alerts
    const roads = dashboard.road_issues || [];
    const roadContainer = document.getElementById('roadListContainer');
    if (roads.length === 0) {
        roadContainer.innerHTML = '<p class="empty-state">No Active Alerts.</p>';
    } else {
        roadContainer.innerHTML = roads.slice(0, 20).map(r => `
            <div class="list-item" style="border-left: 3px solid #EA580C">
                <div>
                    <div class="list-item-title" style="color: #EA580C">🚧 ${r.issue_type.toUpperCase()} (Sev ${r.severity})</div>
                    <div class="list-item-sub">${r.from_dustbin} → ${r.to_dustbin}</div>
                </div>
                <div style="font-size: 10px; color: var(--text-muted);">${formatTime(r.timestamp)}</div>
            </div>
        `).join('');
    }
}

// ── WEBSOCKET ───────────────────────────────────────────────────────
function connectWebSocket() {
    const statusEl = document.getElementById('wsStatus');
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        statusEl.textContent = '● CONNECTED';
        statusEl.className = 'badge live';
    };

    ws.onmessage = (event) => {
        dashboard = JSON.parse(event.data);

        // Update Top Bar
        document.getElementById('wasteIndexBadge').textContent = `Waste Index: ${dashboard.city_waste_index || 0}`;
        document.getElementById('weatherBadge').textContent = `🌧 ${dashboard.rainfall_mm_hr || 0}mm/hr`;

        updateMap();
        renderLists();
    };

    ws.onclose = () => {
        statusEl.textContent = '● OFFLINE';
        statusEl.className = 'badge dead';
        setTimeout(connectWebSocket, 4000);
    };
    ws.onerror = () => ws.close();
}

function formatTime(iso) {
    try {
        return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    } catch { return ''; }
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
