# LCT 40K Table: Advanced Feature Guide

This guide explains several automated systems in more detail. It focuses on what each control does, what information it uses, and the side effects players should know about.

## 1. Mission Generation and Random Layout

Mission generation uses both players' selected **Dispositions**. The table compares Red's disposition with Blue's disposition, finds that matchup in the mission matrix, and uses the result to choose:

- The correct Primary Mission cards for Red.
- The correct Primary Mission cards for Blue.
- A matching deck of three valid Deployment Layout cards.

### Generate Missions

Press **Generate Missions** after both players have selected their dispositions.

- Each player's matching Primary Mission cards are taken from their own Primary deck and displayed near the center.
- All three valid Deployment Layout cards from the matching matrix deck are displayed.
- Use the **Lock-in** button beside a layout to move that card to the mission board as the selected layout.
- Pressing Generate Missions again updates the cards if the selected dispositions have changed.
- Old cards are cleaned up and returned to their correct source decks where possible.

### Random Layout

Press **Random Layout** when you want the table to choose the deployment layout for you.

- The same disposition matchup and mission matrix are used.
- Primary Missions are generated in exactly the same way as with **Generate Missions**.
- Instead of showing all three valid layouts, one of those three is chosen randomly and placed in the middle layout slot.

**Important:** Random Layout does not choose from every layout on the table and does not generate terrain. It randomly chooses from the layouts allowed by the current disposition matchup.

When the game starts, unused layout cards are returned and the Primary Mission cards move to their in-game positions.

## 2. Tactical and Fixed Secondaries

At setup, each seated player receives a **Tactical/Fixed mode card** and a selection of Fixed Secondary cards in their hand.

Your choice is communicated by flipping cards:

- **Tactical mode:** Leave the Tactical/Fixed mode card face up and leave all Fixed Secondary cards face up.
- **Fixed mode:** Flip the Tactical/Fixed mode card face down, then flip exactly two Fixed Secondary cards face down.

Press **F** while hovering over a card to flip it.

### What Happens When Start Is Pressed

The table validates both players before starting:

- Tactical mode is accepted only when no Fixed Secondary cards are face down.
- Fixed mode is accepted only when exactly two Fixed Secondary cards are face down.
- Invalid selections stop the game from starting and produce an explanation in chat.

After a valid start:

- In Tactical mode, the Fixed cards return to the Secondary deck, the deck is shuffled, and the Tactical/Fixed mode card moves to the discard area.
- In Fixed mode, the two selected Fixed cards move face up into the first two Secondary board slots. Unselected cards return to the deck.
- Each player's selected mode is announced in chat.

Pressing **Start** three additional times after a failed validation will Force Start the game. Use this only when you intentionally want to bypass the normal selection checks.

### Secondary Boards

Each player has eight active Secondary slots on their board.

- **Draw 2:** Shuffles the Secondary deck and fills the first two open slots.
- **Draw 1:** Shuffles the Secondary deck and fills the first open slot.
- **X beside a slot:** Moves that Secondary to the player's discard pile.
- **Recycle beside a slot:** Returns that card to the deck, shuffles the deck, and draws a replacement into the same slot.

Cards drawn by the board are placed face up and locked in their slots. The slot must be emptied or recycled before another card can use it.

## 3. Coherency Button

The **Coherency** button performs a live check on the currently selected models.

### Using It

1. Select at least two models.
2. Left-click **Coherency** on either dice mat.
3. Move the models as needed while watching the lines and distance labels.
4. Right-click **Coherency** to stop the check early.

The selected models are captured when the check starts. They continue to be monitored after you deselect them.

### What the Lines Mean

- **Orange line:** A model has no other selected model within 2" base-to-base. The line points to its nearest selected model.
- **Red line:** Two selected models are more than 9" apart base-to-base.
- **Distance label:** Shows the measured base-to-base gap for that warning line.

The check reads live model positions every fraction of a second. Measurements ignore height and use the models' base edges rather than their center points. Oval bases and their current rotation are taken into account.

### Important Implications

- The check automatically stops after **15 seconds**.
- Left-clicking again replaces the current monitored group with your new selection.
- Starting with fewer than two selected models does nothing and leaves an existing check running.
- The warning lines use the table's global vector-line layer. Drawing or clearing lines while Coherency is active can behave unexpectedly.
- Right-clicking Coherency, using **Clear Lines**, or waiting for the timeout removes all Coherency lines and labels.
- This tool checks distances only. Players must still decide how the current Warhammer 40,000 coherency rules apply to the unit.

