# French edge-case script (Paris zone)

100 radio reports in French, one a minute, on the Paris zone. Each line says what should happen.


## A. Procédure radio

1. « À toutes les stations, ici Zéro, essai radio, à vous. »  
   → essai radio, rien sur la carte
2. « Zéro, ici Alpha un, je vous reçois cinq sur cinq, à vous. »  
   → réponse à l'essai radio
3. « Zéro, ici Bravo deux, reçu fort et clair, à vous. »  
   → réponse à l'essai radio
4. « Alpha un, ici Zéro, donnez votre position, à vous. »  
   → demande de position
5. « Zéro, ici Alpha un, à l'église Saint-Sulpice, à vous. »  
   → Alpha 1 à l'église Saint-Sulpice
6. « Alpha un, ici Zéro, reçu, terminé. »  
   → accusé de réception
7. « Allô, allô, on teste. »  
   → bavardage, ignoré
8. « Reçu, terminé. »  
   → accusé de réception, rien sur la carte

## B. Lieux

9. « Zéro, ici Bravo un, à la station Odéon, à vous. »  
   → Bravo 1 à la station Odéon
10. « Zéro, ici Charlie un, dans le jardin du Luxembourg, près de la fontaine Médicis, à vous. »  
   → Charlie 1 à la fontaine Médicis (deux indices)
11. « Zéro, ici Delta un, devant la mairie, à vous. »  
   → devant la mairie : signalé, côté inconnu sans position précédente
12. « Zéro, ici Écho un, au Café de Flore, à vous. »  
   → Écho 1 au Café de Flore
13. « Zéro, ici Foxtrot trois, au Panthéon, à vous. »  
   → Foxtrot 3 au Panthéon
14. « Zéro, ici Golf quatre, rue de Rennes, à vous. »  
   → rue de Rennes (rue longue : zone large)
15. « Zéro, ici Hôtel un, au coin de la rue de Seine et de la rue Jacob, à vous. »  
   → carrefour des deux rues
16. « Zéro, ici Kilo deux, entre Mabillon et le marché Saint-Germain, à vous. »  
   → sur la ligne entre les deux
17. « Zéro, ici Sierra deux, place de l'Odéon, à vous. »  
   → place de l'Odéon
