DEC-SAVE-001: A save file writes the whole run state in one transaction,
and a failed write leaves the previous save intact
and the game still playable.

Context: Players lose an hour of progress when a save is half-written,
which is the one failure they will not forgive.

Source: the save transaction module

DEC-SAVE-002: A save is written once per level transition and never on a timer.