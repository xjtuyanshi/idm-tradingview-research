"""Static release contracts for the clean-slate IDM v11 Pine artifact.

The suite deliberately checks product semantics instead of one preferred set of
local variable names.  It does *not* prove Pine compilation, fill parity,
profitability, or calibrated probability.  It prevents the specific regression
that made v10.1 signal-starved: an obsolete multi-stage episode can no longer
replace direct, bar-confirmed setups with a generic ``WAIT_LOCATION`` state.

The v11 Pine source is expected at the repository root.  A missing source is a
release failure rather than a skipped contract: the test and the implementation
are one deliverable.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
PINE = ROOT / "intraday_decision_map_v11_aggressive_clean.pine"


def _assert_any_regex(
    testcase: unittest.TestCase,
    source: str,
    patterns: tuple[str, ...],
    message: str,
) -> None:
    if not any(re.search(pattern, source, flags=re.I | re.S) for pattern in patterns):
        testcase.fail(f"{message}; accepted patterns: {patterns}")


def _regex_hits(source: str, patterns: tuple[str, ...]) -> int:
    """Count semantic identifier hits while tolerating naming variants."""

    return sum(len(re.findall(pattern, source, flags=re.I)) for pattern in patterns)


def _without_line_comments(source: str) -> str:
    """Discard ``//`` comments so a prose promise cannot satisfy a contract."""

    return "\n".join(line.split("//", 1)[0] for line in source.splitlines())


def _call_blocks(source: str, callee_pattern: str) -> list[str]:
    """Return complete Pine call expressions, including nested calls.

    This small scanner is intentionally independent of Pine formatting and
    ignores parentheses inside quoted strings.
    """

    starts = list(re.finditer(rf"(?<![A-Za-z0-9_])(?:{callee_pattern})\s*\(", source))
    blocks: list[str] = []
    for match in starts:
        open_index = source.find("(", match.start())
        depth = 0
        quote: str | None = None
        escaped = False
        for index in range(open_index, len(source)):
            char = source[index]
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in ('"', "'"):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(source[match.start() : index + 1])
                    break
    return blocks


