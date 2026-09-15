local mp = "scripts/MaxYari/ReAnimation_v3/"

local omwself = require('openmw.self')
local types = require('openmw.types')
local animation = require('openmw.animation')
local vfs = require('openmw.vfs')
local I = require('openmw.interfaces')

local animManager = require(mp .. "scripts/anim_manager")
local gutils = require(mp .. "scripts/gutils")

local selfActor = gutils.Actor:new(omwself)

-- omwself.controls is a sol property whose getter returns a pointer to the actor's control struct,
-- so every "omwself.controls.sneak" is two C++ crossings rather than one. The struct is owned by
-- the script's own SelfObject and lives as long as this script does - a reloaded script re-runs
-- this file and re-takes the reference - so the handle can be held. Reading .sneak / .run off it is
-- still a property call each, which is cheap: a bool straight out of the struct, no lookups.
local controls = omwself.controls

-- Max Yari's Script Services (MSS) is a required dependency: checked once, when this script loads.
if not require('openmw.core').contentFiles.has("MaxYariScriptServices.omwscripts") then
    print("[ReAnimation] ERROR: critical dependency is missing: Max Yari's Script Services (MSS). Please install it.")
    require('openmw.ui').showMessage("ReAnimation: Critical dependency is missing, please install Max Yari's Script Services (MSS)")
end

local cloneAnimOptions = gutils.cloneAnimOptions

-- Every override with a parent reads self.parentOptions when it starts on update, and the API only
-- fills that in when the parent passes through its playBlended handler. A parent that was already
-- playing when the save loaded never does, so options() hit cloneAnimOptions(nil) on every frame
-- and each error aborted the whole override loop. Until its parent has been seen playing, such an
-- override simply does not start on update. The start-on-event path is unaffected: it sets
-- parentOptions just before asking the condition.
local function addOverride(anim)
    if anim.parent and anim.startOnUpdate then
        local condition = anim.condition
        anim.condition = function(self)
            return self.parentOptions ~= nil and condition(self)
        end
    end
    I.ReAnimation.addAnimationOverride(anim)
end

-- One above `priority` on every bone group, and two above on the lower body. For an override that
-- starts on update while its parent is already playing: the parent can no longer be hidden, so the
-- override has to outrank it -- copying its priority is not enough, because the engine evicts any
-- state whose priority set equals the one being played (animation.cpp:905). That erased the parent,
-- the override then stopped for lack of one, and the view model was left with nothing playing.
-- The uneven lower body keeps it from ever equalling a uniform engine set too, such as Hit's
-- (Movement + 1).
local function outrankPriority(priority)
    local BG = animation.BONE_GROUP
    local function base(group)
        if type(priority) == "number" then return priority end
        return priority[group]
    end
    return {
        [BG.LeftArm] = base(BG.LeftArm) + 1,
        [BG.RightArm] = base(BG.RightArm) + 1,
        [BG.Torso] = base(BG.Torso) + 1,
        [BG.LowerBody] = base(BG.LowerBody) + 2,
    }
end

-- Available bone-groups:
-- BoneGroup.LeftArm
-- BoneGroup.LowerBody
-- BoneGroup.RightArm
-- BoneGroup.Torso


-- The shield arm (runforwardshield) and runbounce are each a single walk-paced cycle, played under
-- every walk, run and sneak group without lining up with any of them, so only their speed follows
-- the movement group, never their phase: its live rate while walking or running, and 1/2.8 of it
-- while sneaking - there are no sneak versions of these cycles, and the walk-paced ones run 2.8x too
-- fast against sneak cycles. Content tuning, not an engine constant, and exactly the ratio the old
-- speed formula produced (walk and run over the engine's own constants, sneak over 33.5452 * 2.8
-- where the engine uses 33.5452).
local WALK_CYCLE_SNEAK_PACE = 1 / 2.8

local function walkCyclePace(moveGroupname)
    if string.find(moveGroupname, "sneak", 1, true) then return WALK_CYCLE_SNEAK_PACE end
    return 1
end

-- onUpdate for the shield: the engine re-scales the parent every frame (analog input, strafing,
-- buffs), so the shield arm follows it at its pace. setSpeed only when the result changes.
local function syncShieldSpeed(self)
    local parentSpeed = animation.getSpeed(omwself, self.parent)
    if not parentSpeed then return end
    local speed = parentSpeed * walkCyclePace(self.parent)
    if speed ~= self.syncedSpeed then
        animation.setSpeed(omwself, self.groupname, speed)
        self.syncedSpeed = speed
    end
end

