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
  slowed down between the keys both have to match. The head looks straight ahead throughout.
- **Held forward (by default, spells):** the torso is the third person's, turned toward facing ahead,
  with the first person's arms on it pointing where the first person points them - and the third
  person's timing, the first person's arms sped up and slowed down to match it.

Walks, runs, sneaks and turns always keep the third person's timing and legs - their own keys, copied
as they are - since the engine paces the character's movement by them. On top of what the first person
gives them:

- **Torso motion.** A first-person walk holds the torso still, which on third-person legs looks rigid.
  Every walk, run and sneak moves it the way gait studies find people's bodies move over their legs,
  made from what the third person's legs do: a forward nod as the weight comes down on each step, the
  chest rolling against the hips' sway so the neck stays over the line of the walk and leaning over
  the standing leg, the shoulders swinging against the legs - the head looking ahead and only
  bobbing - and leaning forward where it would otherwise lean back.
- **Moves made from an idle.** Whatever locomotion a stance with an idle lacks - walks, runs, turns on
  the spot, a jump; for a thrown weapon in ReAnimation's third-person set all of it, for its two-handed
  weapons the turns and jump - is made from that idle on the third person's legs, leaning as they do,
  the arms bouncing on walks and runs. Sneaks can be made the same way, stance by stance, leaning into
  the third person's crouch.
- **Breathing.** Idles whose upper body is the first person's breathe, one smooth breath per loop of
  a few seconds.
