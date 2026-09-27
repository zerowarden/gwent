"""Construct proposal backends from frozen study declarations."""

from gwent_evaluation.models import SpecError
from gwent_evaluation.tuning.models import OptimizerMethod, StudySpec
from gwent_evaluation.tuning.optimizers import ProposalOptimizer, RandomSearch
from gwent_evaluation.tuning.parameters import encode_parameters


def create_optimizer(study: StudySpec, method: OptimizerMethod) -> ProposalOptimizer:
    """Construct only declared settings; optional dependencies load only for CMA."""
    settings = next((item for item in study.optimizers if item.method is method), None)
    if settings is None:
        raise SpecError("Optimizer method is not declared in the study.")
    if method is OptimizerMethod.RANDOM:
        return RandomSearch(settings, dimensions=len(study.parameter_space.parameters))
    try:
        from gwent_evaluation.tuning.cma_backend import CmaEsSearch
    except ImportError as error:
        raise SpecError(
            "CMA requires the optional gwent-evaluation[tuning] dependencies."
        ) from error
    return CmaEsSearch(
        settings,
        initial_mean=encode_parameters(
            study.parameter_space, study.incumbent, frozen_configuration=study.incumbent
        ),
    )