-- The bounce keeps the stride's spine bob going while an attack plays during movement. There are
-- two: runbounce (xRunBounceV2.kf) for the Reanimation v2 one-handed set, whose poses sit on the v2
-- pelvis, and runbouncev3 for every v3 set. Bows get neither. weapononehand covers every one-handed
-- weapon, short blades, blunt and axes included. Attack variants keep their hidden parent group
-- playing, so alt attacks count as their parent - alt and star throws as throwweapon, the alternate
-- fists as handtohand.
-- With the FBA Compatibility folder installed the movement groups carry 3rd-person legs and root
-- motion on the lower body, which a bounce would take over: the legs would fall back to the rig
-- pose, and with no root motion under a movement group that has velocity the player stops dead.
-- Movement keeps the lower body during attacks anyway (the attack's lower body priority is below
-- Movement), so there the bob comes from the 3rd-person stride.
local FBA_COMPAT = vfs.fileExists("ReAnimation_FBA_Compatibility.txt")

local BOUNCE_V2_ATTACK_GROUPS = { "weapononehand" }
local BOUNCE_V3_ATTACK_GROUPS = { "weapontwohand", "weapontwowide", "throwweapon", "crossbow", "handtohand" }

local function isAnyPlaying(groups)
    for i = 1, #groups do
        if animManager.isPlaying(groups[i]) then return true end
    end
    return false
end

-- runbounce has no parent group to copy a speed from, so it computes the one the engine gives a
-- movement animation, from the same inputs (character.cpp:754, :2402):
--     min(10, currentSpeed / (154.064 walking | 222.857 running | 33.5452 sneaking))
-- currentSpeed already carries the analog stick deflection and the strafing penalty
-- (actor.cpp:73-75), so recomputing this every frame in onUpdate follows a controller. The sneak
-- divisor also carries the walk-cycle pace (see WALK_CYCLE_SNEAK_PACE). Walk/run/sneak come from the
-- control flags, which can disagree with the engine's movement state - holding run while
-- over-encumbered still walks.
local function bounceSpeed()
    local moveAnimSpeed = 154.064
    if controls.sneak then
        moveAnimSpeed = 33.5452 / WALK_CYCLE_SNEAK_PACE
    elseif controls.run then
        moveAnimSpeed = 222.857
    end
    return math.min(10, selfActor:getCurrentSpeed() / moveAnimSpeed)
end

-- onUpdate for runbounce. setSpeed only when the result changes.
local function syncBounceSpeed(self)
    local speed = bounceSpeed()
    if speed ~= self.syncedSpeed then
        animation.setSpeed(omwself, self.groupname, speed)
        self.syncedSpeed = speed
    end
end

-- Shared by both bounces. They share the priority set too, which is safe only because their attack
-- groups never play together - the engine evicts one of two states whose sets are equal.
local function bounceOptions(self)
    self.syncedSpeed = nil
    -- camelCase only: playBlended reads blendMask/startKey/... and silently ignored the
    -- lowercase keys this used to pass, so it played on all bones, auto-disabling, unlooped.
    return {
        startKey = "start",
        stopKey = "stop",
        loops = 999,
        forceLoop = true,
        autoDisable = false,
        -- Not a flat Movement + 1: that equals Hit's priority on every bone group, and the
        -- engine evicts any state whose whole set equals the one being played
        -- (animation.cpp:905) - a hit erased the bounce, and the bounce restarting on the
        -- next update erased the hit recoil. Only the lower body is blended, so only its
        -- value shows: one above movement, as before. It ties with Hit there, and the tie
        -- goes to the state first in name order, so the hit* recoil keeps the spine and the
        -- bob resumes after it.
        priority = {
            [animation.BONE_GROUP.LeftArm] = animation.PRIORITY.Movement,
            [animation.BONE_GROUP.RightArm] = animation.PRIORITY.Movement,
            [animation.BONE_GROUP.Torso] = animation.PRIORITY.Movement,
            [animation.BONE_GROUP.LowerBody] = animation.PRIORITY.Movement + 1,
        },
        blendMask = animation.BLEND_MASK.LowerBody,
        speed = bounceSpeed()
    }
end


-- Options for the thrown shield corrections, from either start path. They never touch the parent:
-- they outrank it, by one on the arms. The star and sneak idles and the star movement groups also
-- sit one above the same parents, so that ties on the left arm - and the engine hands a tie to the
-- state first by name, which "idle1tshield" and "runforward1tshield" are ahead of "idle1tsneak",
-- "idle1tstar*" and "*1tstar". The lower body goes three up rather than their one or two, so the
-- whole set never equals theirs and neither state gets evicted. Movement + 1 stays under Weapon, so
-- a throw still takes the left arm.
local function thrownShieldOptions(self, pOptions)
    local opts = cloneAnimOptions(pOptions or self.parentOptions)
    opts.blendMask = animation.BLEND_MASK.LeftArm
    opts.blendmask = animation.BLEND_MASK.LeftArm
    opts.priority = outrankPriority(opts.priority)
    opts.priority[animation.BONE_GROUP.LowerBody] = opts.priority[animation.BONE_GROUP.LowerBody] + 1
    return opts
