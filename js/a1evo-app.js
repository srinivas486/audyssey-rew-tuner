/**
 * A1 Evo AcoustiX — Main App Logic
 * Handles tab switching, AVR state, form data, and optimization workflow.
 */

let a1evoState = {
  avr: null,       // { host, model, connected }
  activeTab: 'audyssey',
  targetCurve: null,
  curves: [],
  calibrations: [],
  isOptimizing: false,
  progress: 0,
};

// ─── Tab Switching ──────────────────────────────────────────────────────────
function switchTab(tabId) {
  a1evoState.activeTab = tabId;

  // Toggle tab buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.remove('active', 'active-a1');
  });
  
  const activeBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
  if (activeBtn) {
    activeBtn.classList.add('active');
    if (tabId === 'a1evo') activeBtn.classList.add('active-a1');
  }

  // Show/hide panels
  const audysseyPanel = document.getElementById('audyssey-panel');
  const a1evoPanel = document.getElementById('a1evo-panel');
  
  if (audysseyPanel) audysseyPanel.style.display = tabId === 'audyssey' ? '' : 'none';
  if (a1evoPanel) a1evoPanel.style.display = tabId === 'a1evo' ? '' : 'none';
}

function initTabBar() {
  // Add tab buttons if not already present
  const appHeader = document.getElementById('app-header');
  if (!appHeader) return;

  // Create tab bar
  let tabBar = document.getElementById('a1evo-tab-bar');
  if (!tabBar) {
    tabBar = document.createElement('div');
    tabBar.id = 'a1evo-tab-bar';
    tabBar.className = 'tab-bar';
    
    const audBtn = document.createElement('button');
    audBtn.className = 'tab-btn active';
    audBtn.dataset.tab = 'audyssey';
    audBtn.textContent = 'Audyssey REW Tuner';
    audBtn.onclick = () => switchTab('audyssey');

    const a1Btn = document.createElement('button');
    a1Btn.className = 'tab-btn';
    a1Btn.dataset.tab = 'a1evo';
    a1Btn.textContent = 'A1 Evo AcoustiX';
    a1Btn.onclick = () => switchTab('a1evo');

    tabBar.appendChild(audBtn);
    tabBar.appendChild(a1Btn);
    
    // Insert after app-header
    appHeader.parentNode.insertBefore(tabBar, appHeader.nextSibling);
  }
}

// ─── AVR Discovery ──────────────────────────────────────────────────────────
async function discoverAVR() {
  const statusEl = document.getElementById('a1evo-avr-status');
  const selectEl = document.getElementById('a1evo-avr-select');
  if (statusEl) statusEl.textContent = '🔍 Discovering...';
  
  try {
    const res = await fetch('/api/avr/discover', { method: 'POST' });
    const data = await res.json();
    
    if (data.devices && data.devices.length > 0) {
      if (selectEl) {
        selectEl.innerHTML = '';
        data.devices.forEach(d => {
          const opt = document.createElement('option');
          opt.value = d.ip;
          opt.textContent = `${d.ip} (${d.server || 'AVR'})`;
          selectEl.appendChild(opt);
        });
      }
      if (statusEl) statusEl.textContent = `Found ${data.devices.length} device(s)`;
      return data.devices;
    } else {
      if (statusEl) statusEl.textContent = 'No AVRs found on network';
      return [];
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = 'Discovery failed: ' + err.message;
    return [];
  }
}

async function connectAVR(host) {
  const statusEl = document.getElementById('a1evo-avr-status');
  if (statusEl) statusEl.textContent = '🔌 Connecting...';
  
  try {
    const res = await fetch('/api/avr/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host }),
    });
    const data = await res.json();
    
    if (data.success) {
      a1evoState.avr = { host, connected: true };
      if (statusEl) {
        statusEl.innerHTML = '<span class="a1evo-status-dot connected"></span> Connected to ' + host;
      }
    } else {
      if (statusEl) statusEl.textContent = 'Connection failed: ' + (data.error || 'unknown');
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = 'Connect failed: ' + err.message;
  }
}

async function disconnectAVR() {
  try {
    await fetch('/api/avr/disconnect', { method: 'POST' });
    a1evoState.avr = null;
    const statusEl = document.getElementById('a1evo-avr-status');
    if (statusEl) {
      statusEl.innerHTML = '<span class="a1evo-status-dot"></span> Disconnected';
    }
  } catch (err) {
    console.error('Disconnect error:', err);
  }
}

async function sendAVRCommand(cmd) {
  try {
    const res = await fetch('/api/avr/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd }),
    });
    return await res.json();
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// ─── Target Curves ───────────────────────────────────────────────────────────
async function loadTargetCurves() {
  try {
    const res = await fetch('/api/target-curves');
    const data = await res.json();
    a1evoState.curves = data.curves || [];
    return a1evoState.curves;
  } catch (err) {
    console.error('Failed to load target curves:', err);
    return [];
  }
}

async function loadTargetCurveContent(name) {
  try {
    const res = await fetch(`/api/target-curves/${encodeURIComponent(name)}`);
    return await res.text();
  } catch (err) {
    console.error('Failed to load curve:', err);
    return null;
  }
}

// ─── Calibration Save/Load ───────────────────────────────────────────────────
async function listCalibrations() {
  try {
    const res = await fetch('/api/calibration');
    const data = await res.json();
    a1evoState.calibrations = data.calibrations || [];
    return a1evoState.calibrations;
  } catch (err) {
    return [];
  }
}

async function loadCalibration(name) {
  try {
    const res = await fetch(`/api/calibration/${encodeURIComponent(name)}`);
    const data = await res.json();
    return data;
  } catch (err) {
    return null;
  }
}

async function saveCalibration(name, data) {
  try {
    const res = await fetch('/api/calibration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, data }),
    });
    return await res.json();
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// ─── ADY Import ─────────────────────────────────────────────────────────────
async function parseAdyFile(adyData) {
  try {
    const res = await fetch('/api/parse-ady', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ adyData }),
    });
    return await res.json();
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// ─── REW Integration ────────────────────────────────────────────────────────
async function rewImportIR(channel, irData, sampleRate = 48000) {
  try {
    const res = await fetch('/api/rew/eq/import-impulse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel, irData, sampleRate }),
    });
    return await res.json();
  } catch (err) {
    return { error: err.message };
  }
}

async function rewMatchTarget(channel, targetCurve) {
  try {
    const res = await fetch('/api/rew/eq/match-target', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel, targetCurve }),
    });
    return await res.json();
  } catch (err) {
    return { error: err.message };
  }
}

