-- FTC-GUID: 59decf

-- Shared variables
deployLineHeight = 2.1
sizeMulti        = 36
local onState = 'https://steamusercontent-a.akamaihd.net/ugc/15097634417370475591/2AAD029EBF3BEC3AD5C81C811310A26009273429/'
local offState = 'https://steamusercontent-a.akamaihd.net/ugc/14757168286520639251/5C85FDDAEEC5C058E7E11536DB93A94C59F20CEB/'

function onLoad(saved_data)
    self.createButton({
        click_function  = "toggleQuarters",
        function_owner  = self,
        label           = "",
        position        = {0, 0.2, 0},
        width           = 2000,
        height          = 2000,
        color           = {0, 0, 0, 0}
    })
end

function toggleQuarters()
    local state = Global.getVar("interactiveButtonTableQuarters_State")
    if state == 1 then
        Global.setVar("interactiveButtonTableQuarters_State", 2)
        params = {
            image = onState,
        }
        drawLines()
    else
        Global.setVar("interactiveButtonTableQuarters_State", 1)
        params = {
            image = offState,
        }
        removeLines()
    end
    self.setCustomObject(params)
    self.reload()
end

-- Draw the two quarter‐lines
function drawLines()
    -- Resolve at click time: a load-time capture can race Global's onLoad.
    local mat = getObjectFromGUID(Global.getVar("mat_GUID"))
    if not mat then return end

    local lineScale = { x = 1, y = deployLineHeight, z = 0.02 }
    local mapBase   = mat.getScale().z * sizeMulti
    local mapHeight = mat.getScale().x * sizeMulti

    -- Long edge line
    lineScale.x = mapHeight
    spawnLine({0, deployLineHeight, 0}, {0,   0, 0}, lineScale, "White", "quarter")

    -- Short edge line
    lineScale.x = mapBase
    spawnLine({0, deployLineHeight, 0}, {0,  90, 0}, lineScale, "White", "quarter")
end

-- Remove any “quarter” GMNotes
function removeLines()
    for _, obj in ipairs(getAllObjects()) do
        if obj.getGMNotes() == "quarter" then
            obj.destroy()
        end
    end
end

-- Helper: spawn a BlockSquare with a given GMNote
function spawnLine(linePos, lineRot, lineScale, color, gmNote)
    local lineObj = spawnObject({
        type     = "BlockSquare",
        position = linePos,
        rotation = lineRot,
        scale    = lineScale
    })
    if lineObj then
        lineObj.setLock(true)
        lineObj.interactable = false
        lineObj.setGMNotes(gmNote)
        lineObj.setColorTint(color)
        local blockComp = lineObj.getComponent("BoxCollider")
        if blockComp then
            blockComp.set("enabled", false)
        end
        local meshComp = lineObj.getComponent("MeshCollider")
        if meshComp then
            meshComp.set("enabled", false)
        end
    end
end