end


local KATANA_ID_TERMS ={ "katana", "scythe", "gravedigger", "bloodrust" }

-- Throwing stars, as opposed to the knives, darts, javelins and axes that share the throwweapon
-- group. A single term is enough here: every star in Morrowind + Tribunal + Bloodmoon (15 of 15)
-- and in Tamriel Data (57 of 57) has "star" in its record id, and nothing else does.
local STAR_ID_TERMS = { "star" }

-- Weapon ids never change what they are, so the matching runs once per distinct weapon and is a
-- single table lookup thereafter. Each table gains one small entry per weapon ever equipped.
local function weaponIdMatcher(terms)
    local cache = {}
    return function()
        local id = I.ReAnimation.getEquippedWeaponId()
        if id == nil then return false end

        local cached = cache[id]
        if cached == nil then
            cached = false
            for i = 1, #terms do
                if string.find(id, terms[i], 1, true) then
                    cached = true
                    break
                end
            end
            cache[id] = cached
        end

        return cached
    end
end

local isKatana = weaponIdMatcher(KATANA_ID_TERMS)
local isThrowingStar = weaponIdMatcher(STAR_ID_TERMS)

-- Same idea for the off hand. This one is polled hard: idleshield's stopCondition runs every frame
-- while it is playing, which with a shield equipped is most of the time. Uncached it cost a
-- getEquipment, a recordId string serialization and an Armor record lookup per frame; now it is the
-- API's time-cached id plus a table lookup.
local isShieldByItemId = {}

local function hasShieldEquipped()
    local slot = types.Actor.EQUIPMENT_SLOT.CarriedLeft
    local id = I.ReAnimation.getEquippedItemId(slot)
    if id == nil then return false end

    local cached = isShieldByItemId[id]
    if cached == nil then
        cached = gutils.isAShield(I.ReAnimation.getEquippedItem(slot)) and true or false
        isShieldByItemId[id] = cached
    end

    return cached
end

-- Weapon type of the right hand, by id like the rest. nil with nothing in it.
local weaponTypeByItemId = {}

local function equippedWeaponType()
    local id = I.ReAnimation.getEquippedWeaponId()
    if id == nil then return nil end

    local weaponType = weaponTypeByItemId[id]
    if weaponType == nil then
        local record = types.Weapon.record(id)
        weaponType = record and record.type or false
        weaponTypeByItemId[id] = weaponType
    end

    return weaponType
end


