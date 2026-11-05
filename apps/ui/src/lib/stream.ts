import { useCallback, useEffect, useRef, useState } from 'react';
import type { Conversation, ConversationEvent } from '@ohd/shared-types';
import { api } from './api';

/** Keeps a conversation live: REST snapshot first, then WebSocket updates. */
export function useConversationStream(conversation_id: string | null) {
  const [events, setEvents] = useState<ConversationEvent[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const closedByUs = useRef(false);

  const appendEvent = useCallback((event: ConversationEvent) => {
    setEvents((prev) => (prev.some((e) => e.id === event.id) ? prev : [...prev, event]));
  }, []);

  useEffect(() => {
    if (!conversation_id) {
      setEvents([]);
      setConversation(null);
      return;
    }
    let cancelled = false;
    closedByUs.current = false;

    const connect = async () => {
      if (cancelled) return;
      try {
        const [snapshotConversation, history] = await Promise.all([
          api.getConversation(conversation_id),
          api.events(conversation_id),
        ]);
        if (cancelled) return;
        setConversation(snapshotConversation);
        setEvents(history);
      } catch {
        // The socket below may still recover; surface connection failures via `connected`.
      }
      const socket = await api.openEventStream(conversation_id, (payload) => {
        const message = payload as {
          kind: string;
          event?: ConversationEvent;
          conversation?: Conversation;
          events?: ConversationEvent[];
        };
        if (message.kind === 'snapshot') {
          if (message.conversation) setConversation(message.conversation);
          if (message.events) setEvents(message.events);
        } else if (message.kind === 'event' && message.event) {
          appendEvent(message.event);
          void refreshConversation();
        }
      });
      socketRef.current = socket;
      socket.onopen = () => setConnected(true);
      socket.onclose = () => {
        setConnected(false);
        if (!cancelled && !closedByUs.current) {
          reconnectTimer.current = window.setTimeout(connect, 1500);
        }
      };
      socket.onerror = () => socket.close();
    };

    const refreshConversation = async () => {
      try {
        const fresh = await api.getConversation(conversation_id);
        if (!cancelled) setConversation(fresh);
      } catch {
        /* transient */
      }
    };

    void connect();
    return () => {
      cancelled = true;
      closedByUs.current = true;
      if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current);
      socketRef.current?.close();
    };
  }, [conversation_id, appendEvent]);

  return { events, conversation, setConversation, setEvents, connected };
}

/** Debounced value helper used by the conversation search box. */
export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
