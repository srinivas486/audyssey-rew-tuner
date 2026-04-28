/**
 * A1 Evo AcoustiX — REW API Integration
 * Proxies REW API calls through our server to localhost:4735
 * 
 * REW API Endpoints (port 4735):
 *   POST /eq/import-impulse  — Import IR as base64 Big-Endian IEEE 754 float32
 *   POST /eq/filter          — Configure filter tasks
 *   POST /eq/match-target    — Match target curve
 *   GET  /measurements/curve — Get resulting curve data
 *   GET  /eq/house-curve     — House curve
 *   POST /eq/export-raw     — Export filter coefficients
 */

const REW_CHANNELS = ['FL','FR','C','SW','SL','SR','BL','BR','SBL','SBR','FD','FS','TM','RL','RR'];

/**
 * Import impulse response into REW for a specific channel.
 * @param {string} channel - e.g. 'FL'
 * @param {Float32Array|Uint8Array} irData - impulse response data
 * @param {number} sampleRate - sample rate (default 48000)
 * @returns {Promise<object>}
 */
async function rewImportImpulse(channel, irData, sampleRate = 48000) {
  // Convert to base64 Big-Endian IEEE 754 float32
  let buffer;
  if (irData instanceof Float32Array) {
    buffer = new ArrayBuffer(irData.length * 4);
    const view = new DataView(buffer);
    for (let i = 0; i < irData.length; i++) {
      view.setFloat32(i * 4, irData[i], false); // Big-Endian
    }
  } else {
    buffer = irData.buffer;
  }

  const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));

  const res = await fetch('/api/rew/eq/import-impulse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel, irData: base64, sampleRate }),
  });
  return res.json();
}

/**
 * Configure REW filter tasks.
 * @param {Array<{channel, filters}>} tasks
 * @returns {Promise<object>}
 */
async function rewConfigureFilters(tasks) {
  const res = await fetch('/api/rew/eq/filter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tasks }),
  });
  return res.json();
}

/**
 * Match measurement to a target curve.
 * @param {string} channel
 * @param {string} targetCurveFile - filename in target_curves/
 * @param {object} options - { maxFilters, targetLevel, freqLimit }
 * @returns {Promise<object>}
 */
async function rewMatchTarget(channel, targetCurveFile, options = {}) {
  // Load target curve content first
  let targetCurve = null;
  try {
    const res = await fetch(`/api/target-curves/${encodeURIComponent(targetCurveFile)}`);
    targetCurve = await res.text();
  } catch (e) {
    console.warn('Could not load target curve file, using default');
  }

  const body = {
    channel,
    targetCurve: targetCurveFile,
    ...options,
  };

  const res = await fetch('/api/rew/eq/match-target', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

/**
 * Get measurement curve for a channel.
 * @param {string} channel
 * @returns {Promise<Array<[freq, dB]>>}
 */
async function rewGetMeasurementCurve(channel) {
  const res = await fetch(`/api/rew/measurements/curve?channel=${channel}`);
  const data = await res.json();
  
  // Normalize to [[freq, dB], ...] format
  if (Array.isArray(data)) {
    return data;
  }
  if (data.data) {
    return data.data;
  }
  return [];
}

/**
 * Set house curve in REW.
 * @param {Array<[freq, dB]>} curveData
 * @returns {Promise<object>}
 */
async function rewSetHouseCurve(curveData) {
  const res = await fetch('/api/rew/eq/house-curve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ curveData }),
  });
  return res.json();
}

/**
 * Get current house curve from REW.
 * @returns {Promise<Array<[freq, dB]>>}
 */
async function rewGetHouseCurve() {
  const res = await fetch('/api/rew/eq/house-curve');
  return res.json();
}

/**
 * Export raw filter coefficients from REW.
 * @param {string} channel
 * @returns {Promise<object>}
 */
async function rewExportRaw(channel) {
  const res = await fetch('/api/rew/eq/export-raw', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel }),
  });
  return res.json();
}

/**
 * Full optimization workflow for one channel:
 * 1. Import IR → 2. Match target → 3. Export coefficients
 */
async function rewFullOptimization(channel, targetCurveFile, irData, options = {}) {
  const results = {
    channel,
    imported: false,
    matched: false,
    filters: [],
    coefficients: null,
  };

  try {
    // Step 1: Import IR
    const importResult = await rewImportImpulse(channel, irData);
    results.imported = !importResult.error;

    // Step 2: Match target
    const matchResult = await rewMatchTarget(channel, targetCurveFile, options);
    results.matched = !matchResult.error;
    if (matchResult.filters) {
      results.filters = matchResult.filters;
    }
  } catch (err) {
    console.error(`REW optimization failed for ${channel}:`, err);
  }

  return results;
}