from __future__ import annotations

from dataclasses import replace

import pytest
from gwent_evaluation.assets import resolve_assets
from gwent_evaluation.provenance import canonical_digest


def test_resolve_assets_rejects_unknown_deck() -> None:
    assets = resolve_assets()

    with pytest.raises(ValueError, match="Unknown sample deck id"):
        _ = assets.deck("missing_deck")


def test_deck_digest_is_deck_specific() -> None:
    assets = resolve_assets()

    monsters = assets.deck_digest("monsters_muster_swarm_strict")
    nilfgaard = assets.deck_digest("nilfgaard_spy_medic_control_strict")

    assert monsters != nilfgaard


def test_deck_digest_changes_with_deck_contents() -> None:
    assets = resolve_assets()
    deck = assets.deck("monsters_muster_swarm_strict")
    mutated = replace(deck, card_definition_ids=deck.card_definition_ids[:-1])

    assert canonical_digest(deck) != canonical_digest(mutated)
