import type { FlyAgent } from '../fly/FlyAgent'
import { isLiveBrainSource, type BrainActivity, type MaleCNSSensoryStimulation } from '../networking/protocol'

interface BrainMapNode {
  x: number
  y: number
  layer: number
  phase: number
}

const BRAIN_MAP_NODES: BrainMapNode[] = [
  ...[0.22, 0.38, 0.54, 0.70, 0.86].map((y, index) => ({ x: 0.08, y, layer: 0, phase: index * 0.71 })),
  ...[0.13, 0.27, 0.41, 0.55, 0.69, 0.83, 0.95].map((y, index) => ({ x: 0.32, y, layer: 1, phase: 1.2 + index * 0.53 })),
  ...[0.18, 0.34, 0.50, 0.66, 0.82].map((y, index) => ({ x: 0.60, y, layer: 2, phase: 2.1 + index * 0.67 })),
  ...[0.28, 0.50, 0.72].map((y, index) => ({ x: 0.88, y, layer: 3, phase: 3.4 + index * 0.81 })),
]

const BRAIN_MAP_EDGES: Array<[number, number]> = []
for (let from = 0; from < 5; from += 1) {
  for (let to = 5; to < 12; to += 1) BRAIN_MAP_EDGES.push([from, to])
}
for (let from = 5; from < 12; from += 1) {
  for (let to = 12; to < 17; to += 1) {
    if ((from + to) % 2 === 0 || Math.abs(from - 5 - (to - 12)) <= 1) BRAIN_MAP_EDGES.push([from, to])
  }
}
for (let from = 12; from < 17; from += 1) {
  for (let to = 17; to < 20; to += 1) {
    if ((from + to) % 2 === 0 || from === 14) BRAIN_MAP_EDGES.push([from, to])
  }
}

/**
 * Small, intentionally explicit interpretability panel for the selected fly.
 * It does not infer a causal relationship from motion: the source badge and
 * the recorded spike/DN window come directly from the brain socket payload.
 */
export class BrainActivityPanel {
  readonly element: HTMLDivElement
  private readonly sourceBadge: HTMLSpanElement
  private readonly agentLabel: HTMLSpanElement
  private readonly mapAgentLabel: HTMLSpanElement
  private readonly inputBar: HTMLSpanElement
  private readonly spikeBar: HTMLSpanElement
  private readonly dnBar: HTMLSpanElement
  private readonly commandBar: HTMLSpanElement
  private readonly stats: HTMLDivElement
  private readonly raster: HTMLDivElement
  private readonly neuralCanvas: HTMLCanvasElement
  private readonly neuralContext: CanvasRenderingContext2D
  private lastSampleAt = Number.NEGATIVE_INFINITY
  private lastFlyId = ''
  private readonly history = new Map<string, number[]>()
  private inputLevel = 0
  private spikeLevel = 0
  private dnLevel = 0
  private commandLevel = 0
  private live = false

  constructor(uiRoot: HTMLElement) {
    this.element = document.createElement('div')
    this.element.className = 'brain-activity-panel'
    this.element.innerHTML = `
      <div class="brain-panel-heading"><strong>NEURAL TRACE</strong><span class="brain-source"></span></div>
      <div class="brain-panel-agent"></div>
      <div class="brain-map-heading"><span>MALECNS ACTIVITY MAP</span><span class="brain-map-agent">SWARM</span></div>
      <canvas class="brain-neural-map" aria-label="Animated MaleCNS activity map"></canvas>
      <div class="brain-map-labels"><span>SENSORY</span><span>INTEGRATION</span><span>MOTOR / DN</span><span>FLIGHT</span></div>
      <div class="brain-flow-row"><span>INPUT</span><i class="brain-flow-track"><b class="brain-input-bar"></b></i><span>SPIKES</span><i class="brain-flow-track"><b class="brain-spike-bar"></b></i></div>
      <div class="brain-flow-row"><span>DN</span><i class="brain-flow-track"><b class="brain-dn-bar"></b></i><span>COMMAND</span><i class="brain-flow-track"><b class="brain-command-bar"></b></i></div>
      <div class="brain-raster" aria-label="Recent neural activity"></div>
      <div class="brain-panel-stats"></div>
    `
    uiRoot.append(this.element)
    this.sourceBadge = this.element.querySelector<HTMLSpanElement>('.brain-source')!
    this.agentLabel = this.element.querySelector<HTMLSpanElement>('.brain-panel-agent')!
    this.mapAgentLabel = this.element.querySelector<HTMLSpanElement>('.brain-map-agent')!
    this.inputBar = this.element.querySelector<HTMLSpanElement>('.brain-input-bar')!
    this.spikeBar = this.element.querySelector<HTMLSpanElement>('.brain-spike-bar')!
    this.dnBar = this.element.querySelector<HTMLSpanElement>('.brain-dn-bar')!
    this.commandBar = this.element.querySelector<HTMLSpanElement>('.brain-command-bar')!
    this.stats = this.element.querySelector<HTMLDivElement>('.brain-panel-stats')!
    this.raster = this.element.querySelector<HTMLDivElement>('.brain-raster')!
    this.neuralCanvas = this.element.querySelector<HTMLCanvasElement>('.brain-neural-map')!
    this.neuralContext = this.neuralCanvas.getContext('2d')!
  }

