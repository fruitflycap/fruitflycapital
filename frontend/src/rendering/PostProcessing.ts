import {
  Camera,
  NoToneMapping,
  Scene,
  SRGBColorSpace,
  WebGLRenderer,
} from 'three'
import {
  BloomEffect,
  EffectComposer,
  EffectPass,
  NormalPass,
  RenderPass,
  SMAAEffect,
  SMAAPreset,
  SSAOEffect,
  ToneMappingEffect,
  ToneMappingMode,
  VignetteEffect,
} from 'postprocessing'

export type RenderQuality = 'performance' | 'demo'

/**
 * Small, explicit presentation pipeline. The performance preset is the
 * default because the application may be running many independent agents;
 * the demo preset adds the expensive cinematic passes on demand.
 */
export class PostProcessingPipeline {
  readonly composer: EffectComposer
  private readonly renderer: WebGLRenderer
  private readonly normalPass: NormalPass
  private readonly ssao: SSAOEffect
  private readonly bloom: BloomEffect
  private readonly vignette: VignetteEffect
  private readonly smaa: SMAAEffect
  private quality: RenderQuality = 'performance'

  constructor(renderer: WebGLRenderer, scene: Scene, camera: Camera) {
    this.renderer = renderer
    renderer.outputColorSpace = SRGBColorSpace
    renderer.toneMapping = NoToneMapping

    this.composer = new EffectComposer(renderer, { depthBuffer: true, multisampling: 0 })
    this.composer.setMainScene(scene)
    this.composer.setMainCamera(camera)

    const renderPass = new RenderPass(scene, camera)
    this.normalPass = new NormalPass(scene, camera, { resolutionScale: 0.5 })
    this.normalPass.enabled = false
    this.ssao = new SSAOEffect(camera, this.normalPass.texture, {
      samples: 4,
      rings: 3,
      radius: 0.18,
      intensity: 0.35,
      resolutionScale: 0.5,
    })
    this.ssao.blendMode.opacity.value = 0

    this.smaa = new SMAAEffect({ preset: SMAAPreset.LOW })
    this.bloom = new BloomEffect({
      intensity: 0.7,
      luminanceThreshold: 1.15,
      luminanceSmoothing: 0.18,
      mipmapBlur: true,
      radius: 0.72,
      levels: 5,
    })
    this.bloom.blendMode.opacity.value = 0
    this.vignette = new VignetteEffect({ offset: 0.42, darkness: 0.22 })
    this.vignette.blendMode.opacity.value = 0
    const toneMapping = new ToneMappingEffect({ mode: ToneMappingMode.ACES_FILMIC })

    this.composer.addPass(renderPass)
    this.composer.addPass(this.normalPass)
    this.composer.addPass(new EffectPass(camera, this.smaa, toneMapping, this.bloom, this.ssao, this.vignette))
    this.setQuality('performance')
  }

  get currentQuality() {
    return this.quality
  }

  setQuality(quality: RenderQuality) {
    this.quality = quality
    const demo = quality === 'demo'
    // Mobile GPUs tend to report a high device pixel ratio, which can make a
    // full-screen WebGL scene disproportionately expensive. Keep the scene
    // crisp enough for the game while capping the backing buffer below CSS
    // pixels on small screens.
    const mobile = window.matchMedia?.('(max-width: 600px)').matches ?? false
    const pixelRatioCap = mobile ? 0.85 : demo ? 1.25 : 1
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, pixelRatioCap))
    // SMAA's preset is immutable after construction, so its LOW preset is
    // intentionally retained for both presets. The quality switch controls
    // the costly lighting effects and pixel ratio instead.
    this.normalPass.enabled = demo
    this.ssao.blendMode.opacity.value = demo ? 0.55 : 0
    this.bloom.blendMode.opacity.value = demo ? 0.78 : 0
    this.vignette.blendMode.opacity.value = demo ? 0.35 : 0
  }

  setCamera(camera: Camera) {
    this.composer.setMainCamera(camera)
  }

  resize(width: number, height: number) {
    this.composer.setSize(width, height)
  }

  render(deltaSeconds: number, camera: Camera) {
    this.setCamera(camera)
    this.composer.render(deltaSeconds)
  }
}
