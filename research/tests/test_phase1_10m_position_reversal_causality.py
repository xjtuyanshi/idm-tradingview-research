from __future__ import annotations

from dataclasses import replace

from research.phase1_10m_position_reversal_oracle import (
    Event,
    PositionReversalEngine,
    ReasonCode,
    SourceKind,
    Stability,
    State,
)
from research.tests.fixture_phase1_10m_position_reversal import (
    LOWER_TRIGGER,
    PUBLISHED_AT_MS,
    VALID_UNTIL_MS,
    bar,
    et_ms,
    prior_atr,
    resistance_band,
    support_band,
)


def test_only_allowlisted_source_kinds_can_authorize_the_lane() -> None:
    current = bar(11, 30, 7430.0, 7443.8, 7420.9, 7443.5)

    for bad_kind in (
        "POSTHOC-FORMING-CLOUD",
        "UNALLOWLISTED-RANDOM-LEVEL",
        "EMA_MTF_LEVEL",
        "OVERNIGHT_HIGH",
        "PREVIOUS_DAY_LOW",
    ):
        result = PositionReversalEngine().ingest(
            current,
            (
                support_band(
                    source_id=bad_kind,
                    source_kind=bad_kind,
                ),
                resistance_band(),
            ),
            prior_atr(),
        )
        assert result.event is Event.DATA_RESET
        assert result.state is State.DISABLED
        assert result.reason_code is ReasonCode.SOURCE_NOT_READY
        assert result.marker_text is None
        assert result.opportunity is None
        assert any(
            "SOURCE_KIND_NOT_ALLOWED" in item
            for item in result.source_rejections
        )

    unknown_target = PositionReversalEngine().ingest(
        current,
        (
            support_band(),
            resistance_band(
                source_id="UNALLOWLISTED-RANDOM-LEVEL",
                source_kind="UNALLOWLISTED-RANDOM-LEVEL",
            ),
        ),
        prior_atr(),
    )
    assert unknown_target.event is Event.DATA_RESET
    assert unknown_target.reason_code is ReasonCode.SOURCE_NOT_READY
    assert unknown_target.opportunity is None

    short_side_bad_reaction = PositionReversalEngine().ingest(
        bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1),
        (
            support_band(),
            resistance_band(
                source_id="POSTHOC-FORMING-CLOUD-SHORT",
                source_kind="POSTHOC-FORMING-CLOUD",
            ),
        ),
        prior_atr(),
    )
    assert short_side_bad_reaction.event is Event.DATA_RESET
    assert short_side_bad_reaction.reason_code is ReasonCode.SOURCE_NOT_READY
    assert short_side_bad_reaction.opportunity is None

    short_side_unknown_target = PositionReversalEngine().ingest(
        bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1),
        (
            support_band(
                source_id="UNALLOWLISTED-SHORT-TARGET",
                source_kind="UNALLOWLISTED-RANDOM-LEVEL",
            ),
            resistance_band(),
        ),
        prior_atr(),
    )
    assert short_side_unknown_target.event is Event.DATA_RESET
    assert short_side_unknown_target.reason_code is ReasonCode.SOURCE_NOT_READY
    assert short_side_unknown_target.opportunity is None

    arbitrary_atr = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band()),
        prior_atr(
            source_id="RANDOM-POSITIVE-NUMBER",
            source_kind="RANDOM-POSITIVE-NUMBER",
        ),
    )
    assert arbitrary_atr.event is Event.DATA_RESET
    assert arbitrary_atr.reason_code is ReasonCode.ATR_NOT_READY
    assert arbitrary_atr.opportunity is None
    assert any(
        "SOURCE_KIND_NOT_ALLOWED" in item
        for item in arbitrary_atr.source_rejections
    )


