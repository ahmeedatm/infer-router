"""Tests du pool de modèles (app.llm.pool).

Contrat : generic_pool() ne contient QUE les deux tiers génériques (light,
heavy), sans les 4 spécialistes de default_pool(). Ce pool réduit sert
désormais d'ablation à deux tiers : la qualité des spécialistes, longtemps
posée a priori, est mesurée depuis exp_specialist, donc elle ne fausse plus
le comparatif light/heavy et default_pool redevient le pool de référence.
"""
from app.llm.pool import default_pool, generic_pool


class TestGenericPool:
    def test_contains_only_light_and_heavy_generic(self):
        pool = generic_pool()
        assert len(pool) == 2
        tiers = {m.tier for m in pool}
        assert tiers == {"light", "heavy"}

    def test_no_domain_specialist(self):
        pool = generic_pool()
        assert all(m.domain is None for m in pool)

    def test_fresh_tuple_each_call(self):
        assert generic_pool() == generic_pool()
        assert generic_pool() is not generic_pool()


class TestDefaultPool:
    def test_includes_generic_pair_plus_four_specialists(self):
        pool = default_pool()
        assert len(pool) == 6
        specialists = [m for m in pool if m.domain is not None]
        assert len(specialists) == 4

    def test_default_pool_superset_of_generic_pool(self):
        default_ids = {m.model_id for m in default_pool()}
        generic_ids = {m.model_id for m in generic_pool()}
        assert generic_ids <= default_ids
