# Canonical Drosophila body integration

## Source of truth

The rendered fly body is sourced from the Apache-2.0 [TuragaLab/flybody]
repository, specifically:

```text
third_party/flybody/flybody/fruitfly/assets/fruitfly.xml
```

The browser serves the same XML and its referenced OBJ meshes through
`frontend/public/models/flybody/fruitfly/assets/`. The frontend build copies
the required files from the vendored package into that public path, rather than
relying on a symlink that Vercel may omit. `FlybodyAssetLoader` parses the XML
at runtime and reconstructs its nested body/geom hierarchy.

## Coordinate and scale adaptation

The XML declares `angle="radian"` and uses MuJoCo's Z-up convention. The
Three.js world is Y-up, so the loaded asset root applies a -90 degree rotation
about X. Flybody's anatomical head direction is MuJoCo +X, while this
simulation's forward direction is Three.js -Z, so the asset also applies a +90
degree Y rotation using Three's `YXZ` order. The order is material: default
`XYZ` would send the head axis downward. The resulting conversion is +X -> -Z
and +Z/up -> +Y. Flybody's XML mesh default scale is `0.1`; the loader
preserves it and converts the XML's centimetre-scale positions and mesh
coordinates to metres. These conversions are interface adaptations, not a
change to the body geometry.

The Three.js renderer applies an explicit 12x display-only magnification so a
millimetre-scale fly can be inspected from the room-scale free camera. It does
not change the FlyBody position, collision radius, sensor origins, or logged
physical units.

All sixteen pilot agents load the same canonical XML/OBJ scene. To keep the
population view interactive, unselected agents use a render-only LOD showing the canonical
head, thorax, abdomen, and wings; the selected agent renders all XML geoms.
Selecting another fly changes only this display detail and camera focus, never
the physical or neural state.

The first-person camera is consequently offset beyond the magnified display
mesh rather than placed at a literal millimetre-scale eye point. This is a
rendering accommodation only; sensor rays continue to originate from the
physical FlyBody frame.

The source XML explicitly exposes `wing_left` and `wing_right` bodies, each
with yaw, roll, and pitch joints. The renderer retains those body nodes and
drives their visual pose with `WingBeatPatternGenerator`.

The browser rigid-body preview uses local body-frame angular velocity. Its
forward axis is Three.js local `-Z`, so a positive right-yaw actuator is
integrated about local `-Y`; this is the sign convention that keeps the
displayed head, heading vector, and velocity direction aligned. It is an
interface convention for the preview and does not alter the Flybody XML.
The preview also bounds translational and angular rates to keep held manual
inputs from numerically flipping or tunnelling through the small display
volume; these are browser stability limits, not Flybody biomechanical data.

## Physics status

MuJoCo is the intended authoritative physics backend for Flybody. The
repository now includes `malecns.flybody.MuJoCoFlybody`, an optional lazy
wrapper that loads this exact XML and steps Flybody's native actuator vector.
The current checkout does not include the MuJoCo Python package or a running
MuJoCo pose server, so the Three.js preview must not be described as running
Flybody MuJoCo physics yet. The backend boundary is deliberately kept separate
so a MuJoCo server can publish pose/joint state later without granting MaleCNS
direct physics access.

On macOS, invoke the environment's interpreter explicitly; do not rely on a
global `python` command. The recommended setup is the `.venv312` command shown
in the root README.

No `FlightCommand` to native Flybody joint-control mapping is introduced here:
the XML's actuators are preserved, and a mapping requires a separate,
documented biomechanical control decision.

If the XML/OBJ static assets are unavailable, the renderer shows a tiny
placeholder and logs an explicit warning. That fallback is only a loading
indicator; scientific renders should wait for `FlyRenderer.ready`.

## Wing beat provenance

The vendored Flybody source contains
`flybody/tasks/pattern_generators.py::WingBeatPatternGenerator`. This project
keeps its public control concept and documented fallback waveform in
`frontend/src/fly/WingBeatPattern.ts`: 218 Hz baseline, +/-5% frequency range,
phase-continuous updates, and the fallback yaw/roll/pitch equations. This
TypeScript bridge is a browser visualization adaptation, not a claim that the
Python Flybody controller has been replaced.

[TuragaLab/flybody]: https://github.com/TuragaLab/flybody
