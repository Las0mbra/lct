-- FTC-GUID: 27de4f,84c3a4

-- This script highlights objects in green when they are selected by a player.
local selectedObjects = {}
local externalHolds = {}   -- guids another script owns; we won't touch their highlight
local checkInterval = 0.25
local checkWaitId = nil
local activeHighlighterGuid = "27de4f"

function onLoad()
    if self.getGUID() ~= activeHighlighterGuid then
        self.interactable = false
        return
    end

    Wait.frames(function()
        self.interactable = false
    end, 30)

    checkWaitId = Wait.time(checkSelections, checkInterval, -1)
end

local colorMapping = {
    Red = {1, 0, 0},
    Blue = {0, 0, 1},
    Green = {0, 1, 0},
    Yellow = {1, 1, 0},
    Purple = {0.5, 0, 0.5},
    Orange = {1, 0.5, 0},
    White = {1, 1, 1},
    Black = {0, 0, 0}
}

function getHighlightColorForPlayer(playerColor)
    return colorMapping[playerColor] or {0.5, 0.5, 0.5}
end

function onDestroy()
    if checkWaitId then
        Wait.stop(checkWaitId)
        checkWaitId = nil
    end
    clearAllHighlights()
end

-- Public API for other scripts (e.g. the coherency / engagement monitors) to
-- take exclusive ownership of a model's highlight. While held, this highlighter
-- ignores the model entirely -- it won't snapshot, recolour, or restore it -- so
-- the owning script's glow can't be captured as an "original" and re-applied on
-- deselect. The owner must releaseHighlight when it's done.
function holdHighlight(params)
    local guid = params.guid
    externalHolds[guid] = true
    selectedObjects[guid] = nil   -- stop tracking it as a selection highlight
end

function releaseHighlight(params)
    externalHolds[params.guid] = nil
end

-- Public API for the Highlight painter (customDiceTable). A paint applied while
-- a model is selected would normally be wiped on deselect (we restore the
-- pre-selection snapshot); this points the tracked snapshot at the paint colour
-- instead, so deselecting restores the paint. No-op if the model isn't tracked
-- yet -- the next checkSelections tick snapshots the already-applied paint as
-- the original, which achieves the same thing.
function setPersistentHighlight(params)
    local e = selectedObjects[params.guid]
    if e ~= nil then e.originalColor = params.color end
end

-- Forget every tracked selection snapshot. The painter's clear-all calls this
-- right before highlightOff-ing the table, so the next tick re-tracks whatever
-- is selected with clean (nil) snapshots and re-applies the selection glow.
function clearPersistentHighlights()
    selectedObjects = {}
end

-- Guids currently owned by other scripts (live monitors). The painter's
-- clear-all skips these so it doesn't fight a running monitor's glow.
function getExternalHolds()
    local t = {}
    for guid in pairs(externalHolds) do t[guid] = true end
    return t
end

function checkSelections()
    local currentSelections = {}

    for _, player in ipairs(Player.getPlayers()) do
        local selected = player.getSelectedObjects() or {}
        local playerColor = player.color
        local highlightColor = getHighlightColorForPlayer(playerColor) -- Get color based on player

        for _, obj in ipairs(selected) do
            local guid = obj.getGUID()

            if (obj.tag == "Figurine" or obj.tag == "Generic" or obj.tag == "Custom_Model") and not selectedObjects[guid] and not externalHolds[guid] then
                selectedObjects[guid] = {
                    object = obj,
                    originalColor = obj.getHighlightColor()
                }
                obj.highlightOn(highlightColor) -- Highlight in player's color
            end

            currentSelections[guid] = true
        end
    end

    for guid, data in pairs(selectedObjects) do
        if not currentSelections[guid] then
            local obj = data.object
            if obj then
                if data.originalColor then
                    obj.highlightOn(data.originalColor)
                else
                    obj.highlightOff()
                end
            end
            selectedObjects[guid] = nil
        end
    end
end



function clearAllHighlights()
    for guid, data in pairs(selectedObjects) do
        local obj = data.object
        if obj then
            -- If it had an original color, restore it
            if data.originalColor then
                obj.highlightOn(data.originalColor)
            else
                obj.highlightOff()
            end
        end
    end
    selectedObjects = {}
end
