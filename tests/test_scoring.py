import pytest

from uoh_mh01.domain.scoring import TerminalCondition, score_for
from uoh_mh01.domain.state import Side


@pytest.mark.parametrize(
    "condition",
    [TerminalCondition.CAPTURE_LANDING, TerminalCondition.CAPTURE_BARRIER, TerminalCondition.CAPTURE_ENTRAPMENT],
)
def test_all_capture_paths_score_the_same_pair(config, condition):
    assert score_for(condition, config.scoring) == (config.scoring.capture_cop, config.scoring.capture_thief)


def test_survival_scores_the_survival_pair(config):
    assert score_for(TerminalCondition.SURVIVAL, config.scoring) == (
        config.scoring.survival_cop,
        config.scoring.survival_thief,
    )


@pytest.mark.parametrize("offending_side", [Side.POLICE, Side.THIEF])
def test_technical_loss_is_symmetric_zero_pair_regardless_of_offender(config, offending_side):
    # TODO.md is explicit: "technical loss 0/0" — both sides score
    # scoring.technical_loss, not just the offending side.
    assert score_for(TerminalCondition.TECHNICAL_LOSS, config.scoring, offending_side=offending_side) == (
        config.scoring.technical_loss,
        config.scoring.technical_loss,
    )


def test_technical_loss_scores_the_symmetric_pair_with_no_offending_side(config):
    # offending_side is optional context for TECHNICAL_LOSS (e.g. a
    # wire-protocol divergence has no single attributable guilty party) —
    # the score does not depend on it. See PRD-02 "Stage 2 corrections".
    assert score_for(TerminalCondition.TECHNICAL_LOSS, config.scoring) == (
        config.scoring.technical_loss,
        config.scoring.technical_loss,
    )


def test_tie_is_reachable_and_scores_the_tie_pair(config):
    # No rule in the rulebook triggers TIE (see PRD-01 "Open questions"), but
    # the scoring table must still be able to produce it.
    assert score_for(TerminalCondition.TIE, config.scoring) == (config.scoring.tie_score, config.scoring.tie_score)
