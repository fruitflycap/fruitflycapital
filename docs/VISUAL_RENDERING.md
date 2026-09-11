# Fruit Fly Capital visual rendering

The visual layer is presentation only. It does not alter MaleCNS topology,
neural state, sensor encoding, physics units, or actuator semantics.

## Minimal dependency plan

- `three` remains the scene, camera, GLTF/OBJ loaders, instancing, and buffer
  management layer.
- `postprocessing` is the only added runtime dependency. It provides SMAA,
  ACES filmic tone mapping, selective bloom, vignette, and an optional low-cost
  normal/AO pass.
- The canonical Flybody XML and its referenced OBJ meshes are vendored under
  `third_party/flybody/` and copied into the generated
  `frontend/public/models/flybody/` build path. The supplied street-city GLB is
  loaded as the surrounding scene; no unrelated prop bundle is required.

## Quality presets

`performance` is the default. It uses a capped device pixel ratio, SMAA, and
tone mapping while keeping bloom and AO disabled. Press `P` in the browser to
toggle the `demo` preset. The demo preset enables subtle bloom, vignette, and
half-resolution SSAO; it is intended for a presentation machine, not for
benchmarking a larger swarm.

The fixed body update remains 120 Hz and the browser render loop remains
`requestAnimationFrame`. Post-processing is not inserted into the neural or
physics loop.

## Canonical fly LOD

Every visible agent still uses the same canonical Flybody XML/OBJ geometry.
LOD only changes which already-loaded XML geoms are drawn:

- `full`: every canonical geom for the selected or nearby agent;
- `medium`: head, thorax, abdomen, and both wings;
- `low`: a smaller canonical silhouette for distant agents.

No billboard or replacement fly is introduced by the LOD system. Independent
agent bodies, sensors, brains, and trajectories remain unchanged.

## Habitats and particles

The world contains up to 100 dynamically keyed market habitats. Their compact
token marker, neon label, floor glow, semantic food/rot/trash/market props, and
particle intensity are derived from the existing provider-neutral
`HabitatProperties` (`brightness`, `particleActivity`, `chaos`, and motion),
not from a hidden target or scripted path. All particles are instances of one
pooled `InstancedMesh`; fly trails are one dynamic `LineSegments` buffer.

The market scene uses physical market habitats as semantic objects placed on
the presentation street floor inside the supplied city. Food habitats use fruit/banana props, rot habitats use
spoiled scraps, trash habitats use cans and bags, and quieter markets use
crates. The city GLB is tinted for night, the Canva sky is assigned to
`scene.background`, and a restrained teal fog reduces the distant hard edge.
Perimeter set dressing is presentation-only. A failed
market-data request cannot turn a missing habitat into a fake prop or target.
In live mode the frontend starts empty and waits for the authoritative market
snapshot; fixture habitats exist only when a local test scenario is explicitly
selected.

### City placement tuning

The imported city is fitted and centered automatically, then receives the
scene-only offsets in `frontend/src/world/CityBackdrop.ts`:

```ts
offsetX: 0,
offsetY: -0.10, // 10 cm lower than the normalized city ground
offsetZ: 0,
rotationY: 0,
scaleMultiplier: 1,
```

Adjust those values to tune the visual model. `offsetY` is in world metres;
negative moves the GLB down. These controls do not move habitats, flies, or
the physics arena. The supplied city remains unrotated so its street plan is
preserved.

The public scene includes a small `SCENE POSITION` panel on the right. Its
buttons and sliders change X, height, Z, rotation, and scale without editing a
URL. Every change is clamped to safe presentation limits and saved in browser
local storage, so a refresh keeps the chosen placement. `RESET CITY POSITION`
restores the authored fit.

## Presentation and debug modes

The initial view is `DEMO`: product title, agent count, CNS-active count, and a
compact pressure status. The camera starts in the user-controlled free street
view; cinematic views are opt-in from developer controls. Press `` ` `` or click the top-right toggle to enter
`DEBUG`, which exposes socket state, causal telemetry, population state,
camera targeting, scenarios, and render metrics.

Camera keys are `1` free orbit, `2` selected-agent follow, `3` first-person,
`4` side/debug, `5` token cinematic, and `6` auto director. None of these
cameras gives the brain privileged coordinates; they only change the human
observer's view.

The default free camera is constrained to the presentation world: panning is
disabled, orbit elevation stays above the floor, and zoom is capped at the
outer scene boundary. This prevents the observer from going underground or
dragging the view outside the city. Its limits are centralized in
`frontend/src/camera/FreeCamera.ts`.