local animations = {
    {
        parent = nil,
        groupname = "bowandarrow1",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function(self)
            local shootHoldTime = animation.getTextKeyTime(omwself, "bowandarrow: shoot max attack")
            local currentTime = animation.getCurrentTime(omwself, "bowandarrow")

            return currentTime and math.abs(shootHoldTime - currentTime) < 0.001
        end,
        stopCondition = function(self)
            return not self:condition()
        end,
        options = function(self)
            return {
                startkey = "tension start",
                stopkey = "tension end",
                loops = 999,
                forceloop = true,
                autodisable = false,
                priority = animation.PRIORITY.Weapon + 1,
                blendmask = animation.BLEND_MASK.UpperBody,
                blendMask = animation.BLEND_MASK.UpperBody,
                startKey = "tension start",
                stopKey = "tension end",
                forceLoop = true,
                autoDisable = false
            }
        end,
        startOnUpdate = true
    },
    {
        parent = "idle1h",
        groupname = "idle1hsneak",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function(self)
            return controls.sneak
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
    },
    {
        parent = "idle1s",
        groupname = "idle1ssneak",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function(self)
            return controls.sneak
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
    },
    {
        parent = "idle2c",
        groupname = "idle2csneak",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function(self)
            return controls.sneak
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
    },
    -- Sneak locomotion needs no override: sneakforward2w etc. are real engine groups, played
    -- natively once a kf defines them. Until then the engine falls back to the 2c ones.
    {
        parent = "idle2w",
        groupname = "idle2wsneak",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function(self)
            return controls.sneak
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
    },
    -- Dagger shield corrections. idle1sshield and runforward1sshield are the 1h shield arms
    -- (idleshield in x1hIdle, runforwardshield in xShieldRun) with the clavicle re-aimed by the 21
    -- degrees the dagger set turns the upper body past the 1h one, so the shield sits where it does
    -- with a 1h weapon rather than that far toward the middle - same as the thrown ones below.
    --
    -- startOnUpdate as well as on the event: a shield put on while the idle is already playing
    -- replays nothing, so the idle never passed through the handler with a shield in hand and the
    -- correction never started. Same for a weapon swap between two daggers.
    {
        parent = {"idle1s","idle1ssneak","jump1s"},
        groupname = "idle1sshield",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = hasShieldEquipped,
        stopCondition = function(self)
            return not self:condition()
        end,
        options = function(self, pOptions)
            local opts = cloneAnimOptions(pOptions or self.parentOptions)
            opts.blendMask = animation.BLEND_MASK.LeftArm
            opts.blendmask = animation.BLEND_MASK.LeftArm

            if pOptions then
                -- Consider: will changing parent options here somehow undesirably propagate to saved self.parentOptions?
                gutils.expandPriority(pOptions)
                pOptions.priority[animation.BONE_GROUP.LeftArm] = -1
            else
                -- Started on update, the idle is already playing and its left arm can no longer be
                -- lowered, so outrank it instead. A copy of its priority would evict it.
                opts.priority = outrankPriority(opts.priority)
            end

            return opts
        end,
        startOnAnimEvent = true,
        startOnUpdate = true
    },
    {
        parent = { "runforward1s", "runback1s", "runleft1s", "runright1s", "walkforward1s", "walkback1s", "walkleft1s", "walkright1s", "sneakforward1s", "sneakback1s", "sneakleft1s", "sneakright1s" },
        groupname = "runforward1sshield",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = hasShieldEquipped,
        stopCondition = function(self)
            return not self:condition()
        end,
        options = function(self, pOptions)
            local opts = cloneAnimOptions(pOptions or self.parentOptions)
            opts.blendMask = animation.BLEND_MASK.LeftArm
            opts.blendmask = animation.BLEND_MASK.LeftArm

            -- Started from the parent's play, the parent has not been played yet: opts.speed is the
            -- engine's initial 1 and onUpdate corrects it this same frame. Started on update, the
            -- parent is already running, so its live speed is read right away.
            local parentSpeed = opts.speed or 1
            if not pOptions then
                parentSpeed = animation.getSpeed(omwself, self.parent) or parentSpeed
            end
            opts.speed = parentSpeed * walkCyclePace(self.parent)
            self.syncedSpeed = nil

            if pOptions then
                gutils.expandPriority(pOptions)
                pOptions.priority[animation.BONE_GROUP.LeftArm] = -1
            end

            return opts
        end,
        onUpdate = syncShieldSpeed,
        startOnAnimEvent = true,
        startOnUpdate = true
    },
    -- Shield corrections for thrown weapons. The thrown set turns the upper body 46 degrees further
    -- round than the 1h set, and has no shield pose of its own, so a shield stayed wherever the
    -- throwing arm pose put it - 20 units off. idle1tshield and runforward1tshield are the 1h shield
    -- arms (idleshield, runforwardshield) with the clavicle re-aimed by those 46 degrees.
    -- idle1t keeps playing under the star and sneak idles, and so do the thrown movement groups
    -- under the star ones, so the engine groups are parent enough. See thrownShieldOptions for how
    -- they win over those overrides.
    {
        parent = { "idle1t", "jump1t" },
        groupname = "idle1tshield",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = hasShieldEquipped,
        stopCondition = function(self)
            return not self:condition()
        end,
        options = thrownShieldOptions,
        startOnAnimEvent = true,
        startOnUpdate = true
    },
    {
        parent = { "runforward1t", "runback1t", "runleft1t", "runright1t", "walkforward1t", "walkback1t", "walkleft1t", "walkright1t", "sneakforward1t", "sneakback1t", "sneakleft1t", "sneakright1t" },
        groupname = "runforward1tshield",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = hasShieldEquipped,
        stopCondition = function(self)
            return not self:condition()
        end,
        options = function(self, pOptions)
            local opts = thrownShieldOptions(self, pOptions)

            -- Same walk-cycle pacing as runforwardshield.
            local parentSpeed = opts.speed or 1
            if not pOptions then
                parentSpeed = animation.getSpeed(omwself, self.parent) or parentSpeed
            end
            opts.speed = parentSpeed * walkCyclePace(self.parent)
            self.syncedSpeed = nil

            return opts
        end,
        onUpdate = syncShieldSpeed,
        startOnAnimEvent = true,
        startOnUpdate = true
    },
    -- Both bounces are polled every frame while not playing, so each checks its attack groups first
    -- (a Lua-side lookup) and only then asks the engine for the speed.
    {
        parent = nil,
        -- The Reanimation v2 bounce, for the v2 one-handed set: its poses sit on the v2 pelvis,
        -- which the v3 bounce would swing aside.
        groupname = "runbounce",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function()
            return not FBA_COMPAT and isAnyPlaying(BOUNCE_V2_ATTACK_GROUPS) and selfActor:getCurrentSpeed() > 1
        end,
        stopCondition = function(self)
            return not self:condition()
        end,
        options = bounceOptions,
        onUpdate = syncBounceSpeed,
        startOnUpdate = true
    },
    {
        parent = nil,
        -- The Reanimation v3 bounce: the v2 one holds the v2 pelvis (5.55 deg off v3), which swings
        -- the whole torso and weapon aside on v3 poses. This one keys only the v3 pelvis and the
        -- spine bob.
        groupname = "runbouncev3",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function()
            return not FBA_COMPAT and isAnyPlaying(BOUNCE_V3_ATTACK_GROUPS) and selfActor:getCurrentSpeed() > 1
        end,
        stopCondition = function(self)
            return not self:condition()
        end,
        options = bounceOptions,
        onUpdate = syncBounceSpeed,
        startOnUpdate = true
    },
    {
        parent = "idlebow",
        groupname = "idlebowsneak",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function(self)
            return controls.sneak
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
    },
    -- Sneak locomotion needs no override, same as 2w - sneakforwardcrossbow etc. in
    -- xcrossbowSneakMovement play natively.
    {
        parent = "idlecrossbow",
        groupname = "idlecrossbowsneak",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function(self)
            return controls.sneak
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
    },
    -- Sneak locomotion needs no override, same as 2w - sneakforwardhh etc. in xhhSneakMovement
    -- play natively.
    {
        parent = "idlehh",
        groupname = "idlehhsneak",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = function(self)
            return controls.sneak
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
    }
}


