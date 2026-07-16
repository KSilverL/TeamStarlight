// Converts the mic's Float32 samples into 16-bit PCM, batched into ~100ms chunks before
// posting back to the main thread. The AudioContext this runs on is constructed with
// `sampleRate: 24000` (see useRealtimeVoice.ts), so the browser's own audio graph already
// resamples the mic input to the backend's required 24kHz — this worklet only does the
// Float32 -> Int16 conversion, no manual resampling math.

const BATCH_SAMPLES = 2400; // ~100ms at 24kHz — snappy turn-taking without chatty postMessage/WS traffic

class PCM16Worklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this._batch = new Int16Array(BATCH_SAMPLES);
    this._filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel || channel.length === 0) return true;

    for (let i = 0; i < channel.length; i++) {
      const s = Math.max(-1, Math.min(1, channel[i]));
      this._batch[this._filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this._filled === BATCH_SAMPLES) {
        this.port.postMessage(this._batch.buffer.slice(0));
        this._filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm16-worklet", PCM16Worklet);
