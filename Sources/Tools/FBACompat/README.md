# FBA compatibility builder

Builds `01 FBA Compatibility`, the installer's FBA option: ReAnimation's 1st-person animations with the
legs, pelvis and root motion of the 3rd-person animations that OpenMW Full Body Awareness (FBA)
plays in 1st person,
plus a slight forward chest lean so the body doesn't fill the screen when looking down.

It always starts from the original animations, so rebuilding never stacks changes.

## What you need

- Python 3.8 or newer. Nothing else: only Python's standard library is used.
- The downloaded ReAnimation archive, extracted. Mod managers install only the mod and the patches
  you pick, not `Sources/`, so the script is only in the archive. Run it there: it finds
  `00 Core` next to it.

## Run it

```
python3 Sources/Tools/FBACompat/build_compat.py
```

On Windows the command is `py` instead of `python3`, or double-click `build_compat.py`: the window
asks the questions below and stays open at the end until you press Enter.

It asks for each setting with the default filled in. Press Enter to keep a default, or pass `-y`
to accept all of them without being asked. Any setting can also be given on the command line:

```
python3 Sources/Tools/FBACompat/build_compat.py -y --hip-motion 1.0
```

`-v` prints per-group detail while building; without it you get one line per file, then warnings.
It prints which FBA animations it used, since that folder is found by itself.

Everything is built in a temporary folder and copied to the output only at the end, so a build that
fails or is closed halfway leaves the output as it was. Kfs an earlier build left in the output that
this one no longer makes are deleted from `01 FBA Compatibility`, and only listed for an output
folder of your own. Kfs that key no leg bone (the shield and torch arm overlays) have no legs to
merge and are left out.

It refuses to convert animations that are already converted: those whose data folder has
`ReAnimation_FBA_Compatibility.txt`, like a mod manager's ReAnimation installed with the FBA option
ticked. Point `--anims` at the archive's `00 Core/Animations/xbase_anim.1st` instead.

| Option | Default | What it does |
|---|---|---|
| `--fba DIR` | found via `openmw.cfg` or the mods folder | FBA's folder (the one containing `meshes/xbase_anim.1st.kf`). In `openmw.cfg` the last enabled `data=` line with FBA wins. |
| `--anims DIR` | this mod's `00 Core/Animations/xbase_anim.1st` | The animations to convert. |
| `--out DIR` | this mod's `01 FBA Compatibility/Animations/xbase_anim.1st` | Where the converted animations go. |
| `--lean DEG` | `15` | Extra forward chest lean. The neck counter-rotates, so the view and arms stay as animated. |
| `--hip-motion 0..1` | `0.5` | How much of FBA's hip lunge to keep during attacks. Below 1.0 steps are shortened to match and the legs bend to reach them. If the feet misbehave, use `1.0`. |
| `--sway 0..1` | `0.33` | How much of the walk/run hip swing reaches the upper body. |
| `--idle-when-feet-lift y/n` | `y` | Use idle legs where FBA would lift both feet off the ground (the crossbow reload). |
| `--strafing-speed-fix y/n` | `y` | Strafing animation speed fix, below. |
| `--alias PATTERN=NAME` | none | Renames our animation groups before their 3rd-person legs are looked up, for sets named their own way. A regular expression; repeat it for several, they apply in order. |

### Strafing animation speed fix

It doesn't touch the 3rd-person strafing animations, but those usually take very quick steps: the game
plays a walk or run as fast as it needs to keep up with your movement, and FBA's run strafes cover
half the ground per step its forward run does, so they play twice as fast - and the 1st-person part
of the animation swung along at the same frantic pace. With the fix the 1st-person part swings half as
often: one 1st-person step to two of the legs'. It applies wherever a strafe's stride per step is 2/3
of the forward one's or less (with FBA: the run strafes, not the walk or sneak ones). The footstep
sounds stay on the legs' steps.

### Other animation sets

`--anims` and `--out` convert any set of 1st-person animations, not only ReAnimation's. Groups are
matched to FBA's 3rd-person ones by name, so a set with names of its own needs `--alias`, e.g. a
katar set that walks on the hand-to-hand legs:

```
python3 Sources/Tools/FBACompat/build_compat.py -y --anims "<mod>/Animations/xbase_anim.1st" \
    --out "<patch>/Animations/xbase_anim.1st" --alias "^katar(alt)?$=handtohand" --alias "katar=hh"
```

Footsteps are read from `SoundGen` keys, or `SoundGenRef` ones (a set playing over another one that
sounds the steps).

## Install the result

The installer's "FBA Compatibility" option already ships it built with the defaults; this is for a
build of your own.

Converting ReAnimation's own animations also writes `ReAnimation_FBA_Compatibility.txt` next to the
output's `Animations` folder: it is how ReAnimation's scripts know the patch is installed. (With an
output that isn't an `Animations/xbase_anim.1st` folder, copy it there yourself from
`01 FBA Compatibility`.)

- **By hand:** add the output's data folder (`01 FBA Compatibility` by default) as a data folder
  **after** ReAnimation's `00 Core` and FBA.
- **With a mod manager:** install the output's data folder as a mod of its own, after ReAnimation.
  For example, zip the `Animations` folder and `ReAnimation_FBA_Compatibility.txt` from
  `01 FBA Compatibility` and install the zip, or build straight into a new mod's folder with
  `--out "<mod manager's mods folder>/ReAnimation FBA (my build)/Animations/xbase_anim.1st"`. Leave
  the installer's FBA option unticked, or your build has to load after it.

## Other scripts here

- `check_all.py [--anims DIR] [--out DIR] [kf names]` compares the built animations with the
  originals (spine and neck drift, chest lean, foot heights, root motion, which foot steps where).
  The defaults are ReAnimation's `00 Core` and `01 FBA Compatibility`.
- `fba_fingers.py [-y] [--fba DIR] [--data DIR] [--out DIR]` builds a 1st-person hands package for
  FBA: the vanilla 1st-person hand meshes back, and FBA's own animations converted to their fingers.
  FBA's First Person Hands patch does the same, so you only need this to build it yourself.
