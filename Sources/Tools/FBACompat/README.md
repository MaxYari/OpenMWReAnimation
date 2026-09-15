# FBA compatibility builder

Builds the **ReAnimation FBA Compatibility** folder: ReAnimation's 1st-person animations with the
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
| `--anims DIR` | this mod's `Animations/xbase_anim.1st` | The animations to convert. |
| `--out DIR` | `../ReAnimation FBA Compatibility/Animations/xbase_anim.1st` | Where the converted animations go. |
| `--lean DEG` | `15` | Extra forward chest lean. The neck counter-rotates, so the view and arms stay as animated. |
| `--hip-motion 0..1` | `0.5` | How much of FBA's hip lunge to keep during attacks. Below 1.0 steps are shortened to match and the legs bend to reach them. If the feet misbehave, use `1.0`. |
| `--sway 0..1` | `0.33` | How much of the walk/run hip swing reaches the upper body. |
| `--idle-when-feet-lift y/n` | `y` | Use idle legs where FBA would lift both feet off the ground (the crossbow reload). |

## Install the result

Add the output's parent folder (`ReAnimation FBA Compatibility`) as a data folder **after**
ReAnimation and FBA. Its `ReAnimation_FBA_Compatibility.txt` is how ReAnimation's scripts know it's
installed.

## Other scripts here

- `check_all.py [kf names]` compares the built animations with the originals (spine and neck drift,
  chest lean, foot heights, root motion, which foot steps where).
- `fba_fingers.py <FBA folder> <Morrowind Data Files> <output>` builds the separate
  **FBA 1st-Person Hands** package, which restores the vanilla 1st-person hands and converts FBA's
  own animations to their fingers.
