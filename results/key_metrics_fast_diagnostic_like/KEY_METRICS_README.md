# Key Metrics Chosen

1. **Exposure improvement (with CI)**
- Primary thesis objective is reducing value-weighted exposure.
- CI is required to avoid over-trusting seed noise.

2. **Response-time improvement (with CI)**
- Exposure gains are less credible if achieved by delaying response.
- This guards against planner choices that starve urgent tasks.

3. **Communication increase (with CI) vs +30% target**
- Your deployment constraint explicitly includes communication overhead.
- Plotting against the target line makes pass/fail obvious.

4. **Preventive funnel conversion rates**
- Diagnoses where model-scored deterrence dies: risk gate, support gate, acceptance, dispatch, completion.
- This is the most direct way to debug why proposed is (or is not) outperforming.

## Caution
- Forecast metrics are currently near-zero/NaN in your runs, so they are not decision-driving yet.
- Composite rank is useful for dashboards, but less defensible than objective-specific metrics with CIs.