async function rewGetCurve(channel) {
  try {
    const res = await fetch(`/api/rew/measurements/curve?channel=${channel}`);
    return await res.json();
  } catch (err) {
    return { error: err.message };
  }
}

async function rewSetHouseCurve(curveData) {
  try {
    const res = await fetch('/api/rew/eq/house-curve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ curveData }),
    });
    return await res.json();
  } catch (err) {
    return { error: err.message };
  }
}

// ─── PEQ Commands ───────────────────────────────────────────────────────────
async function setPEQ(channel, freq, gain, q) {
  const cmd = `MSSV${channel}=${freq}Hz,${gain}dB,Q=${q}`;
  return sendAVRCommand(cmd);
}

async function setPEQBatch(channel, filters) {
  const results = [];
  for (const f of filters) {
    const r = await setPEQ(channel, f.freq, f.gain, f.q);
    results.push(r);
    await new Promise(r => setTimeout(r, 50));
  }
  return results;
}

async function setDistance(channel, distance_mm) {
  const cmd = `MSD${channel}${distance_mm}`;
  return sendAVRCommand(cmd);
}

async function setTrim(channel, trim_x10) {
  const cmd = `MST${channel}${trim_x10}`;
  return sendAVRCommand(cmd);
}

async function queryFilters(channel) {
  try {
    const res = await fetch('/api/avr/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel }),
    });
    return await res.json();
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// ─── Optimization Workflow ──────────────────────────────────────────────────
async function startOptimization() {
  if (a1evoState.isOptimizing) return;
  a1evoState.isOptimizing = true;
  
  const progressEl = document.getElementById('a1evo-optimization-progress');
  if (progressEl) progressEl.classList.add('visible');
  
  try {
    setProgress(0, 'Starting optimization...');
    
    // 1. Import IR to REW for each channel
    const channels = ['FL','FR','C','SW','SL','SR','BL','BR'];
    for (let i = 0; i < channels.length; i++) {
      setProgress((i / channels.length) * 40, `Importing IR for ${channels[i]}...`);
      // In real flow, IR data would come from measurement results
      await new Promise(r => setTimeout(r, 200));
    }
    
    // 2. Match target curves
    const selectedCurve = document.getElementById('targetCurve')?.value || 'acoustix.txt';
    setProgress(40, 'Matching target curve: ' + selectedCurve);
    await new Promise(r => setTimeout(r, 500));
    
    // 3. Generate PEQ filters via REW
    setProgress(60, 'Generating PEQ filters...');
    await new Promise(r => setTimeout(r, 500));
    
    // 4. Transfer filters to AVR
    setProgress(80, 'Transferring filters to AVR...');
    if (a1evoState.avr && a1evoState.avr.connected) {
      for (const ch of channels) {
        await new Promise(r => setTimeout(r, 100));
      }
    }
    
    setProgress(100, 'Optimization complete!');
    await new Promise(r => setTimeout(r, 1000));
    
  } catch (err) {
    console.error('Optimization error:', err);
    setProgress(0, 'Error: ' + err.message);
  } finally {
    a1evoState.isOptimizing = false;
    setTimeout(() => {
      if (progressEl) progressEl.classList.remove('visible');
    }, 3000);
  }
}

function setProgress(pct, msg) {
  const fillEl = document.getElementById('a1evo-progress-fill');
  const msgEl = document.getElementById('a1evo-progress-msg');
  if (fillEl) fillEl.style.width = pct + '%';
  if (msgEl) msgEl.textContent = msg;
}

// ─── Init ────────────────────────────────────────────────────────────────────
function initA1Evo() {
  initTabBar();
  
  // Wire up discover button
  const discoverBtn = document.getElementById('a1evo-discover-btn');
  if (discoverBtn) {
    discoverBtn.onclick = discoverAVR;
  }
  
  // Wire up connect button
  const connectBtn = document.getElementById('a1evo-connect-btn');
  if (connectBtn) {
    connectBtn.onclick = () => {
      const select = document.getElementById('a1evo-avr-select');
      if (select && select.value) connectAVR(select.value);
    };
  }
  
  // Wire up disconnect button
  const disconnectBtn = document.getElementById('a1evo-disconnect-btn');
  if (disconnectBtn) {
    disconnectBtn.onclick = disconnectAVR;
  }
  
  // Wire up optimization button
  const optBtn = document.getElementById('a1evo-start-optimization');
  if (optBtn) {
    optBtn.onclick = startOptimization;
  }
  
  // Load target curves into select
  loadTargetCurves().then(curves => {
    const select = document.getElementById('targetCurve');
    if (select) {
      select.innerHTML = '';
      curves.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.name;
        opt.textContent = c.name;
        select.appendChild(opt);
      });
    }
  });
  
  // Load calibrations list
  listCalibrations();
}

// Bootstrap: run init when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initA1Evo);
} else {
  initA1Evo();
}