/**
 * A1 Evo AcoustiX — Standalone Express Server
 * Serves the Audyssey REW Tuner SPA and provides A1 Evo API routes.
 * 
 * Routes:
 *   POST /api/avr/discover    — SSDP multicast AVR discovery
 *   POST /api/avr/command     — Send Telnet command to AVR
 *   POST /api/avr/connect     — Connect to AVR via Telnet
 *   POST /api/avr/disconnect  — Disconnect Telnet
 *   GET  /api/rew/*           — Proxy to REW API (localhost:4735)
 *   GET  /api/calibration     — List saved calibrations
 *   GET  /api/calibration/:name — Load a calibration (.oca)
 *   POST /api/calibration     — Save calibration (.oca)
 *   GET  /api/target-curves   — List target curve files
 */

const http = require('http');
const path = require('path');
const fs = require('fs');
const dgram = require('dgram');
const net = require('net');

// ─── Port Selection ────────────────────────────────────────────────────────
function findFreePort(startPort = 18443) {
  return new Promise((resolve, reject) => {
    const server = http.createServer();
    server.listen(startPort, '0.0.0.0', () => {
      resolve(server.address().port);
      server.close();
    });
    server.on('error', (err) => {
      if (err.code === 'EADDRINUSE') {
        resolve(findFreePort(startPort + 1));
      } else {
        reject(err);
      }
    });
  });
}

// ─── Static File Server ─────────────────────────────────────────────────────
function serveStatic(req, res, baseDir) {
  let urlPath = req.url.split('?')[0];
  if (urlPath === '/' || urlPath === '/index.html') {
    urlPath = '/index.html';
  }
  const filePath = path.join(baseDir, decodeURIComponent(urlPath));

  // Security: prevent path traversal
  const resolved = path.resolve(filePath);
  if (!resolved.startsWith(baseDir)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  const ext = path.extname(filePath).toLowerCase();
  const mimeTypes = {
    '.html': 'text/html',
    '.js':   'application/javascript',
    '.css':  'text/css',
    '.json': 'application/json',
    '.txt':  'text/plain',
    '.ady':  'application/json',
    '.oca':  'application/json',
  };
  const contentType = mimeTypes[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end(`Not found: ${urlPath}`);
      return;
    }
    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
}

// ─── AVR Client (in-memory singleton) ──────────────────────────────────────
let avrSocket = null;
let avrHost = null;
let avrPort = 23;

const AVR_CHANNELS = ['FL','FR','C','SW','SL','SR','BL','BR','SBL','SBR','FD','FS','TM','RL','RR'];

function avrConnect(host) {
  return new Promise((resolve, reject) => {
    if (avrSocket && !avrSocket.destroyed) {
      avrSocket.destroy();
    }
    avrHost = host;
    avrSocket = net.connect(23, host);

    const timeout = setTimeout(() => {
      avrSocket.destroy();
      reject(new Error('Connection timeout'));
    }, 5000);

    avrSocket.on('connect', () => {
      clearTimeout(timeout);
      // Handle telnet negotiation (IAC commands)
      avrSocket.once('data', (data) => {
        // Just consume any initial telnet negotiation bytes
        resolve({ host, port: 23, connected: true });
      });
      // Send a no-op to trigger response
      avrSocket.write('?\r', () => {});
      // Give it a moment then resolve
      setTimeout(() => resolve({ host, port: 23, connected: true }), 500);
    });

    avrSocket.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });
  });
}

function avrSendCommand(cmd) {
  return new Promise((resolve, reject) => {
    if (!avrSocket || avrSocket.destroyed) {
      reject(new Error('AVR not connected'));
      return;
    }
    let response = '';
    const timeout = setTimeout(() => {
      avrSocket.removeListener('data', onData);
      reject(new Error('Command timeout'));
    }, 5000);

    function onData(data) {
      response += data.toString();
      // Denon sends response ending with \r after each command
      if (response.includes('\r') || response.includes('\n')) {
        clearTimeout(timeout);
        avrSocket.removeListener('data', onData);
        resolve(response.trim());
      }
    }

    avrSocket.on('data', onData);
    avrSocket.write(cmd + '\r', (err) => {
      if (err) {
        clearTimeout(timeout);
        avrSocket.removeListener('data', onData);
        reject(err);
      }
    });
  });
}

function avrDisconnect() {
  return new Promise((resolve) => {
    if (avrSocket && !avrSocket.destroyed) {
      avrSocket.destroy();
    }
    avrSocket = null;
    avrHost = null;
    resolve({ disconnected: true });
  });
}

