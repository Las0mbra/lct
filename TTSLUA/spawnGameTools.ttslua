-- FTC-GUID: a76485

local Ypos = 6
local Xoffset = -70
local XposHideArmy = 115.2
local ZposHideArmy = 40.25
local hideShowArmyBtnLbl = "ARMY\nfor reserves/embarked"

local hideArmyBtnR = {
    label="HIDE "..hideShowArmyBtnLbl, click_function="hideArmyR", function_owner=self,
    position={XposHideArmy,Ypos,ZposHideArmy}, rotation={0,0,0},
    height=500, width=2400, font_size=200, color="Red", font_color={1,1,1}
}
local hideArmyBtnB = {
    label="HIDE "..hideShowArmyBtnLbl, click_function="hideArmyB", function_owner=self,
    position={XposHideArmy+Xoffset,Ypos,-ZposHideArmy}, rotation={0,180,0},
    height=500, width=2400, font_size=200, color="Red", font_color={1,1,1}
}
local showArmyBtnR = {
    label="SHOW "..hideShowArmyBtnLbl, click_function="showArmyR", function_owner=self,
    position={XposHideArmy-6,Ypos,ZposHideArmy}, rotation={0,0,0},
    height=500, width=2400, font_size=200, color="Green", font_color={1,1,1}
}
local showArmyBtnB = {
    label="SHOW "..hideShowArmyBtnLbl, click_function="showArmyB", function_owner=self,
    position={XposHideArmy+Xoffset-6,Ypos,-ZposHideArmy}, rotation={0,180,0},
    height=500, width=2400, font_size=200, color="Green", font_color={1,1,1}
}

-- Activation / Wound tracker tokens: a Reset button (also auto-fired at every
-- phase change from startMenu) plus per-token Spawn buttons that clone the parked
-- master copies. Mirrored on the Red (+Z) and Blue (-Z) edges of the tool.
local XposReset = 112.2
local ZposReset = 42.75
local resetBtnLbl = "Reset Activation tokens\n(auto at phase change)"
local resetBtnR = {
    label=resetBtnLbl, click_function="resetTokens", function_owner=self,
    position={XposReset,Ypos,ZposReset}, rotation={0,0,0},
    height=500, width=2400, font_size=200, color="White", font_color={0,0,0}
}
local resetBtnB = {
    label=resetBtnLbl, click_function="resetTokens", function_owner=self,
    position={XposReset+Xoffset,Ypos,-ZposReset}, rotation={0,-180,0},
    height=500, width=2400, font_size=200, color="White", font_color={0,0,0}
}

local tokenBtnOffset = 5
local tokenBtnWidth = 1800
local tokenBtnFontSize = 200
local XposSpawnA = XposReset - tokenBtnOffset
local spawnActivationBtnR = {
    label="Spawn Activation\ntoken", click_function="spawnActivation", function_owner=self,
    position={XposSpawnA,Ypos,ZposReset}, rotation={0,0,0},
    height=500, width=tokenBtnWidth, font_size=tokenBtnFontSize, color={0,0,0}, font_color={1,1,1}
}
local spawnActivationBtnB = {
    label="Spawn Activation\ntoken", click_function="spawnActivation", function_owner=self,
    position={XposSpawnA+Xoffset,Ypos,-ZposReset}, rotation={0,180,0},
    height=500, width=tokenBtnWidth, font_size=tokenBtnFontSize, color={0,0,0}, font_color={1,1,1}
}

local XposSpawnW = XposReset + tokenBtnOffset
local spawnWoundsBtnR = {
    label="Spawn Wound\ntoken", click_function="spawnWounds", function_owner=self,
    position={XposSpawnW,Ypos,ZposReset}, rotation={0,0,0},
    height=500, width=tokenBtnWidth, font_size=tokenBtnFontSize, color={0,0,0}, font_color={1,1,1}
}
local spawnWoundsBtnB = {
    label="Spawn Wound\ntoken", click_function="spawnWounds", function_owner=self,
    position={XposSpawnW+Xoffset,Ypos,-ZposReset}, rotation={0,180,0},
    height=500, width=tokenBtnWidth, font_size=tokenBtnFontSize, color={0,0,0}, font_color={1,1,1}
}

-- Parked master tokens cloned by the Spawn buttons (resolved in onLoad).
local activationMaster = nil
local woundsMaster = nil
-- Local button positions keyed by master + player edge, for clone placement.
local spawnButtonByMaster = {}

local hiddenZone = {}

