local mp = "scripts/MaxYari/ReAnimation_v3/"

local omwself = require('openmw.self')
local types = require('openmw.types')
local core = require("openmw.core")

local animation = require('openmw.animation')
local I = require('openmw.interfaces')
local animManager = require(mp .. "scripts/anim_manager")
local gutils = require(mp .. "scripts/gutils")
local EventsManager = require(mp .. "scripts/events_manager")

DebugLevel = 0

local animations = {}
local trackedAnims = {}
local trackedAnims_n = 0

local stance = nil

local ATTACK_TYPES = { "chop", "slash", "thrust", "shoot" }

-- Key-triggered animations (see "Key-triggered animation handling" below)
local keyAnims = {}       -- [parent groupname] = { anim, ... }, everything that was registered
local keyAnims_n = 0
local activeKeyAnims = {} -- the same shape, pre-filtered by armature type and stance

local frame_n = 0

-- -1 rather than 0: frame_n also starts at 0, so an initial value of 0 made the very first
-- checkActorStates() call short-circuit and leave state.stance/state.armatureType nil,
-- which fails every armature/stance gate until the first onUpdate tick.
local state_check_frame_n = -1
local state = {
    stance = nil,
    armatureType = nil,
    onStateChange = EventsManager:new()
}

--- Helper methods ----------------------
-----------------------------------------
local function isProperArmatureType(anim)
    if anim.armatureType == gutils.ARMATURE_TYPE.Any then return true end
    return anim.armatureType == state.armatureType
end

local function isProperStance(anim)
    if anim.stance == gutils.STANCE.Any then return true end
    return anim.stance == state.stance
end

local function addToTrackedAnimsList(anim)  
    if anim.alwaysTracked then return end -- alwaysTracked anims are managed by rebuildTrackedAnimsList  
    table.insert(trackedAnims, anim)
    trackedAnims_n = trackedAnims_n + 1
end

local function removeFromTrackedAnimsList(i)
    local anim = trackedAnims[i]    
    if anim.alwaysTracked then return end -- alwaysTracked anims are managed by rebuildTrackedAnimsList 
    table.remove(trackedAnims, i)
    trackedAnims_n = trackedAnims_n - 1
end

local function rebuildTrackedAnimsList()
    local newTrackedAnims = {}    
    for _, anims in pairs(animations) do
        -- Backwards: onUpdate walks this list from the end, so it meets a parent's higher-ranked
        -- overrides before its lower ones (see Override ranking).
        for i = #anims, 1, -1 do
            local anim = anims[i]
            anim.alwaysTracked = false
            if anim.running then
                table.insert(newTrackedAnims, anim)                
            elseif anim.startOnUpdate and isProperArmatureType(anim) and isProperStance(anim) then
                anim.alwaysTracked = true
                table.insert(newTrackedAnims, anim) 
            end           
        end
    end
    trackedAnims = newTrackedAnims
    trackedAnims_n = #trackedAnims
end

