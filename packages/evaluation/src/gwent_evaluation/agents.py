from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.arena import BotFamilyDefinition, bot_family
from gwent_engine.ai.baseline import BaseProfileDefinition, get_base_profile_definition
from gwent_engine.ai.observations import OBSERVATION_CONTRACT_VERSION

from gwent_evaluation.models import AgentSpec
from gwent_evaluation.provenance import canonical_digest


class AgentResolutionError(ValueError):
    """Raised when an agent spec cannot be resolved to an engine implementation."""


@dataclass(frozen=True, slots=True)
class ResolvedAgent:
    """An agent spec bound to its canonical engine family and named configuration."""

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

        return self.family.build_seeded(
            bot_id=bot_id,
            profile_id=self.profile_id,
            seed=seed,
        )

    def configuration(self) -> dict[str, object]:
        return {
            "family": self.family_id,
            "profile": self.profile,
            "fixed_configuration": self.family.fixed_configuration,
            "observation_contract_version": OBSERVATION_CONTRACT_VERSION,
        }

    def digest(self) -> str:
        return canonical_digest(self.configuration())


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
