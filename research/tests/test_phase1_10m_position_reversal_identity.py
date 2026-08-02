"""R4 canonical identity grammar and collision regressions."""

from __future__ import annotations

import pytest

from research.phase1_10m_position_reversal_oracle import (
    Event,
    IDENTITY_ASCII_ALNUM,
    IDENTITY_COMPONENT_MAX_LENGTH,
    IDENTITY_COMPONENT_SAFE_CHARS,
    PositionReversalEngine,
    ReasonCode,
    State,
    canonical_identity_component,
    canonical_source_identity,
)
from research.tests.fixture_phase1_10m_position_reversal import (
    LOWER_TRIGGER,
    bar,
    prior_atr,
    resistance_band,
    support_band,
)


def _support_reclaim_bar():
    return bar(11, 30, 7430.0, 7443.8, 7420.9, 7443.5)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("A", True),
        ("SATY:Map_Level-1", True),
        ("v1.2-2026", True),
        ("", False),
        (" A", False),
        ("A ", False),
        ("A B", False),
        ("A|B", False),
        ("A@B", False),
        ("A#B", False),
        ("Ä", False),
        ("-A", False),
        ("A-", False),
        ("A" * 64, True),
        ("A" * 65, False),
    ),
)
def test_python_component_grammar_matches_the_generated_pine_reference_model(
    value: str, expected: bool
) -> None:
    # This is the exact predicate rendered in Pine: raw==trim, 1..64,
    # alphanumeric boundaries, and every character in the finite ASCII set.
    pine_reference = (
        1 <= len(value) <= IDENTITY_COMPONENT_MAX_LENGTH
        and value == value.strip()
        and value[0:1] in IDENTITY_ASCII_ALNUM
        and value[-1:] in IDENTITY_ASCII_ALNUM
        and all(character in IDENTITY_COMPONENT_SAFE_CHARS for character in value)
    )
    try:
        canonical_identity_component(value)
        python_result = True
    except ValueError:
        python_result = False

    assert pine_reference is expected
    assert python_result is expected


@pytest.mark.parametrize(
    ("source_id", "source_version"),
    (
        (" PADDED", "v1"),
        ("PADDED ", "v1"),
        ("PADDED", " v1"),
        ("PADDED", "v1 "),
        (" PADDED ", " v1 "),
    ),
)
def test_space_padded_band_identity_fails_closed_on_first_and_continuation_bar(
    source_id: str, source_version: str
) -> None:
    engine = PositionReversalEngine()
    padded = support_band(source_id=source_id, source_version=source_version)
    target = resistance_band(
        source_id="TARGET",
        source_version="v1",
        lower_bound=7480.0,
        upper_bound=7480.0,
    )

    first = engine.ingest(
        bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER),
        (padded, target),
        prior_atr(),
    )
    second = engine.ingest(
        bar(12, 10, 7421.2, 7432.0, 7421.0, 7422.0),
        (padded, target),
        prior_atr(),
    )

    for result in (first, second):
        assert result.event is Event.DATA_RESET
        assert result.reason_code is ReasonCode.SOURCE_NOT_READY
        assert result.state is State.DISABLED
        assert result.episode_id is None
        assert result.opportunity is None
        assert any(
            "IDENTITY_NON_CANONICAL" in item
            for item in result.source_rejections
        )


def test_dup_and_space_padded_dup_are_rejected_without_silent_normalization() -> None:
    result = PositionReversalEngine().ingest(
        bar(12, 0, 7430.0, 7480.0, 7420.9, 7430.0),
        (
            support_band(source_id="DUP", source_version="v1"),
            resistance_band(source_id=" DUP ", source_version="v1"),
        ),
        prior_atr(),
    )

    assert result.event is Event.DATA_RESET
    assert result.reason_code is ReasonCode.SOURCE_NOT_READY
    assert result.state is State.DISABLED
    assert result.episode_id is None
    assert result.opportunity is None
    assert result.source_rejections == (
        "RAW_ID(' DUP ','v1'):IDENTITY_NON_CANONICAL",
    )


def test_two_valid_duplicate_identities_use_one_canonical_registry_key() -> None:
    result = PositionReversalEngine().ingest(
        bar(12, 0, 7430.0, 7480.0, 7420.9, 7430.0),
        (
            support_band(source_id="DUP", source_version="v1"),
            resistance_band(source_id="DUP", source_version="v1"),
        ),
        prior_atr(),
    )

    assert result.event is Event.DATA_RESET
    assert result.reason_code is ReasonCode.SOURCE_IDENTITY_DRIFT
    assert result.state is State.DISABLED
    assert result.opportunity is None
    assert result.source_rejections == ("CID1:DUP@v1:DUPLICATE_IDENTITY",)


