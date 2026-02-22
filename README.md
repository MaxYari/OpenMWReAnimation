# ReAnimation - first-person - v2: Rogue
An immersive reimagining of (some) of the TES3: Morrowind 1st-person animations. Developed for OpenMW engine.

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

- Download this repository as an archive and install using Mod Organizer 2. Or manually place the contents of this repository into your ".../Morrowind/Data Files" folder. 
- Enable the mod's .omwscript files in "Content Files" tab of the OpenMW launcher ( `ReAnimation_API` and `ReAnimation_v2_Rogue` at the time of writing). 
- If you _only_ want to use ReAnimation as an API  for another mod (i.e only as a dependency that doesnt add any animations on its own) - only enable `ReAnimation_API` AND delete "Animations" folder from within this mod.

Have fun!

## Mod compatibility

Compatible with practically any other animation mod. ReAnimation uses OpenMW system of animation overrides and will only override a specific set of animations. Recommended to use with [MCAR](https://www.nexusmods.com/morrowind/mods/48628) for delightfull swimming and casting animations, but will work just fine without it.

[Better Bodies](https://www.nexusmods.com/morrowind/mods/48387) - causes a left-shoulder's sharp polygon to protrude on the left side of the screen while having naked arms (as well as with some common shirts) and sneaking with a dagger. Most noticeable with a [Low First Person Sneak Mode](https://www.nexusmods.com/morrowind/mods/43108). This is most likely an issue on the side of Better Bodies. Until it's fixed - simply wear a peace of armor on your left shoulder that doesn't bug out.

## Vanilla/MWSE compatibility

Not currently compatible. If you would like to port the scripting part to MWSE - please do, I'm not familiar with MWSE and am not planning to change that.
However, if possible - keep this mod as a dependency, instead of reuploading the whole thing.

## For Modders

ReAnimation exposes an API (Interface for other mods to use). The interface works around some of the OpenMW Lua animation API limitations and provides a simple way of adding alternating attack animations for different weapons, as well as a slightly less simple way of defining generic conditional animation overrides.

To ensure that the ReAnimation interface is available, your mod should either be loaded after the ReAnimation API, or you should interact with the interface from inside the update function instead of the global scope. But in the latter case, ensure that you register your animations/overrides only once, and not every update tick.

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

Generic conditional animation override:

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






