# First-person animations to third person

Merges a set of first-person animations with a set of third-person ones, so NPCs - and you, with the
camera pulled back - move the way the first-person set does. Any two sets: the third-person one can
be vanilla's, a whole-set replacer like Animation Compilation, a mod's own additions, or several of
these over each other. It writes plain animation replacers into the third-person skeleton folders;
there is no script and nothing to register.

Each animation it writes is the first-person one's upper body on the third-person animation's legs,
hips and root motion - the third-person animation of the same name, or the one the engine would play
in its place. By stance, either way round:

- **Most stances (weapons):** the whole upper body is the first person's - chest, spine and arms turned
  the way it turns them, in the character's frame, on the third person's hips - and its timing is the
  first person's too: its text keys (when a hit lands), with the third person's legs sped up and
  slowed down between the keys both have to match. The head looks ahead through attacks.
- **Held forward (by default, spells):** the torso is the third person's, turned toward facing ahead,
  with the first person's arms on it pointing where the first person points them - and the third
  person's timing, the first person's arms sped up and slowed down to match it.

Walks, runs, sneaks and turns always keep the third person's timing and legs - their own keys, copied
as they are - since the engine paces the character's movement by them.

## Run it

```
python3 Sources/Tools/FirstToThird/first_to_third.py
```

It first says how many settings were not given on the command line and asks whether to take the
defaults for all of them or go through them one by one. One by one, each is explained with its
default shown - press Enter to keep it - and the ones that take group or weapon names list what the
set has. `-y` takes every default without asking; any setting can also be given on the command line:

```
python3 first_to_third.py -y --first "My Mod/animations/xbase_anim.1st" --third "Animation Compilation"
```

Needs Python 3 and the `FBACompat` folder next to this one, whose `.kf` reader it uses. Morrowind.bsa
(found from openmw.cfg; give `--data-files` otherwise) is read when vanilla is underneath, and for the
rest pose of any bone the animations given leave unkeyed. Files are converted several at once, one per
CPU (`--jobs N` to change that; one at a time on systems without fork, such as Windows). On a Steam
Deck, for all three skeletons, a spell casting set of 4 files takes half a minute and ReAnimation's 95 a
minute and a half; the tool says roughly how long yours will before it starts. `-v` prints what each
animation was built from.

## Settings

