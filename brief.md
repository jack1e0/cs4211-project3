
    ## System description
The system manages a communication mechanism where data is sent and received based on the parity of certain state variables.

## Requirements
- The system must initialize state variables to specific values.
- The system must allow sending data when certain conditions on parity and state variables are met.
- The system must allow receiving data when the parity of two state variables differs.
- The system must track whether a final condition has been reached.

## Constants
- `parity`: A function mapping natural numbers to integers.

## Variables
- `h`: A collection (e.g., array or map) to hold received data.
- `r`: A counter for received messages, initialized to 1.
- `s`: A counter for sent messages, initialized to 1.
- `d`: A variable representing the data to be sent or received.
- `p`: A variable representing the parity of `s`.
- `q`: A variable representing the parity of `r`.
- `b`: A boolean flag indicating whether the final condition has been reached.

## States
- The system can be in a state where `b` is `TRUE` (final condition reached) or `FALSE` (final condition not reached).
- The values of `p` and `q` reflect the parity of `s` and `r`, respectively.

## Events / Operations
- **INITIALISATION**
  - Purpose: Set initial values for all state variables.
  
- **final**
  - Purpose: Set the final condition flag to `TRUE` when certain conditions are met.
  
- **receive**
  - Purpose: Store received data and update counters when the parity of `p` and `q` differs.
  
- **send**
  - Purpose: Send data and update counters when the parity of `p` and `q` is the same and other conditions are satisfied.

## Guards
- **INITIALISATION**: No guards.
- **final**: Enabled when `r = n + 1` and `b = FALSE`.
- **receive**: Enabled when `p ≠ q`.
- **send**: Enabled when `p = q`, `s ≠ n + 1`, `p = parity(s)`, and `q = parity(r)`.

## Actions
- **INITIALISATION**:
  - `h ≔ ∅`
  - `r ≔ 1`
  - `s ≔ 1`
  - `d :∈ D`
  - `p ≔ 1`
  - `q ≔ 1`
  - `b ≔ FALSE`
  
- **final**:
  - `b ≔ TRUE`
  
- **receive**:
  - `h(r) ≔ d`
  - `r ≔ r + 1`
  - `q ≔ 1 - q`
  
- **send**:
  - `d ≔ f(s)`
  - `s ≔ s + 1`
  - `p ≔ 1 - p`

## Initialisation
- `h` is initialized to an empty collection.
- `r` is initialized to 1.
- `s` is initialized to 1.
- `d` is initialized to an element of set `D`.
- `p` is initialized to 1.
- `q` is initialized to 1.
- `b` is initialized to `FALSE`.

## Invariants
- `p = parity(s)`
- `q = parity(r)`

## Assumptions
- The function `f` is defined and applicable for the variable `s`.
- The set `D` is defined and contains valid elements for `d`.

## Concurrency model
- The system operates with a single process.
- Interaction is through shared state (variables).
- No specific scheduling assumptions are made.

## Other notes
- The model does not utilize bounded queues or arrays beyond the defined variables.

