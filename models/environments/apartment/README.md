# Blender apartment

`apartment.blend` is an editable, metre-scale scene authored for this project.
It contains a living room, hall and dining room, two 1.30 m doorways, a couch,
coffee table, dining table, four chairs, console, bookcase and plants.
All geometry was generated locally; no third-party furniture assets are used.

Export the saved source after editing it in Blender:

```sh
blender -noaudio --background --python flex/scripts/prepare-environment.py -- \
  --blend models/environments/apartment/apartment.blend
./flex/scripts/build-sim.sh
./build/flex/puppybot-sim --environment apartment
```

The first command produces `apartment.glb`, `scene.json`, and `apartment.bin`
in `build/flex/sim/environments/apartment/`. Flexscript loads the binary mesh
and physics colliders directly. Blender is only needed for authoring/export.
The normal simulator build and original case catalog do not require Blender.

`SIM_WORLD` stores `sim_bounds` as `[minX,minY,maxX,maxY]`, `sim_spawn` as
`[x,y,headingRadians]`, and `sim_title`. Coordinates use Z up and metres.
Objects tagged `sim_collision` export one fixed box each, with their own
position, local dimensions, scale and Z rotation. Keep separate tabletop and
leg objects: the space beneath them stays empty. Tilted or sheared collider
transforms require simpler collision objects before export. At most 160
colliders and one million vertices fit the current native asset format.

Objects tagged `sim_cutaway` are shortened to 0.38 m in the existing world
overview. Their collisions and robot-camera geometry retain full height.
The Blender authoring camera and lights are excluded from the GLB export and
are never added as robot sensors. Native rendering uses material base colours
and its existing lighting; it does not reproduce Blender's full materials.

Furniture is static. Rugs, books, leaves and sofa cushions are visual detail;
the couch body and plant pots provide conservative physical bounds. The floor
is flat; the current robot drive model does not climb rugs or steps.

To recreate the original source, move your edited `.blend` somewhere safe and
run the exporter with `--generate` instead of `--blend`. It refuses to replace
an existing source. Exporting with `--blend` preserves that file.
