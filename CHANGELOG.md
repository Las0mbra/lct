# Changelog

Player-facing changes to the LCT 40k TTS table.

How this file is used by the compiler (`compile.py --release`):
- The **topmost** `## vX.Y.Z` heading is the current version. It is stamped into
  the TTS save name (e.g. `LCT - Warhammer 40k Map - v1.0.0`) and into the
  in-game `GAME_VERSION`.
- The `-` bullet points directly under that heading are the patch notes shown
  to players in-game the first time they open a map built from a newer version
  than their saved game.

To cut a release: add a new `## vX.Y.Z` section at the top with its bullets,
then run `python3 compile.py --release`.

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
