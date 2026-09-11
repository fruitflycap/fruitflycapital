export type TradeAudioSide = 'buy' | 'sell'

type AudioContextConstructor = new () => AudioContext

/**
 * A small procedural sound bed keeps the experience self-contained and fast:
 * no large MP3 download, no third-party player, and no CDN audio dependency.
 * Browsers still require a user gesture before audio can begin, so the scene
 * calls enable() on the first pointer/keyboard interaction.
 */
export class SceneAudio {
  private context: AudioContext | null = null
  private master: GainNode | null = null
  private ambientSources: AudioScheduledSourceNode[] = []
  private enabled = false
  private lastCueAt: Record<TradeAudioSide, number> = { buy: 0, sell: 0 }
  private transition: Promise<boolean> | null = null

  get isEnabled() {
    return this.enabled
  }

  async enable(): Promise<boolean> {
    if (this.transition) return this.transition
    this.transition = this.startAudio()
    try {
      return await this.transition
    } finally {
      this.transition = null
    }
  }

  async disable(): Promise<void> {
    if (!this.context) {
      this.enabled = false
      return
    }
    try {
      await this.context.suspend()
    } finally {
      this.enabled = false
    }
  }

  async toggle(): Promise<boolean> {
    if (this.enabled) {
      await this.disable()
      return false
    }
    return this.enable()
  }

  private async startAudio(): Promise<boolean> {
    const audioWindow = window as Window & { webkitAudioContext?: AudioContextConstructor }
    const AudioContextImplementation = window.AudioContext ?? audioWindow.webkitAudioContext
    if (!AudioContextImplementation) return false

    try {
      if (!this.context) {
        this.context = new AudioContextImplementation()
        this.master = this.context.createGain()
        this.master.gain.value = 0.055
        this.master.connect(this.context.destination)
        this.startAmbient()
      }

      const state = String(this.context.state)
      if (state === 'suspended' || state === 'interrupted') await this.context.resume()
      this.enabled = this.context.state === 'running'
      return this.enabled
    } catch {
      this.enabled = false
      return false
    }
  }

  playTradeCue(side: TradeAudioSide) {
    if (!this.enabled || !this.context || !this.master) return
    const nowMs = performance.now()
    if (nowMs - this.lastCueAt[side] < 220) return
    this.lastCueAt[side] = nowMs
    const start = this.context.currentTime + 0.012
    if (side === 'buy') {
      this.playTone(440, start, 0.1, 0.055, 'sine')
      this.playTone(660, start + 0.075, 0.16, 0.045, 'sine')
    } else {
      this.playTone(440, start, 0.1, 0.05, 'triangle')
      this.playTone(275, start + 0.075, 0.18, 0.042, 'triangle')
    }
  }

  private startAmbient() {
    if (!this.context || !this.master) return
    const context = this.context
    const droneFilter = context.createBiquadFilter()
    droneFilter.type = 'bandpass'
    droneFilter.frequency.value = 185
    droneFilter.Q.value = 1.4
    const droneGain = context.createGain()
    droneGain.gain.value = 0.18
    droneGain.connect(droneFilter)
    droneFilter.connect(this.master)

    // Two quiet detuned oscillators create a soft fly-wing hum rather than a
    // harsh loop. The LFO makes it breathe slowly in the background.
    for (const [frequency, detune] of [[92, -6], [184, 5]] as const) {
      const oscillator = context.createOscillator()
      oscillator.type = 'sawtooth'
      oscillator.frequency.value = frequency
      oscillator.detune.value = detune
      oscillator.connect(droneGain)
      oscillator.start()
      this.ambientSources.push(oscillator)
    }
    const pulse = context.createOscillator()
    pulse.type = 'sine'
    pulse.frequency.value = 0.075
    const pulseDepth = context.createGain()
    pulseDepth.gain.value = 0.09
    pulse.connect(pulseDepth)
    pulseDepth.connect(droneGain.gain)
    pulse.start()
    this.ambientSources.push(pulse)

    const noiseBuffer = context.createBuffer(1, context.sampleRate * 2, context.sampleRate)
    const noiseData = noiseBuffer.getChannelData(0)
    for (let index = 0; index < noiseData.length; index += 1) {
      noiseData[index] = (Math.random() * 2 - 1) * 0.22
    }
    const noise = context.createBufferSource()
    noise.buffer = noiseBuffer
    noise.loop = true
    const wingFilter = context.createBiquadFilter()
    wingFilter.type = 'bandpass'
    wingFilter.frequency.value = 720
    wingFilter.Q.value = 0.55
    const wingGain = context.createGain()
    wingGain.gain.value = 0.11
    noise.connect(wingFilter)
    wingFilter.connect(wingGain)
    wingGain.connect(this.master)
    noise.start()
    this.ambientSources.push(noise)
  }

  private playTone(frequency: number, start: number, duration: number, volume: number, type: OscillatorType) {
    if (!this.context || !this.master) return
    const oscillator = this.context.createOscillator()
    const gain = this.context.createGain()
    oscillator.type = type
    oscillator.frequency.setValueAtTime(frequency, start)
    gain.gain.setValueAtTime(0.0001, start)
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.012)
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration)
    oscillator.connect(gain)
    gain.connect(this.master)
    oscillator.start(start)
    oscillator.stop(start + duration + 0.02)
  }
}
