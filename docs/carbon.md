# Carbon tracking

Every AgentForge run estimates the carbon cost of its Claude calls, alongside the budget.

- **Carbon used**: CO2e from the Claude calls that actually ran.
- **Carbon saved**: CO2e from calls that were planned but never made, because the run was a dry run, a cap or policy stopped it early, or local checks settled the task.

It appears in three places:

1. The up-front **Budget estimate** (`Estimated carbon: ~2.1 g CO2e`).
2. The end-of-run **Carbon summary** in the console and `final_summary.md`.
3. `budget.json` under `"carbon"`, with used/saved calls, chars, Wh, grams CO2e, `saved_pct`, and the assumptions used.

## How it is calculated

```
input_tokens  = chars_sent / chars_per_token
output_tokens = ai_calls * output_tokens_per_call
energy_wh     = input_tokens/1000 * wh_per_1k_input_tokens
              + output_tokens/1000 * wh_per_1k_output_tokens
co2e_g        = energy_wh/1000 * grid_intensity_g_per_kwh
saved         = planned - used   (calls and chars, floored at 0)
```

This is an **estimate, not a measurement**. Anthropic does not publish per-request energy data, so the defaults are rough public figures for frontier-model inference. Treat the numbers as comparable between runs, not as audited emissions.

## Configuration

```yaml
carbon:
  enabled: true                  # false removes it from output and budget.json
  grid_intensity_g_per_kwh: 475  # global avg ~473 (Ember 2024); UK ~130
  wh_per_1k_input_tokens: 0.25
  wh_per_1k_output_tokens: 0.6
  output_tokens_per_call: 1000
  chars_per_token: 4
```