for _, anim in ipairs(animations) do
    addOverride(anim)
end

-- Torch corrections. The engine holds a torch up with its own "torch" group on the left arm, at
-- Priority Torch over whatever the weapon set does - fixed bone rotations under the neck. Weapon
-- sets that turn the upper body further round than the 1h set carry the torch toward the middle of
-- the screen with it: 21 degrees for daggers, 46 for thrown weapons. torch1s and torch1t are the same
-- arm with the clavicle re-aimed by that difference, so the torch lands where it does over the 1h set.
--
-- Deliberately not an override of "torch": the engine re-plays torch every frame while one is held
-- (updateWeaponState), and each play runs the override handler, which would clone options and
-- restart the correction every frame. So it polls and outranks the torch instead. The torch group
-- itself is the cheapest torch check there is - the engine only plays it with a light in the left
-- hand, and while none is held the lookup is a Lua table read, no equipment fetch.
local function addTorchCorrection(id, groupname, weaponType)
    local function condition()
        return animManager.isPlaying("torch")
            and equippedWeaponType() == weaponType
            -- Tracking already waits for the Weapon stance before starting this, but a running
            -- override is never stopped by a stance change: sheathing leaves the dagger in the
            -- hand and the torch up.
            and types.Actor.getStance(omwself) == types.Actor.STANCE.Weapon
    end

    addOverride({
        id = id,
        parent = nil,
        groupname = groupname,
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = condition,
        stopCondition = function() return not condition() end,
        options = function()
            return {
                startKey = "start",
                stopKey = "stop",
                startkey = "start",
                stopkey = "stop",
                loops = 999,
                forceLoop = true,
                autoDisable = false,
                priority = outrankPriority(animation.PRIORITY.Torch),
                blendMask = animation.BLEND_MASK.LeftArm,
                blendmask = animation.BLEND_MASK.LeftArm
            }
        end,
        startOnUpdate = true
    })
end

addTorchCorrection("TorchDagger", "torch1s", types.Weapon.TYPE.ShortBladeOneHand)
addTorchCorrection("TorchThrown", "torch1t", types.Weapon.TYPE.MarksmanThrown)

I.ReAnimation.addAltAttackAnimations({
    parentAttackGroupname = "weapononehand",
    altAttackGroupname = "weapononehand1",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson
})



-- Two-handed attacks alternate downward/upward, and the downward swing additionally picks at
-- random between the vanilla animation and a substitute one.
--
-- Katanas share the weapontwohand animation group with claymores but want their own chops, so the
-- set is registered twice under mutually exclusive conditions. Each keeps its own alternation
-- counters, so swapping weapons mid-fight resumes each sequence where it left off rather than
-- restarting it.
--
-- What we actually want is "is this weapon built on a katana mesh", which no single name fragment
-- expresses: the scythes are enchanted dai-katanas, and Gravedigger, Bloodrust and Raphalas' Sword
-- are uniques named after nothing in particular. These four terms cover every such weapon in
-- Morrowind + Tribunal + Bloodmoon (7 of 7) and in Tamriel Data (17 of 17), with no false hits.
-- A modded katana under some other name would fall through to the claymore set and simply chop
-- like a claymore.


