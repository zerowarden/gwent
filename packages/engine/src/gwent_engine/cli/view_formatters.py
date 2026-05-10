from __future__ import annotations

from collections.abc import Mapping

from gwent_engine.core.ids import CardInstanceId


def card_ref_text(
    card_instance_id: CardInstanceId,
    card_names_by_instance_id: Mapping[CardInstanceId, str],
    card_values_by_instance_id: Mapping[CardInstanceId, int],
) -> str:
    card_name = card_names_by_instance_id.get(card_instance_id)
    if card_name is None:
        return str(card_instance_id)
    card_value = card_values_by_instance_id.get(card_instance_id)
    if card_value is None:
        return f"[{card_name}]"
    return f"[{card_name}] ({card_value})"


def card_list_text(
    card_ids: tuple[CardInstanceId, ...],
    *,
    card_names_by_instance_id: Mapping[CardInstanceId, str],
    card_values_by_instance_id: Mapping[CardInstanceId, int],
) -> str:
    if not card_ids:
        return "-"
    return ", ".join(
        card_ref_text(
            card_id,
            card_names_by_instance_id,
            card_values_by_instance_id,
        )
        for card_id in card_ids
    )


def board_total(
    strengths_by_instance_id: Mapping[CardInstanceId, int],
    card_ids: tuple[CardInstanceId, ...],
) -> int:
    return sum(strengths_by_instance_id.get(card_id, 0) for card_id in card_ids)


def board_row_label(label: str, *, active: bool) -> str:
    return f"{label} (weather)" if active else label


def board_card_list_text(
    card_ids: tuple[CardInstanceId, ...],
    *,
    card_names_by_instance_id: Mapping[CardInstanceId, str],
    strengths_by_instance_id: Mapping[CardInstanceId, int],
) -> str:
    if not card_ids:
        return "-"
    return ", ".join(
        (
            f"[{card_names_by_instance_id.get(card_id, str(card_id))}] "
            f"({strengths_by_instance_id.get(card_id, 0)})"
        )
        for card_id in card_ids
    )
