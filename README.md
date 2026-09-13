# ReAnimation - first-person - v3: Complete
![alt text](imgs/preview.png)

An immersive reimagining of absolute most of the TES3: Morrowind 1st-person animations, as well as a massive extension of those with alternating attacks (you won't spam the same attack animation anymore) and sneak animations.

Twice as much animation juice as the original game, if not more. 

Developed for OpenMW engine.

**v3: it  is  out  ba-beeeey!!!**

And it is complete. Animation sets for all the weapon types as well as h2h got remade and expanded. Only spellcasting animations are untouched since MCAR already provides a good set of those. Go and play the hell out of it!

And now I also have a cool donation banner:

<p><a href="https://ko-fi.com/maxyari"><img src="imgs/morrowind_kofi_banner_left_half_bright124.gif" width="25.72%" align="top" alt="Support me on Ko-fi"></a><a href="https://ko-fi.com/maxyari"><img src="imgs/banner_right.png" width="73.88%" align="top" alt="Support me on Ko-fi"></a><br><a href="https://ko-fi.com/maxyari"><img src="imgs/banner_glow.png" width="99.6%" align="top" alt=""></a></p>

If you are reading this - know that you are one of the truly early birds to this update as I have literally not announced it anywhere yet. Thank you for being around, and have fun :) 

**=== The rest of this description will be updated later ===**

v2: Rogue includes: 
- All ReAnimation first-person v1 animations.
- Locomotion animations for 1h weapons and bows.
- Separate set of animations for shortswords/daggers.
- Separate sets of animations for sneaking with 1h weapons, daggers and bows.
- Alternating attack animations for 1h weapons.
- Other smaller niceties.
- API for modders to use, e.g. to add alt attack animations to other weapon types in 1st and 3rd person.

![1h walk](/imgs/demo_1h.gif)
![Dagger walk](/imgs/demo_dagger.gif)
![Bow walk and shoot](/imgs/demo_bow.gif)
![Alternating attacks](/imgs/demo_1h_attacks.gif)

Note: Gifs are fairly low fps, it looks even better in-game.

## How to install