  update(agent: FlyAgent, activity: BrainActivity | null, stimulation: MaleCNSSensoryStimulation | null, elapsedSeconds: number) {
    if (elapsedSeconds - this.lastSampleAt < 0.1 && agent.id === this.lastFlyId) return
    this.lastSampleAt = elapsedSeconds
    this.lastFlyId = agent.id

    const frame = agent.sensors.getFrame()
    // When the remote Brian2 websocket is unavailable, keep the panel useful
    // with the actual local eye/antenna window. It is explicitly labelled as
    // a sensor trace below and is never presented as measured CNS activity.
    const localVisualInput = Math.min(1, frame.leftEye.meanContrast * 0.7 + frame.rightEye.meanContrast * 0.3 + frame.leftEye.meanOpticFlow * 0.2)
    const localOdorInput = Math.min(1, frame.odor.concentration * 1.35 + Math.abs(frame.odor.temporalChange) * 3)
    const visualInput = stimulation ? Math.min(1, stimulation.visual.length / 100) : localVisualInput
    const odorInput = stimulation ? Math.min(1, stimulation.olfactory.length / 250) : localOdorInput
    const input = Math.max(visualInput, odorInput)
    const spikes = activity ? Object.values(activity.spikeCounts).reduce((sum, count) => sum + Math.max(0, count), 0) : 0
    const spikeLevel = Math.min(1, spikes / 24)
    const dnPeak = activity ? Math.max(0, ...Object.values(activity.descendingRates)) : 0
    const dnLevel = Math.min(1, dnPeak / 80)
    const live = isLiveBrainSource(activity?.source)
    const neuralCommand = live ? activity?.flightCommand : undefined
    const actuatorCommand = agent.actuators.get()
    const commandLevel = Math.min(1, Math.max(
      actuatorCommand.forwardThrust,
      Math.abs(actuatorCommand.yawTorque),
      Math.abs(actuatorCommand.pitchTorque),
      Math.abs(actuatorCommand.rollTorque),
    ))
    this.inputLevel = input
    this.spikeLevel = spikeLevel
    this.dnLevel = dnLevel
    this.commandLevel = commandLevel
    this.live = live
    this.sourceBadge.textContent = live
      ? 'LIVE BRIAN2 → DECODER'
      : activity
        ? 'DECODER OUTPUT · NO LIVE BRAIN'
        : 'LOCAL SENSOR TRACE · CNS OFFLINE'
    this.sourceBadge.dataset.state = live ? 'live' : 'waiting'
    this.agentLabel.textContent = `${agent.id} · ${agent.mode.toUpperCase()} · ${live ? 'measured neural window' : activity ? 'decoder window' : 'eye / antenna window'}`
    this.mapAgentLabel.textContent = `${agent.id.toUpperCase()} · SWARM TRACE`
    setBar(this.inputBar, input)
    setBar(this.spikeBar, spikeLevel)
    setBar(this.dnBar, dnLevel)
    setBar(this.commandBar, commandLevel)

    const samples = this.history.get(agent.id) ?? []
    samples.push(spikeLevel)
    if (samples.length > 28) samples.shift()
    this.history.set(agent.id, samples)
    this.raster.replaceChildren(...samples.map((value) => {
      const cell = document.createElement('i')
      cell.style.height = `${Math.max(10, Math.round(value * 100))}%`
      cell.dataset.level = value > 0.02 ? 'active' : 'quiet'
      return cell
    }))
    const neuralLevel = neuralCommand
      ? Math.min(1, Math.max(neuralCommand.thrust, Math.abs(neuralCommand.yaw), Math.abs(neuralCommand.pitch), Math.abs(neuralCommand.roll)))
      : 0
    this.stats.textContent = `SPIKES ${spikes} · DN PEAK ${dnPeak.toFixed(2)} Hz · BRAIN CMD ${neuralLevel.toFixed(2)} · ACTUATOR ${commandLevel.toFixed(2)} · INPUT ${input.toFixed(2)}`
  }