@pytest.mark.parametrize(
    ("source_id", "source_version"),
    (
        ("TARGET|X", "Y"),
        ("TARGET", "X|Y"),
    ),
)
def test_exact_pipe_collision_inputs_are_rejected_before_fingerprint_or_ready(
    source_id: str, source_version: str
) -> None:
    target = resistance_band(
        source_id=source_id,
        source_version=source_version,
        lower_bound=7480.0,
        upper_bound=7480.0,
    )

    with pytest.raises(ValueError, match="IDENTITY_GRAMMAR_INVALID"):
        _ = target.effective_fingerprint
    with pytest.raises(ValueError, match="IDENTITY_GRAMMAR_INVALID"):
        _ = target.identity
    with pytest.raises(ValueError, match="IDENTITY_GRAMMAR_INVALID"):
        canonical_source_identity(source_id, source_version)

    result = PositionReversalEngine().ingest(
        _support_reclaim_bar(),
        (support_band(), target),
        prior_atr(),
    )
    assert result.event is Event.DATA_RESET
    assert result.reason_code is ReasonCode.SOURCE_NOT_READY
    assert result.state is State.DISABLED
    assert result.episode_id is None
    assert result.opportunity is None
    assert any(
        "IDENTITY_GRAMMAR_INVALID" in item
        for item in result.source_rejections
    )


@pytest.mark.parametrize(
    ("source_id", "source_version"),
    (
        ("A@B", "C"),
        ("A", "B@C"),
        ("A#B", "C"),
        ("A", "B#C"),
        ("A B", "C"),
        ("A", "B C"),
        ("Ä", "v1"),
        ("A" * 65, "v1"),
        ("-A", "v1"),
        ("A-", "v1"),
    ),
)
def test_legacy_at_hash_whitespace_unicode_and_boundary_ambiguity_fail_closed(
    source_id: str, source_version: str
) -> None:
    candidate = resistance_band(
        source_id=source_id,
        source_version=source_version,
    )
    result = PositionReversalEngine().ingest(
        _support_reclaim_bar(),
        (support_band(), candidate),
        prior_atr(),
    )

    assert result.event is Event.DATA_RESET
    assert result.reason_code is ReasonCode.SOURCE_NOT_READY
    assert result.state is State.DISABLED
    assert result.opportunity is None
    assert any(
        "IDENTITY_GRAMMAR_INVALID" in item
        for item in result.source_rejections
    )


@pytest.mark.parametrize(
    ("source_id", "source_version"),
    (
        ("ATR|X", "Y"),
        ("ATR", "X|Y"),
        ("ATR@X", "Y"),
        ("ATR", "X@Y"),
        ("ATR#X", "Y"),
        ("ATR", "X#Y"),
        (" ATR ", "v1"),
    ),
)
def test_atr_identity_uses_the_same_fail_closed_delimiter_grammar(
    source_id: str, source_version: str
) -> None:
    candidate = prior_atr(source_id=source_id, source_version=source_version)
    with pytest.raises(ValueError):
        _ = candidate.effective_fingerprint
    result = PositionReversalEngine().ingest(
        _support_reclaim_bar(),
        (support_band(), resistance_band()),
        candidate,
    )

    assert result.event is Event.DATA_RESET
    assert result.reason_code is ReasonCode.ATR_NOT_READY
    assert result.state is State.DISABLED
    assert result.opportunity is None
    expected = (
        "IDENTITY_NON_CANONICAL"
        if source_id != source_id.strip() or source_version != source_version.strip()
        else "IDENTITY_GRAMMAR_INVALID"
    )
    assert any(expected in item for item in result.source_rejections)


def test_legal_safe_ascii_source_target_and_atr_identities_still_publish_ready() -> None:
    source = support_band(
        source_id="SATY:Map_Level-1",
        source_version="v1.2",
    )
    target = resistance_band(
        source_id="SATY:Map_Target-2",
        source_version="v1.2",
    )
    atr = prior_atr(
        source_id="SATY:ATR_Context-2026.07.31",
        source_version="v1",
    )

    result = PositionReversalEngine().ingest(
        _support_reclaim_bar(),
        (source, target),
        atr,
    )

    assert result.event is Event.BOUNCE_CONFIRMED
    assert result.reason_code is ReasonCode.READY
    assert result.state is State.READY
    assert result.opportunity is not None
    assert result.episode_id is not None
    assert "CID1:SATY:Map_Level-1@v1.2" in result.episode_id
    assert "CID1|B|SATY_ATR_MAP_LEVEL|CID1:SATY:Map_Level-1@v1.2|" in (
        result.episode_id
    )
    assert result.opportunity.target_source == "CID1:SATY:Map_Target-2@v1.2"
    assert result.opportunity.atr_source == (
        "CID1:SATY:ATR_Context-2026.07.31@v1"
    )
    assert "CID1|B|SATY_ATR_MAP_LEVEL|CID1:SATY:Map_Target-2@v1.2|" in (
        result.opportunity.opportunity_id
    )
    assert "CID1|A|PREVIOUS_COMPLETED_DAILY_ATR|" in (
        result.opportunity.opportunity_id
    )


