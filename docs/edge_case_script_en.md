# English edge-case script (Paris zone)

100 radio reports, one a minute, covering every case the app handles. Read them aloud on the Paris zone, or play `docs/edge_case_script_en.jsonl`. Each line says what should happen.


## A. Radio procedure

1. “All stations, this is Zero, radio check, over.”  
   → radio check, nothing plotted
2. “Zero, this is Alpha one, loud and clear, over.”  
   → radio check reply, nothing plotted
3. “Zero, this is Bravo two, read you five by five, over.”  
   → radio check reply, nothing plotted
4. “Alpha one, this is Zero, send your position, over.”  
   → request to Alpha 1, nothing plotted
5. “Zero, this is Alpha one, at the Saint-Sulpice church, over.”  
   → Alpha 1 at Église Saint-Sulpice
6. “Alpha one, this is Zero, roger, out.”  
   → acknowledgement, ticks Alpha 1's report
7. “Hello hello, testing.”  
   → chatter, ignored
8. “Roger, out.”  
   → acknowledgement, nothing plotted

## B. Places

9. “Zero, this is Bravo one, at Odeon station, over.”  
   → Bravo 1 at Odéon station
10. “Zero, this is Charlie one, in the Luxembourg gardens, near the Medici fountain, over.”  
   → Charlie 1 by Fontaine Médicis (two clues)
11. “Zero, this is Delta one, outside the town hall, over.”  
   → Delta 1 near the Mairie du 6e (alias)
12. “Zero, this is Echo one, at the Café de Flore, over.”  
   → Echo 1 at Café de Flore (exact name of a café)
13. “Zero, this is Foxtrot three, at the Pantheon, over.”  
   → Foxtrot 3 at the Panthéon
14. “Zero, this is Golf four, on Rue de Rennes, over.”  
   → Golf 4 on Rue de Rennes (long street: wide area)
15. “Zero, this is Hotel one, at the corner of Rue de Seine and Rue Jacob, over.”  
   → Hotel 1 at the crossing
16. “Zero, this is Kilo two, between Mabillon and the Saint-Germain market, over.”  
   → Kilo 2 on the line between them
17. “Zero, this is Sierra two, at Place de l'Odéon, over.”  
   → Sierra 2 at Place de l'Odéon
18. “Zero, this is Echo two, at the church, over.”  
   → Echo 2 at Saint-Sulpice (bare 'church': the one in the area)

## C. Directions and distances

19. “Zero, this is Alpha two, two hundred metres north of the Saint-Sulpice church, over.”  
   → wedge 200 m north
20. “Zero, this is Bravo two, about three hundred metres east of the Pantheon, over.”  
   → wider wedge: 'about'
21. “Zero, this is Charlie two, between two hundred and three hundred metres south of the Luxembourg palace, over.”  
   → 200-300 m band south
22. “Zero, this is Delta three, one hundred yards west of the Odeon theatre, over.”  
   → 91 m west
23. “Zero, this is Echo one, three hundred feet south of the Café de Flore, over.”  
   → 91 m south
24. “Zero, this is Golf four, two blocks west of Mabillon, over.”  
   → about 200 m west
25. “Zero, this is Hotel one, five minutes' walk from Odeon station, over.”  
   → a ring about 400 m out (no direction)
26. “Zero, this is Kilo two, four hundred metres from the Pantheon, over.”  
   → a 400 m ring (no direction)
27. “Zero, this is Sierra two, bearing zero four five, three hundred metres from the Saint-Sulpice church, over.”  
   → narrow wedge at 045, 300 m
28. “Zero, this is Alpha two, on azimuth sixteen hundred mils, two hundred metres from the Pantheon, over.”  
   → bearing 090 (mils), 200 m
29. “Zero, this is Bravo two, north-northeast of the Medici fountain, two hundred metres, over.”  
   → bearing 022.5
30. “Zero, this is Charlie two, opposite the Café de Flore, over.”  
   → band outside it, side not said: flagged
31. “Zero, this is Delta three, inside the Luxembourg gardens, over.”  
   → the garden's footprint
32. “Zero, this is Echo two, in the area of Odeon, over.”  
   → wide circle, flagged
33. “Zero, this is Foxtrot three, just past the Pantheon, over.”  
   → flagged: Foxtrot 3 was at the Panthéon, so there is no viewpoint