- **Attacks settle** into their stance idle's first frame at the end of the follow-through, or of
  the tail where there is one.

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
| `--alias PAIRS` | none | Stances of the set's own that a script plays over one of the engine's, as `stance=engine stance`, comma separated: `katar=hh` builds a katar moveset as hand-to-hand - `katar` and `kataralt` pair with the third person's `handtohand`, `idlekatar` with `idlehh`, `walkforwardkatar` with `walkforwardhh`, `jumpkatar` with `jumphh`, `idlekatarsneak` with the sneaking idle - and gets every setting hand-to-hand gets (name `hh` in them). Written back under the set's own names; moves made from such a stance's idle are named for it too (`xkatarTurn.kf`). |
| `--third PATHS` | none | The third-person animations to build on, comma separated, later ones winning as in the load order: mod or Data Files folders (a whole-set replacer's `meshes/xbase_anim.kf` and the mod's `animations/` folders both count), `meshes`, `animations` or skeleton folders (`xbase_anim`), or `.kf` files. |
| `--vanilla y/n` | `y` | Vanilla's third-person animations underneath, as in the game: the sets above go over them, and a whole-set replacer among them takes their place. `n`: only the sets given. |
| `--out DIR` | the folder the first-person folder is in | Where the skeleton folders (`xbase_anim`, `xbase_animkna`, `xbase_anim_female`) are written. |
| `--beasts y/n` | `y` | Also build for beast races, on their own third-person animations. |
| `--women y/n` | `y` | Women play a few animations of their own over everyone's (Animation Compilation's women have their own walk). Build what those change, on them. |
| `--hold-torso STANCES` | `spell` | Stances whose torso is the third person's, held forward, with only the arms the first person's - for what points the arms at something. Every other stance's whole upper body follows the first person. `all`, `none`, or stances. |
| `--steady-head y/n` | `y` | Where the upper body follows the first person, the head looks straight ahead in everything - idles, moves, attacks - upright, at the angle below level the third person's stance idle looks at, riding on the neck: in first person the head turns with every swing and often sits turned in an idle too, which the camera never shows. |
| `--third-timing STANCES` | `spell` | Stances that keep the third person's timing; every other stance plays at the first person's, with its text keys. Walks, runs, sneaks and turns always keep the third person's. |
| `--keep-forward 0..1` | `0.75` | Held-forward stances: how much the torso and head are held facing forward - shoulders square, in the posture of their stance's idle - through everything. 1.0 holds them still; 0.0 leaves the third-person animation's own leans, twists and side-on stances. Idles keep their breathing and are only turned that share of the way square. |
| `--point-arms 0..1` | `1.0` | Held-forward stances: how much the arms keep the direction the first person gives them, the way the character faces, whatever the torso does. 1.0: a cast goes straight ahead even where the body turns. 0.0: the arms hang on the torso and turn with it. |
| `--two-handed-follow y/n` | `y` | Two-handed weapons, bows and crossbows (`2c`, `2b`, `2w`, `bow`, `crossbow`) keep their arms on the torso instead of pointing them. |
| `--idle-arms y/n` | `y` | For the stances held forward: where the third person shows a stance's idle arms - turning on the spot with a spell ready, walking or jumping in a stance with no walks or jump of its own (a spell) - and the first person has that idle but none of these, make them too, with its arms. |
| `--lower-arms SPEC` | none | Animations whose arms sit too high in third person, as `group section=degrees`, comma separated, e.g. `spellcast target=15`. The arms pivot down at the shoulder, by the full amount where the hands are highest; the hands keep the way they face. |
| `--moves STANCES` | `all` | Whose walks, runs, sneaks and jumps to convert: `all`, `none`, or stances such as `2w, hh` (`plain` for no weapon; `1t` takes in a mod's `1tstar`). The others are left alone, so the third person's own keep playing for them - made from an idle or not. |
| `--idle-moves STANCES` | `all` | Stances whose missing walks, runs, turns on the spot and jump are made from their idle, on the third person's legs (the engine's group for the stance, or the one it would play instead: a thrown weapon's walk on the one-handed one's legs), with the idle's upper body as it holds it on average. Only what the first person lacks is made: a stance with walks and runs of its own gets its turns and jump. Without them it would turn and jump with the third person's own arms, or another weapon's. `all`, `none`, or stances. For the stances following the first person; those held forward get `--idle-arms`. |
| `--idle-sneak STANCES` | `2w, 2c, 1t` | Stances whose sneaking idle (`idle2wsneak`) and sneaks (`sneakforward2w`...) are made from their idle, in place of any the first person has - or, where the first person has a sneaking idle of its own, whose sneaks are made from that, which is converted as it is - on the third person's sneaking legs. The sneaking idle plays the idle itself over and over at its own pace, on the third person's (Animation Compilation's lasts 16 seconds), breathing. `all`, `none`, or stances. |
| `--idle-lean 0..1` | `1.0` | Moves made from an idle lean forward by this share of how far the third person's torso leans in the same move against its stance idle: a sneak's crouch (about 60 degrees on Animation Compilation's spear sneak), a run (about 20). The arms keep the way they point, the head its gaze. 0.0 keeps the idle's upright torso, on crouching legs too. |
| `--align-steps y/n` | `y` | The first person's own walks, runs and sneaks bob, sway and swing their arms in time with their own steps, which need not fall where the third person's feet strike - Animation Compilation's beasts strike a quarter of a stride later than its people. y enters the first person's loop where its right foot strikes as the third person's does, by both sets' footstep keys (`SoundGen: Right`, `Left`); n starts both loops together. |
| `--spine-sway y/n` | `y` | Only without torso motion (`--torso-motion 0`): the chest of a walk following the first person sways as the third person's spine does (y), or keeps the first person's own (n) - for a first-person set that moves its torso already, such as a third-person set put on another skeleton. |
| `--torso-motion 0..2` | `1.0` | Walks, runs and sneaks - the first person's own and those made from an idle: the torso moves as people's do over their legs, made from the third person's legs (see "Torso motion" below). This scales the next three: 1.0 as set, 2.0 twice, 0.0 none - the chest then sways as the third person's spine does. |
| `--torso-nod SPEC` | `walk=3.5, run=6.5, sneak=2.5` | Degrees the thorax pitches through, forward and back, twice a stride: running, furthest forward 15% of a stride after each foot strike (Preece et al. 2016: 6.5); walking, just before each heel strike (Ceccato et al. 2009: 3; Chung et al. 2010: 4). Sneaking is unmeasured: walking's, smaller. A move left out does not nod. |
| `--neck-sway 0..1` | `0.3` | Share of the hips' side-to-side sway the neck is carried toward, by bending the lower back sideways - the chest keeping its measured tilt - as people do (most of the trunk's side bending against the pelvis is lumbo-pelvic). Within 8 degrees each way, so on a short lower spine only part of a wide sway is taken out. 1.0 leaves it. |
| `--shoulder-swing SPEC` | `walk=10, run=24, sneak=7` | Degrees the thorax turns through each stride, the shoulder opposite the striking foot coming forward - the arm swing's counter-rotation. Running: turning over during stance, held through flight (Preece et al. 2016: 24; Seay et al. 2011: 25). Walking: a near-sine wave, furthest just before each heel strike (Ceccato et al. 2009: shoulder line 10; Huthwelker et al. 2023: mid-thorax 15). Only as much as the move goes forward or back. A move left out does not swing. |
| `--stance-lean SPEC` | `walk=3.5, run=8, sneak=2.5` | Degrees the thorax tilts through each stride toward the leg it stands on, most early in stance: 5-10% of a stride after the foot strikes running (Preece et al. 2016: 8), at the other foot's toe-off walking (Ceccato et al. 2009: 4; Chung et al. 2010: 3.1-3.5). On top of the neck-centring roll. A move left out does not tilt. |
| `--steady-spine 0..1` | `1.0` | Share of the hips' tilt and twist the lower spine (`Bip01 Spine`, the top bone of the lower body) takes out on walks, runs and sneaks. Animation Compilation's runs pass the hips' swing up through it whole and take it out higher up, in bones the first person's upper body replaces - so whatever the game plays on the upper body over a move, an attack held while running, swayed with the hips. The torso motion goes on the bones above it, which such an attack replaces: it rides a steady base, bobbing with the walk. The thighs (and a beast's tail) hang off this bone in Morrowind's skeletons, so they are turned back under it: the legs, the hips and their swing stay the third person's. Every other animation whose upper body is the first person's - attacks, idles, turns, jumps - holds its lower spine at its stance idle's by this share, so that what plays from the chest up over another one sits there as it does on its own: a spear thrust held while running pointed some 20 degrees off when its own lower spine was turned with its hips. 0.0 leaves the third person's lower spine as it is. |
| `--held-attack-motion 0..1` | `0.1` | The share of a walk's torso motion - nod, shoulder swing, lean - that goes on the lower spine instead of the chest, so an attack held over the walk or run (which replaces the chest up) moves with it that much. The walk's own torso moves the same either way. 0.0 holds it steady. |
| `--keep-arm-facing 0..1` | `0.0` | Walks, runs and sneaks with torso motion: the share of the way the arms face that they keep while the torso nods, swings and leans under them. 1.0 keeps it, the hands carried along by the shoulders only - a guard or a spell held forward stays pointed ahead as the body swings; 0.0 turns the arms with the torso. Both arms alike, so hands on one weapon stay on it. |
| `--face-forward 0..1` | `0.9` | Strafing turns the hips, and the lower spine with them, the way it goes - Animation Compilation's (vanilla's) strafes by 3 to 21 degrees - and an attack held while strafing, which plays from the chest up on that lower spine, turned with them. Sneaking is worse: Animation Compilation's sneaking idle and sneaks turn it 32 degrees aside (and lean it 22 forward), so attacks while sneaking went off to the side. This is the share of a walk's, run's or sneak's average turn its lower spine turns back to face as the standing stance idle's does (a sneaking idle's, and every other animation's, turns all the way; leans are kept); the legs and hips stay as they are, the waist twisting between them, and the walk's own chest faces as it did. 1.0 takes it all out. |
| `--max-twist DEGREES` | `45` | People twist only so far between hips and shoulders (a golf swing's, the most there is, some 45 to 55 degrees) and turn the hips beyond it. A first-person torso on third-person hips twists far past it - ReAnimation's spear chops over 110 degrees. In idles, attacks, turns and jumps whose upper body is the first person's, the hips turn after the shoulders (the line of the shoulders against the line of the hip joints) by a share of the twist that grows smoothly with it - next to nothing well short of this many degrees, all of the excess well past it - smoothed over about 0.05 seconds either way (never across the start of a section or a follow-through), coming in over each wind-up and going as the attack settles into the idle, so attacks start and end on the idle's own legs. The pelvis, the hip joints and a beast's tail turn; the legs bend to keep the feet where they were, the knees turning half as far. The lower spine, and the chest on it, stay where they are, so an attack held over a walk faces as it does standing. Only where the hips turn: everywhere else they and the legs keep the third person's own keys. 0 never turns them. |
| `--split-follows y/n` | `y` | An attack has a short, a medium and a long follow-through, the game picking one by how long the attack was held. The game's own run one after another, each a whole recovery from the hit back to the idle. ReAnimation's start together and cut the weaker ones short, so a quick attack stopped 60 to 90 degrees from the idle the game then goes back to - and the next attack starts from - and the third person's legs, timed through the keys both share, jumped from one of its follow-throughs to another. y gives each weaker one the whole recovery played faster in the time it had, put after the strongest; each then ends where the strongest does - on the idle, or where ReAnimation's tail takes up. |
| `--start-from-idle y/n` | `y` | Attacks end on their stance idle's first frame; y has them start there too, easing out of it over the first third of the wind-up (to `min attack`), 0.1 seconds at most, so a quick one still swings. Attacks chained one into another, and into the idle, then meet without a jump in pose. (A wind-up of a frame or two eases out in under a frame: the engine's own blend into the attack covers that.) |
| `--align-to-third GROUPS` | `throwweapon` | OpenMW drives a held thrown weapon's own mesh animation with the absolute time of the `throwweapon` group in its file; mesh replacers that spin the knife in flight (0 to 4 seconds) are made for vanilla's layout, where the group sits far later, and at 0 to 4 seconds the knife in hand jumps to its flight pose. Files with these groups are moved whole, so the group's first section start lands where the third person has it (ReAnimation's own first-person thrown files are moved so by `KFPostfix`'s `align-time`). `none` for none. |
| `--straight-starts y/n` | `y` | A walk's lead-in (from standing to its loop) and tail move the actor only the way its loop goes: the root's travel across that way is taken out of them, and the body does as it did. Vanilla's two-handed strafes, and so Animation Compilation's, start with the root some 15 units forward of where the loop runs and slide it back in the first steps: the actor stepped back 14 units every time it started to strafe. |
| `--torso-lean SPEC` | `walk=3, run=8, sneak=3` | The least walks, runs and sneaks lean forward, in degrees from upright (the line from the chest's base to the neck), bounce and all: where the torso would lean back of it anywhere in the loop - first-person torsos often stand upright or tipped back, ReAnimation's two-handed ones 4 degrees back - the whole walk is leaned forward until it does not, so it bounces forward, down and to the sides, never back. The arms keep the way they point, the head its gaze. A move left out, or `none`, is not leaned. |
| `--breathing DEGREES` | `3` | Idles whose upper body is the first person's breathe: the chest turns up and back about its base by this much at a full breath and the shoulders lift with it, breathing in quicker than out, one breath for about every 4 seconds of the idle's loop (one for ReAnimation's 4-second idles), looping seamlessly. Rotations only; the head keeps its gaze and the arms the way they point, so a weapon held in both hands stays in them. 0 for none. |
| `--settle SECONDS` | `0.2` | Attacks end on their stance idle's first frame: the last third of each follow-through - of its tail, where ReAnimation plays one after it (`<group>extra`) - but this many seconds at most, crossfades into the converted idle's first frame, every bone but the root's travel over the ground (which moves the actor). The idle then picks up without a pop; where an attack starts needs nothing, the game blends into it. 0 for none. |
| `--arm-bounce 0..1` | `0.3` | On walks, runs and sneaks made from an idle, whose arms would otherwise be held still: the elbows and wrists lag behind the body's bob and sway and spring back, looping with the walk. 0.3 moves the hands about a unit. 0.0 turns it off. |
| `--arm-bounce-by SPEC` | none | Arm bounce for some weapon types of their own, e.g. `2w=0.2, hh=0.5`; the rest take `--arm-bounce`. Asked as a yes/no first, and only then once per weapon type. |
| `--arm-bounce-real-time y/n` | `n` | Runs the arm bounce in the walk's own time. `n` steps it a frame per sample, as sets were built before this setting - and a forward walk or run, every key time of whose third-person legs is a sample too (three or four to a frame), barely bounces while the other directions do. `y`: every walk bounces as much as `--arm-bounce` says; stances, comma separated: only theirs. |
| `--arm-bounce-walks y/n` | `n` | Arm bounce on the first person's own walks, runs and sneaks too, which move the arms already - `y` for all, or stances, comma separated, for only theirs (`hh`). |
| `--grip y/n` | `y` | Two-handed weapons and crossbows (`2c`, `2b`, `2w`, `crossbow`): only the right arm, which holds the weapon, bounces; the left reaches after it (two-bone IK) so the left hand stays where it was on the grip. |
| `--skip PATTERNS` | none | Groups not to convert at all, shell patterns, comma separated: `torch*, walk*1h`. |
| `--legs-from PAIRS` | none | Where a group the third person lacks takes its legs and timing from, as `group=third-person group`, when the automatic pairing (below) gets it wrong. `group=third-person group@key` instead holds that group's pose at that key under the whole animation: a bow's tension hold on the full draw, `bowandarrow1=bowandarrow@shoot max attack`. Moves made from an idle take legs given here too: `walkforwardkatar=walkforward1h` - and lean as that stance's own move does against its own idle. |
| `--unpaired y/n` | `y` | A group with nothing to pair with (a tail, a flourish) keeps its own timing and text keys, on its stance's idle. `n` leaves such groups out. |
| `--prefix TEXT` | none | Put in front of every file name written - see "Which file wins" below. |
| `--keep-bones` | off | Keep the tracks of bones the third-person skeleton lacks (the first person's extra finger joints, a mod's own bones), for a build that works on them and leaves them out itself afterwards. Off, they are left out: the engine warns for each one every time an actor loads the file. |

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
- **Jumps** get what walks get - kept forward with arms pointed where held forward, leaning as the third
  person's where made from an idle - except the bounces and the least lean. Turns made from an idle
  likewise.
- **Torso motion.** The thorax moves against the room as gait studies measure it, in step with the
  third person's legs - its footstep keys mark where each foot strikes:
  - Running: the mean curves of Preece, Mason and Bramah (2016, *Human Movement Science*, 28 runners at
    3.9 m/s, figure 1), made left-right symmetric - pitching forward twice a stride, most 15% of a
    stride after each foot strike; tilting toward the standing leg, most 5-10% after it; turning the
    shoulder opposite the striking foot forward during stance and holding it through flight.
  - Walking: near-sine waves - the thorax turned furthest just before each heel strike (Huthwelker et
    al. 2023, *Human Movement Science*, 201 walkers at 5 km/h; Ceccato et al. 2009, *PLoS ONE*), tilted
    toward the standing leg most at the other foot's toe-off (Ceccato; Chung et al. 2010), and leaning
    furthest forward just before each heel strike (Ceccato).
  - Sneaking: walking's, smaller - no study measures it.

  The head is held steady in rotation and bobs with the body (Pozzo et al. 1990, Hirasaki et al. 1999);
  a side bend of the back at the chest's base carries the neck toward `--neck-sway` of the hips' sway
  without changing the thorax's tilt (Preece et al. figure 3h: the trunk bends sideways against the
  pelvis mostly at the lumbo-pelvic junction). The turn balances the legs swinging fore and aft, so a
  strafe gets as much of it as it goes forward or back. All of it goes from the chest up (`Bip01
  Spine1`, `Spine2`), the upper body, on a lower spine steadied against the hips' tilt and twist
  (`--steady-spine`): an attack held while running replaces the upper body and holds still on it,
  bobbing with the walk. The legs hang off the lower spine and are turned back under it, so they, the
  hips and the hips' swing are the third person's exactly. Every curve is a smooth
  looping function of the stride, so the motion has none of the kinks Animation Compilation's root
  keys have, and loops by construction; the lead-in and tail fade it in and out.
- **The arm bounce** is run over the walk's loop until it settles into a cycle of its own, so it loops
  seamlessly; the path its spring follows is smoothed the same way first.
- **Moves made from an idle** are written as `x<stance>Movement.kf` (walks and runs),
  `x<stance>Turn.kf`, `x<stance>Jump.kf`, `x<stance>SneakMovement.kf` and `x<stance>IdleSneak.kf` -
  ReAnimation's own names for them, mostly - after `--prefix`, with `FromIdle` added where a converted
  file has that name already (ignoring case, as the game does): runs made from a stance's idle beside
  its converted walks in `x2wMovement.kf` go into `x2wMovementFromIdle.kf`.
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
