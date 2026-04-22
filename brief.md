## System description
The system manages access control through a set of doors, allowing entities to pass, accept, or refuse access based on certain conditions.

## Requirements
- The system must initialize all state variables to empty or default values.
- The system must allow an entity to pass through a door if it is in the `mPass` set.
- The system must allow an entity to be accepted if it meets specific conditions related to its card and current state.
- The system must allow an entity to be refused access based on its state and card.
- The system must manage entities that are off green and off red states.
- The system must track acknowledged entities.
- The system must allow entities to be added to the card system.
- The system must allow entities to be accepted or refused based on their current state.

## Constants
- `org`: Origin of the access request.
- `dst`: Destination of the access request.
- `D`: Set of doors.
- `L`: Set of locations.

## Variables
- `sit`: Current state of entities (location).
- `dap`: Data access path for entities.
- `BLR`: Set of blocked locations.
- `mCard`: Mapping of doors to entities' cards.
- `mAckn`: Set of acknowledged entities.
- `mAccept`: Set of entities that have been accepted.
- `GRN`: Set of entities currently in a green state.
- `mPass`: Set of entities that are allowed to pass.
- `mOff_grn`: Set of entities that are off green.
- `mRefuse`: Set of entities that have been refused access.
- `RED`: Set of entities currently in a red state.
- `mOff_red`: Set of entities that are off red.

## States
- The system can be in a state where all sets (`mAccept`, `mRefuse`, `mPass`, `GRN`, `RED`, `mOff_grn`, `mOff_red`, `mAckn`, `BLR`, `mCard`, `dap`) are empty or populated based on the actions taken.

## Events / Operations
- **INITIALISATION**
  - Purpose: Initialize all state variables to their default values.
  
- **pass**
  - Parameters: `d` (entity)
  - Purpose: Allow an entity to pass through a door.

- **accept**
  - Parameters: `p` (entity), `d` (door)
  - Purpose: Accept an entity based on card validation.

- **refuse**
  - Parameters: `p` (entity), `d` (door)
  - Purpose: Refuse access to an entity based on conditions.

- **off_grn**
  - Parameters: `d` (entity)
  - Purpose: Mark an entity as off green.

- **off_red**
  - Parameters: `d` (entity)
  - Purpose: Mark an entity as off red.

- **CARD**
  - Parameters: `p` (entity), `d` (door)
  - Purpose: Add an entity's card to the system.

- **ACKN**
  - Parameters: `d` (entity)
  - Purpose: Acknowledge an entity.

- **ACCEPT**
  - Parameters: `d` (entity)
  - Purpose: Mark an entity as accepted.

- **REFUSE**
  - Parameters: `d` (entity)
  - Purpose: Mark an entity as refused.

- **PASS**
  - Parameters: `d` (entity)
  - Purpose: Mark an entity as passed.

- **OFF_GRN**
  - Parameters: `d` (entity)
  - Purpose: Mark an entity as off green.

- **OFF_RED**
  - Parameters: `d` (entity)
  - Purpose: Mark an entity as off red.

## Guards
- **INITIALISATION**: No guards.
- **pass**: Enabled if `d ∈ mPass`.
- **accept**: Enabled if `d ↦ p ∈ mCard`, `sit(p) = org(d)`, `p ↦ dst(d) ∈ aut`, and `p ∉ dom(dap)`.
- **refuse**: Enabled if `d ↦ p ∈ mCard` and `¬(sit(p) = org(d) ∧ p ↦ dst(d) ∈ aut ∧ p ∉ dom(dap))`.
- **off_grn**: Enabled if `d ∈ mOff_grn`.
- **off_red**: Enabled if `d ∈ mOff_red`.
- **CARD**: Enabled if `p ∈ P` and `d ∈ D ∖ BLR`.
- **ACKN**: Enabled if `d ∈ mAckn`.
- **ACCEPT**: Enabled if `d ∈ mAccept`.
- **REFUSE**: Enabled if `d ∈ mRefuse`.
- **PASS**: Enabled if `d ∈ GRN`.
- **OFF_GRN**: Enabled if `d ∈ GRN`.
- **OFF_RED**: Enabled if `d ∈ RED`.

## Actions
- **INITIALISATION**: Set all variables to empty or default values.
- **pass**: Update `dap`, set `sit(dap∼(d))` to `dst(d)`, update `mAckn`, and remove `d` from `mPass`.
- **accept**: Update `dap(p)` to `d`, remove `d` from `mCard`, and add `d` to `mAccept`.
- **refuse**: Remove `d ↦ p` from `mCard` and add `d` to `mRefuse`.
- **off_grn**: Update `dap`, add `d` to `mAckn`, and remove `d` from `mOff_grn`.
- **off_red**: Update `mAckn` and remove `d` from `mOff_red`.
- **CARD**: Add `d` to `BLR` and `d ↦ p` to `mCard`.
- **ACKN**: Remove `d` from `BLR` and `mAckn`.
- **ACCEPT**: Add `d` to `GRN`.
- **REFUSE**: Add `d` to `RED`.
- **PASS**: Remove `d` from `GRN`, add `d` to `mPass`, and remove `d` from `mAccept`.
- **OFF_GRN**: Remove `d` from `GRN` and add `d` to `mOff_grn`.
- **OFF_RED**: Remove `d` from `RED`, add `d` to `mOff_red`, and remove `d` from `mRefuse`.

## Initialisation
- `sit ≔ P × {outside}`
- `dap ≔ ∅`
- `BLR ≔ ∅`
- `mCard ≔ ∅`
- `mAckn ≔ ∅`
- `mAccept ≔ ∅`
- `GRN ≔ ∅`
- `mPass ≔ ∅`
- `mOff_grn ≔ ∅`
- `mRefuse ≔ ∅`
- `RED ≔ ∅`
- `mOff_red ≔ ∅`

## Invariants
- `ran(dap) = mAccept ∪ mPass ∪ mOff_grn`
- `mAccept ∩ (mPass ∪ mOff_grn) = ∅`
- `mPass ∩ mOff_grn = ∅`
- `red = mRefuse ∪ mOff_red`
- `mRefuse ∩ mOff_red = ∅`
- `GRN ⊆ mAccept`
- `RED ⊆ mRefuse`

## Assumptions
- The behavior of the system is based on the defined events and their conditions.
- The definitions of `aut` and `P` are not provided and are assumed to be defined elsewhere.

## Concurrency model
- The system operates with a single process managing access control.
- Interaction is through shared state (variables).
- No specific scheduling assumptions are defined.

## Other notes
- The model does not include bounded queues or arrays.
