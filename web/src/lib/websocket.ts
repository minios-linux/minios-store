/**
 * WebSocket client for communicating with MiniOS Store backend.
 *
 * Connects to ws://127.0.0.1:8765 by default.
 * Falls back to minios-store:// URI scheme for desktop integration.
 * Auto-reconnects with exponential backoff.
 */

import type { ClientMessage, ServerMessage, ConnectionStatus, InstallRecipe, InstallMode, PackagingMode } from './types';

const WS_URL = 'ws://127.0.0.1:8765';
const RECONNECT_BASE_DELAY = 2000;
const RECONNECT_MAX_DELAY = 60000;
const RECONNECT_MAX_ATTEMPTS = 10;
const PING_INTERVAL = 15000;

type MessageHandler = (msg: ServerMessage) => void;
type StatusHandler = (status: ConnectionStatus) => void;

class StoreWebSocket {
  private ws: WebSocket | null = null;
  private messageHandlers = new Set<MessageHandler>();
  private statusHandlers = new Set<StatusHandler>();
  private _status: ConnectionStatus = 'disconnected';
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private destroyed = false;
  private hasLoggedError = false;

  get status(): ConnectionStatus {
    return this._status;
  }

  connect(): void {
    if (this.destroyed) return;
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return;
    }

    this.setStatus('connecting');

    try {
      this.ws = new WebSocket(WS_URL);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.hasLoggedError = false;
        this.setStatus('connected');
        this.startPing();
        if (import.meta.env.DEV) {
          console.log('[WS] Connected to backend');
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as ServerMessage;
          console.log('[WS] Received:', msg.type, msg);
          this.messageHandlers.forEach(handler => handler(msg));
        } catch {
          console.warn('[WS] Failed to parse message:', event.data);
        }
      };

      this.ws.onclose = () => {
        this.setStatus('disconnected');
        this.stopPing();
        
        if (!this.hasLoggedError && import.meta.env.DEV) {
          console.warn('[WS] Backend not available. Install functionality disabled until backend starts.');
          this.hasLoggedError = true;
        }
        
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        // onclose will fire after onerror, handle reconnect there
      };
    } catch {
      this.setStatus('disconnected');
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this.destroyed = true;
    this.clearReconnect();
    this.stopPing();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.setStatus('disconnected');
  }

  send(message: ClientMessage): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      return false;
    }
    try {
      this.ws.send(JSON.stringify(message));
      return true;
    } catch {
      return false;
    }
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onStatusChange(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  private setStatus(status: ConnectionStatus): void {
    if (this._status !== status) {
      this._status = status;
      this.statusHandlers.forEach(handler => handler(status));
    }
  }

  private scheduleReconnect(): void {
    if (this.destroyed) return;
    
    // Stop trying after max attempts in development mode
    if (import.meta.env.DEV && this.reconnectAttempts >= RECONNECT_MAX_ATTEMPTS) {
      if (!this.hasLoggedError) {
        console.warn('[WS] Max reconnection attempts reached. Backend appears to be offline.');
        this.hasLoggedError = true;
      }
      return;
    }
    
    this.clearReconnect();

    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(2, this.reconnectAttempts),
      RECONNECT_MAX_DELAY
    );
    this.reconnectAttempts++;

    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startPing(): void {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      this.send({ type: 'ping' });
    }, PING_INTERVAL);
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }
}

// Singleton instance
export const storeWs = new StoreWebSocket();

/** Encode JSON as UTF-8 base64url for the URI fallback payload. */
function encodeUriPayload(value: unknown): string {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  let binary = '';
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '');
}

/**
 * Fallback: install via the minios-store:// URI scheme when the WebSocket
 * service is unavailable. The legacy recipes=id:level:compression parameter
 * is retained for compatibility, while payload carries the complete recipes
 * needed for script/deb installs and acceptedLicenses preserves explicit
 * license acceptance from the web UI.
 */
export function installViaUriScheme(
  recipes: InstallRecipe[],
  mode: InstallMode,
  packaging: PackagingMode,
  distroCodename?: string | null,
  systemArch?: string | null,
  moduleName?: string,
  acceptedLicenses: string[] = [],
): void {
  const recipeParts = recipes.map(r => `${r.id}:${r.level}:${r.compression}`).join(',');
  const params = new URLSearchParams({
    mode,
    recipes: recipeParts,
    payload: encodeUriPayload(recipes),
  });

  if (mode === 'module') {
    params.set('packaging', packaging);
    if (moduleName?.trim()) {
      params.set('moduleName', moduleName.trim());
    }
  }

  if (distroCodename) {
    params.set('distro', distroCodename);
  }

  if (systemArch) {
    params.set('arch', systemArch);
  }

  if (acceptedLicenses.length > 0) {
    params.set('acceptedLicenses', acceptedLicenses.join(','));
  }

  window.location.href = `minios-store://install?${params.toString()}`;
}
