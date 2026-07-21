"use client";

import { useCallback, useRef, useState } from "react";

// Mirrors LLM_service's WS /intake/{sid}/voice protocol (see API.md — "native speech-to-speech").
// This connects DIRECTLY to the Python LLM_service, bypassing the Next.js API routes and the
// Java backend: tsldemo has no WebSocket infrastructure today, so a full proxy chain is out of
// scope for this MVP. NEXT_PUBLIC_LLM_SERVICE_WS_URL must point straight at it (e.g.
// ws://localhost:8080).

export type VoiceStatus = "idle" | "connecting" | "recording" | "error";

export interface VoiceBriefPartial {
  topic?: string;
  target_platforms?: string[];
  user_intent?: string;
  [key: string]: unknown;
}

interface TranscriptFrame {
  type: "transcript";
  role: "user" | "assistant";
  text: string;
}
interface AudioFrame {
  type: "audio";
  audio: string;
}
interface BriefUpdateFrame {
  type: "brief_update";
  brief_partial: VoiceBriefPartial;
  complete: boolean;
}
interface InterruptedFrame {
  type: "interrupted";
}
interface ErrorFrame {
  type: "error";
  message?: string;
}
type ServerFrame = TranscriptFrame | AudioFrame | BriefUpdateFrame | InterruptedFrame | ErrorFrame;

interface UseRealtimeVoiceOptions {
  targetPlatforms: string[];
  // `fullText` is the WHOLE accumulated text for the turn so far (not just the latest
  // delta) — the server streams the assistant's reply as many small
  // response.audio_transcript.delta fragments, so callers should REPLACE their bubble's
  // content with `fullText` rather than concatenating it themselves. `isNewTurn` is true
  // exactly once per turn (the first fragment) — start a new message bubble then; false
  // on every subsequent fragment of the SAME turn — update the existing bubble in place.
  // `audioUrl` is set ONLY for a "user" call (one-shot — the whole utterance's clip is
  // already known at that point); assistant audio isn't ready until the turn ends, so it
  // arrives via `onTurnEnd` instead.
  onTranscript: (
    role: "user" | "assistant", fullText: string, isNewTurn: boolean, audioUrl?: string,
  ) => void;
  // Fired once per assistant turn boundary (the server's response.done) — the right
  // moment to persist the turn's final text exactly once, instead of on every delta.
  // `audioUrl` is the assistant's fully-assembled reply clip for the turn (undefined if
  // no audio arrived, e.g. a mock-mode text-only fallback).
  onTurnEnd: (audioUrl?: string) => void;
  onComplete: (briefPartial: VoiceBriefPartial) => void;
  onError: (message: string) => void;
}

const SAMPLE_RATE = 24000;

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000; // avoid blowing the call-stack limit on String.fromCharCode(...bytes)
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

function base64ToInt16(base64: string): Int16Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.length / 2));
}

/** Build a playable/downloadable WAV Blob URL from accumulated 16-bit PCM mono chunks
 * (a plain 44-byte header in front of the raw samples — no encoder needed, since the
 * wire format is already PCM16). Undefined for an empty clip (nothing to play). */
function pcm16ChunksToWavUrl(chunks: Int16Array[], sampleRate: number): string | undefined {
  const totalSamples = chunks.reduce((n, c) => n + c.length, 0);
  if (totalSamples === 0) return undefined;

  const dataSize = totalSamples * 2; // 16-bit = 2 bytes/sample
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  const writeStr = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate (mono, 16-bit)
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++) {
      view.setInt16(offset, chunk[i], true);
      offset += 2;
    }
  }

  return URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
}

