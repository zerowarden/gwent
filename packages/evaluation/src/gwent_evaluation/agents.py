from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.arena import BotFamilyDefinition, bot_family
from gwent_engine.ai.baseline import BaseProfileDefinition, get_base_profile_definition
from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfiguration
from gwent_engine.ai.baseline.policy_artifacts import PolicyArtifact
from gwent_engine.ai.observations import OBSERVATION_CONTRACT_VERSION
from gwent_engine.ai.policy import BaselineConfig
from gwent_shared.json_payloads import canonical_digest

from gwent_evaluation.models import AgentSpec, BotFamily, SuiteSpec


class AgentResolutionError(ValueError):
    """Raised when an agent spec cannot be resolved to an engine implementation."""


def candidate_from_artifact(candidate: AgentSpec, path: Path) -> AgentSpec:
    """Keep benchmark labels and opponents while binding the artifact's exact values."""
    if candidate.family is not BotFamily.HEURISTIC:
        raise AgentResolutionError("A policy artifact requires a heuristic candidate.")
    return replace(
        candidate, profile=None, heuristic_configuration=PolicyArtifact.load(path).configuration
    )


@dataclass(frozen=True, slots=True)
class ResolvedAgent:
    """An agent spec bound to its canonical engine family and configuration."""

    spec: AgentSpec
    family: BotFamilyDefinition
    profile: BaseProfileDefinition | None

    @property
    def agent_id(self) -> str:
        return self.spec.agent_id

    @property
    def family_id(self) -> str:
        return self.family.family.value

    @property
    def profile_id(self) -> str | None:
        return None if self.profile is None else self.profile.profile_id

    @property
    def accepts_seed(self) -> bool:
        return self.family.accepts_seed

    def build(self, *, bot_id: str, seed: int | None = None) -> BotAgent:
        """Build the engine bot, applying the seed only when the family supports one."""

        configuration = self.heuristic_configuration
        if configuration is not None:
            return self.family.build_resolved(bot_id=bot_id, heuristic_configuration=configuration)
        return self.family.build_resolved(
            bot_id=bot_id,
            profile=self.profile,
            seed=seed if self.accepts_seed else None,
        )

    def configuration(self) -> dict[str, object]:
        configuration = self.heuristic_configuration
        if configuration is not None:
            return {
                "family": self.family_id,
                "heuristic_configuration_digest": configuration.digest(),
                "observation_contract_version": OBSERVATION_CONTRACT_VERSION,
            }
        return {
            "family": self.family_id,
            "profile": self.profile,
            "fixed_configuration": self.family.fixed_configuration,
            "observation_contract_version": OBSERVATION_CONTRACT_VERSION,
        }

    def digest(self) -> str:
        return canonical_digest(self.configuration())

    @property
    def heuristic_configuration(self) -> HeuristicConfiguration | None:
        if self.family.family is not BotFamily.HEURISTIC:
            return None
        assert self.profile is not None
        explicit = self.spec.heuristic_configuration
        baseline = (
            explicit.baseline
            if explicit is not None
            else cast(BaselineConfig, self.family.fixed_configuration["baseline"])
        )
        return HeuristicConfiguration(baseline=baseline, profile=self.profile)

    def snapshot(self) -> AgentSpec:
        configuration = self.heuristic_configuration
        if configuration is None:
            return self.spec
        return replace(self.spec, profile=None, heuristic_configuration=configuration)


def snapshot_suite(suite: SuiteSpec) -> SuiteSpec:
    """Materialize heuristic values before scheduling or persisting a run."""
    return replace(
        suite,
        candidate=resolve_agent(suite.candidate).snapshot(),
        opponents=tuple(resolve_agent(agent).snapshot() for agent in suite.opponents),
    )


def resolve_agent(spec: AgentSpec) -> ResolvedAgent:
    try:
        family = bot_family(spec.family)
    except ValueError as error:
        raise AgentResolutionError(f"Unknown bot family: {spec.family.value!r}") from error
    return ResolvedAgent(
        spec=spec,
        family=family,
        profile=_resolve_profile(spec, family=family),
    )


def _resolve_profile(
    spec: AgentSpec,
    *,
    family: BotFamilyDefinition,
) -> BaseProfileDefinition | None:
    if spec.heuristic_configuration is not None:
        return spec.heuristic_configuration.profile
    if not family.accepts_profile:
        if spec.profile is not None:
            raise AgentResolutionError(
                f"Agent {spec.agent_id!r} family {family.family!r} does not accept a profile."
            )
        return None
    profile_id = spec.profile if spec.profile is not None else family.default_profile_id
    if profile_id is None:
        raise AgentResolutionError(
            f"Agent {spec.agent_id!r} family {family.family!r} has no default profile."
        )
    try:
        return get_base_profile_definition(profile_id)
    except ValueError as error:
        raise AgentResolutionError(
            f"Agent {spec.agent_id!r} profile {profile_id!r} is not recognized."
        ) from error
