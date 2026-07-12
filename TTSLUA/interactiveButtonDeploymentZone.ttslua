-- FTC-GUID: 8aba11

-- Shared variables
deployLineHeight = 2.1
sizeMulti        = 36
local visibleState = 'https://steamusercontent-a.akamaihd.net/ugc/11888931357205845979/07DA5D6924B1019561DD4092059BB77E610FCE97/'
local hiddenState = 'https://steamusercontent-a.akamaihd.net/ugc/18084074511729353541/6EFF7064E85559205053CF58B73FEEB5D6EC4A6A/'

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
    local manager = getObjectFromGUID("738804")
    manager.call("showHideIngameDeployment")
    syncDeploymentZoneButtonImage()
end

function syncDeploymentZoneButtonImage()
    local state = Global.getVar("interactiveButtonDeploymentZones")
    local params = {
        image = state == 1 and hiddenState or visibleState,
    }
    self.setCustomObject(params)
    self.reload()
end
