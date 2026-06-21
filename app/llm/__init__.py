"""InferRouter-LLM — cœur post-pivot (ADR-005).

Routage d'intents réseau (texte) vers des LLM cibles, avec évaluation par un
LLM-Juge local. Ce package est construit pendant le spike risk-first et
découplé de l'application FastAPI pré-pivot (load-balancing d'images).
"""
