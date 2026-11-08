# Research Note: Extracting Points From Spatio-Temporal Point Processes

## Scope

In the literature, "extracting points" from a spatio-temporal point process usually means one of four different tasks:

1. Generate a statistically faithful future realization of event points from a fitted process.
2. Separate observed points into background versus triggered points, or infer parent-child links.
3. Convert a continuous conditional-intensity field into a small actionable set of representative points.
4. Cluster raw observed events and choose representative points without trusting a full generative model.

The most empirically accurate method depends on which of these tasks you actually mean.

## Methods That Are Empirically Strong

### 1. Exact simulation from the fitted conditional intensity

Use this when the goal is to produce a realistic point set, not just a few hotspots.

- Standard approach: thinning-based simulation for nonhomogeneous point processes and Hawkes/conditional-intensity models.
- Why it is strong: it preserves the model's event-count distribution, clustering, and uncertainty instead of collapsing the field to a few deterministic peaks.
- Best for: Monte Carlo forecasting, stress testing, uncertainty bands, synthetic catalogs.

Key sources:

- Lewis and Shedler (1979) introduced thinning for nonhomogeneous Poisson simulation.
- Ogata (1981) extended Lewis-style simulation to point processes specified by conditional intensity.
- Bernabeu, Zhuang, and Mateu (2025) review thinning and branching simulation methods for spatio-temporal Hawkes processes.

Practical note:

- If you need one extracted point set that is faithful to the model, repeated simulation plus aggregation of stable high-frequency locations is usually more defensible than taking the top-k cells of the intensity surface once.

### 2. Stochastic declustering / EM branching reconstruction

Use this when the goal is to identify which observed points are likely background points, triggered points, or members of the same cascade.

- Standard approach: infer the latent branching structure and compute posterior background/trigger probabilities.
- Why it is strong: this is the statistically coherent solution when the process is self-exciting and the extraction target is event attribution.
- Best for: Hawkes/ETAS interpretation, declustered catalogs, detecting persistent exogenous sources, identifying event cascades.

Key sources:

- Zhuang, Ogata, and Vere-Jones (2002) split the observed process into background and clustered subprocesses using stochastic declustering.
- Veen and Schoenberg (2008) show that EM-type estimation for space-time branching models is robust and accurate for declustered background estimation.
- Molkenthin et al. (2022) show how Bayesian GP-ETAS can recover background intensity and triggering parameters with uncertainty quantification.

Practical note:

- If your thesis question is "which detections are true persistent sources versus local after-effects?", this is the best-aligned family of methods.

### 3. Intensity or utility mode extraction with repulsion

Use this when the goal is to turn a forecast field into a small set of operational targets.

- Standard approach: score the field, take local modes or ranked cells, then apply non-maximum suppression / hard-core spacing / Poisson-disk-like thinning.
- Why it is strong: in patrol and hotspot allocation problems, nearby maxima often correspond to the same operational opportunity. Repulsion avoids wasting multiple points on one cluster.
- Best for: patrol waypoints, deterrence task seeds, hotspot targeting, limited-resource dispatch.

What is empirically supported:

- Crime hotspot forecasting literature repeatedly evaluates intensity-based hotspot selection by hit rate and PAI/PEI rather than raw pointwise error.
- SEPP/STKDE results show that using the spatio-temporal intensity surface and selecting hotspot regions from it is operationally effective.

Key sources:

- Wheeler et al. (2018) note that intensity surfaces contain richer information than a single selected hotspot set and discuss hit-rate-based hotspot evaluation.
- Rosser and Cheng (2019) show improved predictive accuracy when the SEPP triggering structure is better specified, which matters directly because extraction quality depends on intensity quality.
- Han et al. (2019) report that STKDE identified the most hotspots with the highest average PAI versus SKDE and ProMap in a Baton Rouge burglary study.

Practical note:

- For operational extraction, optimize an integrated quantity such as event probability, expected exposure, or expected utility over a footprint, not just the single-cell intensity value.
- Then apply spacing and persistence filters.

### 4. Model-free spatio-temporal clustering with medoids

Use this when the fitted point-process model is weak or when you need a robust summary of raw event clouds.

- Standard approach: ST-DBSCAN or related density-based clustering, then extract cluster medoids/centroids.
- Why it is strong: it is robust to irregular cluster shape and does not require a fully trusted generative model.
- Best for: preprocessing detections, deduplicating bursts, generating representative cluster centers from raw observations.

Key source:

- Birant and Kut (2007) introduced ST-DBSCAN for spatial-temporal clustering with explicit treatment of spatial and temporal neighborhoods.

Practical note:

- This is usually less faithful than Hawkes/ETAS-based reconstruction when the generative model is known, but often more robust when the model is misspecified.

## What "Empirically Accurate" Usually Means

Different extraction tasks need different validation targets.

- For synthetic point generation: held-out log-likelihood, count calibration, residual analysis, pair-correlation reproduction.
- For declustering/background extraction: recovery of latent branching structure on simulated data, stability of background-rate estimates, posterior uncertainty.
- For operational target extraction: hit rate, PAI/PEI, weighted exposure reduction, travel-adjusted utility, coverage versus concentration tradeoff.

Strong guidance from the literature:

- Point-process papers validate model fidelity with likelihood and residual diagnostics, not classification accuracy alone.
- Hotspot-allocation papers validate extracted targets with hit rate / PAI-like measures because the operational goal is to concentrate coverage where events occur.
- Residual, thinning, Voronoi, and super-thinning diagnostics are important because an apparently good hotspot map can still come from a badly calibrated process.

Relevant sources:

- Ogata (1988) on time-rescaling and residual analysis.
- Baddeley et al. (2005) on residuals for spatial point processes.
- Clements, Schoenberg, and Veen (2012) on super-thinning for space-time model evaluation.

## Recommendation For This Repository

Your current system already implements a pragmatic version of method 3:

- excess-field hotspot extraction from `lambda - mu`
- greedy spacing / Poisson-disk-style thinning
- recent-detection cluster seeding
- persistence and likelihood-ratio-style gating

See:

- `README.md` section "Hotspot Extraction"
- `TaskGenerator.py` hotspot thinning and preventive seeding blocks

For thesis-quality empirical performance, the most defensible next step is not a completely different extractor. It is a better-calibrated version of the current one:

1. Score candidate points by integrated event probability or expected reduction over a local footprint, not only by cellwise excess intensity.
2. Keep repulsion, but make it explicitly spatio-temporal instead of purely spatial when tasks can repeat quickly at the same place.
3. Add stability selection: extract points that survive across bootstrap refits or Monte Carlo draws from the fitted process.
4. Tune merge radius and thresholds on held-out utility metrics, not just raw hotspot score.
5. Use residual or super-thinning diagnostics to check whether the extractor is compensating for model bias instead of benefiting from a well-calibrated intensity model.

## Bottom Line

If the goal is:

- faithful future point sets: use thinning or branching simulation;
- background or triggered point extraction: use stochastic declustering / EM / Bayesian branching reconstruction;
- patrol or deterrence targets: use local utility maxima with repulsion and persistence;
- robust summary of raw detections: use ST-DBSCAN and extract medoids.

For this codebase, the best empirical path is:

- keep the current mode-extraction plus spacing architecture,
- replace cellwise ranking with footprint-integrated utility,
- add uncertainty-aware stability selection,
- validate with held-out operational metrics and point-process residual diagnostics.

## Sources

- Lewis, P. A. W., and G. S. Shedler. 1979. "Simulation of nonhomogeneous poisson processes by thinning." Naval Research Logistics Quarterly. https://doi.org/10.1002/nav.3800260304
- Ogata, Y. 1981. "On Lewis' simulation method for point processes." IEEE Transactions on Information Theory. https://doi.org/10.1109/TIT.1981.1056305
- Ogata, Y. 1988. "Statistical Models for Earthquake Occurrences and Residual Analysis for Point Processes." Journal of the American Statistical Association. https://doi.org/10.1080/01621459.1988.10478560
- Zhuang, J., Y. Ogata, and D. Vere-Jones. 2002. "Stochastic Declustering of Space-Time Earthquake Occurrences." Journal of the American Statistical Association. https://doi.org/10.1198/016214502760046925
- Baddeley, A., R. Turner, J. Moller, and M. Hazelton. 2005. "Residual Analysis for Spatial Point Processes." Journal of the Royal Statistical Society Series B. https://doi.org/10.1111/j.1467-9868.2005.00519.x
- Veen, A., and F. P. Schoenberg. 2008. "Estimation of Space-Time Branching Process Models in Seismology Using an EM-Type Algorithm." Journal of the American Statistical Association. https://doi.org/10.1198/016214508000000148
- Birant, D., and A. Kut. 2007. "ST-DBSCAN: An algorithm for clustering spatial-temporal data." Data and Knowledge Engineering. https://doi.org/10.1016/j.datak.2006.01.013
- Clements, R. A., F. P. Schoenberg, and A. Veen. 2012. "Evaluation of space-time point process models using super-thinning." Environmetrics. https://research.ibm.com/publications/evaluation-of-space-time-point-process-models-using-super-thinning
- Wheeler, A. P., G. Mohler, M. B. Porter, and Y. Tita. 2018. "The utility of hotspot mapping for predicting spatial patterns of crime." Journal of the Royal Statistical Society Series C. https://academic.oup.com/jrsssc/article/67/5/1305/7058390
- Rosser, G., and T. Cheng. 2019. "Improving the Robustness and Accuracy of Crime Prediction with the Self-Exciting Point Process Through Isotropic Triggering." Applied Spatial Analysis and Policy. https://doi.org/10.1007/s12061-016-9198-y
- Han, Y., F. Wang, and Y. Jiang. 2019. "A spatio-temporal kernel density estimation framework for predictive crime hotspot mapping and evaluation." Applied Geography. https://www.sciencedirect.com/science/article/abs/pii/S0143622818300560
- Molkenthin, C., C. Donner, S. Reich, G. Zoller, S. Hainzl, M. Holschneider, and M. Opper. 2022. "GP-ETAS: semiparametric Bayesian inference for the spatio-temporal epidemic type aftershock sequence model." Statistics and Computing. https://doi.org/10.1007/s11222-022-10085-3
- Bernabeu, A., J. Zhuang, and J. Mateu. 2025. "Spatio-Temporal Hawkes Point Processes: A Review." Journal of Agricultural, Biological and Environmental Statistics. https://doi.org/10.1007/s13253-024-00653-7