## 4. Overlay UI

Red and Blue each receive a draggable overlay. It displays both players' current turn count, active phase, VP, CP, and chess-clock time.

The brightly highlighted player row is the active turn.

### Main Controls

- **Round badge:** Passes the turn immediately.
- **Turn text on the active row:** Advances to the next phase.
- **Phase icons:** Jump directly to Command, Movement, Shooting, Charge, or Fight phase for the active player.
- **Pass Turn:** Immediately passes to the other player and resets the phase to Command.
- **Gain CP:** Adds one CP. Each player can use this button only once per battle round.
- **Use CP:** Removes one CP and can be used as often as needed.
- **Clock icon:** Shows or hides the chess-clock information.
- **Star icon:** Opens or closes the detailed Scoreboard UI.
- **Minus icon:** Enables Minimalist mode for that player.
- **Settings icon:** Reserved for future settings and currently only displays a message.

Passing the turn updates turn tracking, resets activation tokens, and applies the table's automatic CP gain. With the current configuration, both players gain one CP whenever a turn is passed.

Minimalist mode hides the phase icons, clock, and Pass Turn/Gain CP/Use CP row. Red and Blue can enable it independently.

The overlay can also be hidden completely using the **Show/Hide UI** game key or the matching dice-mat button.

## 5. Scoreboard UI

Open the Scoreboard using the **Star** button on the overlay or the **Show Scoreboard** game key.

The Scoreboard shows both players side by side:

- Current player names and total scores.
- Primary and Secondary VP scored in each battle round.
- Up to eight currently active Secondary cards.
- Every card detected in each player's discard pile.
- Every Secondary card remaining in each player's deck.

The lists are read from the physical cards, board slots, discard areas, and decks on the table. Moving cards outside their expected areas can make the displayed information inaccurate.

While open, the Scoreboard refreshes automatically every two seconds. It can be viewed by Red, Blue, or a Grey spectator, and each viewer opens or closes their own copy.

## 6. Setting Hotkeys

The table registers custom **Game Keys** when it loads.

To assign them:

1. Load the table and wait for scripting to finish.
2. Open Tabletop Simulator's **Options** menu.
3. Open **Game Keys**.
4. Find the LCT action you want.
5. Click its binding and press the key you want to assign.

Useful available actions include:

- Auto 1 Inch Gap and Auto 2 Inch Gap.
- Save Position and Restore Position.
- Toggle 1", 2", 3", 6", 8", 9", or 12" measurement circles.
- Custom Bubble.
- Clear Bubbles, Clear Bubbles on Selected models, and Clear Lines.
- Roll All Dice and Clear Mat.
- Show Scoreboard and Show/Hide UI.

Many hotkeys act on your current selection or hovered object:

- Measurement-circle keys use the object under your cursor.
- Spacing, Custom Bubble, and selected-bubble clearing use your currently selected models.
- Save Position uses selected models, or the hovered object when nothing suitable is selected.
- Roll All Dice and Clear Mat automatically use the dice mat matching your seated Red or Blue color.

Choose bindings that do not conflict with your normal Tabletop Simulator controls.

## 7. Dynamic Bubble Size Overlay

The Dynamic Bubble tool creates a custom measurement ring around every currently selected model.

### Opening the Overlay

- Right-click the **Go** button beside the custom Size field on your dice mat.
- Or assign and press the **Custom Bubble** game key.

The overlay is private to your player color, so Red and Blue can use it independently.

### Applying a Bubble

1. Select the models you want to measure from.
2. Open the **Custom Bubble Size** overlay.
3. Enter a whole-number distance from **1 to 60**.
4. Press **Enter** or click **OK**.

The entered distance is measured outward from each model's base edge. Circular, oval, and supported rectangular bases are handled according to their shape.

- Entering the same size again toggles that bubble off.
- Entering **0** or leaving the value blank clears measurement bubbles from your selected models.
- Values above 60 are limited to 60.
- Closing the overlay with **X** makes no changes.

The dice mat's normal Size field can also apply a custom bubble directly: enter a size and left-click **Go**.
