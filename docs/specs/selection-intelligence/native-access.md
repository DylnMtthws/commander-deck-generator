# Native ingredient-access protocol

The generator sends 99 library-slot masks and at most eight named ingredient
classes to `cs --engine-access-request request.json`. The request records sample
sizes, seed, games and a SHA-256 identity of the ordered card identities and rules
text. A card can satisfy more than one ingredient class. Sampling is without
replacement, with deterministic seeds and independent games.

The response echoes the identity and hashes the canonical complete request. The
Python adapter rejects mismatched hashes, sample dimensions, group definitions or
out-of-range counts. Failure is reported as unavailable rather than a score.

The reported fractions measure seeing at least one member of every listed class
by 7, 10 and 14 cards seen. Deck construction minimums are separate from draw
requirements. This is not a game simulation: mana, timing, alternative payment
prerequisites, tutors, mulligans, additional draws and opponents are absent. No
win-rate or completed-combo claim follows from ingredient access.

Validation: 132 native sanitizer tests passed, including deterministic sampling,
finite-population frequencies, overlapping classes, impossible requirements and
invalid inputs. The coordinator also exercised the Python/native binding with a
known impossible two-class deck and confirmed zero joint access.