function onLoad()
    self.setName("Spawn game tools")
    self.setPosition({80,-5,0})
    self.setRotation({0,0,0})
    self.setScale({1,1,1})
    self.setLock(true)
    self.interactable = false

    -- Park and lock the master tokens beside the tool so the Spawn buttons can
    -- clone them. Map each master to the local button position used per edge.
    activationMaster = getObjectFromGUID(Global.getVar("activation_GUID"))
    woundsMaster = getObjectFromGUID(Global.getVar("wounds_GUID"))
    lockItem(activationMaster, {80,-5,-3})
    lockItem(woundsMaster, {80,-5,3})
    -- Keyed by the master object; guarded so a missing GUID never indexes with nil.
    spawnButtonByMaster = {}
    if activationMaster then
        spawnButtonByMaster[activationMaster] = {Red = spawnActivationBtnR, Blue = spawnActivationBtnB}
    end
    if woundsMaster then
        spawnButtonByMaster[woundsMaster] = {Red = spawnWoundsBtnR, Blue = spawnWoundsBtnB}
    end

    createMenu()
end

function lockItem(obj, position)
    if not obj then return end
    if position then obj.setPosition(position) end
    obj.setLock(true)
    obj.interactable = false
end

function createMenu()
    self.clearButtons()
    self.createButton(resetBtnR)
    self.createButton(resetBtnB)
    self.createButton(spawnActivationBtnR)
    self.createButton(spawnActivationBtnB)
    self.createButton(spawnWoundsBtnR)
    self.createButton(spawnWoundsBtnB)
    self.createButton(hideArmyBtnR)
    self.createButton(hideArmyBtnB)
    self.createButton(showArmyBtnR)
    self.createButton(showArmyBtnB)
end

-- Reset every Activation token on the table to its "not acted" (green) state.
-- The button here is the manual trigger; startMenu calls the same loop on its own
-- copy automatically at game start and on each phase change.
function resetTokens()
    for _, obj in ipairs(getAllObjects()) do
        if obj.getVar("BCBtype") == "ActivationToken" then
            obj.call("resetAlredyActed")
        end
    end
end

function spawnActivation(obj, player, alt)
    spawnTokenCopy(activationMaster, player)
end

function spawnWounds(obj, player, alt)
    spawnTokenCopy(woundsMaster, player)
end

-- Clone a parked master token next to the Spawn button the player clicked, on
-- their own edge of the tool, then unlock it for use.
function spawnTokenCopy(master, player)
    if not master then return end
    local mousePos = Player[player].getPointerPosition()
    local edge = (mousePos and mousePos.z > 0) and "Red" or "Blue"
    local rot = (edge == "Red") and {0,180,0} or {0,0,0}
    local btn = (spawnButtonByMaster[master] or {})[edge]
    if not btn then return end
    local localPos = btn.position
    local clone = master.clone({
        position = self.positionToWorld({-localPos[1], localPos[2]+5.5, localPos[3]*0.95}),
        rotation = rot,
    })
    clone.setLock(false)
    clone.interactable = true
end

function hideArmyR(obj, player, alt)
    if player ~= "Red" then print("INTRUDER") return end
    hideShowArmy("Red", true)
end

function hideArmyB(obj, player, alt)
    if player ~= "Blue" then print("INTRUDER") return end
    hideShowArmy("Blue", true)
end

function showArmyR(obj, player, alt)
    if player ~= "Red" then print("INTRUDER") return end
    hideShowArmy("Red", false)
end

function showArmyB(obj, player, alt)
    if player ~= "Blue" then print("INTRUDER") return end
    hideShowArmy("Blue", false)
end

function hideShowArmy(color, hideShow)
    hiddenZone.Red = getObjectFromGUID(Global.getVar("redHiddenZone_GUID"))
    hiddenZone.Blue = getObjectFromGUID(Global.getVar("blueHiddenZone_GUID"))
    local zoneData = {
        position={
            hide={x=20, y=0.75, z=74.25},
            show={x=0, y=-50.75, z=74.25}
        },
        scale={
            hide={x=140, y=230, z=48},
            show={0.1,0.1,0.1}
        }
    }

    local hideIndex = hideShow and "hide" or "show"
    if color == "Blue" then
        zoneData.position.hide.z = -zoneData.position.hide.z
        zoneData.position.show.z = -zoneData.position.show.z
    end
    if not hiddenZone[color] then
        return
    end
    hiddenZone[color].setPosition(zoneData.position[hideIndex])
    hiddenZone[color].setScale(zoneData.scale[hideIndex])
    hiddenZone[color].setRotation({0,0,0})
end
