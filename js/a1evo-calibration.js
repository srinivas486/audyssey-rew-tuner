/**
 * A1 Evo AcoustiX — .oca save/load + .ady import
 * 
 * .oca format (A1 Evo's native calibration format):
 * {
 *   version: "1.0",
 *   appVersion: "3.0", 
 *   createdAt: "<ISO timestamp>",
 *   avr: { host, model, hasHeightSpeakers },
 *   channels: [{ channel, distance_mm, trim_x10, filters: [] }],
 *   targetCurve: "acoustix.txt",
 *   settings: { ... full form state ... }
 * }
 */

const OCA_VERSION = '1.0';
const OCA_APP_VERSION = '3.0';

/**
 * Build an OCA calibration object from current form state.
 */
function buildOcaCalibration(avrInfo = {}, formValues = {}, channels = []) {
  return {
    version: OCA_VERSION,
    appVersion: OCA_APP_VERSION,
    createdAt: new Date().toISOString(),
    avr: {
      host: avrInfo.host || '',
      model: avrInfo.model || '',
      hasHeightSpeakers: avrInfo.hasHeightSpeakers || false,
    },
    channels: channels,
    targetCurve: formValues.targetCurve || 'acoustix.txt',
    settings: formValues,
  };
}

/**
 * Serialize form values to OCA format.
 */
function serializeFormToOca() {
  const form = document.getElementById('a1evo-settings-form');
  if (!form) return null;

  const fd = new FormData(form);
  const values = {};
  for (const [k, v] of fd.entries()) {
    values[k] = v;
  }
  // Checkboxes
  form.querySelectorAll('input[type="checkbox"]').forEach(el => {
    values[el.name] = el.checked;
  });

  const avrInfo = a1evoState?.avr || {};
  return buildOcaCalibration(avrInfo, values, []);
}

/**
 * Load OCA calibration and populate form.
 */
function deserializeOcaToForm(oca) {
  if (!oca || !oca.settings) return;

  const form = document.getElementById('a1evo-settings-form');
  if (!form) return;

  const settings = oca.settings;

  // Set text/number inputs
  Object.keys(settings).forEach(key => {
    const el = form.querySelector(`[name="${key}"]`);
    if (!el) return;
    if (el.type === 'checkbox') {
      el.checked = settings[key];
    } else if (el.tagName === 'SELECT') {
      el.value = settings[key];
    } else {
      el.value = settings[key];
    }
  });
}

/**
 * Parse a Denon MultEQ Editor .ady file (JSON).
 * Normalize it to internal channel format.
 * 
 * ADY format:
 * {
 *   detectedChannels: [{
 *     channelName: "FL",
 *     responseData: [[freq, dB], ...],
 *     peqFilters: [{ freq, gain, q }, ...]
 *   }],
 *   channelReport: {...},
 *   micCalibration: {...}
 * }
 */
function parseAdyFile(jsonData) {
  if (typeof jsonData === 'string') {
    jsonData = JSON.parse(jsonData);
  }

  const channels = [];
  if (jsonData.detectedChannels) {
    for (const ch of jsonData.detectedChannels) {
      const channel = {
        name: ch.channelName,
        responseData: ch.responseData || [],
        filters: (ch.peqFilters || []).map(f => ({
          freq: f.freq,
          gain: f.gain,
          q: f.q,
        })),
      };
      channels.push(channel);
    }
  }

  return {
    channels,
    micCalibration: jsonData.micCalibration || {},
    channelReport: jsonData.channelReport || {},
  };
}

/**
 * Import a .ady file via file input.
 */
async function importAdyFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const json = JSON.parse(e.target.result);
        const parsed = parseAdyFile(json);
        resolve(parsed);
      } catch (err) {
        reject(new Error('Invalid ADY file: ' + err.message));
      }
    };
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsText(file);
  });
}

/**
 * Save current calibration as .oca file.
 */
async function saveCurrentCalibration(name) {
  const oca = serializeFormToOca();
  if (!oca) return { success: false, error: 'Nothing to save' };
  return saveCalibration(name, oca);
}

/**
 * Load a calibration by name.
 */
async function loadCalibrationByName(name) {
  const data = await loadCalibration(name);
  if (data && data.channels) {
    deserializeOcaToForm(data);
  }
  return data;
}

/**
 * Export calibration as JSON download.
 */
function exportCalibrationAsJson(oca) {
  const blob = new Blob([JSON.stringify(oca, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = (oca.settings?.targetCurve || 'calibration') + '.oca.json';
  a.click();
  URL.revokeObjectURL(url);
}