-- Key-triggered anims are filtered here rather than at trigger time, so the text key handler only
-- ever walks anims that are already valid for the current armature and stance.
local function rebuildActiveKeyAnims()
    local newActive = {}
    for parent, anims in pairs(keyAnims) do
        local matching = nil
        for i = 1, #anims do
            local anim = anims[i]
            if isProperArmatureType(anim) and isProperStance(anim) then
                if not matching then matching = {} end
                matching[#matching + 1] = anim
            end
        end
        newActive[parent] = matching
    end
    activeKeyAnims = newActive
end


local function checkActorStates()
    if state_check_frame_n == frame_n then return end
    
    local stance = types.Actor.getStance(omwself)
    local armature_type = gutils.getArmatureType()

    if stance ~= state.stance or armature_type ~= state.armatureType then
        state.stance = stance
        state.armatureType = armature_type
        -- A first/third person switch rebuilds the model, and clearAnimSources() wipes every
        -- animation state with no event (animation.cpp:778). Drop the mirror so it cannot go stale.
        animManager.resetPlayingState()

        state.onStateChange:emit(state)
        rebuildTrackedAnimsList()
        rebuildActiveKeyAnims()
    end

    state_check_frame_n = frame_n
end

-- Equipped items, resolved lazily and cached per slot. Nothing calls these unless an override asks,
-- so registrations that do not care about equipment pay nothing at all, and every caller shares the
-- one cached lookup.
--
-- Both the object and its lowercased record id are cached: .recordId is not a plain field but a
-- property backed by a C++ call that serializes a fresh string each access, and ids are stored as
-- authored ("BM nordic silver claymore", "King's_Oath") so they need lowering to compare.
--
-- The slot is read through Max Yari's Script Services (MSS), at most once per equipCacheTime seconds
-- (setEquipmentCacheTime, default 0.1) and shared with every other mod asking. Polling conditions -
-- shield, torch and star overrides check every frame - so cost a getEquipment ten times a second
-- rather than every frame; a swap is noticed up to that long after it happens. MSS expires the cache
-- when a pause starts or ends, so an item equipped in the paused inventory is seen on the first frame
-- after. The lowercased id is only rebuilt when MSS reports a different item.
local EQUIPMENT_CACHE_TIME = 0.1
local equipCacheTime = EQUIPMENT_CACHE_TIME
local equipSlotCache = {}

local function refreshEquippedItem(slot)
    local entry = equipSlotCache[slot]
    if entry == nil then
        entry = {}
        equipSlotCache[slot] = entry
    end
    local info = I.MSS.getEquipmentInfo(slot, equipCacheTime)
    if info ~= entry.info then
        entry.info = info
        entry.item = info and info.item
        entry.id = info and string.lower(info.recordId) or nil
    end
    return entry
end

-- Seconds an equipment lookup stays valid. 0 fetches once per frame.
local function setEquipmentCacheTime(seconds)
    equipCacheTime = seconds or EQUIPMENT_CACHE_TIME
end

-- The item equipped in the given EQUIPMENT_SLOT as a GameObject, or nil.
local function getEquippedItem(slot)
    return refreshEquippedItem(slot).item
end

-- Lowercased record id of the item in the given EQUIPMENT_SLOT, or nil.
local function getEquippedItemId(slot)
    return refreshEquippedItem(slot).id
end

-- Convenience wrappers for the weapon hand, which is what most conditions want.
local function getEquippedWeapon()
    return getEquippedItem(types.Actor.EQUIPMENT_SLOT.CarriedRight)
end

local function getEquippedWeaponId()
    return getEquippedItemId(types.Actor.EQUIPMENT_SLOT.CarriedRight)
end

-- True when the equipped weapon's record id contains substr. Plain substring match, no patterns,
-- so substr must be lowercase.
local function isEquippedWeapon(substr)
    local id = getEquippedWeaponId()
    return id ~= nil and string.find(id, substr, 1, true) ~= nil
end

-- True while some override is playing over groupname with the parent hidden (blendMask 0).
-- Reads anim.enabled rather than anim.running on purpose: running is cleared by onUpdate the moment
-- the parent stops, which is the same moment the follow-through text keys are being delivered,
-- whereas enabled is only rewritten by the next attack's wind up.
local function isParentHidden(groupname)
    local anims = animations[groupname]
    if not anims then return false end
    for i = 1, #anims do
        local anim = anims[i]
        if anim.hidesParent and anim.enabled then return true end
    end
    return false
end

local function addToAnimMap(anim)
    local key = anim.parent or "-"    
    local anims = animations[key]
    if not anims then
        anims = {}
        animations[key] = anims
    end
    -- print("Registering animation override with id for parent " .. key)

    -- Ranked overrides are kept highest first among themselves, so the handler reaches a higher one
    -- before every lower one it outranks (see Override ranking). A new one goes in front of the first
    -- lower-ranked one; everything else keeps registration order, which some overrides rely on.
    local rank = anim.overridePriority
    if rank ~= nil then
        for i = 1, #anims do
            local otherRank = anims[i].overridePriority
            if otherRank ~= nil and otherRank < rank then
                table.insert(anims, i, anim)
                return
            end
        end
    end
    table.insert(anims, anim)
end


--- Override ranking --------------------
-----------------------------------------
-- Overrides on one parent that replace the same thing - a star idle and a sneak idle on idle1t, a
-- katana attack set and the general two-handed one on weapontwohand - are ranked with
-- `overridePriority` instead of writing each one's condition to exclude all the others. The higher
-- one plays, and a lower one is not even asked while it does.
--
-- Unranked overrides (overridePriority nil, the default for addAnimationOverride) are outside this
-- entirely. They are what layers on top of the others - the shield arm corrections share idle1t
-- with the star idles - and are never stopped by, nor stop, a ranked one. Equal ranks do not
-- outrank each other either, so those still need mutually exclusive conditions.
--
-- Both paths meet a parent's ranked overrides highest first: addToAnimMap keeps each parent's list
-- in that order, and rebuildTrackedAnimsList lays the tracked list out so onUpdate does too.
--   * The playBlended handler: the first ranked override that passes its checks takes the play.
--     Every lower one after it is skipped without being asked.
--   * onUpdate: while a higher one on its parent is running, a lower one is not asked to start, and
--     one that is running is stopped through the usual stop path. Meeting the higher one first is
--     what makes both handovers happen within one frame.
-- Only onUpdate ever stops an outranked override: that path cancels, clears `running` and drops it
-- from trackedAnims in one go, which the handler's wasRunning bookkeeping relies on.
-- A higher override whose group is missing never takes a play, so the lower one plays instead.

-- True while a higher-ranked override on the same parent is running. Pure Lua: flag reads only.
local function isOutranked(anim)
    local siblings = animations[anim.parent or "-"]
    local rank = anim.overridePriority
    for i = 1, #siblings do
        local other = siblings[i]
        local otherRank = other.overridePriority
        if otherRank ~= nil then
            -- Ranked siblings are sorted highest first, so from here on nothing outranks anim.
            if otherRank <= rank then return false end
            if other.running then return true end
        end
    end
    return false
end


--- Key-triggered animation handling ----
-----------------------------------------
-- A key-triggered animation is fire-and-forget: it starts when a named text key fires on its parent
-- group, and is never tracked afterwards. The engine removes it on its own once it ends
-- (autoDisable), so unlike an override it costs nothing per frame and never enters trackedAnims.
--
-- anim.key is matched against the text key with a single leading and/or trailing "*", compiled once
-- at registration into a mode + literal so matching at runtime is one plain string.find and no
-- allocation. "*follow stop" matches every attack's follow-through stop key regardless of attack
-- type and strength.

local KEY_MATCH_EXACT, KEY_MATCH_PREFIX, KEY_MATCH_SUFFIX, KEY_MATCH_CONTAINS, KEY_MATCH_ANY = 1, 2, 3, 4, 5

local function compileKeyMatcher(anim)
    local pattern = string.lower(anim.key) -- text keys reach us lowercased by the engine
    local head = string.sub(pattern, 1, 1) == "*"
    local tail = string.sub(pattern, -1) == "*"

    if head then pattern = string.sub(pattern, 2) end
    if tail then pattern = string.sub(pattern, 1, -2) end

    if pattern == "" then
        anim.keyMatchMode = KEY_MATCH_ANY
    elseif head and tail then
        anim.keyMatchMode = KEY_MATCH_CONTAINS
    elseif head then
        anim.keyMatchMode = KEY_MATCH_SUFFIX
    elseif tail then
        anim.keyMatchMode = KEY_MATCH_PREFIX
    else
        anim.keyMatchMode = KEY_MATCH_EXACT
    end

    anim.keyMatchLiteral = pattern
    anim.keyMatchOffset = -#pattern -- only used by the suffix mode
end

local function matchesKey(anim, key)
    local mode = anim.keyMatchMode
    if mode == KEY_MATCH_EXACT then
        return key == anim.keyMatchLiteral
    elseif mode == KEY_MATCH_SUFFIX then
        return string.find(key, anim.keyMatchLiteral, anim.keyMatchOffset, true) ~= nil
    elseif mode == KEY_MATCH_PREFIX then
        return string.find(key, anim.keyMatchLiteral, 1, true) == 1
    elseif mode == KEY_MATCH_CONTAINS then
        return string.find(key, anim.keyMatchLiteral, 1, true) ~= nil
    end
    return true -- KEY_MATCH_ANY
end

-- Mirrors the override start flow: condition, then preTrigger (which may flip enabled or swap
-- groupname), then the actual play.
local function triggerKeyAnimation(anim, key)
    -- Fire once per frame. The same logical key can reach us several times in one engine event
    -- flush, because a state emits every key it crosses -- including those of other groups sharing
    -- its .kf file. Without this each copy would cancel and restart the animation.
    if anim.lastTriggerFrame == frame_n then return end
    anim.lastTriggerFrame = frame_n

    if anim.condition and not anim:condition(key) then return end
    if anim.preTrigger then anim:preTrigger(key) end
    if not anim.enabled then return end
    if not animation.hasGroup(omwself, anim.groupname) then return end

    -- playBlended on a group that is still active only updates its priority and returns, so an
    -- animation left over from a previous trigger would silently never restart. Clear it first.
    if animManager.isPlaying(anim.groupname) then
        animation.cancel(omwself, anim.groupname)
    end

    I.AnimationController.playBlendedAnimation(anim.groupname, anim:options(key))
end

--- Tails -------------------------------
-----------------------------------------
-- A tail is a cosmetic flourish played the moment an attack's follow-through ends. Tails are not
-- registered: whenever any group reaches its "<type> [<strength> ]follow stop" key, we look for a
-- "<type> tail start" / "<type> tail stop" pair in "<group>extra" and play it if both keys exist.
-- That covers variant groups for free - weapontwohandsub finds weapontwohandsubextra.
--
-- Priority is Movement + 1 on the upper body only: the one value strictly above Movement (5) and
-- below Weapon (7), so a tail can never interrupt an attack or touch the legs. It ties with Hit, and
-- the engine breaks per-bone-group ties alphabetically by group name, so "<group>extra" losing to
-- "hit1".."hit5" is what lets a stagger cut a flourish short. LowerBody is left unset, which the
-- engine defaults to PRIORITY.Default; that also keeps the set from ever comparing equal to Hit's,
-- which would make the engine destroy one of the two states.
--
-- Tail groups never have overrides of their own - animations[] is keyed by parent group and nothing
-- is registered under an "...extra" name - so a tail's playBlended passes straight through the
-- override handler. Tail keys are "tail start/stop", which never match "follow stop", so a tail
-- cannot trigger another tail.
local TAIL_FOLLOW_STOP = "follow stop"
local TAIL_FOLLOW_STOP_OFFSET = -#TAIL_FOLLOW_STOP
local TAIL_PRIORITY = animation.PRIORITY.Movement + 1

-- Reused for every tail. Only startKey, stopKey and speed change between plays.
local tailOptions = {
    loops = 0,
    autoDisable = true,
    blendMask = animation.BLEND_MASK.UpperBody,
    blendmask = animation.BLEND_MASK.UpperBody,
    priority = {
        [animation.BONE_GROUP.Torso] = TAIL_PRIORITY,
        [animation.BONE_GROUP.LeftArm] = TAIL_PRIORITY,
        [animation.BONE_GROUP.RightArm] = TAIL_PRIORITY,
    },
}

local tailLastFrame = {} -- [tail group] = frame_n, so duplicate key deliveries play it only once

-- Returns tail group, start key and stop key, or nil. Looked up afresh on every follow-through stop:
-- that is once per attack, and two text key lookups per attack cost nothing worth saving. It used
-- to be cached per group and flushed on armature change, which only holds if the flush always lands
-- between the two models. An answer taken from the 3rd person model after the state had already
-- flipped to 1st person - another mod playing attack groups on the player, right at a view switch -
-- stuck as "no tail" and silenced that group's 1st person tails until the next state change.
local function resolveTail(groupname, attackType)
    local tailGroup = groupname .. "extra"
    local startKey = attackType .. " tail start"
    local stopKey = attackType .. " tail stop"
    local prefix = tailGroup .. ": "
    -- Both keys must exist: playBlended silently plays nothing if either is missing.
    if animation.getTextKeyTime(omwself, prefix .. startKey) and
        animation.getTextKeyTime(omwself, prefix .. stopKey) then
        return tailGroup, startKey, stopKey
    end
end

local function tryPlayTail(groupname, key)
    -- A parent hidden behind a variant keeps running and keeps emitting its follow-through keys;
    -- only the group actually on screen should get a flourish. Variant groups need no such check,
    -- since they only emit keys while they really play.
    if isParentHidden(groupname) then return end

    local sep = string.find(key, " ", 1, true) -- the attack type is the first token
    if not sep then return end

    local tailGroup, startKey, stopKey = resolveTail(groupname, string.sub(key, 1, sep - 1))
    if not tailGroup then return end

    -- The same key can arrive several times in one frame when groups share a .kf and key times.
    if tailLastFrame[tailGroup] == frame_n then return end
    tailLastFrame[tailGroup] = frame_n

    -- playBlended on a still-active group only updates its priority, so a tail left over from the
    -- previous swing would never restart. Clear it first.
    if animManager.isPlaying(tailGroup) then
        animation.cancel(omwself, tailGroup)
    end

    tailOptions.startKey = startKey
    tailOptions.stopKey = stopKey
    tailOptions.startkey = startKey -- engine reads camelCase; lowercase is for other mods
    tailOptions.stopkey = stopKey
    -- Inherit the attack's speed: its state still exists at this point (autoDisable is off).
    tailOptions.speed = animation.getSpeed(omwself, groupname) or 1

    I.AnimationController.playBlendedAnimation(tailGroup, tailOptions)
end

local function onAnimationTextKey(groupname, key)
    -- Tails need no registration, so they are checked ahead of the registry early-out below. One
    -- plain find at a fixed offset per key; only follow-through stops go any further.
    if string.find(key, TAIL_FOLLOW_STOP, TAIL_FOLLOW_STOP_OFFSET, true) then
        tryPlayTail(groupname, key)
    end

    if keyAnims_n == 0 then return end

    -- Keeps stance/armature (and therefore activeKeyAnims) current. Internally gated to run at most
    -- once per frame, so this costs a single integer compare on all but the first key of a frame.
    -- Has to run before the lookup below, since that map is what it rebuilds.
    checkActorStates()

    local anims = activeKeyAnims[groupname]
    if not anims then return end

    for i = 1, #anims do
        local anim = anims[i]
        if matchesKey(anim, key) then triggerKeyAnimation(anim, key) end
    end
end

animManager.addOnKeyHandler(onAnimationTextKey)


--- API Functions -----------------------
--- -------------------------------------
--- It is expected that an override has either a parent anim group assigned or startOnUpdate: true. Otherwise override will never start.
--- Optional anim.onUpdate(self, dt) is called every frame while the override is running, after its stop check.
--- Optional anim.overridePriority (number) ranks it against the other ranked overrides on its parent: a higher one that
--- plays keeps lower ones from starting, and stops them. Leave it nil for an override that layers on top of others.
--- See Override ranking.
local function addAnimationOverride(anim)
    -- print("registering animation"  .. anim.groupname)
    if not anim.stance then anim.stance = gutils.STANCE.Weapon end -- Default value for backwards compatibility
    if anim.enabled == nil then anim.enabled = true end -- Default value for backwards compatibility
    
    if type(anim.parent) == "table" then
        for _, parent in ipairs(anim.parent) do
            local newAnimation = gutils.shallowTableCopy(anim)
            newAnimation.parent = parent
            addToAnimMap(newAnimation)            
        end
    else
        addToAnimMap(anim)        
    end
end

local function removeAnimationOverride(id)
    if not id then return end    
    for key, anims in pairs(animations) do
        for i, anim in ipairs(anims) do
            if anim.id == id then
                table.remove(anims, i)
                return true
            end
        end
    end
    return false
end


-- The engine plays the follow-through last, so its start key is the closest thing to "attack
-- over" that the existing playBlended events give us, without watching text keys.
local FOLLOW_START = "follow start"
local FOLLOW_START_OFFSET = -#FOLLOW_START

-- Picks one group out of an alternation step's interchangeable candidates.
-- stepState is the per-step scratch table: { rr, last, repeats }.
local function pickVariant(step, stepState, subAttackMode, maxRepeats)
    local n = #step
    if n == 1 then return step[1] end

    if subAttackMode == gutils.SUB_ATTACK_MODE.RoundRobin then
        stepState.rr = stepState.rr % n + 1
        return step[stepState.rr]
    end

    local idx = math.random(n)

    -- Refuse a run longer than maxRepeats by walking to the next different candidate. If every
    -- entry names the same group there is nothing to switch to and we simply keep it, so a
    -- single-candidate (or all-identical) step can never spin here.
    if maxRepeats > 0 and stepState.repeats >= maxRepeats and step[idx] == stepState.last then
        for _ = 1, n - 1 do
            idx = idx % n + 1
            if step[idx] ~= stepState.last then break end
        end
    end

    local pick = step[idx]
    if pick == stepState.last then
        stepState.repeats = stepState.repeats + 1
    else
        stepState.repeats = 1
    end
    stepState.last = pick

    return pick
end


--[[
Registers per-attack-type variants of a weapon's attack animation.

params:
{
    parentAttackGroupname = "weapontwohand",
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    stance = I.ReAnimation.STANCE.Weapon,   -- optional, defaults to Weapon
    subAttackMode = I.ReAnimation.SUB_ATTACK_MODE.Random,  -- optional, defaults to Random
    timingMatching = I.ReAnimation.TIMING_MATCHING.None,   -- optional, defaults to None
    randomMaxRepeats = 3,                   -- optional, defaults to 3
    sequenceResetTime = 3,                  -- optional, seconds, defaults to 3
    condition = function(self) ... end,     -- optional, truthy for this set to apply at all
    overridePriority = 0,                   -- optional, defaults to 0
    attacks = {
        chop   = { { "weapontwohand", "weapontwohandsub" }, { "weapontwohandalt" } },
        slash  = { { "weapontwohand" }, { "weapontwohandalt" } },
        thrust = { { "weapontwohand" }, { "weapontwohandalt" } },
    },
}

Each attack type maps to two nested lists:

  * The outer list alternates. Attack n of that type uses step (n % #steps), so one step means no
    alternation at all and two steps give the classic A/B swing.
  * The inner list holds interchangeable variants, one picked per attack according to
    `subAttackMode`:
      - SUB_ATTACK_MODE.Random (default) picks uniformly at random. `randomMaxRepeats` caps how many
        times in a row the same variant may come up, so with the default of 3 a fourth identical
        roll is swapped for a different candidate. Set it to 0 to allow unlimited runs. A step with
        a single candidate is unaffected.
      - SUB_ATTACK_MODE.RoundRobin cycles through the candidates in declaration order instead.
    Each alternation step keeps its own picker state, so a step is only ever compared against its
    own history.

`sequenceResetTime` restarts the alternation at its first step when that attack type has not been
used for that many seconds, so a fight opens on the base attack rather than halfway through the
cycle. It is measured from the end of the previous attack of that type - strictly, from the start of
its follow-through - so it counts idle time rather than idle time plus the swing itself. Simulation
time, so time spent paused does not count.
  * A candidate equal to parentAttackGroupname means "don't override" - the engine's own animation
    plays as normal. That is how a variant set can include the vanilla animation as one option.

An attack type missing from `attacks` is left completely alone.

`condition` gates the whole set, so several sets can share one parent group and be selected by
weapon, stance or anything else - see getEquippedWeapon()/isEquippedWeapon(). Two sets on one parent
must never be active together: both would hide the parent and uniquify its priority, and the
engine's equal-priority rule then erases one of them. `overridePriority` takes care of that. Give
the more specific set a higher one and a condition, and while that condition holds - for an attack
type it lists - every lower set on the parent stands down, so the general set needs no condition at
all. Attack sets are always ranked, at 0 unless given a priority, so a set another mod registers at
1 or above outranks ReAnimation's own without either knowing about the other. Sets of equal priority
still need mutually exclusive conditions. See Override ranking.

Every variant group's textkey timings must match the parent's exactly, for the same reason as the
old alternating attacks: the variant plays on top while the hidden parent's keys continue to drive
the engine's hit timing and attack state machine.

`timingMatching` is the way out of that when they cannot:

  - TIMING_MATCHING.None (default) - the above. The variants are authored on the parent's times.
  - TIMING_MATCHING.ToOverride - the parent is re-timed to the variant instead. Each section the
    engine plays has the parent's speed scaled by (parent section length / variant section length),
    so the section takes exactly as long as the variant's own, at the speed the engine asked for.
    The variant keeps its authored pace, and the parent's section keys - "max attack", "hit" and
    the follow-through ends, still the ones the engine acts on - land on the variant's own.

    That makes animations built for another weapon usable as they are: a set cut from the
    hand-to-hand animations can be registered over `weapononehand` without being re-timed to it.
    Both groups must carry the same key *names*; only their times may differ. Nothing is measured
    per frame - the four key lookups happen once per section.
]]
local attackVariantsRegistrations = 0

--- Timing matching --------------------
-----------------------------------------
-- Normally a variant has to be authored on the parent's key times, because the parent keeps playing
-- underneath and its keys are what the engine hits on. TIMING_MATCHING.ToOverride turns that around:
-- the variant keeps its own times and the parent is stretched or squeezed to fit, one section at a
-- time.
--
-- The engine plays an attack as three sections, each its own playBlended with a start and stop key
-- ("slash start" -> "slash max attack", "slash max attack" -> "slash hit", "slash large follow
-- start" -> "slash large follow stop"). Both groups carry the same key names at different times, so
-- for each section:
--
--     wanted wall time = override section length / requested speed
--     parent speed     = parent section length / wanted wall time
--                      = requested speed * parent section / override section
--
-- The override then plays at the speed the engine asked for - the weapon's own speed multiplier -
-- and every section boundary key of the parent lands on the override's own. Keys inside a section
-- are stretched with it, so they keep the parent's proportions rather than moving to the override's
-- times: "min attack", where the engine starts counting the wind up's strength, and "min hit", which
-- decides how much of the release a weak attack skips (character.cpp calculateWindUp, and the
-- AttackRelease branch). startPoint needs no adjustment: it is a fraction of the section, so it
-- means the same thing in both.
--
-- Two text key lookups per group per section, so four per section and twelve per attack. Nothing
-- per frame.
local function retimeParentToOverride(parent, groupname, pOptions)
    local startKey = pOptions.startKey or pOptions.startkey
    local stopKey = pOptions.stopKey or pOptions.stopkey
    if not startKey or not stopKey then return end

    local parentStart = animation.getTextKeyTime(omwself, parent .. ": " .. startKey)
    local parentStop = animation.getTextKeyTime(omwself, parent .. ": " .. stopKey)
    local overrideStart = animation.getTextKeyTime(omwself, groupname .. ": " .. startKey)
    local overrideStop = animation.getTextKeyTime(omwself, groupname .. ": " .. stopKey)
    if not (parentStart and parentStop and overrideStart and overrideStop) then return end

    local parentLength = parentStop - parentStart
    local overrideLength = overrideStop - overrideStart
    -- A zero-length section (some follow-through sections are a single instant) has no timing to
    -- match, and a negative one means the keys were resolved out of order - leave the speed alone.
    if parentLength <= 0 or overrideLength <= 0 then return end

    pOptions.speed = (pOptions.speed or 1) * (parentLength / overrideLength)
end

local function addAttackVariants(params)
    if not params.parentAttackGroupname or not params.attacks then
        error("addAttackVariants(): parentAttackGroupname or attacks were not found in params object.")
        return
    end

    local parent = params.parentAttackGroupname
    local timingMatching = params.timingMatching or gutils.TIMING_MATCHING.None
    if timingMatching ~= gutils.TIMING_MATCHING.None and timingMatching ~= gutils.TIMING_MATCHING.ToOverride then
        error("addAttackVariants(): unknown timing matching mode '" .. tostring(timingMatching) .. "'.")
        return
    end

    local subAttackMode = params.subAttackMode or gutils.SUB_ATTACK_MODE.Random
    if subAttackMode ~= gutils.SUB_ATTACK_MODE.Random and subAttackMode ~= gutils.SUB_ATTACK_MODE.RoundRobin then
        error("addAttackVariants(): unknown sub attack mode '" .. tostring(subAttackMode) .. "'.")
        return
    end

    -- Scratch state for the picker, one entry per alternation step of every attack type.
    local stepStates = {}
    for attackType, steps in pairs(params.attacks) do
        local states = {}
        for i = 1, #steps do states[i] = { rr = 0, last = nil, repeats = 0 } end
        stepStates[attackType] = states
    end

    -- Initial groupname. It must never be the parent, since the override handler cancels
    -- anim.groupname unconditionally and that would kill the engine's own attack animation.
    -- ATTACK_TYPES rather than pairs() so the choice is deterministic between runs.
    local firstGroup = nil
    for _, attackType in ipairs(ATTACK_TYPES) do
        local steps = params.attacks[attackType]
        if steps then
            for _, step in ipairs(steps) do
                for _, groupname in ipairs(step) do
                    if groupname ~= parent then
                        firstGroup = firstGroup or groupname
                    end
                end
            end
        end
    end

    if not firstGroup then
        error("addAttackVariants(): attacks contained no groups other than " .. parent .. ".")
        return
    end

    local override = {
        -- Counter in the default id: several sets can share one parent, gated by different
        -- conditions, and they must stay individually removable.
        id = params.id or ("AttackVariants_" .. parent .. "_" .. attackVariantsRegistrations),
        parent = parent,
        groupname = firstGroup,
        armatureType = params.armatureType,
        stance = params.stance,
        enabled = false,
        -- Marks that options() hides the parent (blendMask 0). The parent keeps running and keeps
        -- emitting its text keys while hidden, so anything key-triggered off it needs to know.
        -- See isParentHidden().
        hidesParent = true,
        variants = params.attacks,
        userCondition = params.condition,
        counters = {},
        stepStates = stepStates,
        lastAttackEndTime = {},
        subAttackMode = subAttackMode,
        timingMatching = timingMatching,
        -- Attack sets on one parent are always alternatives to each other, so they are always ranked.
        overridePriority = params.overridePriority or 0,
        randomMaxRepeats = params.randomMaxRepeats or 3,
        sequenceResetTime = params.sequenceResetTime or 3,
        preOverride = function(self, pOptions)
            local startKey = pOptions.startkey or pOptions.startKey
            if startKey == nil then return end

            -- Only re-pick on the wind up. The release and follow through sections must keep
            -- playing whatever this attack already chose.
            local attackType = gutils.isAttackTypeStart(startKey)
            if not attackType then
                -- Not the wind up, so the pick stays as it is. The follow-through section is the
                -- last one played, so use it to timestamp the end of this attack for the reset
                -- timer. Doing it here rather than on the wind up means the timer measures idle
                -- time instead of idle time plus the attack's own duration.
                if string.find(startKey, FOLLOW_START, FOLLOW_START_OFFSET, true) then
                    local endedType = gutils.isAttackType(startKey)
                    if endedType then self.lastAttackEndTime[endedType] = core.getSimulationTime() end
                end
                return
            end

            local steps = self.variants[attackType]
            if not steps then
                self.enabled = false
                return
            end

            -- Restart the sequence at its first step when this attack type has been idle a while,
            -- so a fight always opens on the base attack rather than mid-alternation. Measured from
            -- the end of the previous attack of this type, in simulation time so a paused menu does
            -- not count. An attack interrupted before its follow-through leaves the older stamp in
            -- place, which simply makes a reset more likely.
            local lastEnd = self.lastAttackEndTime[attackType]

            local n = 0
            if lastEnd and (core.getSimulationTime() - lastEnd) <= self.sequenceResetTime then
                n = (self.counters[attackType] or -1) + 1
            end
            self.counters[attackType] = n

            local stepIndex = (n % #steps) + 1
            local pick = pickVariant(steps[stepIndex], self.stepStates[attackType][stepIndex],
                self.subAttackMode, self.randomMaxRepeats)

            -- Registering a variant is taken as a promise that its animation exists.
            local isVanilla = pick == self.parent

            self.enabled = not isVanilla

            if not isVanilla and pick ~= self.groupname then
                -- Only ever one variant is live at a time, and groupname points at it. The handler
                -- cancels groupname for us, but only after this ran, so it would clear the group we
                -- are switching *to* and orphan the one we are switching away from. Retire it here.
                if animManager.isPlaying(self.groupname) then
                    animation.cancel(omwself, self.groupname)
                end
                self.groupname = pick
            end
        end,
        condition = function(self)
            local startKey = self.parentOptions.startkey or self.parentOptions.startKey
            if startKey == nil then return false end -- A User reported an error there, with startKey being nil. No idea why, but heres a crappy fix anyway.
            local attackType = gutils.isAttackType(startKey)
            -- Unconfigured attack types bail out here, so they never reach the per-section cancel.
            if not attackType or self.variants[attackType] == nil then return false end

            -- Caller supplied gate, e.g. "only while a katana is equipped". enabled is cleared
            -- rather than just returning, because preOverride will not run to clear it and
            -- isParentHidden() reads it - a stale true would wrongly suppress the parent's tail.
            if self.userCondition and not self:userCondition() then
                self.enabled = false
                return false
            end

            return true
        end,
        options = function(self, pOptions)
            -- The clone is taken first, so the override keeps the speed the engine asked for while
            -- the parent below gets re-timed to it.
            local opts = gutils.cloneAnimOptions(pOptions)

            -- Since the engine never runs 2 animations with exact same priorities - it's important to make parent animation priority unique to ensure that it will remain running in the background.
            -- Running original animations in the background is important to keep internal engine's character controller satisfied.
            gutils.uniquifyPriority(pOptions)

            pOptions.blendMask = 0
            pOptions.blendmask = 0

            if self.timingMatching == gutils.TIMING_MATCHING.ToOverride then
                retimeParentToOverride(self.parent, self.groupname, pOptions)
            end

            return opts
        end,
        startOnAnimEvent = true
    }
    attackVariantsRegistrations = attackVariantsRegistrations + 1
    addAnimationOverride(override)
end


--[[
params example:
{
    parentGroupname = "weapononehand",
    overrideGroupname = "weapononehand1",
    armatureType = I.ReAnimation.ARMATURE_TYPE.ThirdPerson,
}
]]

-- This will result in parentAttackGroupname and altAttackGroupname being used one after another.
-- altAttackGroupname textkey timings should match parent textkey timings exactly.
-- Kept as a thin wrapper over addAttackVariants: one alternating pair, for every attack type.
local function addAltAttackAnimations(params)
    if not params.parentAttackGroupname or not params.altAttackGroupname then
        error("addAltAttackAnimation(): parentAttackGroupname or altAttackGroupname were not found in params object.")
        return
    end

    local attacks = {}
    for _, attackType in ipairs(ATTACK_TYPES) do
        attacks[attackType] = { { params.parentAttackGroupname }, { params.altAttackGroupname } }
    end

    addAttackVariants({
        id = "AltAttack", -- preserved so removeAnimationOverride("AltAttack") keeps working
        parentAttackGroupname = params.parentAttackGroupname,
        armatureType = params.armatureType,
        stance = params.stance,
        overridePriority = params.overridePriority,
        attacks = attacks
    })
end


--[[
Registers a fire-and-forget animation that starts when a text key fires on its parent group.

anim:
{
    id           = "myTrigger",          -- optional, for removeKeyTriggeredAnimation
    parent       = "weapontwohand",      -- group whose text keys to listen to; may be an array
    key          = "*follow stop",       -- key to match, with optional leading/trailing "*"
    groupname    = "weapontwohandextra", -- group to play
    armatureType = I.ReAnimation.ARMATURE_TYPE.FirstPerson,
    stance       = I.ReAnimation.STANCE.Weapon,  -- optional, defaults to Weapon
    enabled      = true,                         -- optional, defaults to true
    condition    = function(self, key) ... end,  -- optional, truthy to proceed
    preTrigger   = function(self, key) ... end,  -- optional, may change self.groupname / self.enabled
    options      = function(self, key) ... end,  -- required, returns the playBlended options
}

`key` matching is compiled once at registration:

    "chop hit"      exact
    "*follow stop"  suffix
    "chop*"         prefix
    "*follow*"      contains
    "*"             everything

Note that text keys arrive without their "groupname: " prefix, and lowercased.

Unlike overrides these are never tracked after starting: the engine disposes of them itself, so
they cost nothing per frame. Give them `autoDisable = true` in `options` unless you intend to clean
up manually.
]]
local function addKeyTriggeredAnimation(anim)
    if not anim.parent or not anim.key or not anim.groupname then
        error("addKeyTriggeredAnimation(): parent, key and groupname are all required.")
        return
    end

    if not anim.stance then anim.stance = gutils.STANCE.Weapon end
    if not anim.armatureType then anim.armatureType = gutils.ARMATURE_TYPE.Any end
    if anim.enabled == nil then anim.enabled = true end

    local parents = anim.parent
    if type(parents) ~= "table" then parents = { parents } end

    for _, parent in ipairs(parents) do
        local entry = anim
        if #parents > 1 then
            entry = gutils.shallowTableCopy(anim)
            entry.parent = parent
        end
        compileKeyMatcher(entry)

        local anims = keyAnims[parent]
        if not anims then
            anims = {}
            keyAnims[parent] = anims
        end
        anims[#anims + 1] = entry
        keyAnims_n = keyAnims_n + 1
    end

    rebuildActiveKeyAnims()
end

local function removeKeyTriggeredAnimation(id)
    if not id then return false end
    local removed = false
    for _, anims in pairs(keyAnims) do
        for i = #anims, 1, -1 do
            if anims[i].id == id then
                table.remove(anims, i)
                keyAnims_n = keyAnims_n - 1
                removed = true
            end
        end
    end
    if removed then rebuildActiveKeyAnims() end
    return removed
end





--- Core Override handling--------------------------
--- ------------------------------------------------

I.AnimationController.addPlayBlendedAnimationHandler(function(groupname, options)
    if not next(animations) then return end

    -- This will update actor's stance, armature type and rebuild a list of animations that should be tracked
    checkActorStates()

    -- print("Animation started", groupname, startKey, stopKey)
    -- Update stance and armature statuses here! If they changed - run onActorStateChanged

    local anims = animations[groupname]
    if not anims then return end  

    local startKey = options.startkey or options.startKey
    local stopKey = options.stopkey or options.stopKey

    -- print("Found " .. #anims .. " override(s) for " .. groupname)

    -- Starting override anims. Ranked ones come highest first, and the first to pass takes this play:
    -- lower-ranked ones after it are not asked (see Override ranking).
    local claimedRank = nil
    for _, anim in ipairs(anims) do  
        anim.parentOptions = gutils.cloneAnimOptions(options)
        local rank = anim.overridePriority

        -- print("Anim starts on anim event: " .. tostring(anim.startOnAnimEvent) .. ", proper armature type: " .. tostring(isProperArmatureType(anim)) .. ", proper stance: " .. tostring(isProperStance(anim)))
        if claimedRank and rank and rank < claimedRank then
            -- Outranked for this play. isParentHidden() reads enabled, and a stale true would
            -- suppress the parent's tail. A running one is stopped by onUpdate.
            if anim.hidesParent then anim.enabled = false end
        elseif anim.startOnAnimEvent and animation.hasGroup(omwself, anim.groupname) and isProperArmatureType(anim) and isProperStance(anim) then
            local shouldStart = anim:condition()
            if shouldStart then
                -- Taken even when it ends up playing nothing of its own: an attack set that picked
                -- the vanilla animation still owns this attack.
                if rank then claimedRank = rank end
                -- End this override's groupname and run pre-override pass. 
                -- Reminder: pre-override pass is there to allow for dynamic anim.groupname changes, i.e
                -- it should be supported for anim.preOverride to change its own anim.groupname.  
                --print("Should start " .. anim.groupname, "startKey: " .. tostring(startKey) .. ", stopKey: " .. tostring(stopKey), "enabled: " .. tostring(anim.enabled), "running: " .. tostring(anim.running))        
                if anim.preOverride then anim:preOverride(options) end
                --print("After preover check - enabled: " .. tostring(anim.enabled), "running: " .. tostring(anim.running))        

                -- This is necessary for alt attacks to work
                local wasRunning = false
                if anim.running then
                    animation.cancel(omwself, anim.groupname)
                    anim.running = false
                    wasRunning = true -- Dirty fix for animation not being removed from the tracked list here leading to accumulation for perpetually running anims.
                end

                -- Play the override!   
                if anim.enabled and not anim.running then
                    --print("Overriding " .. anim.parent .. " with " .. anim.groupname, "startKey: " .. tostring(startKey) .. ", stopKey: " .. tostring(stopKey))
                    I.AnimationController.playBlendedAnimation(anim.groupname, anim:options(options)) 
                    anim.running = true
                    if not wasRunning then addToTrackedAnimsList(anim) end
                end
            end
        end
    end
end)



local function onUpdate(dt)
    if not trackedAnims_n or dt <= 0 then return end
    --print("onUpdate called. dt: " .. tostring(dt) .. ", trackedAnims_n: " .. tostring(trackedAnims_n))
    
    frame_n = frame_n + 1    
    if trackedAnims_n <= 0 then return end   

    for i = trackedAnims_n, 1, -1 do
        local anim = trackedAnims[i]
        --print(anim.groupname .. " is being checked for update. Running: " .. tostring(anim.running))
        
        local isParentPlaying = nil
        local isPlaying = nil
        local shouldStart = nil
        local shouldStop = nil

        -- Should we stop an already running animation?
        if anim.running then
            isPlaying = animManager.isPlaying(anim.groupname)
            if anim.parent then isParentPlaying = animManager.isPlaying(anim.parent) end

            -- print("Is anim " .. anim.groupname .. " playing: " .. tostring(isPlaying) .. ", is parent " .. tostring(anim.parent) .. " playing: " .. tostring(isParentPlaying))

            if not isPlaying then anim.running = false end

            -- An outranked one stops without its stopCondition being asked (see Override ranking).
            shouldStop = isPlaying and ((anim.overridePriority and isOutranked(anim)) or
                (anim.stopCondition and anim:stopCondition()) or (anim.parent and not isParentPlaying))
        end

        -- Should we start a non-running tracked animation?
        if anim.startOnUpdate and not anim.running then
            if anim.parent and isParentPlaying == nil then isParentPlaying = animManager.isPlaying(anim.parent) end

            --print("Checking " .. anim.groupname .. " start conditions on update. Parent: " .. tostring(anim.parent) .. ", isParentPlaying: " .. tostring(isParentPlaying) .. ", condition: " .. tostring(anim:condition()) .. ", hasGroup: " .. tostring(animation.hasGroup(omwself, anim.groupname)))
            -- A ranked one is not asked while a higher one on its parent runs (see Override ranking).
            shouldStart = (not anim.parent or isParentPlaying) and not (anim.overridePriority and isOutranked(anim)) and
                anim:condition() and animation.hasGroup(omwself, anim.groupname)
        end

        -- Starting and stopping animations
        if shouldStart then
            --print("Starting " .. anim.groupname .. " on update")
            I.AnimationController.playBlendedAnimation(anim.groupname, anim:options())
            anim.running = true
        end
        if shouldStop then
            --print("Stopping " .. anim.groupname .. " on update")
            animation.cancel(omwself, anim.groupname)
            anim.running = false            
        end

        -- Per-frame hook for overrides that follow something while they play. After the start/stop
        -- handling, so a start this frame gets its first call right away and a stop gets none.
        -- Hooks must not start or stop overrides: that goes through the playBlended handler, which
        -- can append to or rebuild trackedAnims in the middle of this loop.
        if anim.running and anim.onUpdate then
            anim:onUpdate(dt)
        end

        -- Cleanup. Non-running animations are removed from the tracked list (purely for optimization)
        if not anim.running then
            removeFromTrackedAnimsList(i)
        end        
    end
end

return {
    interfaceName = "ReAnimation",
    interface = {
        version = 3.2,
        ARMATURE_TYPE = gutils.ARMATURE_TYPE,
        STANCE = gutils.STANCE,
        SUB_ATTACK_MODE = gutils.SUB_ATTACK_MODE,
        TIMING_MATCHING = gutils.TIMING_MATCHING,
        addAnimationOverride = addAnimationOverride,        
        addAltAttackAnimations = addAltAttackAnimations,
        addAttackVariants = addAttackVariants,
        getEquippedItem = getEquippedItem,
        getEquippedItemId = getEquippedItemId,
        getEquippedWeapon = getEquippedWeapon,
        getEquippedWeaponId = getEquippedWeaponId,
        isEquippedWeapon = isEquippedWeapon,
        setEquipmentCacheTime = setEquipmentCacheTime,
        addKeyTriggeredAnimation = addKeyTriggeredAnimation,
        removeAnimationOverride = removeAnimationOverride,
        removeKeyTriggeredAnimation = removeKeyTriggeredAnimation,
        animations = animations,
        gutils = gutils,
        -- Clears the isPlaying mirror. From the console: luap, then
        -- I.ReAnimation.resetPlayingState()
        resetPlayingState = animManager.resetPlayingState,
        state = state,
    },
    engineHandlers = {
        onUpdate = onUpdate,
    }
}
