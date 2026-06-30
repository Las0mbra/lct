# Changelog

Player-facing changes to the LCT 40k TTS table.

How this file is used by the compiler (`compile.py --release`):
- The **topmost** `## vX.Y.Z` heading is the current version. It is stamped into
  the TTS save name (e.g. `LCT - v1.0.0`) and into the
  in-game `GAME_VERSION`.
- The `-` bullet points directly under that heading are the patch notes shown
  to players in-game the first time they open a map built from a newer version
  than their saved game.

To cut a release: add a new `## vX.Y.Z` section at the top with its bullets,
then run `python3 compile.py --release`.

## v1.9.1
- Added links to other workshop items. 
- Added a small introduction in the notebook about how a game starts. 
- Some more token additions & changes

## v1.9.0 
- Reverted pdfs, edited workshop tags, trying to clean up things 
- UI: Added dedicated modes buttons, so now you can choose map size from initial start menu
- Onslaught mode now is handled appropriately, menus are moved to provide enough space. 
- Added Dice+ button that provides more dice colours 
- Added another token bag that has primary/secondary missions tokens and some additional generic ones. 
- Cool new dice tray
- Bug fixes: Territory lines, GUID spam on map load.


## v1.8.4b
- Refreshed Battlemaster cards
- Cleaning up
- Quick fixes

## v1.8.2c
- Added more Table themes 
- Updated Primary & Secondary mission decks based on this Changelog -> https://github.com/game-datacards/missioncards/blob/main/CHANGELOG.md
- Added more space to the board when Onslaught mode is set
- Fixed minor overlay bugs
- Added tags to T5S2 maps for objective tokens
- Added Dominatus items on main page (1v1 and Solo). 
- Added T5S2 maps on the list.
- Minor bug fixes (Removed Mission gen when map loads,quick roll custom dice bug)

## v1.8.1
- Added a lof of new maps from creators. But most of them came from Battlemaster, made by Superwutz.
- Combat Patrol & Narrattive/Support.
- Added an Advanced control menu on top
- Map/Mod customization: In the menu there is an option to changes loaded maps mat or to change the table theme. 
- Added an End of Battle Scoreboard button that doesnt have the primary/secondary points limitations.
- New Hotkey additions but if you encounter some weird shortcut behaviour you might need to reset your hotkeys.
- New and cleaner UI, things should look cleaner and more symmetrical. Also replaced legacy widgets with counters. 
- Multiple minor bug fixes

## v1.7.0e
- Added back Activation and Wound tokens! 
- Small ui changes (eg. Map filter going away when game starts)

## v1.7.0d
- Deployed test version with Convex fixes.
- Fixed most of the objective based bugs for maps
- Now Back to Selection undo button returns all cards appropriately
- Quick fix with some ui errors and primaries not moving on board 
- Added map filter
- All maps should now be available. If you notice any map errors, let me know!
- Reworked ui to to make it look more intuitive.


## v1.6.5c
- More maps, currently we have all Take and Hold Matchups, Priority Assets vs Priority Assets, Priority Assets vs Recon , Purge the Foe vs Purge the Foe, Purge the Foe vs Recon, Purge the Foe vs Priority Assets. 
- Added a "Back to Menu" button that appears beneath dispotition text after a map is loaded, in case people want to back to the original selection. 
- Revamped Score board overlay so that it looks way better. 
- Added the Tournament Companion PDF

## v1.6.5b
- Map Generation from multiple creators. Now the system of loading layouts, will also pull maps from different creators, so if you press Generate mission again, eg for TnH vs TnH you ll always get appropriate Layouts 1,2 and 3 but you might get Layout 1 from creater A and Layout 2,3 from creator B. Hopefully this will allow for map variety and I will eventually add a tool that will allow for map filtering. 
- Greatly improved performance for Coherency tool 
- Removed/Refactored old legacy code.
- UI: Improved boards contrast 
- Added clear mat button for people who want to use maps with additive loading.  

## v1.6.5 
- UI: New board art 
- UI: Added Gain CP boards 
- UI: There is now an "X" button in the overlay to hide it. You can show it again if you press "Show/Hide" button.
- Code: Improved dice roller performance and trimmed legacy code yet again. 

