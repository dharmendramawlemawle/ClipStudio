import { useEffect, useRef, useState, useCallback } from 'react';
import { JobProgressEvent } from '../types';

export type WSStatus = 'connecting' | 'connected' | 'disconnected';

export function useWebSocket(onJobProgress?: (event: JobProgressEvent) => void) {
  const [status, setStatus] = useState<WSStatus>('disconnected');
  const [lastEvent, setLastEvent] = useState<JobProgressEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const retryCountRef = useRef(0);
  const onJobProgressRef = useRef(onJobProgress);

  // Always keep ref updated to avoid stale closures without triggering reconnects
  useEffect(() => {
    onJobProgressRef.current = onJobProgress;
  }, [onJobProgress]);

  const connect = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    setStatus('connecting');

    // Build URL: if running under Vite proxy or production
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Use window.location.host so Vite proxy can route /ws/events to backend
    const wsUrl = `${protocol}//${window.location.host}/ws/events`;

    try {
      const socket = new WebSocket(wsUrl);
      wsRef.current = socket;
      if (typeof window !== 'undefined') {
        (window as any).__clipstudio_ws = socket;
      }

      socket.onopen = () => {
        setStatus('connected');
        retryCountRef.current = 0;
      };

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.event_type === 'job_progress') {
            const jobEvent = data as JobProgressEvent;
            setLastEvent(jobEvent);
            if (onJobProgressRef.current) {
              onJobProgressRef.current(jobEvent);
            }
          }
        } catch (err) {
          console.warn('Failed to parse WebSocket message:', err);
        }
      };

      socket.onclose = () => {
        setStatus('disconnected');
        wsRef.current = null;
        // Exponential backoff reconnect
        const delay = Math.min(1000 * Math.pow(1.5, retryCountRef.current), 10000);
        retryCountRef.current += 1;
        reconnectTimeoutRef.current = window.setTimeout(connect, delay);
      };

      socket.onerror = () => {
        socket.close();
      };
    } catch (err) {
      console.error('WebSocket connection error:', err);
      setStatus('disconnected');
    }
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      // Clear onclose handler before closing to prevent unwanted reconnect timer
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus('disconnected');
  }, []);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    status,
    lastEvent,
    reconnect: () => {
      disconnect();
      retryCountRef.current = 0;
      connect();
    },
  };
}
