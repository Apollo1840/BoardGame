# Gemu Land

This game requires special cards: **Gemu Cards**

| Category | Details                           |
| -- | -------------------------------- |
| Type | Special card game; turn-based; initiative |
| Players | 2                              |
| Luck | OOOO*                           |
| Strategy | OOOOO                          |
| Confrontation | OOOOO                      |
| Cooperation | *****                        |
| Reaction | *****                           |

## Game Background

On the terrain-rich **Gemu Land**, all kinds of strange monsters live.
Though lacking high intellect, they can wield spells using a special **Gemu Energy**.
For survival, they form cross-species tribes, obey the commands of **Seers**, hunt one another, harvest energy, and strengthen their clans.

## Core Mechanic

By summoning **Monsters** and using **Prophecy Cards** to wage offense and defense, reduce the opponent’s **Faith** to 0 to win.

## Basic Setup

- **Field**: Each player has a field to place cards:
  - Up to 3 Monster Cards (or face-down set Monsters)
  - Up to 3 Prophecy Cards (or face-down set Prophecies)
- **Deck**: Each player has a **20–40 card** deck and an initially empty discard pile.
- **Hand**: Each player starts with **3 cards** in hand. Maximum hand size is 5.
- **Faith**: Each player’s starting Faith is set by the rules (e.g., 50 or 100).

- Players take full **turns** alternately.

## Game Flow

Players alternate turns. Each turn has

> Draw, Summon, Prophecy, Monster, Set

**five phases**, executed in order:

### 1. (Draw) Draw Phase

- Draw: Draw **2 cards** from your deck. Note the hand limit is 5; you can never exceed it.
- Discard: Discard any number of cards from your hand or field.

Note: When the deck is empty, shuffle the discard pile to form a new deck.

### 2. (Summon) Summoning Phase

Summon: Place **1** Monster Card face-up, either from your hand or by flipping a set Monster.

Notes:
- Summoning a high-level monster requires paying Energy equal to its level.
- Summoned monsters remain on the field until destroyed and occupy a monster slot.

### 3. (Prophecy) Prophecy Phase

Prophecy: Place **1** Prophecy Card face-up to resolve its effect.

Notes:
- Normal Prophecies go to the discard pile after use.
- **[Continuous]** Prophecies remain on the field until destroyed, occupying a prophecy slot.

### 4. (Monster) Monster Phase

Each of your monsters may:
- Use **one** skill. (Note: some skills consume Energy.)
- Declare **one** attack. (Note: if the opponent has no Monster Cards or set Monsters, you may attack the opponent directly. See **Battle Damage**.)

### 3. (Set) Set Phase
Set any number of Monster or Prophecy cards onto the field. (Note: do not exceed field limits.)

## Battle Damage

### Monster vs. Monster

- ATK > DEF → the enemy monster is destroyed;
- The opponent’s Faith decreases by **your ATK − enemy DEF**.

### Monster vs. Player

- Allowed only when the opponent has **no monsters or set Monsters** on the field;
- The opponent’s Faith decreases by your monster’s **ATK**.

## Card Types

### Monster Card

- **Attributes**: Has an always-on **[Normal Attribute]** and a **[Responsive Attribute]** that triggers when conditions are met.
- **Skills**: Choose one skill per turn to resolve.

### Prophecy Card

- Either play it directly to resolve its **[Effect]** once, then send it to the discard pile; or set it face-down to await triggering of its **[Reaction Effect]**.
- After use, it can be stacked as Energy points.

## Energy Point System

Energy points are stacked as cards under a Monster Card to activate special skills or to summon high-level monsters.

- **Gaining Energy**:
  - After you use a Prophecy Card, you may stack it under a monster or set Monster; it counts as **1 Energy**.
  - Defeating an enemy monster that carries Energy lets you absorb those points. Operationally, draw from the bottom of your own deck.
  - (Note: A single monster or set Monster can carry up to **10 Energy**.)
- **Spending & Recycling**:
  - Energy points are used to activate certain monster skills.
  - Energy points are used to summon high-level monsters, **1 Energy = 1 level**.
  - After being used, they go to the **top** of the discard pile.

## Abbreviation

- **[Attack Skill]**: The skill is activated while declaring an attack. After using an Attack Skill, that monster cannot attack again this turn.
- **[Continuous]**: A Continuous Prophecy remains on the field and keeps applying its effect.
- **[Continuous/Equip]**: Remains on the field, assigned to a specific monster. Once designated, it cannot be changed. When the designated monster leaves the field, this card is destroyed.
- **[Continuous/Field]**: Remains on the field; Energy from your voluntarily discarded monsters will be stacked under this card.
- **[Quick]**: A special Prophecy that can be played at the very start of a turn, before the Draw Phase.
- **[Buff] / [Shield]**: Unless otherwise specified, it persists attached to a monster until the source monster or the designated monster is destroyed. Can stack; it’s recommended to indicate via rotating/tapping the card or other special means.
- **[Chain]**: When one card’s effect triggers another card’s effect, it forms a chain. A single initiation can trigger up to **three** links (e.g., A → B → C → D; D is the finale and does not trigger further effects). If a card’s “XX effect” triggers another card, call it an “**XX Chain**,” such as **[Draw Chain]**, **[Damage Chain]**.
- **[Finale]**: The concluding action does not become any trigger condition. For example, a **[Finale]** attack will not trigger reaction effects or responsive attributes that require “issuing an attack command.”
