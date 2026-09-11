import { ArrowHelper, Group, Vector3 } from 'three'
import { FlyAgent } from '../fly/FlyAgent'
import { isLiveBrainSource, type BrainActivity, type MaleCNSSensoryStimulation } from '../networking/protocol'

export class DebugRenderer {
  readonly group = new Group()
  private readonly forwardArrow: ArrowHelper
  private readonly upArrow: ArrowHelper
  private readonly velocityArrow: ArrowHelper
  private readonly sensoryArrow: ArrowHelper
  private readonly panel: HTMLDivElement
  private readonly forward = new Vector3()
  private readonly up = new Vector3()
  private readonly velocity = new Vector3()
  private readonly velocityDirection = new Vector3()
  private lastPanelUpdate = Number.NEGATIVE_INFINITY
  private panelVisible = true

  constructor(uiRoot: HTMLElement, private label = 'FLY #001', panelSide: 'left' | 'right' = 'right') {
    this.group.name = 'DebugVectors'
    this.forwardArrow = new ArrowHelper(new Vector3(0, 0, -1), new Vector3(), 0.12, 0x50b7ff, 0.025, 0.012)
    this.upArrow = new ArrowHelper(new Vector3(0, 1, 0), new Vector3(), 0.08, 0x5eff93, 0.02, 0.01)
    this.velocityArrow = new ArrowHelper(new Vector3(1, 0, 0), new Vector3(), 0.08, 0xffd15c, 0.02, 0.01)
    this.sensoryArrow = new ArrowHelper(new Vector3(0, 0, -1), new Vector3(), 0.1, 0xff86db, 0.018, 0.009)
    this.group.add(this.forwardArrow, this.upArrow, this.velocityArrow, this.sensoryArrow)
    this.panel = document.createElement('div')
    this.panel.className = 'debug-panel'
    this.panel.style[panelSide] = '25px'
    uiRoot.append(this.panel)
  }

  setLabel(label: string) {
    this.label = label
  }

  setVectorsVisible(visible: boolean) {
    this.group.visible = visible
  }

  setPanelVisible(visible: boolean) {
    this.panelVisible = visible
    this.panel.hidden = !visible
  }

