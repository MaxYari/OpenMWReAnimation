local mp = "scripts/MaxYari/ReAnimation_v2/"

local I = require('openmw.interfaces')
local animation = require('openmw.animation')
local omwself = require('openmw.self')

local EventsManager = require(mp .. "scripts/events_manager")

local events = EventsManager:new()

local function addOnKeyHandler(cb)
    events:addEventHandler(cb)
end

local function removeOnKeyHandler(cb)
    events:removeEventHandler(cb)
end

local Animation = {}

function Animation:play(groupname, opts)
    local anim = {
        groupname = groupname,
        opts = opts
    }

    I.AnimationController.playBlendedAnimation(anim.groupname, anim.opts)

    setmetatable(anim, self)
    self.__index = self

    return anim
end

function Animation:cancel()
    animation.cancel(omwself, self.groupname)
end

--- Playing-state tracking -----------------------------------------------------------------------
-- The engine keeps an animation "state" per group. isPlaying() below means "a state exists", which
-- is broader than animation.isPlaying(): a group played with autoDisable = false keeps its state
-- after reaching its stop key. Asking the engine costs a C++ crossing per query, and the override
-- update loop makes ~30 of them per frame, so we also maintain a Lua-side mirror.
--
-- The mirror is fed by the two events the engine exposes:
--   * playBlended handler  - a state is created
--   * animationEnded       - a state is erased (disable, equal-priority eviction, auto-disable)
--
-- It cannot be complete. Verified blind spots in OpenMW 0.51:
--   1. playQueued (any Lua) and mwscript PlayGroup/LoopGroup take a direct mAnimation->play path
--      (character.cpp:1952), because playGroupLua always sets mScripted = true.
--   2. openmw.animation.playBlended called directly bypasses this handler - our handler only runs
--      because I.AnimationController.playBlendedAnimation invokes it in Lua first.
--   3. clearAnimSources() clears every state with no event at all (animation.cpp:778), on model
--      rebuilds such as the first/third person switch. Call resetPlayingState() there.
--   4. Anything played before the AnimationController enables Lua animations on its first update.
--   5. The handler runs BEFORE the play, so a play the engine then rejects still marks the group as
--      playing here. reset() returns false and creates no state when a start or stop key is missing
--      (animation.cpp:983-1009), which is exactly what happens for a group whose animation has not
--      been authored yet. This one over-reports rather than under-reports.
--
-- Debug switch: set VERIFY_PLAYING_STATE to true to run both paths and print a warning whenever a
-- remembered answer turns out wrong. Off, isPlaying answers from the cache and asks the engine only
-- on a miss.
local VERIFY_PLAYING_STATE = false

-- nil = unknown, ask the engine and remember. true/false = a remembered answer.
local playingStates = {}

-- Every event that touches a group only INVALIDATES its cached answer, it never asserts a new one.
-- Asserting is not possible here: playAnimation is delivered synchronously while animationEnded is
-- queued (luamanagerimp.cpp:544 vs :552), so when the engine disables and replays a group - which
-- it does for every attack section, character.cpp:1784 and :1808 - the "ended" for the previous
-- section arrives AFTER the "play" for the next one and would wipe a correct entry. Invalidating is
-- order-independent: whichever event lands last, the next query just asks the engine again.
local function invalidatePlayingState(groupname)
    playingStates[groupname] = nil
end

I.AnimationController.addPlayBlendedAnimationHandler(function(groupname)
    invalidatePlayingState(groupname)
end)

I.AnimationController.addAnimationEndedHandler(function(groupname)
    invalidatePlayingState(groupname)
end)

-- Drops every cached answer. Needed when the engine may have discarded states without telling us,
-- i.e. on a model rebuild / armature change (clearAnimSources, animation.cpp:778).
local function resetPlayingState()
    playingStates = {}
end

-- True while the engine holds a state for this group. Prefer this over animation.getCurrentTime
-- wherever only the playing state is wanted; use getCurrentTime directly when the time matters.
local function isPlaying(groupname)
    local cached = playingStates[groupname]

    if VERIFY_PLAYING_STATE then
        local time = animation.getCurrentTime(omwself, groupname)
        local engineSays = time ~= nil and time >= 0
        -- Only a remembered answer can be wrong; a cache miss is not a mismatch.
        if cached ~= nil and cached ~= engineSays then
            -- Unthrottled on purpose: one line per occurrence is what separates a single frame's
            -- flicker from a disagreement that persists.
            print(("[ReAnimation] isPlaying MISMATCH for '%s': engine=%s cached=%s")
                :format(groupname, tostring(engineSays), tostring(cached)))
        end
        playingStates[groupname] = engineSays
        return engineSays
    end

    if cached == nil then
        local time = animation.getCurrentTime(omwself, groupname)
        cached = time ~= nil and time >= 0
        playingStates[groupname] = cached
    end

    return cached
end



function Animation:isPlaying()
    return isPlaying(self.groupname)
end

function Animation:addOnKeyHandler(cb)
    self.eventHandler = function(groupname, key)
        if groupname == self.groupname then
            cb(groupname, key)
        end
    end
    addOnKeyHandler(self.eventHandler)
end

function Animation:removeOnKeyHandler()
    if not self.eventHandler then return end
    removeOnKeyHandler(self.eventHandler)
end

I.AnimationController.addTextKeyHandler(nil, function(...)
    events:emit(...)
end)

local module = {
    Animation = Animation,
    isPlaying = isPlaying,
    addOnKeyHandler = addOnKeyHandler,
    removeOnKeyHandler = removeOnKeyHandler,
    resetPlayingState = resetPlayingState
}

return module
