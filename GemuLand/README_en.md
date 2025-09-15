# Gemu Land

This game requires special cards: **Gemu Cards**

| Category | Details |
| -- | ------------- |
| Type | Special card game; turn-based; first-move advantage |
| Players | 2 |
| Luck | OOOO\* |
| Strategy | OOOOO |
| Competition | OOOOO |
| Cooperation | \*\*\*\*\* |
| Reflexes | \*\*\*\*\* |

## Game Background

On the richly varied continent of Gemu, all kinds of strange monsters live.
Though their intellect is limited, they can wield a special **Gemu Mana** to cast spells.
To survive, they form cross-species tribes, follow the commands of a **Prophet**, hunt one another, harvest mana, and strengthen their tribes.

## Core Mechanic

By summoning **Monsters** and using **Prophecy Cards** to launch offense and defense, reduce the opponent’s **Faith** to 0 to win.

## Basic Setup

- **Field**: Each player has a field to place cards, with:
  - Up to 3 Monster cards (or Set/face-down Monsters)
  - Up to 3 Prophecy cards (or Set/face-down Prophecies)
- **Deck**: Each player has a **20–40 card** deck and an initially empty discard pile.
- **Hand**: Each player starts with **3 cards** in hand. Maximum hand size is **5**.
- **Faith**: Each player’s starting Faith is set by the rules (e.g., 50 or 100).

- Players take turns performing a full **turn**.

## Turn Flow

Players alternate turns. Each turn has

> Draw, Summon, Prophecy, Monster, Set

**five phases**, in order:

### 1. (Draw) Draw Phase

- Draw: Draw **2 cards** from your deck. Note: hand size cap is 5 and may never be exceeded.
- Discard: Discard any number of cards from hand or from the field.

Note: When the deck is empty, shuffle the discard pile to form a new deck.

### 2. (Summon) Summon Phase

Summon: Place **1** Monster card face-up; you may play it from hand or flip a Set (face-down) Monster face-up.

Notes:
- Summoning high-level monsters requires paying Mana equal to their level.
- Summoned monsters remain on the field until destroyed and occupy a Monster slot.

### 3. (Prophecy) Prophecy Phase

Prophecy: Place **1** Prophecy card face-up and resolve its effect.

Notes:
- Normal Prophecies go to the discard pile after use.
- **[Persistent]** Prophecies remain on the field until destroyed and occupy a Monster slot.

### 4. (Monster) Monster Phase

Each of your monsters may:
- Use **1** skill. (Note: some skills consume Mana.)
- Declare **1** attack. (Note: if the opponent has no Monster cards or Set Monsters on the field, you may attack the opponent directly. See **Battle Damage** rules.)

### 3. (Set) Set Phase
Set any number of Monster or Prophecy cards to the field. (Note: do not exceed field limits.)

## Battle Damage

### Monster vs. Monster

- If Attack > Defense → the enemy monster is destroyed;
- The opposing player’s Faith decreases by the difference: your Attack − their Defense.

### Monster vs. Player

- Allowed only when the opponent’s field has **no Monsters or Set Monsters**;
- The opposing player’s Faith decreases by your Attack.

## Card Types

### Monster Cards

- **Traits**: Have always-on **[Normal Traits]** and **[Reactive Traits]** that trigger when conditions are met.
- **Skills**: Choose one skill per turn to resolve its effect.

### Prophecy Cards

- You may play it directly to resolve its **[Effect]** once, then send it to the discard; or Set it to await triggering its **[Reactive Effect]**.
- After use, it may be stacked as Mana points.

## Mana Points System

Mana points are represented by cards stacked beneath a Monster card and are used to activate special skills or to summon high-level monsters.

- **Gaining Mana**:
  - After you use a Prophecy card, you may stack it under a Monster or Set Monster as **1 Mana**;
  - Defeating an enemy monster that has Mana stacked lets you absorb its Mana. Operationally, draw from the bottom of your own deck to represent the gained Mana.
  - (Note: A single Monster or Set Monster can hold at most **10 Mana**.)
- **Spending & Recycling**:
  - Spend Mana points to activate certain Monster skills;
  - Spend Mana to summon high-level monsters, **1 Mana = 1 Level**;
  - Spent Mana cards go to the **top** of the discard pile.

## Special Notes
- A single event can serve as the trigger for only one card; priority goes to the one that declares first. After the triggered effect resolves as an interlude, continue the original event.
- Immune to battle destruction does **not** mean immune to battle damage.
- **Taunt Rank**: Targeting effects cannot override Taunt. The opponent must attack the monster with the higher Taunt priority.
- **Additive vs. Multiplicative Buffs**: Both are cached; actual computation happens on resolution. Apply addition/subtraction first, then multiplication/division, then round **up**.
- **Tokens**: Cannot leave the field to hand/deck; when destroyed they simply vanish; they can use skills and attack; they cannot carry Mana; effects that would move them off the field are treated as “destroy.”
- **Leaving the Field & Mana**: Whenever any card leaves the field (return to hand/topdeck/shuffle back/destroy/banish), its attached Mana goes to the discard by default; if an effect says “you gain its Mana / transfer its Mana,” follow that effect.
- **Faith decrease == taking damage.**

## Abbreviation

- **[Attack Skill]**: Declares an attack while activating a skill. After using an Attack Skill, that monster cannot attack again this turn.
- **[Persistent]**: A Persistent Prophecy remains on the field and continues to apply its effect.
- **[Persistent/Equipment]**: Remains on the field, assigned to a specific monster. Once assigned, the target cannot be changed. When the assigned monster leaves the field, this card is destroyed.
- **[Persistent/Field]**: Remains on the field; Mana from monsters you voluntarily discard will be stacked under this card.
- **[Quick]**: A special Prophecy that can be used at the start of the turn, before the Draw Phase.
- **[Buff]** / **[Shield]**: If no explicit duration is stated, it remains attached to the monster until it—or the designated monster—is destroyed. Buffs stack; consider indicating stacks by turning the card sideways or similar.
- **[Chain]**: When one card’s effect triggers another card’s effect, that is a Chain. A single initiation can trigger up to **three** chained effects (e.g., A → B → C → D; D, as a **[Finale]**, does not trigger further effects). If a card’s “XX Effect” triggers others, call it an “XX Chain,” e.g., **[Draw Chain]**, **[Damage Chain]**.
- **[Finale]**: A concluding action that cannot serve as any trigger. For example, a **[Finale]** attack will not trigger reactions that require “issuing an attack command” as the condition.
