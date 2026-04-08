# Local Queue Weight Sweep

- Base variant: `row_local_priority_queue`
- Risk-open setting: threshold=`0.0000` scale=`0.000100`
- Runs per baseline: `3`
- Horizon: `14400.0` s

## Highlights

- Best exposure: `row_local_priority_queue__risk_open__age_weight_0p005` at `3341.035` with `3.287%` vs reactive.
- Best response: `row_local_priority_queue__risk_open__age_weight_0` at `59.639 s`.
- Best bird deterrence: `row_local_priority_queue__risk_open__preempt_margin_0p5` at `2.701%`.
- Best overall rank: `row_local_priority_queue__risk_open__repartition_period_120` with `5.800`.

## Runtime

```text
                                                output_name             family status  duration_s
      row_local_priority_queue__risk_open__preempt_margin_0     preempt_margin     ok  848.938600
    row_local_priority_queue__risk_open__preempt_margin_0p1     preempt_margin     ok  934.068868
       row_local_priority_queue__risk_open__direct_bonus_14       direct_bonus     ok 1011.682593
                  row_local_priority_queue__risk_open__base               base     ok 1016.525223
       row_local_priority_queue__risk_open__direct_bonus_18       direct_bonus     ok 1017.641014
    row_local_priority_queue__risk_open__deterring_bonus_12    deterring_bonus     ok 1017.655019
        row_local_priority_queue__risk_open__direct_bonus_8       direct_bonus     ok 1020.956339
         row_local_priority_queue__risk_open__distance_0p12           distance     ok 1022.691458
    row_local_priority_queue__risk_open__deterring_bonus_16    deterring_bonus     ok 1056.977813
       row_local_priority_queue__risk_open__age_weight_0p02         age_weight     ok 1069.418388
         row_local_priority_queue__risk_open__distance_0p02           distance     ok 1094.930612
      row_local_priority_queue__risk_open__age_weight_0p005         age_weight     ok 1099.769155
          row_local_priority_queue__risk_open__age_weight_0         age_weight     ok 1121.115153
    row_local_priority_queue__risk_open__preempt_margin_0p5     preempt_margin     ok 1163.996624
         row_local_priority_queue__risk_open__distance_0p08           distance     ok 1167.161160
     row_local_priority_queue__risk_open__deterring_bonus_4    deterring_bonus     ok 1196.153583
row_local_priority_queue__risk_open__repartition_period_120 repartition_period     ok  340.301482
 row_local_priority_queue__risk_open__repartition_period_15 repartition_period     ok  561.784981
 row_local_priority_queue__risk_open__repartition_period_30 repartition_period     ok  547.784149
```

## Sweep Summary

```text
                                                output_name             family  param_value  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  proposed_response_time_mean  proposed_birds_deterred_pct_mean  proposed_comm_mean  proposed_model_completed_mean  proposed_total_planner_rejections_mean
row_local_priority_queue__risk_open__repartition_period_120 repartition_period      120.000                                     3.592780                                   1.997178                    65.062687                          2.602243         4626.666667                      21.000000                              500.333333
       row_local_priority_queue__risk_open__direct_bonus_14       direct_bonus       14.000                                     2.033749                                   2.828442                    64.224330                          2.574997         5053.333333                      18.333333                              713.000000
                  row_local_priority_queue__risk_open__base               base          NaN                                     2.033749                                   2.828442                    64.224330                          2.574997         5053.333333                      18.333333                              713.000000
       row_local_priority_queue__risk_open__direct_bonus_18       direct_bonus       18.000                                     2.033749                                   2.828442                    64.224330                          2.574997         5053.333333                      18.333333                              713.000000
    row_local_priority_queue__risk_open__deterring_bonus_12    deterring_bonus       12.000                                     2.033749                                   2.828442                    64.224330                          2.574997         5053.333333                      18.333333                              713.000000
        row_local_priority_queue__risk_open__direct_bonus_8       direct_bonus        8.000                                     2.033749                                   2.828442                    64.224330                          2.574997         5053.333333                      18.333333                              713.000000
    row_local_priority_queue__risk_open__deterring_bonus_16    deterring_bonus       16.000                                     2.033749                                   2.828442                    64.224330                          2.574997         5053.333333                      18.333333                              713.000000
          row_local_priority_queue__risk_open__age_weight_0         age_weight        0.000                                     5.271739                                   3.215317                    59.639046                          2.495024         5080.000000                      25.000000                             3500.333333
       row_local_priority_queue__risk_open__age_weight_0p02         age_weight        0.020                                     0.279570                                   1.913430                    62.845815                          2.034158         5346.666667                      12.000000                              257.333333
 row_local_priority_queue__risk_open__repartition_period_15 repartition_period       15.000                                     1.225682                                   0.286843                    62.680007                          2.016466         4645.333333                      13.333333                              307.666667
      row_local_priority_queue__risk_open__age_weight_0p005         age_weight        0.005                                     3.191584                                   3.287458                    67.706654                          2.316712         4146.666667                      15.666667                              849.666667
 row_local_priority_queue__risk_open__repartition_period_30 repartition_period       30.000                                     2.197927                                   1.995115                    59.941307                          1.929216         5938.666667                      12.333333                              368.000000
         row_local_priority_queue__risk_open__distance_0p08           distance        0.080                                     2.403896                                   2.350832                    70.510750                          1.623631         3962.666667                      10.666667                              389.666667
    row_local_priority_queue__risk_open__preempt_margin_0p5     preempt_margin        0.500                                     0.432013                                   0.893918                    61.359557                          2.700686         5648.000000                      22.666667                              795.333333
         row_local_priority_queue__risk_open__distance_0p02           distance        0.020                                     2.639044                                   1.086685                    72.290324                          1.783759         4162.666667                      13.000000                              259.333333
    row_local_priority_queue__risk_open__preempt_margin_0p1     preempt_margin        0.100                                     0.379137                                   1.418575                    67.327117                          2.637689         5962.666667                      18.000000                              626.333333
     row_local_priority_queue__risk_open__deterring_bonus_4    deterring_bonus        4.000                                     0.689604                                   1.495201                    65.139887                          2.275502         5512.000000                      14.333333                              563.666667
      row_local_priority_queue__risk_open__preempt_margin_0     preempt_margin        0.000                                     2.147850                                   1.074139                    63.543213                          2.486498         5989.333333                      20.333333                              636.666667
         row_local_priority_queue__risk_open__distance_0p12           distance        0.120                                     2.749686                                   1.454669                    66.341673                          2.599125         5280.000000                      16.000000                             1096.666667
```

## Recommended Next Step

1. Treat `row_local_priority_queue__risk_open__repartition_period_120` as the next exploratory candidate and compare it directly against `s1_risk_open_core` using `exploration.compare_system_performance` after promoting its settings into a named exploration variant.