- Download this repository as an archive and drag and drop it into your mod organiser of choice (e.g [Mod Organizer 2](https://github.com/ModOrganizer2/modorganizer/releases) on Windows or [Nerevarine Organizer](https://github.com/grazelandsnomad/nerevarine_organizer/releases/tag/v0.70) on Linux). 
**--Or--** manually place the contents of this repository into your ".../Morrowind/Data Files" folder. 
- Enable the mod's .omwscript files in "Content Files" tab of the OpenMW launcher ( `ReAnimation_API` and `ReAnimation_v3` at the time of writing). 
- If you _only_ want to use ReAnimation as an API  for another mod (i.e only as a dependency that doesnt add any animations on its own) - only enable `ReAnimation_API` AND delete "Animations" folder from within this mod.

Have fun!

## Mod compatibility

Compatible with practically any other animation mod. ReAnimation uses OpenMW system of animation overrides and will only override a specific set of animations. Recommended to use with [MCAR](https://www.nexusmods.com/morrowind/mods/48628) for delightfull swimming and casting animations, but will work just fine without it.

[Better Bodies](https://www.nexusmods.com/morrowind/mods/48387) - causes a left-shoulder's sharp polygon to protrude on the left side of the screen while having naked arms (as well as with some common shirts) and sneaking with a dagger. Most noticeable with a [Low First Person Sneak Mode](https://www.nexusmods.com/morrowind/mods/43108). This is most likely an issue on the side of Better Bodies. Until it's fixed - simply wear a peace of armor on your left shoulder that doesn't bug out.

[TODO] Maybe that dynamic lua sneak mod that shrinks the player fixes the issue 

## Vanilla/MWSE compatibility

Only v1 version of this mod (far fewer animations in comparison to v3, no alternating attacks e.t.c) is available for vanilla Morrowind, you can find v1 in the downloads section.
v3 is not currently compatible. If you would like to port the scripting part to MWSE - please do, I'm not familiar with MWSE and am not planning to change that.
However, if possible - keep this mod as a dependency, instead of reuploading the whole thing.

[TODO] How to make it work with that first person fullbody mod?

## For Modders

### Basics

ReAnimation exposes an API (Interface for other mods to use). The interface works around some of the OpenMW Lua animation API limitations and provides a simple way of adding alternating attack animations for different weapons, as well as a slightly less simple way of defining generic conditional animation overrides.

To ensure that the ReAnimation interface is available, your mod should either be loaded after the ReAnimation API, or you should interact with the interface from inside the update function instead of the global scope. But in the latter case, ensure that you register your animations/overrides only once, and not every update tick.

#### Attack variants

Is a way to register alternating ("alt" below) and substitute ("sub" below) attack animations. Alternating attadcks play in alternating (duh) fashion, while sub attacks are a random replacement of an attack animation. As a simple example - you might have 2 variants of a downward chop animations and 1 variant of upward swing, you want downchop to always be followerd by up swing, but you also want a random chop to be used every time for your down chop. In this example your chop variants are sub attacks while your upward swing is an alt attack. Below example setups exactly this kind of scenario for two-handed chops.

```Lua
local I = require('openmw.interfaces')

I.ReAnimation.addAttackVariants({
    id = "MyTwoHandAttacks",                  -- optional, for removeAnimationOverride
    parentAttackGroupname = "weapontwohand",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    subAttackMode = I.ReAnimation.SUB_ATTACK_MODE.Random,  -- or RoundRobin
    condition = function() return not I.ReAnimation.isEquippedWeapon("katana") end, -- optional
    attacks = {
        chop   = { { "weapontwohand", "weapontwohandsub" }, { "weapontwohandalt" } },
        slash  = { { "weapontwohand" }, { "weapontwohandalt" } },
        thrust = { { "weapontwohand" }, { "weapontwohandalt" } },
    },
})
```
heare "weapontwohand", "weapontwohandalt" and "weapontwohandsub" are names of animation groups to which your attack animations belong. I.e for chops: vanilla chop is stored in weapontwohand, alt chop is stored in weapontwohandalt group (which i simply made up) and, similarly, sub chop is stored in weapontwohandsub. It IS important that all extra attack animations belong to their own groups distinct in name from the vanilla attack group and each other. It is fine to keep different attack types (chop/slash/thrust) under the same groupname as it is done in the example above.

Here's also an AI slop summary in case I missed something since I dont even want to bother re-reading the things that I wrote above:
- **The outer list alternates.** Attacks of one type step through it in order, so a single step means no alternation. If that attack type isn't used for `sequenceResetTime` seconds (default 3), the sequence starts over from the first step.
- **The inner list holds interchangeable variants.** `subAttackMode` picks one per attack: `Random` (the default; `randomMaxRepeats`, default 3, caps how often the same one comes up in a row, and 0 removes the cap) or `RoundRobin` (in the listed order).
- **Listing the parent group itself plays the vanilla animation**, so vanilla can be one of the options. Attack types you leave out are not touched.
- **`condition` gates the whole set**, e.g. by the equipped weapon (`isEquippedWeapon`, `getEquippedWeaponId`). Several sets can share one parent group, as long as their conditions are never true at the same time.
- **Text key timings must match the parent's exactly**, the same as for alt attacks: a variant plays on top of the hidden vanilla attack, whose keys still trigger hits and move the attack through its stages.

#### Tails

When an attack reaches its follow-through stop (`<type> [small|medium|large] follow stop`), ReAnimation looks for a group named `<attack group>extra` with a `<Type> Tail Start` and `<Type> Tail Stop` key, and plays that section if both exist. For example, `weapontwohand`'s chop plays the `Chop Tail Start` to `Chop Tail Stop` section of `weapontwohandextra`. Variant groups get their own, so `weapontwohandsub` uses `weapontwohandsubextra`.

A tail plays on the upper body only, at the attack's speed. Its priority sits above movement but below attacks, so the next attack, or a stagger from a hit, cuts it short. For a seamless hand-off, make the transition instant in your animation's blend rules YAML:

```yaml
blending_rules:
  - from: "*:*follow start"
    to: "*:*tail start"
    easing: "linear"
    duration: 0
```

Other additions, such as `addKeyTriggeredAnimation` and the equipped-item helpers, are documented in the comments in `ReAnimationAPI.lua`.

#### Old way to register attack variants

This still works and is shorter than the new way of attack variant registration, but is not as flexible and assumes that you implemented alt animations for all attack types of this weapon.

Registering alternating attack animations for a one-handed weapon group:

```Lua
local I = require('openmw.interfaces')

I.ReAnimation.addAltAttackAnimations({
    parentAttackGroupname = "weapononehand",
    altAttackGroupname = "weapononehand1",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    stance = I.ReAnimation.STANCE.Weapon
})
```

This function call will register the "weapononehand1" animation group (which you supposedly created) as a source of alternative chop/slash/thrust animations that will be played alongside the vanilla weapononehand group chop/slash/thrust animations in an alternating fashion. The timing of text keys within each of the alt attacks should match the original attack text key timings perfectly, i.e., the same exact duration of a windup, attack, follow-through, etc. 
This is important due to the fact that the provided alt animations don't actually play _instead_ of the vanilla animations; they play "on top" of them with the vanilla animation being covertly hidden. Vanilla text keys (and not the alt animation text keys) are actually responsible for triggering damage and transitioning between different stages of the attack animation.

Note that `armatureType` and `stance` properties define on which armature and in which stance this override will be active

#### Generic conditional animation override:

```Lua
local I = require('openmw.interfaces')

I.ReAnimation.addAnimationOverride({
    id = "myDaggerSneakOverride"
    parent = "idle1s",
    groupname = "idle1ssneak",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    stance = I.ReAnimation.STANCE.Weapon,
    condition = function(self)
        return omwself.controls.sneak
    end,
    stopCondition = function(self)
        return not self:condition()
    end,
    options = function(self)
        local opts = cloneAnimOptions(self.parentOptions)
        opts.loops = 999
        opts.priority = self.parentOptions.priority + 1
        return opts
    end,
    startOnUpdate = true
})
```
This registers a special "idle1ssneak" idle animation that will play whenever the vanilla "idle1s" animation is playing AND the character is in sneak mode. 

`parentOptions` and the return value of the `options` method are of the same format as [playBlended options parameter](https://openmw.readthedocs.io/en/latest/reference/lua-scripting/openmw_animation.html##(animation).playBlended). 

This is a very raw override method that can barely be considered a properly polished API. It provides a lot of flexibility but also requires some understanding of how the OpenMW animation API functions. The best way to use this method is to pick one of the override definitions from AnimationOverrides.lua as a base for your own.

Added overrides can be removed using 
```Lua
I.ReAnimation.removeAnimationOverride("my_override_id")
```
Where `my_override_id` is an id you provided to the override in `addAnimationOverride` (if you provided such an id at all).


## Appreciation

Thanks to [fallchildren](https://github.com/fallchildren2) for code contributions and motivating me to expose a (somewhat) proper API. 

Thanks to [taitechnic](https://forums.nexusmods.com/profile/193965921-taitechnic/) and [S3ctor](https://github.com/magicaldave) for the help in optimisation.

My thanks go to OpenMW discord community for massively helping me overcome a multitude of Lua hurdles, testing and providing feedback.






