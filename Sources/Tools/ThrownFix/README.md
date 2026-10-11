# Thrown weapon projectiles fix

Builds the installer's thrown weapon options: R-Zero's
[Improved Thrown Weapon Projectiles](https://www.nexusmods.com/morrowind/mods/44763) (ITWP) meshes,
fixed for OpenMW. ITWP makes thrown weapons fly point first, and the knives and stars spin in the air.
In OpenMW its knives and stars also turn 90 degrees in the hand while they are thrown or equipped.
These are its meshes with that fixed, with the stars flying flat instead of on edge, and with
everything spinning faster. Only a few numbers change in each file.

| Folder | Meshes (`meshes/w/`) | Use with |
|---|---|---|
| `02 Thrown Weapon Projectiles Fix` | w_chitin_star, w_knife_glass, w_knife_iron, w_silver_star, w_star_ebony, w_star_glass, w_steel_knife, "w_steel_star " | ITWP itself |
| `03 Thrown Fix - Iron Mesh Improvements` | w_knife_iron | Psymoniser's Iron Mesh Improvements |
| `04 Thrown Fix - Improved Weapon Meshes Steel` | w_steel_knife, "w_steel_star ", w_dart_steel (unchanged) | Pherim's Improved Weapon Meshes - Steel |
| `05 Thrown Fix - Improved Weapon Meshes Ebony` | w_star_ebony, w_dart_ebony (unchanged) | Pherim's Improved Weapon Meshes - Ebony |
| `06 Thrown Fix - Improved Weapon Meshes Organic` | w_chitin_star | Pherim's Improved Weapon Meshes - Organic |
| `07 Thrown Fix - Glass Glowset` | w_knife_glass, w_star_glass | Solidfire's Glass Glowset |

ITWP still has to be installed - its darts aren't in here. Its own `Patches` folder is not needed:
03 to 05 are those patches fixed (a flat folder of meshes that can't be used as a data path as it is),
and 04 and 05 also carry its two dart patches, unchanged. 06 is the chitin star from Improved Weapon
Meshes - Organic's own "04 Improved Thrown Weapons Patch", and 07 the meshes of ITWP's "Glass
Throwables patch for Glass Glowset" (an optional file on ITWP's page). Each goes after 02, and
ReAnimation has to load after ITWP and after those mesh mods: they ship their own, unfixed, copies of
the same meshes.

The space in "w_steel_star .nif" is not a typo: Morrowind.esm spells the mesh that way. The steel
throwing knife only uses w_steel_knife with a plugin that fixes the vanilla record (it points at the
dragon dagger mesh), such as "Steel Throwing Knife_fix.esp" from Improved Weapon Meshes - Steel.

## Build

```
python3 Sources/Tools/ThrownFix/patch_thrown.py "<ITWP folder>" \
    --glowset "<Glass Throwables patch for Glass Glowset folder>" \
    --organic "<Improved Weapon Meshes - Organic folder>"
```

The folders go to this mod's root (`--out` elsewhere). A source left out is skipped. It lists every
change; each mesh is byte-identical to the original apart from those values (three in each knife,
five in each star), and all pass OpenMW's niftest.

## The problem

In OpenMW the throwing knives and stars turn 90 degrees about their long axis while they are thrown
or equipped, and stay correct in idle. The darts are fine. This happens with the vanilla animations,
in first and third person (NPCs included), not just with animation mods.

Each of these meshes has the flight spin on the "template" node (0 to 4 s, constant extrapolation).
Its Y rotation channel ends on two keys at the same time:

    4.0001 s   Y = 0      (end of the flight)
    4.0001 s   Y = -90    (back to the in-hand pose)

and the controller stops at 4.0001 s too.

OpenMW plays a held thrown weapon's own controllers on the absolute time of the thrown weapon
animation group (vanilla's first-person throw sits at 48.7 s and later), so in hand the controller is
clamped to its stop time, 4.0001 s. OpenMW 0.51 finds the key pair with a lower_bound search, which at
exactly that time lands on the first of the two keys. So the held weapon keeps the flight's Y = 0
instead of the in-hand -90. In idle the group isn't playing, the time is 0, and the first key gives
the right pose, which is why it only shows during throws and equips.

The darts end their channels on two different times (4.0 and 4.0001 s), so they don't hit this.

## The change

In every knife and star, the last Y rotation key moved from 4.0001 to 4.0002 s, and the controller's
stop time from 4.0001 to 4.0002 s. Checked against OpenMW 0.51's key lookup: on its own this leaves
the pose at time 0 and the whole flight (0 to 4 s) as they were, and from 4.0002 s on the weapon is in
its in-hand pose.

**Flat stars.** The stars lie flat in the hand, and vanilla's fly flat too. The original's flight
animation sets the Y rotation from the in-hand -90 to 0 as the star leaves the hand, which stands it
on edge, and spins it about the projectile's sideways axis, so it rolls forward like a saw blade. In
every star the flight's Y keys now keep the in-hand -90: OpenMW applies the X spin first and the Y
rotation after it, so the star spins in its own plane and stays flat, turning about the vertical axis
(clockwise seen from above). The pose in hand doesn't change.

**Faster spin.** In flight the knives tumble end over end and the stars spin, 5 turns over the 4 s
(1.25 a second), which looks slow: a throw usually lands within a second. The X rotation's end value
goes from -1800 to -5760 degrees, 16 turns over the same 4 s, so 4 a second. It still ends on a whole
number of turns, so the end pose is the same.

Anything re-exported with the same layout would need the same nudge: a channel ending on two keys at
the same time.

## Credits

R-Zero for Improved Thrown Weapon Projectiles and its Glass Glowset patch. Psymoniser (Iron Mesh
Improvements), Pherim (Improved Weapon Meshes - Steel, Ebony, Organic) and Solidfire (Glass Glowset)
for the meshes the patches are built on. Found while testing ReAnimation's thrown weapon animations.
