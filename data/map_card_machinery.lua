    -- TO CHANGE THE SIZE OF THE AREA FOR THE MAP LOADING/DELETING, READ THIS
    -- Change the zoneScale size to match a zone you create in game (as reference)
    -- Be sure the zone extends below the table too
    -------------------------------------------------------------
    zoneScale = {x=60.12, y=73, z=44.04} --60x44 Strike Force
    -------------------------------------------------------------
    function onLoad()
        self.createButton({
            label = "Load Map",
            font_size = 115,
            color = {0, 1, 0,},
            position = {-0.96, 0.5, 0},
            rotation = {0, 90, 0},
            scale = {1.3, 1, .7},
            width = 570,
            height = 160,
            click_function = "loadMap",
            function_owner = self,
        })

        self.createButton({
            label = "Clear Map",
            font_size = 100,
            position = {1, 0.5, 0},
            rotation = {0, 90, 0},
            scale = {.6, .6, .4},
            width = 530,
            height = 130,
            color = {1, 0, 0},
            click_function = "clearMap",
            function_owner = self,
        })
    end

    string.split = function(s, delimiter)
        local result = { }
        local from  = 1
        local delim_from, delim_to = string.find( s, delimiter, from  )
        while delim_from do
            table.insert( result, string.sub( s, from , delim_from-1 ) )
            from  = delim_to + 1
            delim_from, delim_to = string.find( s, delimiter, from  )
        end
        table.insert( result, string.sub( s, from  ) )
        return result
    end

    -- Wipe everything inside the zone except the mats/build tables and any
    -- MapExclude-tagged object. v2 defers detection a couple frames so the zone
    -- is populated first. onCleared (optional) runs only AFTER the board is
    -- verified clear and the zone removed, so a follow-up spawn can never race
    -- the wipe and leave a previously loaded map behind.
    function wipeMapZone(zone, onCleared) -- @@MAP_ZONES_V2@@ deferred detection
        Wait.frames(function()
            local keep = {["28865a"]=true, ["4ee1f2"]=true, ["6012bf"]=true, ["948ce5"]=true, ["e7ca6e"]=true}
            for _, obj in ipairs(zone.getObjects()) do
                if obj ~= self and not keep[obj.getGUID()] and obj.getGMNotes() ~= "MapExclude" then
                    obj.destruct()
                end
            end
            zone.destruct()
            if onCleared then Wait.frames(onCleared, 2) end
        end, 2)
    end

    -- Clear Map reuses the wipe with no follow-up spawn.
    function scriptzoneCallback(zone)
        wipeMapZone(zone, nil)
    end

    function spawnMapTerrain()
        for _, objectJSON in ipairs(objectJSONs) do
            spawnObjectJSON({
                json = objectJSON
            })
        end
    end

    function loadMap(objectClicked, clickerColor, altClickUsed)
        -- Spawn the scripting zone; its callback wipes the board and, once it is
        -- 100% clear, spawns this card's terrain. Gating the spawn on the wipe
        -- (instead of a fixed timer running alongside it) guarantees nothing from
        -- a previously loaded map survives next to the new one.
        spawnObject({
            position = {x=0, y=26, z=0},
            scale = zoneScale,
            type = 'ScriptingTrigger',
            callback_function = function(zone) wipeMapZone(zone, spawnMapTerrain) end,
            callback_owner = self,
        })
    end

    function clearMap(objectClicked, clickerColor, altClickUsed)
        spawnObject({
            position = {x=0, y=26, z=0},
            scale = zoneScale,
            type = 'ScriptingTrigger',
            callback_function = scriptzoneCallback,
            callback_owner = self,
        })
    end