  update(agent: FlyAgent, elapsedSeconds: number, brainStatus: string, stimulation: MaleCNSSensoryStimulation | null, activity: BrainActivity | null) {
    const origin = agent.body.position
    const forward = this.forward.set(0, 0, -1).applyQuaternion(agent.body.quaternion).normalize()
    const up = this.up.set(0, 1, 0).applyQuaternion(agent.body.quaternion).normalize()
    const velocity = this.velocity.copy(agent.body.velocity)
    const speed = velocity.length()
    this.forwardArrow.position.copy(origin)
    this.forwardArrow.setDirection(forward)
    this.forwardArrow.setLength(0.12, 0.025, 0.012)
    this.upArrow.position.copy(origin)
    this.upArrow.setDirection(up)
    this.velocityArrow.position.copy(origin)
    this.velocityArrow.setDirection(speed > 0.0001 ? this.velocityDirection.copy(velocity).normalize() : forward)
    this.velocityArrow.setLength(Math.min(0.2, speed * 0.45), 0.02, 0.01)
    this.sensoryArrow.position.copy(origin)
    this.sensoryArrow.setDirection(forward)
    this.sensoryArrow.setLength(Math.min(0.25, Math.max(0.03, agent.sensors.getObstacleDistance())), 0.018, 0.009)

    if (!this.panelVisible) return

    // The vectors remain live at render rate, but the textual panel only needs
    // a 10 Hz refresh. Updating innerHTML for two panels every animation frame
    // was a measurable source of UI jank on the high-detail Flybody scene.
    if (elapsedSeconds - this.lastPanelUpdate < 0.1) return
    this.lastPanelUpdate = elapsedSeconds

    const command = agent.actuators.get()
    const sensory = agent.sensors.getFrame()
    const visualStimulation = stimulation?.visual ?? []
    const olfactoryStimulation = stimulation?.olfactory ?? []
    const mechanosensoryStimulation = stimulation?.mechanosensory ?? []
    const stimulationSummary = stimulation
      ? `R8d ${visualStimulation.length} cells · ORN_DA1 ${olfactoryStimulation.length} cells · JO ${mechanosensoryStimulation.length} cells`
      : 'waiting for encoded MaleCNS input'
    const hasSpikes = activity ? Object.values(activity.spikeCounts).some((count) => count > 0) : false
    const hasDescendingSpikes = activity ? Object.values(activity.descendingRates).some((rate) => rate > 0) : false
    const hasLiveBrian2 = isLiveBrainSource(activity?.source)
    const controllerSummary = agent.mode === 'off'
      ? 'OFF: stationary actuator command'
      : agent.mode === 'manual'
        ? 'MANUAL: keyboard actuator drive'
        : hasLiveBrian2
          ? hasSpikes
            ? `MALECNS: live Brian2${hasDescendingSpikes ? ' · DN activity' : ' · no selected-DN spikes'}`
            : 'MALECNS: live window · no spikes'
          : activity
            ? 'MALECNS: decoder-only · no live provider'
          : 'MALECNS: waiting for live spike-rate provider'
    const descendingSummary = activity
      ? hasDescendingSpikes
        ? `L ${rate(activity, 'turn_left').toFixed(2)} · R ${rate(activity, 'turn_right').toFixed(2)} · wing ${rate(activity, 'wing_amplitude').toFixed(2)} Hz`
        : '0 Hz in current window · selected DN populations quiet'
      : 'waiting for CNS activity'
    const flightCommand = activity?.flightCommand
    const p = origin
    this.panel.innerHTML = [
      `<strong>${this.label} / ${agent.mode.toUpperCase()}</strong> · ${controllerSummary} · socket ${brainStatus}`,
      `t ${elapsedSeconds.toFixed(2)} s`,
      `pos (${p.x.toFixed(3)}, ${p.y.toFixed(3)}, ${p.z.toFixed(3)}) m`,
      `vel (${velocity.x.toFixed(3)}, ${velocity.y.toFixed(3)}, ${velocity.z.toFixed(3)}) m/s · |v| ${speed.toFixed(3)}`,
      `LEFT EYE  lum ${sensory.leftEye.meanLuminance.toFixed(3)} · con ${sensory.leftEye.meanContrast.toFixed(3)} · flow ${sensory.leftEye.meanOpticFlow.toFixed(3)}`,
      `RIGHT EYE lum ${sensory.rightEye.meanLuminance.toFixed(3)} · con ${sensory.rightEye.meanContrast.toFixed(3)} · flow ${sensory.rightEye.meanOpticFlow.toFixed(3)}`,
      `OPTIC FLOW ${(0.5 * (sensory.leftEye.meanOpticFlow + sensory.rightEye.meanOpticFlow)).toFixed(3)} · gravity ${sensory.motion.gravityAlignment.toFixed(3)}`,
      `MOTION speed ${sensory.motion.translationalSpeed.toFixed(3)} · ang (${sensory.motion.angularVelocity.x.toFixed(2)}, ${sensory.motion.angularVelocity.y.toFixed(2)}, ${sensory.motion.angularVelocity.z.toFixed(2)}) · wind n/a`,
      `ODOR attract ${sensory.odor.concentration.toFixed(3)} · L ${sensory.odor.leftAntenna.toFixed(3)} · R ${sensory.odor.rightAntenna.toFixed(3)} · danger ${sensory.odor.aversiveConcentration.toFixed(3)}`,
      `CONTACT ground=${sensory.contact.ground} obstacle=${sensory.contact.obstacle} wall=${sensory.contact.wall}`,
      `SENSORY ↓ CNS ${stimulationSummary}`,
      `CNS ACTIVITY ↓ DN ${descendingSummary}`,
      `CNS COMMAND thrust=${flightCommand?.thrust.toFixed(2) ?? '0.00'} yaw=${flightCommand?.yaw.toFixed(2) ?? '0.00'} pitch=${flightCommand?.pitch.toFixed(2) ?? '0.00'} roll=${flightCommand?.roll.toFixed(2) ?? '0.00'}`,
      `unimplemented ${stimulation?.unimplemented.length ?? 5} sensory mappings`,
      `thrust f=${command.forwardThrust.toFixed(2)} v=${command.verticalThrust.toFixed(2)}`,
      `torque y=${command.yawTorque.toFixed(2)} p=${command.pitchTorque.toFixed(2)} r=${command.rollTorque.toFixed(2)}`,
    ].join('<br>')
  }
}

function rate(activity: BrainActivity, name: string) {
  return activity.descendingRates[name] ?? 0
}