I.ReAnimation.addAttackVariants({
    id = "TwoHandKatana",
    parentAttackGroupname = "weapontwohand",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    condition = isKatana,
    attacks = {
        chop   = { { "weapontwohandktn" }, { "weapontwohandktnalt" } },
        slash  = { { "weapontwohand" }, { "weapontwohandalt" } },
        thrust = { { "weapontwohand" }, { "weapontwohandalt" } }
    }
})

I.ReAnimation.addAttackVariants({
    id = "TwoHand",
    parentAttackGroupname = "weapontwohand",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    condition = function() return not isKatana() end,
    attacks = {
        chop   = { { "weapontwohand", "weapontwohandsub" }, { "weapontwohandalt" } },
        slash  = { { "weapontwohand" }, { "weapontwohandalt" } },
        thrust = { { "weapontwohand" }, { "weapontwohandalt" } }
    }
})
I.ReAnimation.addAttackVariants({
    parentAttackGroupname = "weapontwowide",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    subAttackMode = I.ReAnimation.SUB_ATTACK_MODE.Random,
    randomMaxRepeats = 2,
    attacks = { 
        chop   = { { "weapontwowide"}, { "weapontwowidealt" } },
        thrust = { { "weapontwowide", "weapontwowidesub2", "weapontwowidesub3", "weapontwowidesub4" } },
        slash  = { { "weapontwowide", "weapontwowidesub" }, { "weapontwowidealt" } }
    }
})
I.ReAnimation.addAttackVariants({
    parentAttackGroupname = "handtohand",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    subAttackMode = I.ReAnimation.SUB_ATTACK_MODE.RoundRobin,
    attacks = {         
        slash  = { { "handtohand" }, { "handtohandalt" } },
        thrust  = { { "handtohand" }, { "handtohandalt" } },
        chop  = { { "handtohand" }, { "handtohandalt" } }
    }
})
-- Throwing stars are thrown quite differently from knives and darts, so they get their own pair of
-- groups. Same two-registration pattern as the katanas above: mutually exclusive conditions on one
-- parent group.
-- Throwing stars get their own idle, locomotion, jump and equip too. The jump and the equip hide
-- their parent the way alt attacks do (uniquified priority + blendMask 0): they only ever stop
-- together with it, so it never has to come back.
--
-- Idle and locomotion outrank their parent instead, on every start path. They stop the moment the
-- star leaves the hand, and swapping it for a knife is a same-type swap (both 1t) that replays
-- nothing - a hidden parent would stay hidden until its next replay, leaving nothing on the view
-- model in between, and it spins. Outranked, the parent is already showing when the star stops.
--
-- If a group is missing the override simply never runs - hasGroup is checked before options(), so
-- the parent is never hidden and vanilla plays. That makes these safe to register before the
-- animations exist.
-- Only for overrides started from the parent's play: a parent that is already playing can no
-- longer be hidden.
local function starHideOptions(self, pOptions)
    local opts = cloneAnimOptions(pOptions)
    gutils.uniquifyPriority(pOptions)
    pOptions.blendMask = 0
    pOptions.blendmask = 0
    return opts
end

-- For star overrides that can stop while their parent plays on. See outrankPriority for why
-- copying the parent's priority is not enough.
local function starOutrankOptions(self, pOptions)
    local opts = cloneAnimOptions(pOptions or self.parentOptions)
    opts.priority = outrankPriority(opts.priority)
    return opts
end

-- Idle re-evaluates whenever idle1t replays, which covers drawing and sheathing, jumping, and every
-- attack end (the engine sets mResetIdleOnAttackEnd whenever an attack starts). Swapping between two
-- thrown weapons replays nothing -- both are 1t, so no equip animation plays -- and that is what
-- startOnUpdate is for.
--
-- Sneaking is a second override on the same parent rather than its own group, because first person
-- has no "idlesneak" animation at all: refreshIdleAnims falls back to "idle" + weapon short group,
-- so a sneaking thrown-weapon user is still playing idle1t. controls.sneak is the only way to tell,
-- which is exactly why idle1hsneak / idle1ssneak are built the same way. The two conditions are
-- mutually exclusive so only one ever plays. startOnUpdate on both, since toggling
-- sneak does not replay the idle.
addOverride({
    id = "ThrowStarIdle",
    parent = "idle1t",
    groupname = "idle1tstar",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    condition = function() return isThrowingStar() and not controls.sneak end,
    stopCondition = function(self) return not self:condition() end,
    options = starOutrankOptions,
    startOnAnimEvent = true,
    startOnUpdate = true
})
addOverride({
    id = "ThrowStarIdleSneak",
    parent = "idle1t",
    groupname = "idle1tstarsneak",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    condition = function() return isThrowingStar() and controls.sneak end,
    stopCondition = function(self) return not self:condition() end,
    options = starOutrankOptions,
    startOnAnimEvent = true,
    startOnUpdate = true
})

