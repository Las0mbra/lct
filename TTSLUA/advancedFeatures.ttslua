-- FTC-GUID: ed17d0
-- World-space XML panel for optional table features. Runtime state and terrain
-- collider behavior remain owned by startMenu (738804); this object is only the
-- presentation layer and forwards button presses to that controller.

START_MENU_GUID = "738804"

-- Match the dark floating-panel styling used by mapFilter (369707). The anchor
-- block sits at y=0; a -95 UI Z offset lifts this face-up panel to about y=0.95.
UI_VERTICAL_LIFT = -95
PANEL_SCALE = 1.25
PANEL_WIDTH = 660
PANEL_HEIGHT = 250
PANEL_PADDING = 14
PANEL_SPACING = 10

COLOR_ON = "#38C172"
COLOR_OFF = "#6B7280"
BUTTON_ID = "terrainCollidersToggle"

function startMenuObj()
    return getObjectFromGUID(START_MENU_GUID)
end

function terrainCollidersDisabled()
    local startMenu = startMenuObj()
    if not startMenu then return false end
    local ok, enabled = pcall(function()
        return startMenu.call("terrainPassThroughIsEnabled")
    end)
    return ok and enabled == true
end

function buildAdvancedFeaturesUI()
    local enabled = terrainCollidersDisabled()
    local status = enabled and "ON" or "OFF"
    local buttonColor = enabled and COLOR_ON or COLOR_OFF
    local xml = string.format([[
<VerticalLayout position="0 0 %d" rotation="0 0 0" scale="%s %s 1"
    width="%d" height="%d" padding="%d %d %d %d" spacing="%d"
    color="#101015E6" childForceExpandHeight="false">
    <Text fontSize="44" color="#FFFFFF" preferredHeight="70">Advanced Features</Text>
    <Panel preferredHeight="4" color="#FFFFFF40" flexibleHeight="0" />
    <Button id="%s" onClick="onTerrainCollidersToggle" color="%s"
        textColor="#FFFFFF" fontSize="32" preferredHeight="115" flexibleHeight="0">Disable Terrain Colliders: %s</Button>
</VerticalLayout>
]], UI_VERTICAL_LIFT, PANEL_SCALE, PANEL_SCALE,
        PANEL_WIDTH, PANEL_HEIGHT,
        PANEL_PADDING, PANEL_PADDING, PANEL_PADDING, PANEL_PADDING, PANEL_SPACING,
        BUTTON_ID, buttonColor, status)
    self.UI.setXml(xml)
end

-- Public refresh hook called by startMenu after toggling or restoring state.
function syncAdvancedFeaturesUI()
    buildAdvancedFeaturesUI()
end

function onLoad()
    self.setLock(true)
    self.tooltip = false
    -- Object load order is not deterministic. Paint once after all objects have
    -- registered, then retry after a second so a restored ON state cannot leave
    -- the panel showing its OFF fallback.
    Wait.frames(syncAdvancedFeaturesUI, 2)
    Wait.time(syncAdvancedFeaturesUI, 1)
end

function onTerrainCollidersToggle(player, value, id)
    local startMenu = startMenuObj()
    if not startMenu then
        broadcastToAll("Advanced Features could not find the start-menu controller.", {1, 0.25, 0.25})
        return
    end

    local ok = pcall(function()
        startMenu.call("toggleTerrainPassThrough")
    end)
    if not ok then
        broadcastToAll("Advanced Features could not toggle terrain colliders.", {1, 0.25, 0.25})
        return
    end
    Wait.frames(syncAdvancedFeaturesUI, 1)
end