def test_absolute_valid_until_is_required_and_strict_at_bar_open() -> None:
    current = bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1)

    expired_band = PositionReversalEngine().ingest(
        current,
        (
            support_band(),
            resistance_band(valid_until_ms=current.timestamp_ms),
        ),
        prior_atr(),
    )
    assert expired_band.event is Event.DATA_RESET
    assert expired_band.reason_code is ReasonCode.SOURCE_NOT_READY
    assert any("EXPIRED" in item for item in expired_band.source_rejections)

    invalid_window = PositionReversalEngine().ingest(
        current,
        (
            support_band(),
            resistance_band(valid_until_ms=PUBLISHED_AT_MS),
        ),
        prior_atr(),
    )
    assert invalid_window.event is Event.DATA_RESET
    assert invalid_window.reason_code is ReasonCode.SOURCE_NOT_READY
    assert any(
        "VALID_UNTIL_INVALID" in item
        for item in invalid_window.source_rejections
    )

    expired_atr = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band()),
        prior_atr(valid_until_ms=current.timestamp_ms),
    )
    assert expired_atr.event is Event.DATA_RESET
    assert expired_atr.reason_code is ReasonCode.ATR_NOT_READY
    assert any("EXPIRED" in item for item in expired_atr.source_rejections)

    invalid_atr_window = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band()),
        prior_atr(valid_until_ms=PUBLISHED_AT_MS),
    )
    assert invalid_atr_window.event is Event.DATA_RESET
    assert invalid_atr_window.reason_code is ReasonCode.ATR_NOT_READY
    assert any(
        "VALID_UNTIL_INVALID" in item
        for item in invalid_atr_window.source_rejections
    )

    missing_band_expiry = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band(valid_until_ms=0)),
        prior_atr(),
    )
    assert missing_band_expiry.event is Event.DATA_RESET
    assert missing_band_expiry.reason_code is ReasonCode.SOURCE_NOT_READY
    assert any("VALID_UNTIL_INVALID" in item for item in missing_band_expiry.source_rejections)

    future_expiry_is_valid = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band()),
        prior_atr(valid_until_ms=VALID_UNTIL_MS),
    )
    assert future_expiry_is_valid.event is Event.REJECTION_CONFIRMED
    assert future_expiry_is_valid.reason_code is ReasonCode.READY


def test_previous_completed_daily_atr_metadata_is_mechanically_required() -> None:
    current = bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1)
    invalid_atrs = (
        prior_atr(source_timeframe="60"),
        prior_atr(completed_source_open_ms=PUBLISHED_AT_MS),
        prior_atr(completed_source_close_ms=et_ms(16, 10, year=2026, month=7, day=30)),
        prior_atr(
            source_kind=SourceKind.SATY_ATR_MAP_LEVEL,
        ),
    )
    expected = (
        "ATR_TIMEFRAME_INVALID",
        "ATR_SOURCE_BAR_INVALID",
        "ATR_SOURCE_BAR_NOT_COMPLETED",
        "SOURCE_KIND_NOT_ALLOWED",
    )

    for candidate, rejection in zip(invalid_atrs, expected, strict=True):
        result = PositionReversalEngine().ingest(
            current,
            (support_band(), resistance_band()),
            candidate,
        )
        assert result.event is Event.DATA_RESET
        assert result.reason_code is ReasonCode.ATR_NOT_READY
        assert result.data_valid is False
        assert result.opportunity is None
        assert any(rejection in item for item in result.source_rejections)


def test_future_publication_and_future_known_at_cannot_use_the_same_bar() -> None:
    current = bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1)
    engine = PositionReversalEngine()
    future_resistance = resistance_band(
        published_at_ms=et_ms(9, 31),
        level_known_at_ms=et_ms(9, 31),
    )

    result = engine.ingest(
        current,
        (support_band(), future_resistance),
        prior_atr(),
    )

    assert result.event is Event.NONE
    assert result.state is State.WAIT_CLEAR
    assert result.opportunity is None
    assert any("FUTURE_PUBLICATION" in item for item in result.source_rejections)

    known_at_close = resistance_band(
        published_at_ms=et_ms(9, 0),
        level_known_at_ms=et_ms(9, 40),
    )
    second = PositionReversalEngine().ingest(
        current,
        (support_band(), known_at_close),
        prior_atr(),
    )
    assert second.event is Event.NONE
    assert second.opportunity is None
    assert any("FUTURE_KNOWN_AT" in item for item in second.source_rejections)


