"""
tests/test_scoring.py
Covers the NameError bug from the original (f0_male/f0_female typo)
and validates scoring logic end-to-end.
"""
import pytest
from app.config import Settings
from app.services.features import extract_all
from app.services.scoring import score


def _settings(**overrides) -> Settings:
    """Build a Settings instance with test-friendly defaults."""
    return Settings(
        aws_region="us-east-1",
        s3_bucket="test-bucket",
        dynamodb_table="test-table",
        **overrides,
    )


def test_score_does_not_raise_name_error(sine_440, sr):
    """
    Regression: original code had `self.norms[f0_male]` (NameError).
    This test ensures scoring completes without NameError on both genders.
    """
    settings = _settings()
    bundle = extract_all(sine_440, sr)
    # Should not raise
    result = score(bundle, settings)
    assert result is not None


def test_score_range(sine_440, sr):
    settings = _settings()
    bundle = extract_all(sine_440, sr)
    result = score(bundle, settings)
    assert 0.0 <= result.overall_health_score <= 10.0


def test_clean_sine_scores_high(sine_440, sr):
    """A pure sine wave should score well (low jitter, high HNR)."""
    settings = _settings()
    bundle = extract_all(sine_440, sr)
    result = score(bundle, settings)
    assert result.overall_health_score >= 6.0, (
        f"Pure sine should score >= 6, got {result.overall_health_score}"
    )


def test_both_locales_present(sine_440, sr):
    """Result must always carry both PT and EN messages."""
    settings = _settings()
    bundle = extract_all(sine_440, sr)
    result = score(bundle, settings)
    assert result.patient_message_pt
    assert result.patient_message_en
    assert len(result.recommendations_pt) >= 1
    assert len(result.recommendations_en) >= 1


def test_unanalysable_audio_raises(silence, sr):
    """silence → f0=None → score() should raise ValueError, not crash with NameError."""
    settings = _settings()
    bundle = extract_all(silence, sr)
    assert bundle.f0 is None
    with pytest.raises(ValueError, match="F0 extraction failed"):
        score(bundle, settings)


def test_score_weights_sum_to_one():
    s = _settings()
    total = (
        s.score_weight_jitter
        + s.score_weight_shimmer
        + s.score_weight_hnr
        + s.score_weight_voiced
    )
    assert abs(total - 1.0) < 0.001, f"Weights must sum to 1.0, got {total}"
