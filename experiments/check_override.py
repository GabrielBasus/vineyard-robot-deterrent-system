"""Check per-run override counts directly from per_run_metrics to verify
whether override_sweep_summary mean_override_count is per-run or a total."""
import csv, pathlib, statistics as stats

RESULTS = pathlib.Path(r'C:\Users\gabri\Documents\CalPoly\Thesis\Code\results\testbench')
SWEEP = RESULTS / 'habituation_stl_override_sweep'

for mu_subdir in ('mu_2em05', 'mu_1em04', 'mu_4em04'):
    variant_dir = SWEEP / mu_subdir / 'B4_slack_30s'
    prm = variant_dir / 'per_run_metrics.csv'
    if not prm.exists():
        print(f'MISSING: {prm}')
        continue
    with open(prm, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    b4_on = [r for r in rows
             if r.get('baseline','') == 'B4_res_stl_full_multicue'
             and r.get('habituation_condition','') == 'hab_on']
    ov_vals = []
    for r in b4_on:
        v = r.get('urgent_reactive_override_total', '')
        try:
            ov_vals.append(float(v))
        except:
            pass
    if ov_vals:
        print(f'{mu_subdir}/B4_slack_30s hab_on:')
        print(f'  per-run override counts: {ov_vals}')
        print(f'  mean={stats.mean(ov_vals):.1f}  (this should match summary mean_override_count)')
    else:
        print(f'{mu_subdir}: urgent_reactive_override_total not found in per_run')
        print(f'  cols: {list(rows[0].keys())[:10]}...')
    print()