def test_source_known_exactly_at_bar_open_is_causal() -> None:
    current = bar(11, 30, 7430.0, 7443.8, 7420.9, 7443.5)
    support = support_band(
        published_at_ms=et_ms(11, 30),
        level_known_at_ms=et_ms(11, 30),
    )
    result = PositionReversalEngine().ingest(
        current,
        (support, resistance_band()),
        prior_atr(),
    )

    assert result.event is Event.BOUNCE_CONFIRMED
    assert result.reason_code is ReasonCode.READY
    assert result.visible_at_ms == et_ms(11, 40)


def test_target_published_after_touch_is_not_backfilled_at_confirmation() -> None:
    engine = PositionReversalEngine()
    touch = bar(12, 0, 7425.0, 7430.0, 7420.9, LOWER_TRIGGER)
    future_target = resistance_band(
        lower_bound=7445.0,
        upper_bound=7445.0,
        published_at_ms=et_ms(12, 5),
        level_known_at_ms=et_ms(12, 5),
    )
    first = engine.ingest(
        touch,
        (support_band(), future_target),
        prior_atr(),
    )
    assert first.event is Event.SUPPORT_WATCH
    assert first.target_candidate is None

    confirm = bar(12, 10, 7421.3, 7435.0, 7421.0, 7434.0)
    second = engine.ingest(
        confirm,
        (support_band(), future_target),
        prior_atr(),
    )
    assert second.event is Event.BOUNCE_CONFIRMED
    assert second.state is State.FAILED
    assert second.reason_code is ReasonCode.TARGET_MISSING
    assert second.opportunity is None


def test_stale_forming_and_missing_identity_sources_fail_closed() -> None:
    current = bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1)
    cases = (
        resistance_band(
            published_at_ms=et_ms(9, 0, year=2026, month=7, day=29),
            level_known_at_ms=et_ms(9, 0, year=2026, month=7, day=29),
        ),
        resistance_band(stability=Stability.FORMING),
        resistance_band(source_version=""),
    )
    expected = ("STALE", "STABILITY_NOT_PRIOR_PUBLISHED", "IDENTITY_MISSING")

    for candidate, rejection in zip(cases, expected, strict=True):
        result = PositionReversalEngine().ingest(
            current,
            (support_band(), candidate),
            prior_atr(),
        )
        if rejection in {"STALE", "IDENTITY_MISSING"}:
            assert result.event is Event.DATA_RESET
            assert result.reason_code is ReasonCode.SOURCE_NOT_READY
            assert result.state is State.DISABLED
        else:
            assert result.event is Event.NONE
        assert result.opportunity is None
        assert any(rejection in item for item in result.source_rejections)


def test_one_stale_extra_band_resets_an_otherwise_valid_source_surface() -> None:
    current = bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1)
    stale_extra = resistance_band(
        source_id="SATY-ATR-STALE-EXTRA",
        source_version="v2",
        lower_bound=7520.0,
        upper_bound=7520.0,
        published_at_ms=current.timestamp_ms - 36 * 60 * 60 * 1000 - 1,
        level_known_at_ms=current.timestamp_ms - 36 * 60 * 60 * 1000 - 1,
    )
    result = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band(), stale_extra),
        prior_atr(),
    )
    assert result.data_valid is False
    assert result.event is Event.DATA_RESET
    assert result.reason_code is ReasonCode.SOURCE_NOT_READY
    assert result.state is State.DISABLED
    assert result.opportunity is None
    assert any("SATY-ATR-STALE-EXTRA" in item and "STALE" in item for item in result.source_rejections)


