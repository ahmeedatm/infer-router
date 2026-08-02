# Campagne de validation réelle

InferRouter est mesuré en réutilisant le plan déjà produit par le tier
qu'il choisit, ce qui isole la décision de routage de la variance d'un
modèle entre deux appels. Les autres stratégies viennent de cases.json,
InferRouter de cases-inferrouter.json.

| Stratégie | simple | medium | complex | Global | Taux moyen |
|---|---|---|---|---|---|
| heavy | 100 % | 75 % | 62 % | 79 % | 79 % |
| inferrouter | 88 % | 75 % | 62 % | 75 % | 75 % |
| light | 75 % | 62 % | 62 % | 67 % | 69 % |
| noop | 0 % | 0 % | 0 % | 0 % | 6 % |
| oracle | 100 % | 100 % | 100 % | 100 % | 100 % |