34. “Zero, this is Golf four, just short of the Saint-Germain market, over.”  
   → near side, read from its last position
35. “Zero, this is Hotel one, to the left of the Odeon theatre, over.”  
   → left, as seen from its last position
36. “Zero, this is Kilo two, fifty metres north of Bravo one, over.”  
   → another unit as the anchor
37. “Zero, this is Sierra two, I'm with Alpha one, over.”  
   → Sierra 2 at Alpha 1's position

## D. Callsigns

38. “Zero, this is Alfa won, at the Medici fountain, over.”  
   → Alpha 1 (misheard callsign fixed)
39. “Zero this is Charly too, at the Odeon theatre, over.”  
   → Charlie 2
40. “Zero, this is fox trot three, at the Pantheon, over.”  
   → Foxtrot 3
41. “Zero, this is Ecko ate, at Mabillon, over.”  
   → Echo 8 (a new unit)
42. “Zero, this is Delter three, at the Saint-Sulpice fountain, over.”  
   → Delta 3 at Fontaine des Quatre Évêques
43. “Zero, uh, at the Saint-Germain market, over.”  
   → no callsign: held, 'say again your callsign'
44. “This is Delta three, over.”  
   → push-to-talk: claims the held report; radio-net mode: a call only
45. “Bravo one and Bravo two, at the corner of Rue de Rennes and Rue du Four, over.”  
   → two units in one call
46. “Zero, this is Charlie one, Delta one reports he's at the Sorbonne, over.”  
   → relay: Delta 1 at the Sorbonne
47. “Zero, this is Alpha two, Bravo one says he is near Odeon, I'm still north of the church, over.”  
   → relay moves Bravo 1; Alpha 2 placed by the church nearest it

## E. Corrections and history

48. “Zero, this is Echo one, south of the Saint-Sulpice church, over.”  
   → Echo 1 south of the church
49. “Zero, this is Echo one, correction, east of the church, not south, over.”  
   → replaces the last fix (old one struck through)
50. “Zero, this is Golf four, negative, not at Rue de Rennes, I am at Saint-Placide station, over.”  
   → Golf 4 at Saint-Placide
51. “Zero, this is Hotel one, holding position, over.”  
   → same place as before
52. “Zero, this is Kilo two, no change, over.”  
   → same place as before
53. “Zero, this is Sierra two, I'll be at the Pantheon in ten minutes, over.”  
   → intent: not a move
54. “Zero, this is Alpha one, moving towards Boulevard Saint-Germain, over.”  
   → walking corridor towards it
55. “Zero, this is Bravo two, back where I was ten minutes ago, over.”  
   → position from history
56. “Zero, this is Charlie one, now at the church, over.”  
   → the church nearest Charlie 1
57. “Zero, this is Delta one, at the Pantheon, over.”  
   → Delta 1 at the Panthéon

## F. Misheard and unknown places

58. “Zero, this is Echo two, at Odin station, over.”  
   → Odéon by sound, flagged 'confirm'
59. “Zero, this is Foxtrot three, on Rude Rennes, over.”  
   → Rue de Rennes (fuzzy)
60. “Zero, this is Golf four, near San Sulpice, over.”  
   → Saint-Sulpice
61. “Zero, this is Hotel one, at the Saint Germain de Pray church, over.”  
   → Saint-Germain-des-Prés church, flagged
62. “Zero, this is Kilo two, at Mabion station, over.”  
   → Mabillon
63. “Zero, this is Sierra two, at the Luxemburg garden, over.”  
   → Jardin du Luxembourg
64. “Zero, this is Alpha two, at the Pantion, over.”  
   → Panthéon
65. “Zero, this is Bravo two, at the banana tower, over.”  
   → unknown place: not plotted
66. “Zero, this is Charlie two, at the Eiffel Tower, over.”  
   → outside the mapped area: not plotted

## G. Grid references

67. “Zero, this is Delta three, grid five one two one one zero, over.”  
   → 100 m square 31U DQ 512 110
68. “Zero, this is Echo one, grid three one uniform delta quebec five one two one one zero, over.”  
   → full grid, same square
69. “Zero, this is Foxtrot three, grid nine nine nine nine nine nine, over.”  
   → outside the area: not plotted
70. “Zero, this is Golf four, grid five one two one one, over.”  
   → not a valid grid: say again the grid
71. “Zero, this is Hotel one, grid nine nine nine nine nine nine, by the Saint-Sulpice church, over.”  
   → bad grid, uses the church instead

