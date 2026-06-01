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
