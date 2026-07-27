import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { installViaUriScheme, storeWs } from './websocket';
import type { InstallRecipe } from './types';

// ---------------------------------------------------------------------------
// installViaUriScheme
// ---------------------------------------------------------------------------

function paramsFrom(href: string): URLSearchParams {
  return new URLSearchParams(href.split('?')[1] || '');
}

const recipe = (over: Partial<InstallRecipe>): InstallRecipe => ({
  id: 'vlc', name: 'VLC', method: 'apt', level: 'auto', compression: 'zstd', ...over,
});

describe('installViaUriScheme', () => {
  let assignedHref = '';

  beforeEach(() => {
    assignedHref = '';
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        set href(v: string) { assignedHref = v; },
        get href() { return assignedHref; },
      },
    });
  });

  it('builds a module install URI with packaging', () => {
    installViaUriScheme([recipe({})], 'module', 'single');
    expect(assignedHref.startsWith('minios-store://install?')).toBe(true);
    const p = paramsFrom(assignedHref);
    expect(p.get('mode')).toBe('module');
    expect(p.get('recipes')).toBe('vlc:auto:zstd');
    expect(p.get('packaging')).toBe('single');
  });

  it('omits packaging in system mode', () => {
    installViaUriScheme([recipe({})], 'system', 'single');
    const p = paramsFrom(assignedHref);
    expect(p.get('mode')).toBe('system');
    expect(p.has('packaging')).toBe(false);
  });

  it('encodes multiple recipes plus distro and arch', () => {
    installViaUriScheme(
      [
        recipe({ id: 'vlc', level: '05', compression: 'zstd' }),
        recipe({ id: 'gimp', level: 'auto', compression: 'xz' }),
      ],
      'module',
      'separate',
      'bookworm',
      'amd64',
    );
    const p = paramsFrom(assignedHref);
    expect(p.get('recipes')).toBe('vlc:05:zstd,gimp:auto:xz');
    expect(p.get('packaging')).toBe('separate');
    expect(p.get('distro')).toBe('bookworm');
    expect(p.get('arch')).toBe('amd64');
  });

  it('omits distro/arch when not provided', () => {
    installViaUriScheme([recipe({})], 'module', 'single');
    const p = paramsFrom(assignedHref);
    expect(p.has('distro')).toBe(false);
    expect(p.has('arch')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// StoreWebSocket (singleton) with a mocked global WebSocket
// ---------------------------------------------------------------------------

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string) { this.sent.push(data); }
  close() { this.readyState = MockWebSocket.CLOSED; }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }
  simulateMessage(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }
  simulateClose() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }
}

function resetSingleton() {
  const s = storeWs as unknown as Record<string, unknown>;
  if (s.pingTimer) clearInterval(s.pingTimer as ReturnType<typeof setInterval>);
  if (s.reconnectTimer) clearTimeout(s.reconnectTimer as ReturnType<typeof setTimeout>);
  s.destroyed = false;
  s.ws = null;
  s.reconnectAttempts = 0;
  s._status = 'disconnected';
  s.pingTimer = null;
  s.reconnectTimer = null;
  s.hasLoggedError = false;
  s.messageHandlers = new Set();
  s.statusHandlers = new Set();
}

describe('StoreWebSocket', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
    resetSingleton();
  });

  afterEach(() => {
    resetSingleton();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('transitions to connected on open', () => {
    const statuses: string[] = [];
    storeWs.onStatusChange((s) => statuses.push(s));

    storeWs.connect();
    expect(storeWs.status).toBe('connecting');

    MockWebSocket.instances[0].simulateOpen();
    expect(storeWs.status).toBe('connected');
    expect(statuses).toContain('connecting');
    expect(statuses).toContain('connected');
  });

  it('dispatches parsed messages to subscribers', () => {
    const received: unknown[] = [];
    storeWs.onMessage((m) => received.push(m));

    storeWs.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();
    ws.simulateMessage({ type: 'pong' });

    expect(received).toEqual([{ type: 'pong' }]);
  });

  it('ignores malformed message payloads', () => {
    const received: unknown[] = [];
    storeWs.onMessage((m) => received.push(m));

    storeWs.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();
    ws.onmessage?.({ data: 'not-json{' });

    expect(received).toEqual([]);
  });

  it('send returns false unless the socket is open', () => {
    storeWs.connect();
    const ws = MockWebSocket.instances[0];
    expect(storeWs.send({ type: 'ping' })).toBe(false); // still connecting
    ws.simulateOpen();
    expect(storeWs.send({ type: 'ping' })).toBe(true);
    expect(ws.sent.some((m) => m.includes('ping'))).toBe(true);
  });

  it('unsubscribing stops delivering messages', () => {
    const received: unknown[] = [];
    const unsub = storeWs.onMessage((m) => received.push(m));

    storeWs.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();
    unsub();
    ws.simulateMessage({ type: 'pong' });

    expect(received).toEqual([]);
  });

  it('sends a ping on the keepalive interval', () => {
    vi.useFakeTimers();
    storeWs.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    vi.advanceTimersByTime(15000);
    expect(ws.sent.some((m) => m.includes('ping'))).toBe(true);
  });

  it('schedules a reconnect after the socket closes', () => {
    vi.useFakeTimers();
    storeWs.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();
    ws.simulateClose();

    expect(storeWs.status).toBe('disconnected');
    // Base backoff delay is 2000ms -> a fresh socket is created.
    vi.advanceTimersByTime(2000);
    expect(MockWebSocket.instances.length).toBe(2);
  });
});
