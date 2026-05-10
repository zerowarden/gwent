from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from gwent_engine.ai.baseline.policies.leader import (
    AGGRESSIVE_LEADER_POLICY,
    CONSERVATIVE_LEADER_POLICY,
)
from gwent_engine.ai.baseline.policies.protocol import (
    LeaderPolicy,
    ScorchPolicy,
)
from gwent_engine.ai.baseline.policies.scorch import (
    OPPORTUNISTIC_SCORCH_POLICY,
    RESERVE_SCORCH_POLICY,
)
from gwent_engine.ai.policy import (
    LEGACY_PRESERVE_LEADER_POLICY_ID,
    LEGACY_TEMPO_LEADER_POLICY_ID,
    PolicySelection,
)
from gwent_engine.core.errors import DefinitionLoadError


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    """Resolved policy objects for one active heuristic profile.

    This keeps the wiring layer simple: profile composition resolves policy
    names once and then hands the bot a ready-to-use bundle.
    """

    scorch: ScorchPolicy
    leader: LeaderPolicy


@dataclass(frozen=True, slots=True)
class PolicyCatalog:
    """Central registry for available named policies.

    The catalog owns validation and resolution so profile loading and profile
    composition do not need to import or index separate maps directly.
    """

    scorch: Mapping[str, ScorchPolicy]
    leader: Mapping[str, LeaderPolicy]

    def resolve(self, selection: PolicySelection) -> PolicyBundle:
        return PolicyBundle(
            scorch=self.scorch[selection.scorch],
            leader=self.leader[selection.leader],
        )

    def validate(self, selection: PolicySelection, *, context: str) -> None:
        self._require_known(selection.scorch, self.scorch, context=context)
        self._require_known(selection.leader, self.leader, context=context)

    def _require_known(
        self,
        policy_name: str,
        policies: Mapping[str, object],
        *,
        context: str,
    ) -> None:
        if policy_name not in policies:
            raise DefinitionLoadError(f"{context} references unknown policy {policy_name!r}.")


SCORCH_POLICIES: Mapping[str, ScorchPolicy] = MappingProxyType(
    {
        OPPORTUNISTIC_SCORCH_POLICY.name: OPPORTUNISTIC_SCORCH_POLICY,
        RESERVE_SCORCH_POLICY.name: RESERVE_SCORCH_POLICY,
    }
)

LEADER_POLICIES: Mapping[str, LeaderPolicy] = MappingProxyType(
    {
        CONSERVATIVE_LEADER_POLICY.name: CONSERVATIVE_LEADER_POLICY,
        AGGRESSIVE_LEADER_POLICY.name: AGGRESSIVE_LEADER_POLICY,
        LEGACY_PRESERVE_LEADER_POLICY_ID: CONSERVATIVE_LEADER_POLICY,
        LEGACY_TEMPO_LEADER_POLICY_ID: AGGRESSIVE_LEADER_POLICY,
    }
)

POLICY_CATALOG = PolicyCatalog(
    scorch=SCORCH_POLICIES,
    leader=LEADER_POLICIES,
)


__all__ = [
    "LEADER_POLICIES",
    "POLICY_CATALOG",
    "SCORCH_POLICIES",
    "PolicyBundle",
    "PolicyCatalog",
    "PolicySelection",
]
