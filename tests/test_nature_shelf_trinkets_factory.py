import numpy as np

from infinigen.assets.objects import creatures, mollusk, rocks
from infinigen.assets.objects.creatures import carnivore, herbivore
from infinigen.assets.objects.creatures.parts import generic_nurbs
from infinigen.assets.objects.elements.nature_shelf_trinkets import generate
from infinigen.core.util.math import FixedSeed


def test_nature_shelf_creature_filter_env_defaults_off(monkeypatch):
    monkeypatch.delenv(
        generate.DISABLE_NATURE_SHELF_CREATURE_TRINKETS_ENV_VAR, raising=False
    )

    assert generate._disable_nature_shelf_creature_trinkets_enabled() is False


def test_nature_shelf_factory_choices_default_unchanged():
    factories, probs = generate._nature_shelf_trinket_factory_choices(
        disable_creatures=False
    )

    assert factories is generate.NatureShelfTrinketsFactory.factories
    assert probs is generate.NatureShelfTrinketsFactory.probs
    assert creatures.CarnivoreFactory in factories
    assert creatures.HerbivoreFactory in factories
    np.testing.assert_array_equal(probs, generate.NatureShelfTrinketsFactory.probs)


def test_nature_shelf_factory_choices_filters_creatures():
    factories, probs = generate._nature_shelf_trinket_factory_choices(
        disable_creatures=True
    )

    assert factories is not generate.NatureShelfTrinketsFactory.factories
    assert creatures.CarnivoreFactory not in factories
    assert creatures.HerbivoreFactory not in factories
    assert len(factories) == len(generate.NatureShelfTrinketsFactory.factories) - 2
    assert len(probs) == len(factories)


def test_nature_shelf_factory_choices_probs_renormalize_without_creatures():
    factories, probs = generate._nature_shelf_trinket_factory_choices(
        disable_creatures=True
    )
    normalized = probs / probs.sum()

    assert np.isclose(normalized.sum(), 1.0)
    assert all(prob > 0.0 for prob in normalized)
    assert len(normalized) == len(factories)


def test_nature_shelf_creature_filter_env_truthy(monkeypatch):
    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv(
            generate.DISABLE_NATURE_SHELF_CREATURE_TRINKETS_ENV_VAR, value
        )

        assert generate._disable_nature_shelf_creature_trinkets_enabled() is True


def test_nature_shelf_creature_filter_env_falsey(monkeypatch):
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv(
            generate.DISABLE_NATURE_SHELF_CREATURE_TRINKETS_ENV_VAR, value
        )

        assert generate._disable_nature_shelf_creature_trinkets_enabled() is False


def test_nature_shelf_creature_helpers_unchanged():
    carnivore = object.__new__(creatures.CarnivoreFactory)
    herbivore = object.__new__(creatures.HerbivoreFactory)
    boulder = object.__new__(rocks.BoulderFactory)

    assert generate._is_creature_base_factory(carnivore) is True
    assert generate._is_creature_base_factory(herbivore) is True
    assert generate._is_creature_base_factory(boulder) is False


def test_nature_shelf_fast_stable_pose_allowed_unchanged():
    clam = object.__new__(mollusk.ClamFactory)
    mussel = object.__new__(mollusk.MusselFactory)
    boulder = object.__new__(rocks.BoulderFactory)

    assert generate._fast_stable_pose_allowed(clam) is True
    assert generate._fast_stable_pose_allowed(mussel) is True
    assert generate._fast_stable_pose_allowed(boulder) is False


def test_nature_shelf_creature_nurbs_templates_available():
    for prefix in (
        "body_feline",
        "head_carnivore",
        "body_herbivore",
        "head_herbivore",
    ):
        assert any(k.startswith(prefix) for k in generic_nurbs.NURBS_KEYS)


def test_nature_shelf_creature_genomes_sample_nurbs_handles():
    with FixedSeed(0):
        carnivore_genome = carnivore.tiger_genome()

    with FixedSeed(0):
        herbivore_genome = herbivore.herbivore_genome()

    assert carnivore_genome.parts.item.part_factory.params["length"] > 0
    assert herbivore_genome.parts.item.part_factory.params["length"] > 0


def test_nature_shelf_creature_factories_sample_nurbs_handles(monkeypatch):
    def fake_genome_to_creature(genome, name):
        return object(), []

    def fake_join_and_rig_parts(root, parts, genome, **kwargs):
        return object(), [], None, []

    for module in (carnivore, herbivore):
        monkeypatch.setattr(module.creature, "genome_to_creature", fake_genome_to_creature)
        monkeypatch.setattr(module, "offset_center", lambda root: None)
        monkeypatch.setattr(module.joining, "join_and_rig_parts", fake_join_and_rig_parts)
        monkeypatch.setattr(module.butil, "parent_to", lambda *args, **kwargs: None)

    placeholder = object()

    with FixedSeed(0):
        root = creatures.CarnivoreFactory(factory_seed=0, hair=False).create_asset(
            0, placeholder
        )
    assert root is not None

    with FixedSeed(0):
        root = creatures.HerbivoreFactory(factory_seed=0, hair=False).create_asset(
            0, placeholder
        )
    assert root is not None