def test_noncanonical_or_inconsistent_source_freshness_fails_closed() -> None:
    current = bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1)
    noncanonical_freshness = 24 * 60 * 60 * 1000

    # The resistance would still be temporally fresh under its own 24h value,
    # but v1 permits only the shared canonical 36h contract.  It is excluded
    # rather than allowed to drift from Pine's single freshness surface.
    band_result = PositionReversalEngine().ingest(
        current,
        (
            support_band(),
            resistance_band(stale_after_ms=noncanonical_freshness),
        ),
        prior_atr(),
    )
    assert band_result.event is Event.NONE
    assert band_result.opportunity is None
    assert any(
        "FRESHNESS_NON_CANONICAL" in item
        for item in band_result.source_rejections
    )

    atr_result = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band()),
        prior_atr(stale_after_ms=noncanonical_freshness),
    )
    assert atr_result.event is Event.DATA_RESET
    assert atr_result.reason_code is ReasonCode.ATR_NOT_READY
    assert atr_result.data_valid is False
    assert any(
        "FRESHNESS_NON_CANONICAL" in item
        for item in atr_result.source_rejections
    )


def test_whitespace_only_band_and_atr_identities_fail_closed() -> None:
    current = bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1)
    band_cases = (
        resistance_band(source_id="   "),
        resistance_band(source_version="\t\n"),
    )
    for candidate in band_cases:
        result = PositionReversalEngine().ingest(
            current,
            (support_band(), candidate),
            prior_atr(),
        )
        assert result.event is Event.DATA_RESET
        assert result.reason_code is ReasonCode.SOURCE_NOT_READY
        assert result.state is State.DISABLED
        assert result.opportunity is None
        assert any("IDENTITY_MISSING" in item for item in result.source_rejections)

    atr_cases = (
        prior_atr(source_id="   "),
        prior_atr(source_version="\t"),
    )
    for candidate in atr_cases:
        result = PositionReversalEngine().ingest(
            current,
            (support_band(), resistance_band()),
            candidate,
        )
        assert result.event is Event.DATA_RESET
        assert result.reason_code is ReasonCode.ATR_NOT_READY
        assert any("IDENTITY_MISSING" in item for item in result.source_rejections)


def test_unconfirmed_bar_does_not_advance_or_publish() -> None:
    engine = PositionReversalEngine()
    forming = bar(
        9,
        30,
        7478.0,
        7486.3,
        7462.8,
        7465.1,
        is_confirmed=False,
    )
    result = engine.ingest(forming, (support_band(), resistance_band()), prior_atr())
    assert result.visible is False
    assert result.data_valid is False
    assert result.event is Event.NONE
    assert result.reason_code is ReasonCode.DATA_UNCONFIRMED
    assert engine.opportunities == ()

    confirmed = replace(forming, is_confirmed=True)
    next_result = engine.ingest(
        confirmed,
        (support_band(), resistance_band()),
        prior_atr(),
    )
    assert next_result.event is Event.REJECTION_CONFIRMED
    assert next_result.visible_at_ms == et_ms(9, 40)


def test_same_source_id_and_version_cannot_drift_bounds() -> None:
    engine = PositionReversalEngine()
    idle = bar(8, 0, 7440.0, 7445.0, 7435.0, 7440.0)
    first = engine.ingest(idle, (support_band(), resistance_band()), prior_atr())
    assert first.data_valid is True

    drifted = resistance_band(
        lower_bound=7468.0,
        upper_bound=7468.0,
    )
    second = engine.ingest(
        bar(8, 10, 7440.0, 7445.0, 7435.0, 7440.0),
        (support_band(), drifted),
        prior_atr(),
    )
    assert second.event is Event.DATA_RESET
    assert second.reason_code is ReasonCode.SOURCE_IDENTITY_DRIFT
    assert second.data_valid is False