18. « Zéro, ici Écho deux, à l'église, à vous. »  
   → Saint-Sulpice (l'église de la zone)

## C. Directions et distances

19. « Zéro, ici Alpha deux, deux cents mètres au nord de l'église Saint-Sulpice, à vous. »  
   → 200 m au nord
20. « Zéro, ici Bravo deux, environ trois cents mètres à l'est du Panthéon, à vous. »  
   → plus large : « environ »
21. « Zéro, ici Charlie deux, entre deux cents et trois cents mètres au sud du palais du Luxembourg, à vous. »  
   → bande de 200 à 300 m
22. « Zéro, ici Delta trois, cent mètres à l'ouest du théâtre de l'Odéon, à vous. »  
   → 100 m à l'ouest
23. « Zéro, ici Écho un, à cinq cents mètres au sud du Café de Flore, à vous. »  
   → 500 m au sud
24. « Zéro, ici Golf quatre, à deux rues à l'ouest de Mabillon, à vous. »  
   → environ 200 m à l'ouest
25. « Zéro, ici Hôtel un, à cinq minutes à pied de la station Odéon, à vous. »  
   → anneau d'environ 400 m
26. « Zéro, ici Kilo deux, à quatre cents mètres du Panthéon, à vous. »  
   → anneau de 400 m
27. « Zéro, ici Sierra deux, azimut quarante-cinq degrés, trois cents mètres de l'église Saint-Sulpice, à vous. »  
   → azimut 045, 300 m
28. « Zéro, ici Alpha deux, azimut mille six cents millièmes, deux cents mètres du Panthéon, à vous. »  
   → azimut 090 (millièmes OTAN)
29. « Zéro, ici Bravo deux, au nord-nord-est de la fontaine Médicis, à vous. »  
   → azimut 022,5
30. « Zéro, ici Charlie deux, en face du Café de Flore, à vous. »  
   → autour, côté non précisé
31. « Zéro, ici Delta trois, à l'intérieur du jardin du Luxembourg, à vous. »  
   → dans le jardin
32. « Zéro, ici Écho deux, dans le secteur de l'Odéon, à vous. »  
   → large cercle
33. « Zéro, ici Foxtrot trois, au-delà du Panthéon, à vous. »  
   → signalé : Foxtrot 3 était au Panthéon, pas de point de vue
34. « Zéro, ici Golf quatre, juste avant le marché Saint-Germain, à vous. »  
   → côté proche, vu de sa position précédente
35. « Zéro, ici Hôtel un, à gauche du théâtre de l'Odéon, à vous. »  
   → à gauche, vu de sa position précédente
36. « Zéro, ici Kilo deux, cinquante mètres au nord de Bravo un, à vous. »  
   → une autre unité comme repère
37. « Zéro, ici Sierra deux, je suis avec Alpha un, à vous. »  
   → à la position d'Alpha 1

## D. Indicatifs

38. « Zéro, ici Alfa un, à la fontaine Médicis, à vous. »  
   → Alpha 1 (indicatif mal entendu)
39. « Zéro, ici Charly deux, au théâtre de l'Odéon, à vous. »  
   → Charlie 2
40. « Zéro, ici Fox trot trois, au Panthéon, à vous. »  
   → Foxtrot 3
41. « Zéro, ici Écho huit, à Mabillon, à vous. »  
   → Écho 8 (nouvelle unité)
42. « Zéro, ici Delter trois, à la fontaine Saint-Sulpice, à vous. »  
   → Delta 3 à la fontaine des Quatre-Évêques
43. « Zéro, euh, au marché Saint-Germain, à vous. »  
   → pas d'indicatif : « répétez votre indicatif »
44. « Ici Delta trois, à vous. »  
   → push-to-talk : réclame le rapport ; réseau : simple appel
45. « Bravo un et Bravo deux, au coin de la rue de Rennes et de la rue du Four, à vous. »  
   → deux unités dans un appel
46. « Zéro, ici Charlie un, Delta un signale qu'il est à la Sorbonne, à vous. »  
   → relais : Delta 1 à la Sorbonne
47. « Zéro, ici Alpha deux, Bravo un dit qu'il est près de l'Odéon, je suis toujours au nord de l'église, à vous. »  
   → relais Bravo 1 ; Alpha 2 placé

## E. Corrections et historique

48. « Zéro, ici Écho un, au sud de l'église Saint-Sulpice, à vous. »  
   → Écho 1 au sud de l'église
49. « Zéro, ici Écho un, je corrige, à l'est de l'église, pas au sud, à vous. »  
   → remplace la position
50. « Zéro, ici Golf quatre, négatif, pas rue de Rennes, je suis à la station Saint-Placide, à vous. »  
   → Golf 4 à Saint-Placide
51. « Zéro, ici Hôtel un, je ne bouge pas, à vous. »  
   → même position
52. « Zéro, ici Kilo deux, pas de changement, à vous. »  
   → même position
53. « Zéro, ici Sierra deux, je serai au Panthéon dans dix minutes, à vous. »  
   → intention, pas un déplacement
54. « Zéro, ici Alpha un, je me dirige vers le boulevard Saint-Germain, à vous. »  
   → déplacement vers le boulevard
55. « Zéro, ici Bravo deux, je longe la rue de Vaugirard, à vous. »  
   → le long de la rue
56. « Zéro, ici Charlie un, maintenant à l'église, à vous. »  
   → l'église la plus proche de Charlie 1
57. « Zéro, ici Delta un, au Panthéon, à vous. »  
   → Delta 1 au Panthéon

## F. Lieux mal entendus ou inconnus

58. « Zéro, ici Écho deux, à la station Odin, à vous. »  
   → Odéon par le son, signalé
59. « Zéro, ici Foxtrot trois, sur la rude Rennes, à vous. »  
   → rue de Rennes
60. « Zéro, ici Golf quatre, près de San Sulpice, à vous. »  
   → Saint-Sulpice
61. « Zéro, ici Hôtel un, à l'église Saint Germain de Pré, à vous. »  
   → Saint-Germain-des-Prés
62. « Zéro, ici Kilo deux, à la station Mabion, à vous. »  
   → Mabillon
63. « Zéro, ici Sierra deux, au jardin du Luxemburg, à vous. »  
   → jardin du Luxembourg
64. « Zéro, ici Alpha deux, au Pantion, à vous. »  
   → Panthéon
65. « Zéro, ici Bravo deux, à la tour banane, à vous. »  
   → lieu inconnu : rien sur la carte
66. « Zéro, ici Charlie deux, à la tour Eiffel, à vous. »  
   → hors zone : rien sur la carte

## G. Coordonnées

67. « Zéro, ici Delta trois, carroyage cinq un deux un un zéro, à vous. »  
   → carré de 100 m 31U DQ 512 110
68. « Zéro, ici Écho un, coordonnées trente et un U D Q cinq un deux un un zéro, à vous. »  
   → même carré
69. « Zéro, ici Foxtrot trois, carroyage neuf neuf neuf neuf neuf neuf, à vous. »  
   → hors zone : répétez
70. « Zéro, ici Golf quatre, carroyage cinq un deux un un, à vous. »  
   → coordonnée invalide : répétez
71. « Zéro, ici Hôtel un, carroyage neuf neuf neuf neuf neuf neuf, près de l'église Saint-Sulpice, à vous. »  
   → coordonnée fausse, utilise l'église

## H. Observations

72. « Zéro, ici Alpha un, contact, deux chars ennemis se dirigent vers le nord, trois cents mètres à l'est de l'église, à vous. »  
   → 2 chars ennemis, cap nord
73. « Zéro, ici Bravo un, contact, infanterie ennemie, une dizaine, au marché Saint-Germain, à vous. »  
   → infanterie ennemie
74. « Zéro, ici Charlie un, contact, véhicule inconnu, à l'arrêt, près du théâtre de l'Odéon, à vous. »  
   → camp inconnu (jaune)
75. « Zéro, ici Delta un, des civils se rassemblent place Saint-Sulpice, à vous. »  
   → civils (vert)
76. « Zéro, ici Écho un, contact, drone au-dessus de nous, à vous. »  
   → drone à la position d'Écho 1
77. « Zéro, ici Foxtrot trois, drone ennemi au-dessus du Panthéon, cap à l'ouest, à vous. »  
   → drone ennemi, cap ouest
78. « Zéro, ici Golf quatre, un autre drone au-dessus du Panthéon, à vous. »  
   → deuxième drone, pas fusionné
79. « Zéro, ici Hôtel un, je vois les mêmes chars, trois cents mètres à l'est de l'église, à vous. »  
   → fusionné : vu par deux
80. « Zéro, ici Kilo deux, engin explosif rue de Tournon, ne pas approcher, à vous. »  
   → EEI : reste sur la carte
81. « Zéro, ici Sierra deux, tireur d'élite à deux cents mètres au nord de moi, à vous. »  
   → mesuré depuis Sierra 2
82. « Zéro, ici Alpha deux, contact, blindé ennemi à mes deux heures, environ cent mètres, à vous. »  
   → anneau de 100 m autour d'Alpha 2 (méthode horaire)
83. « Zéro, ici Bravo deux, drone ami au-dessus de nous, c'est le nôtre, à vous. »  
   → drone ami, pas d'alerte
84. « Zéro, ici Charlie deux, contact, artillerie ennemie qui tire, au sud de la tour Montparnasse, à vous. »  
   → artillerie ennemie
85. « Zéro, ici Delta trois, mine au coin de la rue Guynemer et de la rue de Vaugirard, à vous. »  
   → mine : alerte même sans « ennemi »
86. « Zéro, ici Écho deux, hélicoptère inconnu au-dessus du palais du Luxembourg, à vous. »  
   → hélicoptère, camp inconnu
87. « Zéro, ici Foxtrot trois, contact, char ennemi au palais du Luxembourg, à vous. »  
   → deuxième contact (les premiers allaient au nord)
88. « Zéro, ici Golf quatre, le pont des Arts est détruit, à vous. »  
   → état du lieu : détruit
89. « Zéro, ici Hôtel un, la rue de Seine est bloquée, à vous. »  
   → état du lieu : bloqué
90. « Zéro, ici Kilo deux, la rue de Seine est rouverte, à vous. »  
   → état du lieu : rouvert

## I. Ordres

91. « Charlie un, ici Zéro, rejoignez la fontaine Médicis, à vous. »  
   → ordre : destination en pointillé
92. « Zéro, ici Charlie un, bien reçu, j'exécute, terminé. »  
   → accusé de l'ordre
93. « Zéro, ici Charlie un, à la fontaine Médicis, à vous. »  
   → arrivée : ordre terminé
94. « Delta un, ici Zéro, restez sur position, à vous. »  
   → ordre de tenir

## J. Mélange et répétitions

95. « Zero, this is Alpha deux, south of l'église Saint-Sulpice, over. »  
   → franglais : Alpha 2 au sud de l'église
96. « Zéro, ici Bravo un, en route vers le boulevard Saint-Germain, à vous. »  
   → déplacement vers le boulevard
97. « Zéro, ici Charlie deux, entre Mabillon et Odéon, à vous. »  
   → entre les deux
98. « Zéro, ici Écho un, je répète, au Panthéon, à vous. »  
   → Écho 1 au Panthéon
99. « Zéro, ici Sierra deux, répétez votre dernier message, à vous. »  
   → demande de répétition
100. « À toutes les stations, ici Zéro, fin de l'exercice, terminé. »  
   → rien sur la carte

## Checked offline

Every line behaves as written with the offline rules (no cloud model). Checked by playing the script through the radio-net layer: `python -m scripts.make_edge_script_fr --play`.
