"use client";

// Subscribe to one workflow task's progress stream.
//
// `GET /tasks/{id}/events` replays its ENTIRE buffer to every client that connects, then
// follows live. That is what makes reloading a page mid-run work — the draft that arrived
// while you were away is still on the wire — and it is also why every consumer needs the
// same two pieces of care: dedupe on the monotonic `seq` the backend stamps on each event,
// or a reconnect re-fires side effects that already happened; and close the EventSource on
// unmount, or navigating away leaks a connection that keeps replaying into a dead component.
//
// Both the plans page and the chat page had hand-rolled copies of this. This is the shared
// one; chat still carries its own, which does considerably more with the events it reads.

import { useEffect, useRef } from "react";

/** One frame off the stream. The envelope is fixed; the rest depends on `type`
 *  (see LLM_service/core/events.py), so callers narrow the fields they need. */
export interface TaskEvent {
  type: string;
  node: string;
  phase: string;
  platform: string | null;
  status: string;
  ts: number;
  seq?: number;
  [key: string]: unknown;
}

/**
 * Watch `taskId` until it changes or the component unmounts. Pass null to watch nothing —
 * which is the normal state of a plan slot that has not been commissioned yet.
 *
 * `onEvent` is read through a ref, so an inline arrow function is fine: the subscription is
 * keyed on the task id alone and will not tear down and replay the whole buffer just because
 * the parent re-rendered.
 */
export function useTaskEvents(taskId: string | null, onEvent: (event: TaskEvent) => void): void {
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  });

  useEffect(() => {
    if (!taskId) return;

    const source = new EventSource(`/api/tasks/${taskId}/events`);
    let lastSeq = -1;

    source.onmessage = (message) => {
      let event: TaskEvent;
      try {
        event = JSON.parse(message.data as string) as TaskEvent;
      } catch {
        return; // a malformed frame is not worth tearing the stream down for
      }
      if (typeof event.seq === "number") {
        if (event.seq <= lastSeq) return; // already seen — this is the replay
        lastSeq = event.seq;
      }
      handler.current(event);
    };

    source.onerror = () => {
      // The browser retries a dropped SSE connection on its own, and the replay-on-connect
      // means a reconnect loses nothing. Only give up once the connection is properly closed.
      if (source.readyState === EventSource.CLOSED) source.close();
    };

    return () => source.close();
  }, [taskId]);
}
