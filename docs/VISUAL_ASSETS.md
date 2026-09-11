# Open visual assets

## Canonical fly

- **Asset:** TuragaLab/Flybody `fruitfly.xml` plus referenced OBJ meshes
- **License:** Apache-2.0, as distributed by the upstream repository
- **Use:** canonical Drosophila body and wing/leg/abdomen assembly
- **Loader:** `frontend/src/rendering/FlybodyAsset.ts`

## World geometry

The supplied city GLB is the normal visible floor and the invisible arena
bounds remain separate physics limits. A procedural floor is used only if the
city asset cannot load. Live market habitats are procedural geometry with
compact food/rot/trash/market details, and their colored tops identify the
encoded sensory parameters assigned to each habitat.
The world can render up to 100 market identities without downloading one
large prop pack per token.

The supplied `street_city_7_for_games_free.glb` is copied to
`frontend/public/models/city/street_city.glb` and loaded by
`frontend/src/world/CityBackdrop.ts`. It is fitted around the presentation
floor while the physical fly bounds stay unchanged and receives a cool night
grade. The application does not add a second perimeter plate or unrelated side
props; the city, habitats, and flies are the visible world elements. Live habitats
are placed on the street floor inside the city and display neon token symbol/name labels plus
physical food, rot, trash-can, bag, or crate props.

The scene no longer uses unrelated bundled context props; only the coin/market
habitats are rendered as semantic objects.

Habitat particles are pooled instances. The scene has no unrelated decorative
fly population. The four
additional render-only bodies attached to each primary CNS agent are explicitly
labelled followers and do not add brains, sensors, or consensus votes.

## Canva background

- **Asset:** `frontend/public/design/fruit-fly-capital-canva-background.png`
- **Format:** 16:9 PNG, text-free, suitable for Canva upload or a pitch-deck
  background
- **Intent:** dark graphite market-ecology atmosphere with restrained emerald,
  cyan, and warm-gold light; the center and upper-left remain usable for
  overlaid brand copy
- **Provenance:** generated for this project; it is a presentation asset, not
  a biological or market-data input
