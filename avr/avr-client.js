/**
 * AVR Telnet Client (Server-side)
 * Wraps Node.js net module for raw TCP Telnet connections to Denon/Marantz AVRs.
 * Port: 23 (Telnet)
 * 
 * Protocol:
 *   MSSV<ch>=<freq>Hz,<gain>dB,Q=<q>  — Set PEQ filter
 *   MSD<ch><distance_mm>              — Set distance (mm)
 *   MST<ch><trim_x10>                 — Set trim (0.1 dB units)
 *   MSQ<ch>                           — Query filter values
 */

const net = require('net');

const CHANNELS = ['FL','FR','C','SW','SL','SR','BL','BR','SBL','SBR','FD','FS','TM','RL','RR'];

class AvrClient {
  constructor() {
    this.socket = null;
    this.host = null;
    this.port = 23;
    this.ready = false;
    this._commandQueue = [];
    this._processingQueue = false;
    this._responseHandlers = new Map();
    this._idleTimer = null;
  }

  /**
   * Connect to AVR at given host
   * @param {string} host - IP address of the AVR
   * @returns {Promise<{host, port, connected: true}>}
   */
  connect(host) {
    return new Promise((resolve, reject) => {
      if (this.socket && !this.socket.destroyed) {
        this.socket.destroy();
      }

      this.host = host;
      this.socket = net.connect(23, host);
      this.ready = false;

      const timeout = setTimeout(() => {
        this.socket.destroy();
        reject(new Error('Connection timeout (5s)'));
      }, 5000);

      this.socket.on('connect', () => {
        clearTimeout(timeout);
        // AVR typically sends a welcome string or prompt
        this._onceData((data) => {
          // Consume telnet negotiation if any
          this.ready = true;
          resolve({ host, port: 23, connected: true });
        });
        // Send a probe to trigger welcome
        this.socket.write('?\r');
      });

      this.socket.on('error', (err) => {
        clearTimeout(timeout);
        reject(err);
      });

      this.socket.on('close', () => {
        this.ready = false;
      });

      // Accumulate incoming data
      this._buffer = '';
      this.socket.on('data', (chunk) => {
        this._buffer += chunk.toString();
        this._flushBuffer();
      });
    });
  }

  /**
   * Internal: wait for first data event
   */
  _onceData(cb) {
    const handler = (data) => {
      this.socket.removeListener('data', handler);
      cb(data.toString());
    };
    this.socket.on('data', handler);
  }

  /**
   * Internal: flush accumulated buffer by finding complete lines
   */
  _flushBuffer() {
    if (!this._buffer) return;
    // Denon sends \r terminated responses
    const lines = this._buffer.split('\r');
    const hasPartial = this._buffer.endsWith('\r');
    
    for (let i = 0; i < lines.length - (hasPartial ? 1 : 0); i++) {
      const line = lines[i].trim();
      if (line) {
        // Dispatch to response handlers
        const cb = this._responseHandlers.get('line');
        if (cb) cb(line);
      }
    }
    
    this._buffer = hasPartial ? lines[lines.length - 1] : '';
  }

  /**
   * Send a raw command and wait for response
   * @param {string} cmd - Command string (no trailing \r needed)
   * @returns {Promise<string>} response
   */
  sendCommand(cmd) {
    return new Promise((resolve, reject) => {
      if (!this.socket || this.socket.destroyed) {
        reject(new Error('AVR not connected'));
        return;
      }

      // Set up one-time response handler
      const handler = (line) => {
        this._responseHandlers.delete('line');
        resolve(line);
      };
      this._responseHandlers.set('line', handler);

      // Set timeout
      const timer = setTimeout(() => {
        this._responseHandlers.delete('line');
        reject(new Error(`Command timeout: ${cmd}`));
      }, 5000);

      this.socket.write(cmd + '\r', (err) => {
        if (err) {
          clearTimeout(timer);
          this._responseHandlers.delete('line');
          reject(err);
        }
      });
    });
  }

  /**
   * Set a PEQ filter on a channel
   * Format: MSSV<ch>=<freq>Hz,<gain>dB,Q=<q>
   * @param {string} channel - e.g. 'FL', 'SW'
   * @param {number} freq - frequency in Hz
   * @param {number} gain - gain in dB
   * @param {number} q - Q factor
   */
  async setPEQ(channel, freq, gain, q) {
    const cmd = `MSSV${channel}=${freq}Hz,${gain}dB,Q=${q}`;
    return this.sendCommand(cmd);
  }

  /**
   * Set multiple PEQ filters for a channel (up to 6+)
   * @param {string} channel
   * @param {Array<{freq, gain, q}>} filters
   */
  async setPEQBatch(channel, filters) {
    const results = [];
    for (const f of filters) {
      const r = await this.setPEQ(channel, f.freq, f.gain, f.q);
      results.push(r);
      // Small delay between commands
      await new Promise(r => setTimeout(r, 50));
    }
    return results;
  }

  /**
   * Set speaker distance
   * Format: MSD<ch><distance_mm>
   * @param {string} channel
   * @param {number} distance_mm - distance in millimeters
   */
  async setDistance(channel, distance_mm) {
    const cmd = `MSD${channel}${distance_mm}`;
    return this.sendCommand(cmd);
  }

  /**
   * Set channel trim
   * Format: MST<ch><trim_x10>  (trim in 0.1 dB units)
   * @param {string} channel
   * @param {number} trim_x10 - trim value in 0.1 dB (e.g. 105 = +10.5 dB)
   */
  async setTrim(channel, trim_x10) {
    const cmd = `MST${channel}${trim_x10}`;
    return this.sendCommand(cmd);
  }

  /**
   * Query current filter settings for a channel
   * Format: MSQ<ch>
   * @param {string} channel
   * @returns {Promise<string>} filter query response
   */
  async queryFilters(channel) {
    return this.sendCommand(`MSQ${channel}`);
  }

  /**
   * Query power state
   */
  async getPowerStatus() {
    return this.sendCommand('PWST?');
  }

  /**
   * Disconnect from AVR
   */
  disconnect() {
    return new Promise((resolve) => {
      if (this.socket && !this.socket.destroyed) {
        this.socket.destroy();
      }
      this.socket = null;
      this.host = null;
      this.ready = false;
      resolve({ disconnected: true });
    });
  }

  /**
   * Check if connected
   */
  isConnected() {
    return this.socket && !this.socket.destroyed && this.ready;
  }
}

module.exports = { AvrClient, CHANNELS };