def test_atr_must_also_be_prior_known_fresh_and_version_stable() -> None:
    current = bar(9, 30, 7478.0, 7486.3, 7462.8, 7465.1)
    future_atr = prior_atr(known_at_ms=et_ms(9, 31))
    result = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band()),
        future_atr,
    )
    assert result.event is Event.DATA_RESET
    assert result.reason_code is ReasonCode.ATR_NOT_READY
    assert result.opportunity is None

    engine = PositionReversalEngine()
    idle = bar(8, 0, 7440.0, 7445.0, 7435.0, 7440.0)
    engine.ingest(idle, (support_band(), resistance_band()), prior_atr())
    drift = prior_atr(value=99.0)
    changed = engine.ingest(
        bar(8, 10, 7440.0, 7445.0, 7435.0, 7440.0),
        (support_band(), resistance_band()),
        drift,
    )
    assert changed.event is Event.DATA_RESET
    assert changed.reason_code is ReasonCode.ATR_IDENTITY_DRIFT


def test_same_legacy_identity_cannot_drift_valid_until_in_one_runtime() -> None:
    engine = PositionReversalEngine()
    idle = bar(8, 0, 7440.0, 7445.0, 7435.0, 7440.0)
    first = engine.ingest(idle, (support_band(), resistance_band()), prior_atr())
    assert first.data_valid is True

    changed = engine.ingest(
        bar(8, 10, 7440.0, 7445.0, 7435.0, 7440.0),
        (
            support_band(),
            resistance_band(valid_until_ms=VALID_UNTIL_MS - 600_000),
        ),
        prior_atr(),
    )
    assert changed.event is Event.DATA_RESET
    assert changed.reason_code is ReasonCode.SOURCE_IDENTITY_DRIFT
    assert any("IDENTITY_DRIFT" in item for item in changed.source_rejections)


def test_effective_ids_change_when_source_target_or_atr_content_changes() -> None:
    current = bar(11, 30, 7430.0, 7443.8, 7420.5, 7443.5)

    base = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band()),
        prior_atr(),
    )
    changed_source = PositionReversalEngine().ingest(
        current,
        (
            support_band(lower_bound=7420.8, upper_bound=7420.8),
            resistance_band(),
        ),
        prior_atr(),
    )
    changed_target = PositionReversalEngine().ingest(
        current,
        (
            support_band(),
            resistance_band(valid_until_ms=VALID_UNTIL_MS - 600_000),
        ),
        prior_atr(),
    )
    changed_atr = PositionReversalEngine().ingest(
        current,
        (support_band(), resistance_band()),
        prior_atr(completed_source_open_ms=et_ms(1, 0, year=2026, month=7, day=30)),
    )

    for result in (base, changed_source, changed_target, changed_atr):
        assert result.event is Event.BOUNCE_CONFIRMED
        assert result.reason_code is ReasonCode.READY
        assert result.opportunity is not None
        assert result.opportunity.source_fingerprint.startswith(
            "CID1|B|SATY_ATR_MAP_LEVEL|"
        )
        assert result.opportunity.target_source_fingerprint.startswith(
            "CID1|B|SATY_ATR_MAP_LEVEL|"
        )
        assert result.opportunity.atr_source_fingerprint.startswith(
            "CID1|A|PREVIOUS_COMPLETED_DAILY_ATR|"
        )
        assert str(result.opportunity.source_valid_until_ms) in (
            result.opportunity.source_fingerprint
        )
        assert str(result.opportunity.target_valid_until_ms) in (
            result.opportunity.target_source_fingerprint
        )
        assert str(result.opportunity.atr_valid_until_ms) in (
            result.opportunity.atr_source_fingerprint
        )

    assert base.episode_id != changed_source.episode_id
    assert base.opportunity is not None
    assert changed_source.opportunity is not None
    assert changed_target.opportunity is not None
    assert changed_atr.opportunity is not None
    assert base.opportunity.opportunity_id != changed_source.opportunity.opportunity_id
    assert base.opportunity.opportunity_id != changed_target.opportunity.opportunity_id
    assert base.opportunity.opportunity_id != changed_atr.opportunity.opportunity_id
    assert base.opportunity.source_valid_until_ms == VALID_UNTIL_MS
    assert base.opportunity.target_valid_until_ms == VALID_UNTIL_MS
    assert base.opportunity.atr_valid_until_ms == VALID_UNTIL_MS