## v1.6.4b
- Fixed Dice Roller issue on red side. 
- Added updated primary/secondary cards (improved wording)
- UI/UX changes 
- Added Sort Secondary buttons to place secondary cards on empty spots 
- Additional game keys and sorted them alphabetically.

## v1.6.3b
- Improved Map Loading (this wont work with maps outside the mod)
- Proper Objective marker graphics! Try it!
- Added legacy quick roll feature if you right click dice spawn buttons in ordered manner. (This still uses the new dice rolling algorith).
- Added engange on all fronts fixed

## v16.2c
- Edited the new dice roller yet again. Removed the instant dice rolling buttons but there should be better stability
- Automatically set Deployment Zone on Map Load.
- Additional dev tools on backend
- Removed old pdfs and added the new Core Rules with bookmarks (thanks to Bookmarkable PDF by CaptironJack) for easier navigation in game. 
- Added an image with the new strategems 
- All primary & secondary cards are now using the amazing card design by Shinobau https://github.com/game-datacards/missioncards 
- Added new extra tokens (inside a memory bag) by MothmyTitania have a look! 
- Added a new coherency button that dynamically calculates the distance between selected units. Keep in mind while it's on you can't really draw lines until you toggle it off (right click on button) or 15 seconds pass
- FIX: fixed a small issue with coherency being wonky with oval based models.


## v1.6.1
- FIX: Fixed a dice rolling bug and weird cloning issues if both SuS & Lethals occured. 
- FEATURE: Dynamic Objective/Ruin Markers that calculates dynamically where it should be placed, cause with so many layouts and different DZones it would be a hell to manually place these onto every map and even harder to change it later. 
- FEATURE: Mission Dispotition Take and hold Maps are in! Keep in mind other matchups remain random. 
- UI/UX: Moved Mission Generation near the centre for better visibility. 
- UI/UX: Added a 15'' bubble button too.


## v1.5.2
- QOL: Deployment zones are now disabled when game starts. 
- Fix: Territory button wasn't synced before.
- Fix: Reverted to old stats helper from Ricu
- Fix: Fixed a bug with LOS markers that weren't able to separate markers from different players.

## v1.5.1 
- TOOL ADDITION :Added LOS markers by the amazing Kvothe! 
- FEATURE: There is a button next to area denial that now handles the new show territory areas, it's based on current Deployment zone so it wont work before choosing one 
- UI/UX: Added more options to the overlay for better readability. Now there are Pass Turn, Gain CP and Use CP buttons. There is also a new side button "-" pressing that will toggle to a more mininalistic UI. 
- UI/UX: Added banners above map decks. This is still placeholder art until we get all the layout info.
- QUICK FIX: Clicking the Start Button 3 times allows to "Force Start" the game and ignore tactical/fixed step. 

## v1.5.0 
- TOOL ADDITION :Added LOS markers by the amazing Kvothe! 
- FEATURE: There is a button next to area denial that now handles the new show territory areas, it's based on current Deployment zone so it wont work before choosing one 
- UI/UX: Added more options to the overlay for better readability. Now there are Pass Turn, Gain CP and Use CP buttons. There is also a new side button "-" pressing that will toggle to a more mininalistic UI. 
- Added banners above map decks. This is still placeholder art until we get all the layout info.

## v1.4.0
- Backend compiler improvements 
- Added dynamic custom overlay bubble, set a hotkey and try it! 
- Minor UI fixes

## v1.3.3
- Dropped support for 10th edition 
- Gaining or decreasting CP via widget and/or overlay now is logged in chat for tracking.
- Added deployment zone picker based on dispotition.
- Added VP limitations for primary, secondary missions and totla scores. 
- Changed scoreboard buttons 
- Added the option to change table mat 
- Multiple new tokens 
- Major code cleanup

## v1.0.0
- CP tracking added to the VP/CP overlay
- Table texture editing and new control buttons
- Option to draw a single secondary only
- Renamed legacy bags for clarity
