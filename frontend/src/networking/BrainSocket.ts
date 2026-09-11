import type { ActuatorCommand, BrainActivity, BrainInputMessage, EnvironmentUpdateMessage, MaleCNSSensoryStimulation, SwarmTelemetryMessage, SwarmRoleMessage, FundStatusUpdateMessage, PortfolioUpdateMessage, TradeHistoryUpdateMessage } from './protocol'
import { isBrainOutputMessage, isEnvironmentUpdateMessage, isSwarmRoleMessage, isSwarmUpdateMessage } from './protocol'

export type BrainSocketStatus = 'disconnected' | 'connecting' | 'connected' | 'error'
export type SwarmTelemetryRole = SwarmRoleMessage['role'] | 'unknown'

const neutralCommand: ActuatorCommand = {
  forwardThrust: 0,
  verticalThrust: 0.5,
  yawTorque: 0,
  pitchTorque: 0,
  rollTorque: 0,
}

export class BrainSocket {
  private socket: WebSocket | null = null
  private latestCommands = new Map<string, ActuatorCommand>()
  private latestStimulations = new Map<string, MaleCNSSensoryStimulation>()
  private latestActivity = new Map<string, BrainActivity>()
  private readonly pendingInputs = new Set<string>()
  private latestEnvironment: EnvironmentUpdateMessage['environment'] | null = null
  private latestSwarmDecision: Record<string, unknown> | null = null
  private latestFundStatus: FundStatusUpdateMessage['fund'] | null = null
  private latestPortfolio: PortfolioUpdateMessage['fund'] | null = null
  private latestTrades: TradeHistoryUpdateMessage['trades'] = []
  private status: BrainSocketStatus = 'disconnected'
  private readonly listeners = new Set<(status: BrainSocketStatus) => void>()
  private reconnectTimer: number | null = null
  private reconnectAttempt = 0
  private shouldReconnect = true
  private role: SwarmTelemetryRole = 'unknown'
  private readonly roleListeners = new Set<(role: SwarmTelemetryRole) => void>()

  constructor(private readonly url: string) {}