-- Sneak idle for everything else in the thrown group (knives, darts, javelins, axes). Built like
-- idle1hsneak rather than the star pair: it only needs to outrank idle1t, not hide it. The not-star
-- condition keeps it from stacking on ThrowStarIdleSneak. Sneak locomotion needs no override -
-- sneakforward1t etc. in x1tSneakMovement play natively.
addOverride({
    id = "ThrowIdleSneak",
    parent = "idle1t",
    groupname = "idle1tsneak",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    condition = function() return controls.sneak and not isThrowingStar() end,
    stopCondition = function(self) return not self:condition() end,
    options = function(self)
        local opts = cloneAnimOptions(self.parentOptions)
        opts.loops = 999

        -- The priority can arrive as a per-bone-group table rather than a number: any override
        -- that hides idle1t rewrites it into one (gutils.uniquifyPriority) before this one's
        -- parentOptions clone is taken, since clones are made in registration order.
        local p = opts.priority
        if type(p) == "number" then
            opts.priority = p + 1
        else
            local BG = animation.BONE_GROUP
            opts.priority = {
                [BG.LeftArm] = p[BG.LeftArm] + 1,
                [BG.LowerBody] = p[BG.LowerBody] + 1,
                [BG.RightArm] = p[BG.RightArm] + 1,
                [BG.Torso] = p[BG.Torso] + 1
            }
        end
        return opts
    end,
    startOnUpdate = true
})

-- Star locomotion follows the thrown cycle it replaces, every frame, through the override onUpdate
-- hook. The engine starts movement groups at speed 1 and re-scales them each frame to the actor's
-- current speed (character.cpp:2402) - analog input, strafing, buffs, and a run's first frame, which
-- it computes from the *walk* speed - so any speed copied once goes stale. syncStarMove copies it
-- every frame, nudged by the phase error so the two cycles stay aligned too: an animation's time
-- cannot be set directly, and a cancel-and-replay would trigger a blend. The star and thrown cycles
-- have identical loop lengths with Start/Stop on Loop Start/Stop, so their completions are the same
-- fraction of the same cycle.
local PHASE_GAIN = 2          -- speed nudge per unit of phase error; halves a small error in ~0.4 s
local PHASE_MAX_NUDGE = 0.25  -- never more than 25% off the parent's speed
local PHASE_DEADZONE = 0.002  -- about 2 ms of a 1 s cycle; below it, plain parent speed

local function syncStarMove(self)
    local parentSpeed = animation.getSpeed(omwself, self.parent)
    if not parentSpeed then return end

    local speed = parentSpeed
    local parentDone = animation.getCompletion(omwself, self.parent)
    local done = animation.getCompletion(omwself, self.groupname)
    if parentDone and done then
        local err = parentDone - done
        err = err - math.floor(err + 0.5) -- wrap to [-0.5, 0.5): both cycles loop
        if math.abs(err) > PHASE_DEADZONE then
            local nudge = math.max(-PHASE_MAX_NUDGE, math.min(PHASE_MAX_NUDGE, err * PHASE_GAIN))
            speed = parentSpeed * (1 + nudge)
        end
    end

    if speed ~= self.syncedSpeed then
        animation.setSpeed(omwself, self.groupname, speed)
        self.syncedSpeed = speed
    end
end

local function starMoveOptions(self, pOptions)
    local opts = starOutrankOptions(self, pOptions)
    self.syncedSpeed = nil
    if not pOptions then
        -- Started on update, with the parent already running: start from its live speed and phase.
        opts.speed = animation.getSpeed(omwself, self.parent) or opts.speed
        opts.startPoint = animation.getCompletion(omwself, self.parent) or opts.startPoint
    end
    -- Started from the parent's play, the parent has not been played yet: opts carries the engine's
    -- own initial speed (1) and resume point, and onUpdate takes over in this same frame's Lua update.
    return opts
end

