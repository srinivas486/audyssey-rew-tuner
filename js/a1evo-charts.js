/**
 * A1 Evo AcoustiX — Chart.js integration for target curves and bass management.
 * Renders the curveChart and bassShakerChart from embedded HTML.
 */

let curveChartInstance = null;
let bassShakerChartInstance = null;

// ─── Target Curve Chart ─────────────────────────────────────────────────────
function initCurveChart(canvasId = 'curveChart') {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const ctx = canvas.getContext('2d');

  // Destroy existing
  if (curveChartInstance) {
    curveChartInstance.destroy();
    curveChartInstance = null;
  }

  // Default flat curve
  const defaultCurveData = {
    labels: Array.from({ length: 31 }, (_, i) => 100 + i * 100),
    datasets: [{
      label: 'Target Response',
      data: Array.from({ length: 31 }, () => 0),
      borderColor: '#ffb300',
      backgroundColor: 'rgba(255, 179, 0, 0.1)',
      borderWidth: 2,
      tension: 0.4,
      pointRadius: 0,
      fill: true,
    }]
  };

  curveChartInstance = new Chart(ctx, {
    type: 'line',
    data: defaultCurveData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1a1a',
          borderColor: '#ffb300',
          borderWidth: 1,
          titleColor: '#ffb300',
          bodyColor: '#eceff1',
        }
      },
      scales: {
        x: {
          type: 'logarithmic',
          title: { display: true, text: 'Hz', color: '#90a4ae' },
          ticks: { color: '#90a4ae', maxTicksLimit: 8 },
          grid: { color: 'rgba(255,255,255,0.05)' },
        },
        y: {
          title: { display: true, text: 'dB', color: '#90a4ae' },
          ticks: { color: '#90a4ae' },
          grid: { color: 'rgba(255,255,255,0.05)' },
          min: -12,
          max: 12,
        }
      }
    }
  });

  return curveChartInstance;
}

function updateCurveChart(curveData, label = 'Target Response') {
  if (!curveChartInstance) {
    initCurveChart();
  }
  if (!curveChartInstance) return;

  // curveData format: [[freq, dB], ...] or flat array of dB values at fixed freqs
  let labels, data;
  
  if (Array.isArray(curveData) && Array.isArray(curveData[0])) {
    // [[freq, dB], ...] pairs
    labels = curveData.map(p => p[0]);
    data = curveData.map(p => p[1]);
  } else if (Array.isArray(curveData)) {
    data = curveData;
    labels = Array.from({ length: data.length }, (_, i) => 100 + i * 100);
  } else {
    return;
  }

  curveChartInstance.data.labels = labels;
  curveChartInstance.data.datasets[0].data = data;
  curveChartInstance.data.datasets[0].label = label;
  curveChartInstance.update();
}

// ─── Bass Shaker Chart ────────────────────────────────────────────────────────
function initBassShakerChart(canvasId = 'bassShakerChart') {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const ctx = canvas.getContext('2d');

  if (bassShakerChartInstance) {
    bassShakerChartInstance.destroy();
    bassShakerChartInstance = null;
  }

  bassShakerChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [20, 30, 40, 50, 60, 80, 100, 150, 200, 300],
      datasets: [{
        label: 'Shaker Target',
        data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        borderColor: '#ffb300',
        backgroundColor: 'rgba(255, 179, 0, 0.15)',
        borderWidth: 2,
        tension: 0.4,
        pointRadius: 0,
        fill: true,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: { legend: { display: false } },
      scales: {
        x: {
          type: 'logarithmic',
          ticks: { color: '#90a4ae', maxTicksLimit: 6 },
          grid: { color: 'rgba(255,255,255,0.05)' },
        },
        y: {
          ticks: { color: '#90a4ae' },
          grid: { color: 'rgba(255,255,255,0.05)' },
          min: -20,
          max: 6,
        }
      }
    }
  });

  return bassShakerChartInstance;
}

function updateBassShakerChart(curveData) {
  if (!bassShakerChartInstance) {
    initBassShakerChart();
  }
  if (!bassShakerChartInstance) return;

  if (Array.isArray(curveData) && Array.isArray(curveData[0])) {
    bassShakerChartInstance.data.labels = curveData.map(p => p[0]);
    bassShakerChartInstance.data.datasets[0].data = curveData.map(p => p[1]);
  } else if (Array.isArray(curveData)) {
    bassShakerChartInstance.data.datasets[0].data = curveData;
  }
  bassShakerChartInstance.update();
}

// ─── Parse .txt curve file ───────────────────────────────────────────────────
/**
 * Parse a target curve file (text, one freq/gain pair per line, tab or comma separated).
 * Returns [[freq, dB], ...]
 */
function parseCurveFile(content) {
  const lines = content.trim().split('\n');
  const data = [];
  
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    
    // Split by tab, comma, or whitespace
    const parts = trimmed.split(/[\t,]+/).map(p => p.trim());
    if (parts.length >= 2) {
      const freq = parseFloat(parts[0]);
      const gain = parseFloat(parts[1]);
      if (!isNaN(freq) && !isNaN(gain)) {
        data.push([freq, gain]);
      }
    }
  }
  
  return data.sort((a, b) => a[0] - b[0]);
}

// ─── Sync crossover slider track ─────────────────────────────────────────────
/**
 * Initialize dual-thumb crossover slider (min + max range).
 * From embedded HTML's crossover-slider class.
 */
function initCrossoverSlider(containerId, minInput, maxInput) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const track = container.querySelector('.track');
  const trackInfill = container.querySelector('.track-infill');
  const minSlider = container.querySelector(`input[name="${minInput}"]`);
  const maxSlider = container.querySelector(`input[name="${maxInput}"]`);

  if (!minSlider || !maxSlider) return;

  function updateTrack() {
    const min = parseInt(minSlider.value);
    const max = parseInt(maxSlider.value);
    const rangeMin = parseInt(minSlider.min);
    const rangeMax = parseInt(maxSlider.max);
    const range = rangeMax - rangeMin;

    const minPct = ((min - rangeMin) / range) * 100;
    const maxPct = ((max - rangeMin) / range) * 100;

    if (trackInfill) {
      trackInfill.style.left = minPct + '%';
      trackInfill.style.width = (maxPct - minPct) + '%';
    }
  }

  minSlider.addEventListener('input', updateTrack);
  maxSlider.addEventListener('input', updateTrack);
  updateTrack();
}

// Init all crossover sliders on page
function initAllCrossoverSliders() {
  const sliderContainers = document.querySelectorAll('.a1evo-crossover-slider');
  // For each container, find the two range inputs and init
  document.querySelectorAll('[id$="XOGroup"]').forEach(group => {
    const minInput = group.querySelector('input[name$="CrossoverMin"]');
    const maxInput = group.querySelector('input[name$="CrossoverMax"]');
    if (minInput && maxInput) {
      const baseName = minInput.name.replace('CrossoverMin', '');
      initCrossoverSlider(group.querySelector('.a1evo-crossover-slider')?.id || group.id, baseName + 'CrossoverMin', baseName + 'CrossoverMax');
    }
  });
}