  connect() {
    this.shouldReconnect = true
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) return
    this.setStatus('connecting')
    const socket = new WebSocket(this.url)
    this.socket = socket
    socket.addEventListener('open', () => {
      this.reconnectAttempt = 0
      this.setRole('unknown')
      this.setStatus('connected')
      this.claimTelemetryProducer()
    })
    socket.addEventListener('close', () => {
      if (this.socket !== socket) return
      this.socket = null
      this.pendingInputs.clear()
      this.setRole('unknown')
      this.setStatus('disconnected')
      this.scheduleReconnect()
    })
    socket.addEventListener('error', () => this.setStatus('error'))
    socket.addEventListener('message', (event) => this.handleMessage(event.data))
  }

  disconnect() {
    this.shouldReconnect = false
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.socket?.close()
    this.socket = null
    this.pendingInputs.clear()
    this.setRole('unknown')
    this.setStatus('disconnected')
  }

  onStatusChange(listener: (status: BrainSocketStatus) => void) {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  onSwarmRoleChange(listener: (role: SwarmTelemetryRole) => void) {
    this.roleListeners.add(listener)
    return () => this.roleListeners.delete(listener)
  }

  send(frame: BrainInputMessage) {
    if (this.socket?.readyState !== WebSocket.OPEN || this.role !== 'producer') return false
    // The Brian2 adapter is deliberately slower than the render loop. Never
    // let one fly build an unbounded queue of stale sensory frames while its
    // previous fixed window is still running.
    if (this.pendingInputs.has(frame.flyId)) return false
    this.socket.send(JSON.stringify(frame))
    this.pendingInputs.add(frame.flyId)
    return true
  }

  requestEnvironment() {
    if (this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(JSON.stringify({ type: 'environment_request' }))
    return true
  }

  sendSwarmTelemetry(message: SwarmTelemetryMessage) {
    if (this.socket?.readyState !== WebSocket.OPEN || this.role !== 'producer') return false
    this.socket.send(JSON.stringify(message))
    return true
  }

  telemetryRole() {
    return this.role
  }

  swarmDecision() {
    return this.latestSwarmDecision
  }

  requestFundStatus() { return this.request({ type: 'fund_status_request' }) }
  requestPortfolio() { return this.request({ type: 'portfolio_request' }) }
  requestTradeHistory() { return this.request({ type: 'trade_history_request' }) }
  fundStatus() { return this.latestFundStatus }
  portfolio() { return this.latestPortfolio }
  tradeHistory() { return this.latestTrades }

  environmentUpdate() {
    return this.latestEnvironment
  }

  commandsFor(flyId: string): ActuatorCommand {
    return this.latestCommands.get(flyId) ?? neutralCommand
  }

  stimulationFor(flyId: string): MaleCNSSensoryStimulation | null {
    return this.latestStimulations.get(flyId) ?? null
  }

  activityFor(flyId: string): BrainActivity | null {
    return this.latestActivity.get(flyId) ?? null
  }

  getStatus() {
    return this.status
  }

  private handleMessage(raw: unknown) {
    if (typeof raw !== 'string') return
    try {
      const message: unknown = JSON.parse(raw)
      if (isBrainOutputMessage(message)) {
        this.pendingInputs.delete(message.flyId)
        this.latestCommands.set(message.flyId, message.commands)
        if (message.stimulation) this.latestStimulations.set(message.flyId, message.stimulation)
        if (message.flightCommand && message.descendingRates && message.spikeCounts) {
          this.latestActivity.set(message.flyId, {
            flightCommand: message.flightCommand,
            maleCnsCommand: message.maleCnsCommand,
            steeringReference7d: message.steeringReference7d,
            lowLevelFlightCommand: message.lowLevelFlightCommand,
            flybodyJointAction: message.flybodyJointAction,
            physicalVelocity: message.physicalVelocity,
            physicalPosition: message.physicalPosition,
            descendingRates: message.descendingRates,
            spikeCounts: message.spikeCounts,
            source: message.source,
          })
        }
      } else if (isEnvironmentUpdateMessage(message)) {
        this.latestEnvironment = message.environment
      } else if (isSwarmUpdateMessage(message)) {
        this.latestSwarmDecision = message.decision
      } else if (isSwarmRoleMessage(message)) {
        this.setRole(message.role === 'available' ? 'unknown' : message.role)
        if (message.role === 'available') this.claimTelemetryProducer()
      } else if (message && typeof message === 'object' && (message as { type?: string }).type === 'fund_status_update') {
        this.latestFundStatus = (message as FundStatusUpdateMessage).fund
      } else if (message && typeof message === 'object' && (message as { type?: string }).type === 'portfolio_update') {
        this.latestPortfolio = (message as PortfolioUpdateMessage).fund
      } else if (message && typeof message === 'object' && (message as { type?: string }).type === 'trade_history_update') {
        this.latestTrades = (message as TradeHistoryUpdateMessage).trades
      }
    } catch {
      this.setStatus('error')
    }
  }

  private request(message: Record<string, unknown>) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(JSON.stringify(message)); return true
  }

  private claimTelemetryProducer() {
    if (this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(JSON.stringify({ type: 'swarm_claim' }))
    return true
  }

  private setStatus(status: BrainSocketStatus) {
    this.status = status
    this.listeners.forEach((listener) => listener(status))
  }

  private setRole(role: SwarmTelemetryRole) {
    if (this.role === role) return
    this.role = role
    this.roleListeners.forEach((listener) => listener(role))
  }

  private scheduleReconnect() {
    if (!this.shouldReconnect || this.reconnectTimer !== null) return
    const delay = Math.min(5000, 250 * 2 ** Math.min(this.reconnectAttempt, 5))
    this.reconnectAttempt += 1
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }
}
