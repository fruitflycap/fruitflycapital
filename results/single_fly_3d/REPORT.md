# Autonomous flight experiment report

Seed: `20260909`  
Neural provider: `none`  
Interpretation: the `malecns_connected` condition runs the exact sensory encoder and decoder with an empty rate window. It is not a live Brian2 autonomous run.

## A — visual stabilization

Both conditions received four identical small rotational disturbances. The
MaleCNS-connected and motor-disabled conditions had mean yaw command `0.000000`
and `0.000000`, respectively. Their mean angular speed at 0.5 s after each
disturbance was `0.003849` and `0.003849` rad/s. The identical values indicate
passive rigid-body damping only; no neural stabilizing response was observed.

## B — visual target

Left, right, above, and below target stimulus conditions were run. Every
condition produced maximum absolute yaw, pitch, and roll command `0.0` and
maximum selected descending rate `0.0 Hz`. Elevation-specific encoding is
currently unsupported by the R8d mean-luminance encoder, so above/below are
recorded stimulus labels rather than claims of a CNS distinction.

## C — odor source

The visual source was hidden and concentration was generated from distance to
the odor source. The connected condition changed distance from
`0.935307 m` to `0.935427 m`, with heading change `0.000000` rad. The motor-disabled
condition changed distance from `0.935307 m` to `0.938532 m`, with heading change
`0.000000` rad. Both had zero horizontal path and zero decoded yaw; no odor
tracking behavior was observed.

## D — free flight

The unscripted 60 s run had path length `0.015080 m`, final position
`[0.0, 0.46491950030999146, 0.0] m`, and landed=`False`. Selected descending activity and decoded yaw were
zero. This is a neutral-provider baseline, not evidence of autonomous flight.
