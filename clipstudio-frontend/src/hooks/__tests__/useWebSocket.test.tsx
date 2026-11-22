import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWebSocket } from '../useWebSocket';
import { JobProgressEvent } from '../../types';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static readonly CONNECTING = 0;
  static readonly CLOSING = 2;

  readonly OPEN = MockWebSocket.OPEN;
  readonly CLOSED = MockWebSocket.CLOSED;
  readonly CONNECTING = MockWebSocket.CONNECTING;
  readonly CLOSING = MockWebSocket.CLOSING;

  url: string;
  readyState: number = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    setTimeout(() => {
      if (this.readyState === MockWebSocket.CONNECTING) {
        this.readyState = MockWebSocket.OPEN;
        if (this.onopen) this.onopen();
      }
    }, 0);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose();
    }
  }

  simulateMessage(data: any) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) });
    }
  }

  simulateClose() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose();
    }
  }

  simulateError() {
    if (this.onerror) {
      this.onerror();
    }
  }
}

describe('useWebSocket Reliability & Stability', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('connects once on initial render', () => {
    const onProgress = vi.fn();
    const { result } = renderHook(() => useWebSocket(onProgress));

    expect(MockWebSocket.instances.length).toBe(1);
    expect(result.current.status).toBe('connecting');

    act(() => {
      vi.advanceTimersByTime(10);
    });

    expect(result.current.status).toBe('connected');
  });

  it('unrelated state changes and re-renders create NO additional WebSocket connection', () => {
    let renderCount = 0;

    const { result, rerender } = renderHook(
      ({ counter }: { counter: number }) => {
        renderCount++;
        // Simulate recreating the callback inline on every render (unstable callback)
        const unstableCallback = (_event: JobProgressEvent) => {
          // access counter to simulate closure
          void counter;
        };
        return useWebSocket(unstableCallback);
      },
      { initialProps: { counter: 0 } }
    );

    act(() => {
      vi.advanceTimersByTime(10);
    });

    expect(MockWebSocket.instances.length).toBe(1);
    expect(result.current.status).toBe('connected');

    // Trigger multiple re-renders with new props and new callback identities
    rerender({ counter: 1 });
    rerender({ counter: 2 });
    rerender({ counter: 3 });

    act(() => {
      vi.advanceTimersByTime(10);
    });

    // WebSocket constructor MUST NOT be called again
    expect(MockWebSocket.instances.length).toBe(1);
    expect(result.current.status).toBe('connected');
  });

  it('job-progress events invoke the latest callback without stale closure', () => {
    const received: string[] = [];

    const { rerender } = renderHook(
      ({ prefix }: { prefix: string }) => {
        return useWebSocket((event: JobProgressEvent) => {
          received.push(`${prefix}:${event.job_id}`);
        });
      },
      { initialProps: { prefix: 'initial' } }
    );

    act(() => {
      vi.advanceTimersByTime(10);
    });

    const socket = MockWebSocket.instances[0];

    // First event with initial prefix
    act(() => {
      socket.simulateMessage({
        event_type: 'job_progress',
        job_id: 'job-1',
        status: 'running',
        progress_percent: 50,
      });
    });

    expect(received).toEqual(['initial:job-1']);

    // Re-render with new prefix
    rerender({ prefix: 'updated' });

    // Second event should use latest callback
    act(() => {
      socket.simulateMessage({
        event_type: 'job_progress',
        job_id: 'job-2',
        status: 'completed',
        progress_percent: 100,
      });
    });

    expect(received).toEqual(['initial:job-1', 'updated:job-2']);
    // Still exactly 1 socket instance
    expect(MockWebSocket.instances.length).toBe(1);
  });

  it('genuine close or error triggers automatic reconnect with exponential backoff', () => {
    const onProgress = vi.fn();
    const { result } = renderHook(() => useWebSocket(onProgress));

    act(() => {
      vi.advanceTimersByTime(10);
    });

    expect(MockWebSocket.instances.length).toBe(1);
    expect(result.current.status).toBe('connected');

    const firstSocket = MockWebSocket.instances[0];

    // Simulate unexpected network drop
    act(() => {
      firstSocket.simulateClose();
    });

    expect(result.current.status).toBe('disconnected');

    // Advance by backoff delay (1000ms * 1.5^0 = 1000ms)
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // Reconnect should spawn a second instance
    expect(MockWebSocket.instances.length).toBe(2);

    act(() => {
      vi.advanceTimersByTime(10);
    });

    expect(result.current.status).toBe('connected');
  });

  it('unmount cleanly closes the socket and clears pending reconnect timers', () => {
    const onProgress = vi.fn();
    const { unmount } = renderHook(() => useWebSocket(onProgress));

    act(() => {
      vi.advanceTimersByTime(10);
    });

    const socket = MockWebSocket.instances[0];
    expect(socket.readyState).toBe(MockWebSocket.OPEN);

    unmount();

    expect(socket.readyState).toBe(MockWebSocket.CLOSED);

    // Advance time to verify no reconnect happens after unmount
    act(() => {
      vi.advanceTimersByTime(20000);
    });

    expect(MockWebSocket.instances.length).toBe(1);
  });

  it('manual reconnect clears previous socket and reconnects cleanly without duplicates', () => {
    const onProgress = vi.fn();
    const { result } = renderHook(() => useWebSocket(onProgress));

    act(() => {
      vi.advanceTimersByTime(10);
    });

    expect(MockWebSocket.instances.length).toBe(1);

    act(() => {
      result.current.reconnect();
    });

    act(() => {
      vi.advanceTimersByTime(10);
    });

    expect(MockWebSocket.instances.length).toBe(2);
    expect(result.current.status).toBe('connected');
  });
});