## H. Sightings

72. “Zero, this is Alpha one, contact, two enemy tanks moving north, three hundred metres east of the church, over.”  
   → 2 enemy tanks, red, heading north
73. “Zero, this is Bravo one, contact, enemy infantry, about ten, at the Saint-Germain market, over.”  
   → enemy infantry, count 10
74. “Zero, this is Charlie one, contact, unknown vehicle, static, near the Odeon theatre, over.”  
   → side unknown (yellow), never assumed enemy
75. “Zero, this is Delta one, civilians gathering at Place Saint-Sulpice, over.”  
   → civilians (green)
76. “Zero, this is Echo one, contact, drone overhead, over.”  
   → asks where it is ('overhead' is not yet read as the reporter's position)
77. “Zero, this is Foxtrot three, enemy drone over the Pantheon, heading west, over.”  
   → enemy drone, arrow west
78. “Zero, this is Golf four, another drone over the Pantheon, over.”  
   → a second drone, not merged  
   ⚠ offline rules today: merged with the first drone: English 'another' is not read yet (Ukrainian 'ще один' is)
79. “Zero, this is Hotel one, I see the same tanks, three hundred metres east of the church, over.”  
   → merged with the tanks: seen by two
80. “Zero, this is Kilo two, IED on Rue de Tournon, do not approach, over.”  
   → IED: stays on the map
81. “Zero, this is Sierra two, sniper, two hundred metres north of me, over.”  
   → sniper measured from Sierra 2
82. “Zero, this is Alpha two, contact, enemy APC at my two o'clock, about one hundred metres, over.”  
   → clock direction from Alpha 2  
   ⚠ offline rules today: not plotted: the clock method is not read in English by the offline rules
83. “Zero, this is Bravo two, friendly drone overhead, ours, over.”  
   → own drone: not a threat  
   ⚠ offline rules today: asks for a location instead of ignoring our own drone
84. “Zero, this is Charlie two, contact, enemy artillery firing, south of the Montparnasse tower, over.”  
   → enemy artillery
85. “Zero, this is Delta three, mine at the corner of Rue Guynemer and Rue de Vaugirard, over.”  
   → mine: warning without 'enemy'
86. “Zero, this is Echo two, helicopter, unknown, over the Luxembourg palace, over.”  
   → helicopter, side unknown
87. “Zero, this is Foxtrot three, contact, enemy tank at the Odeon theatre, over.”  
   → separate from the first tanks  
   ⚠ offline rules today: merged with the first tanks although 500 m away
88. “Zero, this is Golf four, the Pont des Arts is destroyed, over.”  
   → place status: destroyed  
   ⚠ offline rules today: place status not read in English: asks for a location
89. “Zero, this is Hotel one, Rue de Seine is blocked, over.”  
   → place status: blocked  
   ⚠ offline rules today: place status not read in English: asks for a location
90. “Zero, this is Kilo two, Rue de Seine is open again, over.”  
   → place status: reopened  
   ⚠ offline rules today: place status not read in English: asks for a location

## I. Orders

91. “Charlie one, this is Zero, move to the Medici fountain, over.”  
   → order: destination drawn dashed
92. “Zero, this is Charlie one, wilco, out.”  
   → acknowledges the order
93. “Zero, this is Charlie one, at the Medici fountain, over.”  
   → arrival closes the order
94. “Delta one, this is Zero, hold your position, over.”  
   → hold order

## J. French and repeats

95. “Zéro, ici Alpha deux, au sud de l'église Saint-Sulpice, terminé.”  
   → French: Alpha 2 south of the church
96. “Zéro, ici Bravo un, je me dirige vers le boulevard Saint-Germain, terminé.”  
   → French: Bravo 1 moving towards it
97. “Zéro, ici Charlie deux, entre Mabillon et Odéon, terminé.”  
   → French: between
98. “Zero, this is Echo one, I say again, at the Pantheon, over.”  
   → Echo 1 at the Panthéon
99. “Zero, this is Sierra two, say again your last, over.”  
   → say-again request, nothing plotted
100. “All stations, this is Zero, end of exercise, out.”  
   → nothing plotted

## Known gaps

7 of 100 lines are marked ⚠: the offline rules get them wrong today. Everything else was checked by playing the script through the radio-net layer offline (`python -m scripts.make_edge_script --play`).