export function useRealtimeVoice(opts: UseRealtimeVoiceOptions) {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const wsRef = useRef<WebSocket | null>(null);
  const micCtxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const playCtxRef = useRef<AudioContext | null>(null);
  const nextPlayTimeRef = useRef(0);
  // The assistant's accumulated reply text for the CURRENT turn only — tracked
  // separately from the user's role so an interleaved user transcript (the model can
  // start replying before the user's own transcript catches up — transcription is a
  // side channel, never a gate on the model) never gets mistaken for a new assistant
  // turn and fragments it into multiple bubbles.
  const openAssistantTextRef = useRef<string | null>(null);
  // Raw PCM16 accumulators for "save/replay this clip" — assistant: one reply's worth,
  // reset on turn end; user: buffered continuously between one input_transcript and the
  // next (there's no explicit "user speech ended" event on the wire — the completed
  // transcript IS that signal), reset once consumed.
  const assistantAudioChunksRef = useRef<Int16Array[]>([]);
  const userAudioChunksRef = useRef<Int16Array[]>([]);

  // Always-latest callbacks/config so the WS handlers below never close over stale props.
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const stop = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    workletRef.current?.disconnect();
    workletRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    micCtxRef.current?.close().catch(() => {});
    micCtxRef.current = null;
    openAssistantTextRef.current = null;
    assistantAudioChunksRef.current = [];
    userAudioChunksRef.current = [];
    setStatus("idle");
  }, []);

  const playChunk = useCallback((pcm: Int16Array) => {
    let ctx = playCtxRef.current;
    if (!ctx) {
      ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      playCtxRef.current = ctx;
      nextPlayTimeRef.current = ctx.currentTime;
    }
    const float = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) {
      float[i] = pcm[i] / (pcm[i] < 0 ? 0x8000 : 0x7fff);
    }

    const buffer = ctx.createBuffer(1, float.length, SAMPLE_RATE);
    buffer.copyToChannel(float, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);

    // Schedule back-to-back so chunks don't overlap or gap — a small sequential playback
    // queue via the AudioContext's own clock, no jitter-buffer sophistication (MVP).
    const startAt = Math.max(nextPlayTimeRef.current, ctx.currentTime);
    source.start(startAt);
    nextPlayTimeRef.current = startAt + buffer.duration;
  }, []);

  const flushPlayback = useCallback(() => {
    // Barge-in: drop the scheduled queue by resetting the clock. Chunks already started keep
    // playing to completion — acceptable for the MVP (no per-chunk stop tracking).
    if (playCtxRef.current) {
      nextPlayTimeRef.current = playCtxRef.current.currentTime;
    }
  }, []);

  const start = useCallback(async (sessionId: string) => {
    if (status === "recording" || status === "connecting") return;
    setStatus("connecting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const micCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
      micCtxRef.current = micCtx;
      await micCtx.audioWorklet.addModule("/pcm16-worklet.js");
      const source = micCtx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(micCtx, "pcm16-worklet");
      workletRef.current = worklet;
      source.connect(worklet);
      // Deliberately not connected to micCtx.destination — we never want to loop the raw
      // mic back out of the speakers (would echo alongside the assistant's own audio).

      const base = process.env.NEXT_PUBLIC_LLM_SERVICE_WS_URL || "ws://localhost:8080";
      const ws = new WebSocket(`${base}/intake/${sessionId}/voice`);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "start", target_platforms: optsRef.current.targetPlatforms }));
        setStatus("recording");
      };

      worklet.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
        userAudioChunksRef.current.push(new Int16Array(e.data));
        if (ws.readyState !== WebSocket.OPEN) return;
        const audio = bytesToBase64(new Uint8Array(e.data));
        ws.send(JSON.stringify({ type: "audio", audio }));
      };

      ws.onmessage = (e: MessageEvent<string>) => {
        let msg: ServerFrame;
        try {
          msg = JSON.parse(e.data) as ServerFrame;
        } catch {
          return;
        }
        switch (msg.type) {
          case "transcript": {
            if (msg.role === "user") {
              // One-shot per turn (the completed-transcription event itself is the
              // "utterance ended" signal) — the mic audio buffered since the last one
              // is this utterance's clip.
              const audioUrl = pcm16ChunksToWavUrl(userAudioChunksRef.current, SAMPLE_RATE);
              userAudioChunksRef.current = [];
              optsRef.current.onTranscript("user", msg.text, true, audioUrl);
            } else {
              const isNewTurn = openAssistantTextRef.current === null;
              const fullText = (openAssistantTextRef.current ?? "") + msg.text;
              openAssistantTextRef.current = fullText;
              optsRef.current.onTranscript("assistant", fullText, isNewTurn);
            }
            break;
          }
          case "audio": {
            const pcm = base64ToInt16(msg.audio);
            assistantAudioChunksRef.current.push(pcm);
            playChunk(pcm);
            break;
          }
          case "interrupted":
            flushPlayback();
            break;
          case "brief_update": {
            // response_done — the assistant's turn is over; hand back its finished clip
            // and persist its final text now (once) instead of on every delta.
            const audioUrl = pcm16ChunksToWavUrl(assistantAudioChunksRef.current, SAMPLE_RATE);
            assistantAudioChunksRef.current = [];
            openAssistantTextRef.current = null;
            optsRef.current.onTurnEnd(audioUrl);
            if (msg.complete) {
              optsRef.current.onComplete(msg.brief_partial);
              stop();
            }
            break;
          }
          case "error":
            optsRef.current.onError(msg.message || "Voice session error.");
            stop();
            break;
        }
      };

      ws.onerror = () => {
        optsRef.current.onError("Could not reach the voice service.");
        stop();
      };
      ws.onclose = () => {
        setStatus((s) => (s === "recording" || s === "connecting" ? "idle" : s));
      };
    } catch (err) {
      optsRef.current.onError(err instanceof Error ? err.message : "Microphone access failed.");
      stop();
    }
  }, [status, stop, playChunk, flushPlayback]);

  return { status, start, stop };
}