class V11PineContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not PINE.exists():
            raise AssertionError(f"missing clean-slate v11 Pine target: {PINE}")
        cls.source = PINE.read_text(encoding="utf-8")
        cls.code = _without_line_comments(cls.source)

    def test_is_an_independent_v11_strategy(self) -> None:
        strategies = _call_blocks(self.code, r"strategy")
        self.assertEqual(len(strategies), 1)
        self.assertRegex(self.source, r"(?i)(IDM\s*v?11|VERSION[^\n]*11\.)")
        for stale_title in ("v10.1", "v10.0", "Lean Prototype"):
            self.assertNotIn(stale_title, strategies[0])

    def test_old_serial_episode_and_generic_wait_copy_are_absent(self) -> None:
        forbidden_patterns = {
            "legacy WAIT_LOCATION blocker": r"\b(?:BLOCK_)?WAIT_LOCATION\b",
            "legacy serial episode states": (
                r"\bEPISODE_(?:FIRST_TEST|DEPARTED|RETEST_HELD|TRIGGERED)\b"
            ),
            "legacy episode state variable": r"\b(?:long|short|entry)?EpisodeState\b",
            "legacy side episode owner": r"\b(?:long|short)Episode\b",
            "generic bullish observation": r"偏多观察",
            "generic bearish observation": r"偏空观察",
            "generic wait-for-location copy": r"等待(?:价格)?(?:回到)?位置",
        }
        for description, pattern in forbidden_patterns.items():
            self.assertNotRegex(
                self.code,
                re.compile(pattern, re.I),
                description,
            )

        # These two v10 throttles made valid later setups disappear.  A
        # per-setup de-dup latch is fine; a global cooldown/quota is not.
        self.assertNotRegex(self.code, re.compile(r"global\w*cooldown", re.I))
        self.assertNotRegex(
            self.code,
            re.compile(r"(?:max|daily)\w*signals?\w*(?:day|quota|limit)", re.I),
        )

    def test_all_four_direct_setup_families_are_defined_and_routed(self) -> None:
        setup_patterns: dict[str, tuple[str, ...]] = {
            "Trend Ignition": (
                r"\bSETUP_?(?:TREND_?)?IGNITION\b",
                r"\b(?:trendIgnition|ignitionSetup|(?:long|short)Ignition)\b",
            ),
            "Pullback Continuation": (
                r"\bSETUP_?PULLBACK(?:_?(?:CONTINUATION|CONTINUE))?\b",
                r"\b(?:pullbackContinuation|continuationPullback|(?:long|short)Pullback|pullback(?:Long|Short))\b",
            ),
            "Compression Breakout": (
                r"\bSETUP_?(?:COMPRESSION_?)?BREAKOUT\b",
                r"\b(?:compressionBreakout|breakoutCompression|(?:long|short)Breakout)\b",
            ),
            "Level Rejection": (
                r"\bSETUP_?(?:LEVEL_?)?REJECTION\b",
                r"\b(?:levelRejection|rejectionSetup|(?:long|short)Rejection)\b",
            ),
        }
        for setup, patterns in setup_patterns.items():
            hits = _regex_hits(self.code, patterns)
            self.assertGreaterEqual(
                hits,
                2,
                f"{setup} must be a real condition plus a routed use, not display-only prose",
            )

        _assert_any_regex(
            self,
            self.code,
            (
                r"(?i)(?:level|long|short)?\w*REJECTION.{0,1200}PULLBACK.{0,1200}BREAKOUT.{0,1200}IGNITION",
                r"(?i)rejection\w*priority.{0,1000}pullback.{0,1000}breakout.{0,1000}ignition",
                r"(?i)setupPriority\s*=.*(?:rejection|拒绝)",
            ),
            "v11 needs an explicit deterministic same-bar setup priority",
        )

    def test_signal_and_plan_lifecycle_are_explicit(self) -> None:
        lifecycle_patterns: dict[str, tuple[str, ...]] = {
            "BUY": (r"\b(?:EVENT|ACTION|SIGNAL|PLAN)_?BUY\b", r'"BUY"'),
            "SELL": (r"\b(?:EVENT|ACTION|SIGNAL|PLAN)_?SELL\b", r'"SELL"'),
            "HOLD": (r"\b(?:EVENT|ACTION|STATE|PLAN)_?HOLD\b", r'"HOLD"'),
            "PROTECT": (
                r"\b(?:EVENT|ACTION|STATE|PLAN)_?PROTECT\b",
                r'"PROTECT"',
            ),
            "EXIT": (
                r"\b(?:EVENT|ACTION|STATE|PLAN)_[A-Z_]*EXIT\b",
                r'"EXIT"',
            ),
        }
        for lifecycle, patterns in lifecycle_patterns.items():
            self.assertGreaterEqual(
                _regex_hits(self.code, patterns),
                2,
                f"{lifecycle} must be defined and consumed by the event/plan route",
            )

        shape_calls = _call_blocks(self.code, r"plotshape")
        shape_code = "\n".join(shape_calls)
        self.assertGreaterEqual(len(shape_calls), 2)
        self.assertRegex(shape_code, re.compile(r"(?:BUY|买)", re.I))
        self.assertRegex(shape_code, re.compile(r"(?:SELL|卖)", re.I))

    def test_3m_is_canonical_and_10m_context_is_confirmed(self) -> None:
        _assert_any_regex(
            self,
            self.source,
            (r"3\s*(?:m|分钟).{0,8}(?:执行|触发|canonical)",),
            "the visible UI must identify 3m as the execution host",
        )
        _assert_any_regex(
            self,
            self.source,
            (r"10\s*(?:m|分钟).{0,8}(?:同步|只读|relay)",),
            "the visible UI must identify 10m as the synchronized read-only host",
        )

        _assert_any_regex(
            self,
            self.code,
            (
                r"\b(?:chartIs3m|hostIs3m|hostIsCanonical3m|isThreeMinute)\b",
                r"timeframe\.period\s*==\s*\"3\"",
            ),
            "v11 must identify the canonical 3m host",
        )
        security_calls = _call_blocks(
            self.code,
            r"request\.security(?:_lower_tf)?",
        )
        self.assertTrue(
            any(
                re.search(r'(?i)(?:"3"|TF_ENGINE|TF_EXEC|tf3m|TF_3M)', call)
                for call in security_calls
            ),
            "10m must relay the canonical 3m event/state rather than recompute a second system",
        )
        self.assertTrue(
            any(
                re.search(r'(?i)(?:"10"|TF_CONTEXT|tf10m)', call)
                and (
                    re.search(r"\[[ \t]*1[ \t]*\]", call)
                    or re.search(r"(?i)confirm(?:ed)?", call)
                )
                and "lookahead=barmerge.lookahead_on" in re.sub(r"\s+", "", call)
                for call in security_calls
            ),
            "10m context must use the previous confirmed HTF bar with lookahead_on",
        )

        if "strategy.entry(" in self.code:
            _assert_any_regex(
                self,
                self.code,
                (
                    r"(?i)(?:enableOrders|ordersEnabled).{0,120}(?:chartIs3m|hostIs3m|hostIsCanonical3m|isThreeMinute)",
                    r"(?i)(?:chartIs3m|hostIs3m|hostIsCanonical3m|isThreeMinute).{0,120}(?:enableOrders|ordersEnabled)",
                ),
                "strategy orders must be optional and gated to the canonical 3m host",
            )

    def test_data_window_exposes_auditable_decision_fields(self) -> None:
        audit_calls = [
            block
            for block in _call_blocks(self.code, r"plot|plotchar")
            if "display.data_window" in block
        ]
        audit = "\n".join(audit_calls)
        self.assertGreaterEqual(
            len(audit_calls),
            11,
            "Data Window needs enough numeric audit fields to replay one decision",
        )
        fields: dict[str, tuple[str, ...]] = {
            "confirmed 10m source time": (
                r"(?i)(?:source|confirmed|源).{0,20}10m.{0,20}(?:time|时间)",
                r"(?i)10m.{0,20}(?:source|confirmed|源).{0,20}(?:time|时间)",
            ),
            "market/context state": (
                r"(?i)(?:market|context|背景|行情).{0,12}(?:state|状态|code|direction|方向)",
            ),
            "candidate/setup": (r"(?i)(?:candidate|setup|候选|形态|触发类型)",),
            "grade": (r"(?i)(?:grade|等级|ABC)",),
            "reason/blocker": (r"(?i)(?:reason|blocker|原因|尚缺|阻挡)",),
            "event id": (r"(?i)(?:event.{0,5}id|事件.{0,5}(?:id|编号))",),
            "entry": (r"(?i)(?:entry|入场)",),
            "stop": (r"(?i)(?:stop|止损)",),
            "T1": (r"(?i)(?:\bT1\b|目标.?1)",),
            "T2": (r"(?i)(?:\bT2\b|目标.?2)",),
            "plan event": (r"(?i)(?:plan.{0,8}event|计划.{0,8}事件)",),
        }
        missing_fields = [
            field
            for field, patterns in fields.items()
            if not any(re.search(pattern, audit, re.I | re.S) for pattern in patterns)
        ]
        self.assertFalse(
            missing_fields,
            f"missing Data Window fields: {', '.join(missing_fields)}",
        )

    def test_dashboard_is_one_minimal_four_row_table(self) -> None:
        tables = _call_blocks(self.code, r"table\.new")
        self.assertEqual(len(tables), 1, "v11 may render only one dashboard table")
        compact_table_call = re.sub(r"\s+", "", tables[0])
        table_cells = "\n".join(_call_blocks(self.code, r"table\.cell"))
        issues: list[str] = []
        if not re.search(r"table\.new\([^,]+,[1-3],4(?:,|\))", compact_table_call):
            issues.append("table is not exactly four rows tall")
        row_semantics = {
            "现在": r'"(?:现在|当前)',
            "背景": r'"(?:背景|10m|10分钟)',
            "下一步": r'"(?:下一步|触发)',
            "计划": r'"(?:计划|持仓)',
        }
        for row_name, pattern in row_semantics.items():
            if not re.search(pattern, table_cells, re.I | re.S):
                issues.append(f"missing {row_name} row")
        self.assertFalse(issues, "; ".join(issues))

    def test_abc_is_a_rule_grade_not_a_fake_probability(self) -> None:
        for grade in "ABC":
            _assert_any_regex(
                self,
                self.code,
                (
                    rf"\bGRADE_?{grade}\b",
                    rf'(?i)\bgrade\w*\s*(?::=|=).*?"{grade}"',
                    rf'"{grade}级"',
                ),
                f"missing explicit {grade} rule grade",
            )
        self.assertNotRegex(
            self.source,
            re.compile(r"(?i)(?:A|B|C)级[^\n]{0,40}(?:胜率|概率|confidence)"),
            "ABC is a deterministic rule grade, not a claimed historical probability",
        )

    def test_empty_state_names_both_next_buy_and_next_sell_triggers(self) -> None:
        next_buy_patterns = (
            r"(?i)\bnext\w*buy\w*trigger\b",
            r"下一(?:个)?\s*(?:BUY|买入|做多)\s*(?:触发|条件)",
            r"(?:BUY|买入|做多)\s*(?:下一)?触发",
        )
        next_sell_patterns = (
            r"(?i)\bnext\w*sell\w*trigger\b",
            r"下一(?:个)?\s*(?:SELL|卖出|做空)\s*(?:触发|条件)",
            r"(?:SELL|卖出|做空)\s*(?:下一)?触发",
        )
        _assert_any_regex(
            self,
            self.code,
            next_buy_patterns,
            "empty state must name the exact next BUY trigger",
        )
        _assert_any_regex(
            self,
            self.code,
            next_sell_patterns,
            "empty state must name the exact next SELL trigger",
        )

    def test_dynamic_alert_is_chinese_human_language_not_json(self) -> None:
        alert_calls = _call_blocks(self.code, r"alert(?!condition)")
        self.assertTrue(alert_calls, "v11 needs dynamic alert() notifications")
        alert_code = "\n".join(alert_calls)
        self.assertIn("alert.freq_once_per_bar_close", alert_code)
        self.assertIn("barstate.isconfirmed", self.code)
        self.assertRegex(
            self.source,
            re.compile(r'"[^"\n]*(?:做多|买入)[^"\n]*"'),
        )
        self.assertRegex(
            self.source,
            re.compile(r'"[^"\n]*(?:做空|卖出)[^"\n]*"'),
        )
        self.assertRegex(
            self.source,
            re.compile(r'"[^"\n]*(?:持有|保护|退出|止损|止盈)[^"\n]*"'),
        )
        self.assertRegex(self.code, r"str\.tostring\(")
        for json_fragment in (
            '"event_family"',
            '"event_id"',
            '\\"event_family\\"',
            '\\"event_id\\"',
        ):
            self.assertNotIn(
                json_fragment,
                alert_code,
                "the normal dynamic phone alert must not expose machine JSON",
            )


if __name__ == "__main__":
    unittest.main()
