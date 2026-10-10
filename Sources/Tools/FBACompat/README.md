# FBA compatibility builder

Builds `01 FBA Compatibility`, the installer's FBA option: ReAnimation's 1st-person animations with the
legs, pelvis and root motion of the 3rd-person animations that OpenMW Full Body Awareness (FBA)
plays in 1st person,
plus a slight forward chest lean so the body doesn't fill the screen when looking down.

It always starts from the original animations, so rebuilding never stacks changes.

## Run it

```
python3 Sources/Tools/FBACompat/build_compat.py
```

It asks for each setting with the default filled in. Press Enter to keep a default, or pass `-y`
to accept all of them without being asked. Any setting can also be given on the command line:

```
python3 Sources/Tools/FBACompat/build_compat.py -y --hip-motion 1.0
```

`-v` prints per-group detail while building; without it you get one line per file, then warnings.

| Option | Default | What it does |
|---|---|---|
| `--fba DIR` | found via `openmw.cfg` or the mods folder | FBA's folder (the one containing `meshes/xbase_anim.1st.kf`). |
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

Add the output's parent folder (`01 FBA Compatibility`) as a data folder **after**
ReAnimation's `00 Core` and FBA - or tick "FBA Compatibility" in the installer, which ships it built
with the defaults. Its `ReAnimation_FBA_Compatibility.txt` is how ReAnimation's scripts know it's
installed.

## Other scripts here

- `check_all.py [kf names]` compares the built animations with the originals (spine and neck drift,
  chest lean, foot heights, root motion, which foot steps where).
- `fba_fingers.py <FBA folder> <Morrowind Data Files> <output>` builds the separate
  **FBA 1st-Person Hands** package, which restores the vanilla 1st-person hands and converts FBA's
  own animations to their fingers.
