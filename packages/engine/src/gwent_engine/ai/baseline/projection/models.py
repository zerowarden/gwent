from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.core import LeaderAbilityKind, Row


@dataclass(frozen=True, slots=True)
class ProjectedRowState:
    row: Row
    effective_strength: int
    non_hero_effective_strength: int
    non_hero_unit_count: int
    horn_active: bool
    scorchable_unit_strengths: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PublicBoardProjection:
    viewer_score: int
    opponent_score: int
    viewer_rows: tuple[ProjectedRowState, ProjectedRowState, ProjectedRowState]
    opponent_rows: tuple[ProjectedRowState, ProjectedRowState, ProjectedRowState]
    active_weather_rows: tuple[Row, ...]

    @property
    def score_gap(self) -> int:
        return self.viewer_score - self.opponent_score


@dataclass(frozen=True, slots=True)
class ScorchImpact:
    """Exact public-board resolution of Scorch at the current moment.

    This distinguishes damage dealt to the viewer versus the opponent using the
    same effective-strength rules as the projection layer, so boosted targets
    and self-damaging Scorch lines are evaluated consistently.
    """

    viewer_strength_lost: int
    opponent_strength_lost: int

    @property
    def total_strength_lost(self) -> int:
        return self.viewer_strength_lost + self.opponent_strength_lost

    @property
    def net_swing(self) -> int:
        return self.opponent_strength_lost - self.viewer_strength_lost

    @property
    def has_live_targets(self) -> bool:
        return self.total_strength_lost > 0

    @property
    def self_damaging(self) -> bool:
        return self.net_swing <= 0 and self.has_live_targets


@dataclass(frozen=True, slots=True)
class PlayActionProjection:
    current_score_gap: int
    viewer_score_after: int
    opponent_score_after: int
    projected_score_gap_after: int
    projected_net_board_swing: int
    viewer_hand_count_after: int
    opponent_hand_count_after: int
    post_action_hand_value: int
    horn_option_value_before: float
    horn_option_value_after: float
    horn_future_option_delta: float
    projected_weather_loss: int
    projected_scorch_loss: int
    viewer_scorch_damage: int
    opponent_scorch_damage: int
    net_scorch_swing: int
    projected_synergy_value: int
    projected_dead_card_penalty: int
    projected_avenger_value: int


@dataclass(frozen=True, slots=True)
class LeaderActionProjection:
    """Public tactical effect of a leader action from the current position.

    This intentionally models only the deterministic public impact that the AI
    can already audit from observation data. Unsupported leader kinds return
    `None` from `project_leader_action(...)`, allowing evaluation to fall back
    to legacy generic leader appetite terms.
    """

    ability_kind: LeaderAbilityKind
    projected_net_board_swing: int
    projected_hand_value_delta: int
    viewer_hand_count_delta: int
    is_noop: bool
    minimum_row_total: int | None
    opponent_row_total: int | None
    live_targets: int
    affected_row: Row | None = None
    weather_rows_changed: tuple[Row, ...] = ()
    moved_units: int = 0

    @property
    def has_effect(self) -> bool:
        return not self.is_noop