  /**
   * Draw a compact animated activity map at render rate. The nodes are an
   * explanatory visual layer driven by measured input/spike/DN levels; they
   * are not presented as a full anatomical reconstruction of every neuron.
   */
  animate(elapsedSeconds: number) {
    const rect = this.neuralCanvas.getBoundingClientRect()
    const width = Math.max(1, rect.width)
    const height = Math.max(1, rect.height)
    const scale = Math.min(2, window.devicePixelRatio || 1)
    const pixelWidth = Math.max(1, Math.round(width * scale))
    const pixelHeight = Math.max(1, Math.round(height * scale))
    if (this.neuralCanvas.width !== pixelWidth || this.neuralCanvas.height !== pixelHeight) {
      this.neuralCanvas.width = pixelWidth
      this.neuralCanvas.height = pixelHeight
    }
    const context = this.neuralContext
    context.setTransform(scale, 0, 0, scale, 0, 0)
    context.clearRect(0, 0, width, height)

    const background = context.createLinearGradient(0, 0, width, height)
    background.addColorStop(0, '#06141f')
    background.addColorStop(1, '#0b2730')
    context.fillStyle = background
    context.fillRect(0, 0, width, height)

    const energy = this.inputLevel * 0.28 + this.spikeLevel * 0.52 + this.dnLevel * 0.20
    for (const [fromIndex, toIndex] of BRAIN_MAP_EDGES) {
      const from = BRAIN_MAP_NODES[fromIndex]!
      const to = BRAIN_MAP_NODES[toIndex]!
      const x1 = from.x * width
      const y1 = from.y * height
      const x2 = to.x * width
      const y2 = to.y * height
      context.beginPath()
      context.moveTo(x1, y1)
      context.lineTo(x2, y2)
      context.strokeStyle = `rgba(93, 172, 183, ${0.12 + energy * 0.26})`
      context.lineWidth = 0.7 + energy * 0.8
      context.stroke()

      if ((this.live || this.inputLevel > 0.015) && energy > 0.015) {
        const phase = (elapsedSeconds * (0.42 + energy * 1.8) + from.phase + to.phase) % 1
        const pulseX = x1 + (x2 - x1) * phase
        const pulseY = y1 + (y2 - y1) * phase
        context.beginPath()
        context.arc(pulseX, pulseY, 1.2 + energy * 1.8, 0, Math.PI * 2)
        context.fillStyle = `rgba(122, 241, 190, ${0.18 + energy * 0.72})`
        context.fill()
      }
    }

    for (const node of BRAIN_MAP_NODES) {
      const localLevel = node.layer === 0
        ? this.inputLevel
        : node.layer === 1
          ? this.spikeLevel
          : node.layer === 2
            ? this.dnLevel
            : this.commandLevel
      const flicker = this.live || this.inputLevel > 0.015
        ? (Math.sin(elapsedSeconds * 8 + node.phase) + 1) * 0.5
        : 0
      const level = Math.min(1, localLevel * (0.66 + flicker * 0.34))
      const x = node.x * width
      const y = node.y * height
      const radius = 2.4 + level * 2.6
      const glow = context.createRadialGradient(x, y, 0, x, y, radius * 4.5)
      glow.addColorStop(0, nodeColor(node.layer, 0.75 + level * 0.25))
      glow.addColorStop(1, nodeColor(node.layer, 0))
      context.fillStyle = glow
      context.beginPath()
      context.arc(x, y, radius * 4.5, 0, Math.PI * 2)
      context.fill()
      context.fillStyle = nodeColor(node.layer, 0.38 + level * 0.62)
      context.beginPath()
      context.arc(x, y, radius, 0, Math.PI * 2)
      context.fill()
      context.strokeStyle = nodeColor(node.layer, 0.8)
      context.lineWidth = 0.8
      context.stroke()
    }

    context.fillStyle = this.live ? 'rgba(211, 255, 235, .72)' : 'rgba(159, 184, 202, .58)'
    context.font = '8px ui-monospace, SFMono-Regular, Menlo, monospace'
    context.fillText(this.live ? 'LIVE WINDOW · PULSES FOLLOW CNS OUTPUT' : this.inputLevel > 0.015 ? 'LOCAL SENSOR WINDOW · CNS FEED OFFLINE' : 'WAITING FOR SENSOR WINDOW', 10, height - 9)
  }
}

function setBar(element: HTMLSpanElement, value: number) {
  element.style.transform = `scaleX(${Math.max(0.02, Math.min(1, value))})`
  element.dataset.active = value > 0.02 ? 'true' : 'false'
}

function nodeColor(layer: number, alpha: number) {
  const colors = ['92, 211, 255', '105, 240, 190', '255, 207, 105', '255, 137, 201']
  return `rgba(${colors[layer] ?? colors[0]}, ${Math.max(0, Math.min(1, alpha))})`
}