// ─── SSDP Discovery ─────────────────────────────────────────────────────────
function ssdpDiscover() {
  return new Promise((resolve, reject) => {
    const client = dgram.createSocket({ type: 'udp4', reuseAddr: true });
    const timeout = setTimeout(() => {
      client.close();
      resolve([]);
    }, 4000);

    const results = [];

    client.on('message', (msg, rinfo) => {
      const str = msg.toString();
      if (str.includes('Denon') || str.includes('Marantz') || str.includes('ACT-DenonDevice')) {
        const locationMatch = str.match(/LOCATION:\s*(.+)/i);
        const serverMatch = str.match(/SERVER:\s*(.+)/i);
        const usnMatch = str.match(/USN:\s*(.+)/i);
        results.push({
          ip: rinfo.address,
          location: locationMatch ? locationMatch[1].trim() : null,
          server: serverMatch ? serverMatch[1].trim() : null,
          usn: usnMatch ? usnMatch[1].trim() : null,
        });
      }
    });

    client.bind(() => {
      client.setBroadcast(true);
      const search = [
        'M-SEARCH * HTTP/1.1',
        'HOST: 239.255.255.250:1900',
        'MAN: "ssdp:discover"',
        'MX: 3',
        'ST: urn:schemas-denon-com:device:ACT-DenonDeviceService:1',
        '', ''
      ].join('\r\n');

      client.send(search, 0, search.length, 1900, '239.255.255.250', (err) => {
        if (err) {
          clearTimeout(timeout);
          client.close();
          reject(err);
        }
      });
    });

    client.on('error', (err) => {
      clearTimeout(timeout);
      client.close();
      reject(err);
    });
  });
}

// ─── REW API Proxy ──────────────────────────────────────────────────────────
const REW_API = 'http://127.0.0.1:4735';

function proxyRew(req, res, pathSuffix, body) {
  return new Promise((resolve, reject) => {
    const url = `${REW_API}${pathSuffix}`;
    const options = {
      method: body ? 'POST' : 'GET',
      headers: { 'Content-Type': 'application/json' },
    };
    const fetchReq = http.request(url, options, (fetchRes) => {
      let data = '';
      fetchRes.on('data', (chunk) => data += chunk);
      fetchRes.on('end', () => {
        try {
          resolve({ status: fetchRes.statusCode, body: JSON.parse(data) });
        } catch {
          resolve({ status: fetchRes.statusCode, body: data });
        }
      });
    });
    fetchReq.on('error', reject);
    if (body) fetchReq.write(JSON.stringify(body));
    fetchReq.end();
  });
}

// ─── Calibration Storage ────────────────────────────────────────────────────
const CALIBRATION_DIR = path.join(__dirname, 'calibrations');
const TARGET_CURVES_DIR = path.join(__dirname, 'target_curves');

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function listCalibrations() {
  ensureDir(CALIBRATION_DIR);
  return fs.readdirSync(CALIBRATION_DIR)
    .filter(f => f.endsWith('.oca'))
    .map(f => ({ name: f.replace('.oca', ''), file: f }));
}

function loadCalibration(name) {
  const filePath = path.join(CALIBRATION_DIR, name + '.oca');
  if (!fs.existsSync(filePath)) throw new Error('Calibration not found');
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function saveCalibration(name, data) {
  ensureDir(CALIBRATION_DIR);
  const filePath = path.join(CALIBRATION_DIR, name + '.oca');
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
  return { saved: true, path: filePath };
}

function listTargetCurves() {
  ensureDir(TARGET_CURVES_DIR);
  if (!fs.existsSync(TARGET_CURVES_DIR)) return [];
  return fs.readdirSync(TARGET_CURVES_DIR)
    .filter(f => f.endsWith('.txt') || f.endsWith('.curve'))
    .map(f => ({ name: f, file: f }));
}

function getTargetCurve(name) {
  const filePath = path.join(TARGET_CURVES_DIR, name);
  if (!fs.existsSync(filePath)) throw new Error('Target curve not found');
  return fs.readFileSync(filePath, 'utf8');
}

// ─── Parse JSON body helper ─────────────────────────────────────────────────
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => body += chunk);
    req.on('end', () => {
      try { resolve(body ? JSON.parse(body) : {}); }
      catch (e) { reject(new Error('Invalid JSON')); }
    });
    req.on('error', reject);
  });
}