-- Locomotion additionally polls, so a weapon swapped mid-run is noticed. Only one movement group
-- plays at a time, so at most one of these is ever running, but startOnUpdate does mean all eight
-- sit in trackedAnims permanently - roughly eight isPlaying calls per frame, the same shape as the
-- shield's twelve.
for _, base in ipairs({ "walkforward", "walkback", "walkleft", "walkright",
                        "runforward", "runback", "runleft", "runright",
                        "sneakforward", "sneakback", "sneakleft", "sneakright" }) do
    addOverride({
        id = "ThrowStarMove_" .. base,
        parent = base .. "1t",
        groupname = base .. "1tstar",
        armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
        condition = isThrowingStar,
        stopCondition = function(self) return not self:condition() end,
        options = starMoveOptions,
        onUpdate = syncStarMove,
        startOnAnimEvent = true,
        startOnUpdate = true
    })
end

-- The jump plays twice per jump -- from "start" in the air, then from "loop stop" for the landing --
-- and the engine clears and replays it each time, so starting on the event covers both and carries
-- the landing's start key into the star group (xThrownStarJump.yaml keys its landing blend on it).
-- No startOnUpdate: a star equipped in mid-air keeps the thrown jump until the next one. And no
-- stopCondition either: the thrown jump underneath is hidden, so stopping the star one mid-air on an
-- unequip would leave nothing playing until landing. It stops with its parent instead.
addOverride({
    id = "ThrowStarJump",
    parent = "jump1t",
    groupname = "jump1tstar",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    condition = isThrowingStar,
    options = starHideOptions,
    startOnAnimEvent = true
})

-- Equip and unequip are sections of the weapon's own group, "throwweapon: equip start/stop" and
-- "unequip start/stop" (character.cpp:1405, :1463). Like vanilla, the star keeps them in its attack
-- group, throwweaponstar, played over the hidden parent like the jump. xThrownStarThrow.kf defines
-- that group too, but has no equip or unequip start key, so the engine skips that source and takes
-- the section from xThrownStarEqUneq.kf (animation.cpp:926, :997). Key times must match the parent's
-- exactly: the hidden parent's "equip attach" / "unequip detach" still show and hide the weapon, and
-- the engine disables it at the section's end (character.cpp:1834, :1860), which is what stops this.
--
-- The ThrowStar attack set below plays throwweaponstar on the same parent, and playBlended on a group
-- that is still active only updates its priority. So this clears the other side's leftover before
-- each play: preOverride clears a throw still winding up when a sheathe starts the unequip, and the
-- condition clears a finished equip section when any other section - a throw - plays. That relies on
-- this override being registered before the ThrowStar set, so it runs first for the same play.
--
-- isThrowingStar holds for unequip too: the engine only plays unequip on a sheathe, and never once
-- the weapon has changed, so the star is still in the hand. Weapon to weapon swaps play neither.
-- No hidesParent: enabled never clears here, so it would suppress every thrown tail for good.
-- Stance Any, not the Weapon default: a sheathe drops the stance to Nothing before unequip plays.
local EQUIP_START = "equip start"
local UNEQUIP_START = "unequip start"

addOverride({
    id = "ThrowStarEquip",
    parent = "throwweapon",
    groupname = "throwweaponstar",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    stance = I.ReAnimation.STANCE.Any,
    condition = function(self)
        local startKey = self.parentOptions.startkey or self.parentOptions.startKey
        if startKey == EQUIP_START or startKey == UNEQUIP_START then
            return isThrowingStar()
        end
        if self.running then
            animation.cancel(omwself, self.groupname)
            self.running = false
        end
        return false
    end,
    preOverride = function(self)
        if not self.running and animManager.isPlaying(self.groupname) then
            animation.cancel(omwself, self.groupname)
        end
    end,
    options = starHideOptions,
    startOnAnimEvent = true
})

I.ReAnimation.addAttackVariants({
    id = "ThrowStar",
    parentAttackGroupname = "throwweapon",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    condition = isThrowingStar,
    attacks = {
        -- "throwweaponaltstar", matching the group in xThrownStarThrowAlt.kf. A variant group that
        -- does not exist is worse than a missing throw: the set switches to it, the engine cannot
        -- play it over the hidden parent, and from then on the handler's hasGroup check on that
        -- stale groupname skips the whole set, so every later throw falls back to the parent's.
        shoot = { { "throwweaponstar" }, { "throwweaponaltstar" } }
    }
})
I.ReAnimation.addAttackVariants({
    id = "Throw",
    parentAttackGroupname = "throwweapon",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    condition = function() return not isThrowingStar() end,
    attacks = {
        shoot = { { "throwweapon" }, { "throwweaponalt" } }
    }
})

-- Tails need no registration: any attack group's follow-through stop plays "<group>extra" if it has
-- matching "<Type> Tail Start/Stop" keys. See the Tails section in ReAnimationAPI.lua.