| Option | Default | What it does |
|---|---|---|
| `--first DIR` | `animations/xbase_anim.1st` under the current folder, if there is one | The first-person `.kf` files to convert. |
| `--skip-files PATTERNS` | none | First-person files to leave out entirely, shell patterns, comma separated: an old version the set keeps for compatibility, say (`_xReanimationv1.kf`). Left out, a file is not used for anything else either - not as the stance idle other groups' arms are measured against, not for the skeleton's rest pose. |
| `--third PATHS` | none | The third-person animations to build on, comma separated, later ones winning as in the load order: mod or Data Files folders (a whole-set replacer's `meshes/xbase_anim.kf` and the mod's `animations/` folders both count), `meshes`, `animations` or skeleton folders (`xbase_anim`), or `.kf` files. |
| `--vanilla y/n` | `y` | Vanilla's third-person animations underneath, as in the game: the sets above go over them, and a whole-set replacer among them takes their place. `n`: only the sets given. |
| `--out DIR` | the folder the first-person folder is in | Where the skeleton folders (`xbase_anim`, `xbase_animkna`, `xbase_anim_female`) are written. |
| `--beasts y/n` | `y` | Also build for beast races, on their own third-person animations. |
| `--women y/n` | `y` | Women play a few animations of their own over everyone's (Animation Compilation's women have their own walk). Build what those change, on them. |
| `--hold-torso STANCES` | `spell` | Stances whose torso is the third person's, held forward, with only the arms the first person's - for what points the arms at something. Every other stance's whole upper body follows the first person. `all`, `none`, or stances. |
| `--steady-head y/n` | `y` | Where the upper body follows the first person, attacks hold the head looking ahead as in the stance idle: in first person the head turns with every swing, which the camera never shows. |
| `--third-timing STANCES` | `spell` | Stances that keep the third person's timing; every other stance plays at the first person's, with its text keys. Walks, runs, sneaks and turns always keep the third person's. |
| `--keep-forward 0..1` | `0.75` | Held-forward stances: how much the torso and head are held facing forward - shoulders square, in the posture of their stance's idle - through everything. 1.0 holds them still; 0.0 leaves the third-person animation's own leans, twists and side-on stances. Idles keep their breathing and are only turned that share of the way square. |
| `--point-arms 0..1` | `1.0` | Held-forward stances: how much the arms keep the direction the first person gives them, the way the character faces, whatever the torso does. 1.0: a cast goes straight ahead even where the body turns. 0.0: the arms hang on the torso and turn with it. |
| `--two-handed-follow y/n` | `y` | Two-handed weapons, bows and crossbows (`2c`, `2b`, `2w`, `bow`, `crossbow`) keep their arms on the torso instead of pointing them. |
| `--idle-arms y/n` | `y` | Where the third person shows a stance's idle arms - turning on the spot with a spell ready, walking or jumping in a stance with no walks or jump of its own (a spell) - and the first person has that idle but none of these, make them too, with its arms. |
| `--lower-arms SPEC` | none | Animations whose arms sit too high in third person, as `group section=degrees`, comma separated, e.g. `spellcast target=15`. The arms pivot down at the shoulder, by the full amount where the hands are highest; the hands keep the way they face. |
| `--moves STANCES` | `all` | Whose walks, runs, sneaks and jumps to convert: `all`, `none`, or stances such as `2w, hh` (`plain` for no weapon; `1t` takes in a mod's `1tstar`). The others are left alone, so the third person's own keep playing for them. |
| `--arm-bounce 0..1` | `0.3` | **Experimental.** On walks, runs and sneaks the elbows and wrists lag behind the body's bob and sway and spring back, looping with the walk. 0.3 moves the hands about a unit. 0.0 turns it off. |
| `--arm-bounce-by SPEC` | none | Arm bounce for some weapon types of their own, e.g. `2w=0.2, hh=0.5`; the rest take `--arm-bounce`. Asked as a yes/no first, and only then once per weapon type. |
| `--grip y/n` | `y` | Two-handed weapons and crossbows (`2c`, `2b`, `2w`, `crossbow`): only the right arm, which holds the weapon, bounces; the left reaches after it (two-bone IK) so the left hand stays where it was on the grip. |
| `--skip PATTERNS` | none | Groups not to convert at all, shell patterns, comma separated: `torch*, walk*1h`. |
| `--legs-from PAIRS` | none | Where a group the third person lacks takes its legs and timing from, as `group=third-person group`, when the automatic pairing (below) gets it wrong. `group=third-person group@key` instead holds that group's pose at that key under the whole animation: a bow's tension hold on the full draw, `bowandarrow1=bowandarrow@shoot max attack`. |
| `--unpaired y/n` | `y` | A group with nothing to pair with (a tail, a flourish) keeps its own timing and text keys, on its stance's idle. `n` leaves such groups out. |
| `--prefix TEXT` | none | Put in front of every file name written - see "Which file wins" below. |

## Worth knowing

- **Pointing the arms can go badly wrong where both hands hold one thing.** Each arm is pointed on its
  own, so wherever the third-person shoulders sit differently from the first person's, the two hands
  drift apart - off the grip of a two-handed weapon or a bow. That is why two-handed stances are left
  on the torso by default (`--two-handed-follow`). Turn `--point-arms` down for anything else that
  needs the hands together.
- **Held forward, the torso is the third person's.** First-person animations often hold the torso
  oddly, or not at all, since the camera sits in the head; for a spell cast what matters is where the
  arms point. They are carried over as the first person holds them against its chest in its stance's
  idle. A first-person punch held forward keeps its arm motion, but not its twist - which is why
  weapons follow the first person instead.
- **Timing.** At the first person's timing the third person's body plays faster or slower between
  the text keys both have; at the third person's, the first person's arms do. A looping animation much
  longer than the third person's (an idle) keeps its own pace either way, over the third person's loop
  repeated as many times as fits. The third person's footsteps and landings go where its legs, warped,
  now make them; the first person's own sounds (a bow's pull) stay with its motion.
- **Jumps** get what walks get - kept forward, arms pointed - except the bounce.
- **Legs are copied, not resampled.** Some sets have several keys at one instant (Animation
  Compilation's walks: four to a frame); the engine plays them in order, and so do the copies. What
  the third-person animation does at its loop's seam, the result does too.
- **Skeletons.** The engine loads beasts' and women's animations over everyone's, and the tool does
  the same. Beasts get a whole set of their own; women only what their own animations change, into
  `xbase_anim_female`. Bone offsets come from the third-person set's own animations - the skeleton
  they were made on - and vanilla's only for bones they leave unkeyed.
- **What gets converted, and on what.** Every first-person group, on the third-person group of the
  same name. For one the third person lacks: a sneaking idle on its sneak idle (`idlesneak`); a
  stance's walk, jump or idle on the group the engine plays for that stance instead (a dagger's walk on
  the one-handed one, a throwing star's on the thrown one's); anything else on the longest group its
  name starts with (`weapononehand1`, an alternate attack, on `weapononehand`). What still has nothing
  keeps its own timing on its stance idle (`--unpaired`). A group split across several files (one per
  section, as some mods do spell casts) is converted file by file, and a file's `.yaml` blending rules
  are copied with it.
- **Groups no engine code asks for** - alternate attacks, variants, a sneaking idle per weapon - are
  converted like the rest, but only play if something plays them: for a ReAnimation set, a script
  registering the same overrides for third person (see "ReAnimation Third Person" in the mods folder
  for one).
- **Which file wins in game** is decided by file name within a skeleton folder, not by load order: the
  one that sorts last. The output keeps the first-person file names, after `--prefix` if given. The
  tool warns about any that sort before `xbase_anim.kf`, because some mods ship a whole copy of that
  file in the same folder, which would then win. A prefix also moves the whole set against other mods'
  third-person files: `xReAnim3P_` sorts after most, so the set wins where they overlap.

## Install the result

The output goes next to the first-person folder by default, so it ships with the mod that has it.
Nothing else is needed: OpenMW loads every `.kf` in `animations/xbase_anim` (and `xbase_animkna`,
`xbase_anim_female`) as long as "use additional animation sources" is on. Built on a replacer like
Animation Compilation, the result matches the game only where that replacer is installed.
