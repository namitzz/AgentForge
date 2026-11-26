"""Carbon accounting for AgentForge runs.

Turns the budget numbers AgentForge already tracks (AI calls and chars
sent) into an estimate of energy (Wh) and emissions (grams CO2e), in two
views:

  - **Used**: the Claude calls that actually happened in this run.
  - **Saved**: the Claude calls that were planned but never made, because
    the run was a dry run, a budget cap or policy stopped it, or the
    decision engine settled the task with free local checks.

Like the rest of the budget module this is a *proxy*, not a meter.
Anthropic does not publish per-request energy figures, so the defaults
below are public, order-of-magnitude estimates for frontier LLM inference
(including data-centre overhead). Every constant can be overridden in
``config.yaml`` under ``carbon:`` (e.g. your local grid intensity).

    energy_wh = input_tokens  / 1000 * wh_per_1k_input_tokens
              + output_tokens / 1000 * wh_per_1k_output_tokens
    co2e_g    = energy_wh / 1000 * grid_intensity_g_per_kwh
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CarbonSettings:
    enabled: bool = True
    # ~4 characters per token for English text and code.
    chars_per_token: float = 4.0
    # Responses are not measured, so assume a typical size per call.
    output_tokens_per_call: int = 1_000
    # Rough public estimates for frontier-model inference, incl. overhead.
    wh_per_1k_input_tokens: float = 0.25
    wh_per_1k_output_tokens: float = 0.6
    # Grid carbon intensity of the data centre. 475 g/kWh is close to the
    # 2024 global average (Ember: 473). UK is ~125-155. Set your region.
    grid_intensity_g_per_kwh: float = 475.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CarbonSettings":
        d = data or {}
        base = cls()
        return cls(
            enabled=bool(d.get("enabled", base.enabled)),
            chars_per_token=float(d.get("chars_per_token", base.chars_per_token)),
            output_tokens_per_call=int(d.get("output_tokens_per_call", base.output_tokens_per_call)),
            wh_per_1k_input_tokens=float(d.get("wh_per_1k_input_tokens", base.wh_per_1k_input_tokens)),
            wh_per_1k_output_tokens=float(d.get("wh_per_1k_output_tokens", base.wh_per_1k_output_tokens)),
            grid_intensity_g_per_kwh=float(d.get("grid_intensity_g_per_kwh", base.grid_intensity_g_per_kwh)),
        )


def estimate_energy_wh(calls: int, chars: int, s: CarbonSettings) -> float:
    """Energy for ``calls`` AI calls that send ``chars`` characters in total."""
    if calls <= 0 and chars <= 0:
        return 0.0
    input_tokens = max(chars, 0) / max(s.chars_per_token, 0.1)
    output_tokens = max(calls, 0) * s.output_tokens_per_call
    return (
        input_tokens / 1000 * s.wh_per_1k_input_tokens
        + output_tokens / 1000 * s.wh_per_1k_output_tokens
    )


def wh_to_co2e_g(wh: float, s: CarbonSettings) -> float:
    return wh / 1000 * s.grid_intensity_g_per_kwh


@dataclass
class CarbonReport:
    settings: CarbonSettings
    used_calls: int
    used_chars: int
    saved_calls: int
    saved_chars: int
    planned_calls: int
    planned_chars: int

    @classmethod
    def from_budget(
        cls,
        settings: CarbonSettings,
        *,
        ai_calls: int,
        chars_sent: int,
        planned_ai_calls: int,
        planned_chars_sent: int,
    ) -> "CarbonReport":
        return cls(
            settings=settings,
            used_calls=ai_calls,
            used_chars=chars_sent,
            saved_calls=max(planned_ai_calls - ai_calls, 0),
            saved_chars=max(planned_chars_sent - chars_sent, 0),
            planned_calls=planned_ai_calls,
            planned_chars=planned_chars_sent,
        )

    # --- derived numbers -------------------------------------------------
    @property
    def used_wh(self) -> float:
        return estimate_energy_wh(self.used_calls, self.used_chars, self.settings)

    @property
    def saved_wh(self) -> float:
        return estimate_energy_wh(self.saved_calls, self.saved_chars, self.settings)

    @property
    def planned_wh(self) -> float:
        return estimate_energy_wh(self.planned_calls, self.planned_chars, self.settings)

    @property
    def used_co2e_g(self) -> float:
        return wh_to_co2e_g(self.used_wh, self.settings)

    @property
    def saved_co2e_g(self) -> float:
        return wh_to_co2e_g(self.saved_wh, self.settings)

    @property
    def planned_co2e_g(self) -> float:
        return wh_to_co2e_g(self.planned_wh, self.settings)

    @property
    def saved_pct(self) -> float:
        total = self.used_co2e_g + self.saved_co2e_g
        return 0.0 if total <= 0 else 100.0 * self.saved_co2e_g / total

    # --- output ----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        s = self.settings
        return {
            "used": {
                "ai_calls": self.used_calls,
                "chars": self.used_chars,
                "energy_wh": round(self.used_wh, 3),
                "co2e_g": round(self.used_co2e_g, 3),
            },
            "saved": {
                "ai_calls": self.saved_calls,
                "chars": self.saved_chars,
                "energy_wh": round(self.saved_wh, 3),
                "co2e_g": round(self.saved_co2e_g, 3),
            },
            "planned_co2e_g": round(self.planned_co2e_g, 3),
            "saved_pct": round(self.saved_pct, 1),
            "assumptions": {
                "chars_per_token": s.chars_per_token,
                "output_tokens_per_call": s.output_tokens_per_call,
                "wh_per_1k_input_tokens": s.wh_per_1k_input_tokens,
                "wh_per_1k_output_tokens": s.wh_per_1k_output_tokens,
                "grid_intensity_g_per_kwh": s.grid_intensity_g_per_kwh,
            },
            "note": "Estimate only: derived from chars sent and public "
                    "per-token energy figures, not measured.",
        }

    def estimate_line(self) -> str:
        return f"- Estimated carbon: ~{fmt_g(self.planned_co2e_g)} CO2e"

    def human_summary(self) -> list[str]:
        return [
            "Carbon summary (estimate):",
            f"- Carbon used: ~{fmt_g(self.used_co2e_g)} CO2e "
            f"({self.used_calls} AI call{'s' if self.used_calls != 1 else ''}, "
            f"{self.used_wh:.2f} Wh)",
            f"- Carbon saved: ~{fmt_g(self.saved_co2e_g)} CO2e "
            f"({self.saved_calls} AI call{'s' if self.saved_calls != 1 else ''} avoided, "
            f"{self.saved_pct:.0f}% of planned)",
        ]


def fmt_g(grams: float) -> str:
    if grams >= 1000:
        return f"{grams / 1000:.2f} kg"
    if grams >= 1:
        return f"{grams:.1f} g"
    return f"{grams:.2f} g"
