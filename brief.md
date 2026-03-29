## System description
The system is defined within the context of a formal model that utilizes Event-B notation. It involves a mechanism to manage and track parity values associated with certain variables. The model includes events for initialization, receiving data, and sending data, with specific conditions and actions tied to these events.

## Requirements
- The system must maintain the parity of two variables, `s` and `r`, which are updated through various events.
- The system must initialize its variables to specific values.
- The system must allow for receiving and sending data based on the parity of the variables.

## Constants
- **parity**: A function that maps natural numbers to integers, representing the parity (even or odd) of a number.

## Variables
- **h**: A mapping that stores data received.
- **r**: An integer representing a count or index related to received data.
- **s**: An integer representing a count or index related to sent data.
- **d**: A variable that holds the data being sent or received.
- **p**: An integer representing the parity of `s`.
- **q**: An integer representing the parity of `r`.
- **b**: A boolean flag indicating a specific state in the system.

## States
The system can be in various states based on the values of its variables, particularly the parity values of `s` and `r`, and the boolean flag `b`.

## Guards
- **For the `final` event**:
  - `r = n + 1`: Ensures that `r` is one more than a natural number `n`.
  - `b = FALSE`: Ensures that the boolean flag `b` is false.

- **For the `receive` event**:
  - `p ≠ q`: Ensures that the parity of `s` is not equal to the parity of `r`.

- **For the `send` event**:
  - `p = q`: Ensures that the parity of `s` is equal to the parity of `r`.
  - `s ≠ n + 1`: Ensures that `s` is not one more than a natural number `n`.
  - `p = parity(s)`: Ensures that `p` correctly reflects the parity of `s`.
  - `q = parity(r)`: Ensures that `q` correctly reflects the parity of `r`.

## Actions
- **Initialization**:
  - Set `h` to an empty mapping.
  - Set `r` to 1.
  - Set `s` to 1.
  - Assign a value from set `D` to `d`.
  - Set `p` to 1.
  - Set `q` to 1.
  - Set `b` to FALSE.

- **Final event**:
  - Set `b` to TRUE.

- **Receive event**:
  - Assign `d` to `h(r)`.
  - Increment `r` by 1.
  - Toggle the value of `q`.

- **Send event**:
  - Assign the result of function `f(s)` to `d`.
  - Increment `s` by 1.
  - Toggle the value of `p`.

## Initialisation
The system initializes all variables to specific starting values, ensuring that the state is set up correctly for subsequent operations.

## Invariants
- **inv1**: The parity `p` must always equal the parity of `s`.
- **inv2**: The parity `q` must always equal the parity of `r`.

## Assumptions
- The function `parity` is well-defined for all natural numbers.
- The mapping `h` is capable of storing data indexed by `r`.

## Other notes
- The model relies on the parity function to enforce certain conditions on the variables `s` and `r`, ensuring that the system behaves correctly in terms of data handling and state transitions.
- The boolean variable `b` serves as a flag to indicate when the system has reached a final state.