// ─── Router ─────────────────────────────────────────────────────────────────
async function handleRequest(req, res, baseDir) {
  const url = new URL(req.url, 'http://localhost');
  const pathname = url.pathname;

  // CORS for local dev
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  try {
    // ─── SSDP AVR Discovery ───────────────────────────────────────────
    if (pathname === '/api/avr/discover' && req.method === 'POST') {
      const results = await ssdpDiscover();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, devices: results }));
      return;
    }

    // ─── AVR Telnet Connect ───────────────────────────────────────────
    if (pathname === '/api/avr/connect' && req.method === 'POST') {
      const body = await parseBody(req);
      const result = await avrConnect(body.host);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, ...result }));
      return;
    }

    // ─── AVR Telnet Disconnect ────────────────────────────────────────
    if (pathname === '/api/avr/disconnect' && req.method === 'POST') {
      const result = await avrDisconnect();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(result));
      return;
    }

    // ─── AVR Send Command ─────────────────────────────────────────────
    if (pathname === '/api/avr/command' && req.method === 'POST') {
      const body = await parseBody(req);
      try {
        const response = await avrSendCommand(body.command);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: true, response }));
      } catch (err) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: err.message }));
      }
      return;
    }

    // ─── AVR Query (MSQ) ──────────────────────────────────────────────
    if (pathname === '/api/avr/query' && req.method === 'POST') {
      const body = await parseBody(req);
      const channel = body.channel || 'FL';
      try {
        const response = await avrSendCommand(`MSQ${channel}`);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: true, response }));
      } catch (err) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: err.message }));
      }
      return;
    }

    // ─── REW Proxy ────────────────────────────────────────────────────
    if (pathname.startsWith('/api/rew/')) {
      const suffix = pathname.replace('/api/rew', '');
      let body = null;
      if (['POST', 'PUT'].includes(req.method)) {
        body = await parseBody(req);
      }
      const result = await proxyRew(req, res, suffix, body);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(result.body));
      return;
    }

    // ─── Calibration Routes ───────────────────────────────────────────
    if (pathname === '/api/calibration' && req.method === 'GET') {
      const list = listCalibrations();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, calibrations: list }));
      return;
    }

    if (pathname === '/api/calibration' && req.method === 'POST') {
      const body = await parseBody(req);
      if (!body.name) throw new Error('Missing name');
      const result = saveCalibration(body.name, body.data);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, ...result }));
      return;
    }

    if (pathname.startsWith('/api/calibration/') && req.method === 'GET') {
      const name = decodeURIComponent(pathname.replace('/api/calibration/', ''));
      const data = loadCalibration(name);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, ...data }));
      return;
    }

    // ─── Target Curves ────────────────────────────────────────────────
    if (pathname === '/api/target-curves' && req.method === 'GET') {
      const list = listTargetCurves();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, curves: list }));
      return;
    }

    if (pathname.startsWith('/api/target-curves/') && req.method === 'GET') {
      const name = decodeURIComponent(pathname.replace('/api/target-curves/', ''));
      const content = getTargetCurve(name);
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end(content);
      return;
    }

    // ─── Parse ADY File ───────────────────────────────────────────────
    if (pathname === '/api/parse-ady' && req.method === 'POST') {
      const body = await parseBody(req);
      if (!body.adyData) throw new Error('Missing adyData');
      // ADY is JSON from Denon MultEQ Editor — normalize it
      try {
        const parsed = typeof body.adyData === 'string' ? JSON.parse(body.adyData) : body.adyData;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: true, data: parsed }));
      } catch (err) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: 'Invalid ADY format' }));
      }
      return;
    }

    // ─── Static Files ──────────────────────────────────────────────────
    serveStatic(req, res, baseDir);

  } catch (err) {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: err.message }));
  }
}

// ─── Main ───────────────────────────────────────────────────────────────────
async function main() {
  const baseDir = __dirname;
  const PORT = await findFreePort(18443);

  const server = http.createServer((req, res) => {
    handleRequest(req, res, baseDir).catch((err) => {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    });
  });

  server.listen(PORT, '0.0.0.0', () => {
    console.log(`A1 Evo AcoustiX server running at http://localhost:${PORT}`);
    console.log(`Serving static files from: ${baseDir}`);
    console.log(`Calibrations dir: ${CALIBRATION_DIR}`);
    console.log(`Target curves dir: ${TARGET_CURVES_DIR}`);
  });
}

main().catch(console.error);