def test_valid_reaction_target_and_atr_identity_changes_each_change_ids() -> None:
    current = _support_reclaim_bar()

    def ready(source_id: str, target_version: str, atr_id: str):
        result = PositionReversalEngine().ingest(
            current,
            (
                support_band(source_id=source_id),
                resistance_band(source_version=target_version),
            ),
            prior_atr(source_id=atr_id),
        )
        assert result.event is Event.BOUNCE_CONFIRMED
        assert result.reason_code is ReasonCode.READY
        assert result.opportunity is not None
        return result

    base = ready("SATY-ATR-LOWER-TRIGGER", "v1", "SATY-ATR-MAP")
    changed_reaction = ready("SATY-ATR-LOWER-TRIGGER-ALT", "v1", "SATY-ATR-MAP")
    changed_target = ready("SATY-ATR-LOWER-TRIGGER", "v2", "SATY-ATR-MAP")
    changed_atr = ready("SATY-ATR-LOWER-TRIGGER", "v1", "SATY-ATR-MAP-ALT")

    assert base.episode_id != changed_reaction.episode_id
    assert base.opportunity is not None
    assert changed_reaction.opportunity is not None
    assert changed_target.opportunity is not None
    assert changed_atr.opportunity is not None
    assert base.opportunity.opportunity_id != (
        changed_reaction.opportunity.opportunity_id
    )
    assert base.opportunity.opportunity_id != changed_target.opportunity.opportunity_id
    assert base.opportunity.opportunity_id != changed_atr.opportunity.opportunity_id


def test_colon_inside_components_remains_injective_around_reserved_at_separator() -> None:
    left = canonical_source_identity("A:B", "C")
    right = canonical_source_identity("A", "B:C")

    assert left == "CID1:A:B@C"
    assert right == "CID1:A@B:C"
    assert left != right


def test_enabled_bad_extra_band_is_global_fatal_but_disabled_bad_extra_is_exempt() -> None:
    current = _support_reclaim_bar()
    bad_extra = resistance_band(
        source_id="EXTRA|BAD",
        lower_bound=7550.0,
        upper_bound=7550.0,
    )

    blocked = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band(), bad_extra),
        prior_atr(),
    )
    assert blocked.event is Event.DATA_RESET
    assert blocked.reason_code is ReasonCode.SOURCE_NOT_READY
    assert blocked.state is State.DISABLED
    assert blocked.episode_id is None
    assert blocked.opportunity is None

    inactive_bad_extra = resistance_band(
        enabled=False,
        source_id="EXTRA|BAD",
        lower_bound=7550.0,
        upper_bound=7550.0,
    )
    ready = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band(), inactive_bad_extra),
        prior_atr(),
    )
    assert ready.event is Event.BOUNCE_CONFIRMED
    assert ready.reason_code is ReasonCode.READY
    assert ready.opportunity is not None


def test_identity_invalid_after_ready_suppresses_current_snapshot_but_preserves_ledger() -> None:
    engine = PositionReversalEngine()
    published = engine.ingest(
        _support_reclaim_bar(),
        (support_band(), resistance_band()),
        prior_atr(),
    )
    assert published.opportunity is not None
    immutable = published.opportunity

    reset = engine.ingest(
        bar(11, 40, 7443.5, 7445.0, 7438.0, 7440.0),
        (support_band(source_id=" BAD "), resistance_band()),
        prior_atr(),
    )

    assert reset.event is Event.DATA_RESET
    assert reset.reason_code is ReasonCode.SOURCE_NOT_READY
    assert reset.state is State.DISABLED
    assert reset.episode_id is None
    assert reset.opportunity is None
    assert engine.opportunities == (immutable,)
    assert engine.latest_opportunity == immutable


def test_watch_invalid_reset_first_valid_contiguous_bar_is_immediately_eligible() -> None:
    engine = PositionReversalEngine()
    watch = engine.ingest(
        bar(11, 20, 7434.0, 7438.0, 7420.9, LOWER_TRIGGER),
        (support_band(), resistance_band()),
        prior_atr(),
    )
    assert watch.event is Event.SUPPORT_WATCH

    reset = engine.ingest(
        bar(11, 30, 7421.2, 7425.0, 7420.9, 7422.0),
        (support_band(source_id="BAD|ID"), resistance_band()),
        prior_atr(),
    )
    assert reset.event is Event.DATA_RESET
    assert reset.episode_id is None
    assert reset.opportunity is None

    recovered = engine.ingest(
        bar(11, 40, 7430.0, 7443.8, 7420.9, 7443.5),
        (support_band(), resistance_band()),
        prior_atr(),
    )
    assert recovered.event is Event.BOUNCE_CONFIRMED
    assert recovered.reason_code is ReasonCode.READY
    assert recovered.opportunity is not None


def test_python_runtime_fails_closed_when_trim_normalized_atr_timeframe_drifts() -> None:
    engine = PositionReversalEngine()
    first = engine.ingest(
        bar(8, 0, 7440.0, 7445.0, 7435.0, 7440.0),
        (support_band(), resistance_band()),
        prior_atr(source_timeframe="D"),
    )
    assert first.data_valid is True

    changed = engine.ingest(
        bar(8, 10, 7440.0, 7445.0, 7435.0, 7440.0),
        (support_band(), resistance_band()),
        prior_atr(source_timeframe=" D "),
    )
    assert changed.event is Event.DATA_RESET
    assert changed.reason_code is ReasonCode.ATR_IDENTITY_DRIFT
    assert changed.state is State.DISABLED
    assert changed.opportunity is None
