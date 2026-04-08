from __future__ import annotations

import argparse
import time
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.collections import LineCollection
from matplotlib.patches import Circle, Polygon as MplPolygon

import DeterrentSystem as ds


def _fmt_hms(t_s: float) -> str:
    t = max(0, int(round(t_s)))
    h = t // 3600
    m = (t % 3600) // 60
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _split_tasks(tasks_active, tasks_done):
    xd, yd, xp, yp = [], [], [], []
    for tr in tasks_active:
        ttype = str(tr.get("type", "")).strip().lower()
        origin = str(tr.get("origin", "")).strip().lower()
        # Be robust to labeling drift: hotspot/fallback tasks are patrol-like,
        # detection tasks are deterring-like.
        is_det = (ttype == "deterring") or (origin == "detection")
        if is_det:
            xd.append(tr["x"])
            yd.append(tr["y"])
        else:
            xp.append(tr["x"])
            yp.append(tr["y"])
    xdone = [tr["x"] for tr in tasks_done]
    ydone = [tr["y"] for tr in tasks_done]
    return xd, yd, xp, yp, xdone, ydone


def _task_class(tr):
    """
    Robust task class for demo metrics.
    Returns: ('deterring'|'patrolling', 'direct_detection'|'model_scored'|'-')
    """
    ttype = str(tr.get("type", "")).strip().lower()
    origin = str(tr.get("origin", "")).strip().lower()
    mode = tr.get("mode")
    if ttype == "deterring":
        # Immediate detection tasks typically have no mode.
        # Model-scored deterrence tasks use a selected deterrence mode.
        src = "model_scored" if mode not in (None, "", "none") else "direct_detection"
        # Fallback on origin when mode is absent.
        if src == "direct_detection" and origin not in ("", "detection"):
            src = "model_scored"
        return "deterring", src
    return "patrolling", "-"


def run_demo(
    sim_speed=1.0,
    fps=15,
    dt=5.0,
    seed=321,
    W=500.0,
    H=500.0,
    row_spacing_m=4.8,
    row_width_m=3.2,
    headland_space_m=10.0,
    robot_radius_m=0.9,
    done_draw_max=600,
    max_sim_steps_per_update=8,
):
    # This demo is visualization-first and disables CSV telemetry overhead.
    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    frames = ds.run_simulation_frames_persistent(
        simulation_mode="proposed",
        T_end=24 * 3600,  # full simulated day
        dt=dt,
        seed=seed,
        W=W,
        H=H,
        NX=90,
        NY=72,
        Nrobots=6,
        uav_fraction=0.0,
        warmup_s=3600.0,
        # Keep robots moving for demo readability.
        enable_patrolling=True,
        include_fallback_patrol=True,
        task_replan_period_s=20.0,
        hold_time_s=12.0,
        idle_roam_enabled=True,
        idle_roam_interval_s=25.0,
        idle_roam_jitter_m=18.0,
        # Low-pressure defaults with enough structure for non-center patrol spread.
        mu_true=1.8e-7,
        alpha_true=0.10,
        omega_true=1000.0,
        sigma_true=9.0,
        beta_true=0.35,
        # During warmup robots are stationary; wider detection helps seed
        # each zone beyond anchor-centered detections.
        detect_range_m=220.0,
        # Add stronger row/edge value contrast for spatially diverse hotspots.
        row_gain=2.0,
        edge_gain=0.9,
        event_viz_window_s=10.0,
        telemetry_clear_on_start=False,
        telemetry_prompt_save=False,
        row_spacing_m=row_spacing_m,
        row_width_m=row_width_m,
        headland_space_m=headland_space_m,
    )
    first = next(frames)

    fig = plt.figure(figsize=(12, 7))
    gs = fig.add_gridspec(1, 2, width_ratios=[4.2, 1.5])
    ax = fig.add_subplot(gs[0, 0])
    ax_info = fig.add_subplot(gs[0, 1])
    ax_info.axis("off")

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-5, W + 5)
    ax.set_ylim(-5, H + 5)
    ax.set_title("Vineyard Bird-Deterrence Demo (24h simulated day)", pad=28)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")

    # Vineyard boundary
    bx, by = zip(*(first["boundary"] + [first["boundary"][0]]))
    ax.plot(bx, by, "k-", lw=1.2, zorder=1)

    # Zone overlays
    zone_patches = []
    for cell in first["cells"]:
        if not cell:
            zone_patches.append(None)
            continue
        p = MplPolygon(cell, closed=True, fill=True, alpha=0.08, edgecolor="#808080", facecolor="#bfd3ff", zorder=1)
        ax.add_patch(p)
        zone_patches.append(p)

    # Vineyard rows as blocks
    row_patches = []
    if row_spacing_m > 0 and row_width_m > 0:
        k = 0
        while True:
            y = headland_space_m + k * row_spacing_m
            if y - 0.5 * row_width_m > (H - headland_space_m):
                break
            y0 = y - 0.5 * row_width_m
            y1 = y + 0.5 * row_width_m
            p = MplPolygon(
                [(headland_space_m, y0), (W - headland_space_m, y0), (W - headland_space_m, y1), (headland_space_m, y1)],
                closed=True,
                fill=True,
                alpha=0.15,
                edgecolor="none",
                facecolor="#6f8f5e",
                zorder=0,
            )
            ax.add_patch(p)
            row_patches.append(p)
            k += 1
        lines = [
            ((headland_space_m, headland_space_m + i * row_spacing_m), (W - headland_space_m, headland_space_m + i * row_spacing_m))
            for i in range(k)
        ]
        row_lines = LineCollection(lines, colors="#557148", linewidths=0.35, alpha=0.35, zorder=0.2)
        ax.add_collection(row_lines)

    # Events and tasks (visually separated for non-technical audience)
    truth_sc = ax.scatter([], [], s=44, c="#2ca02c", marker="x", zorder=5, label="Birds Present (ground truth)")
    det_sc = ax.scatter([], [], s=44, c="#d62728", marker="x", zorder=6, label="Bird Detections (sensor)")
    det_task_sc = ax.scatter([], [], s=72, c="#ff7f0e", marker="o", edgecolors="k", linewidths=0.3, zorder=4, label="Deterring Tasks")
    pat_task_sc = ax.scatter([], [], s=56, c="#1f77b4", marker="D", edgecolors="k", linewidths=0.2, zorder=4, label="Patrol Tasks")
    done_sc = ax.scatter([], [], s=18, c="#888888", marker=".", alpha=0.55, zorder=2, label="Completed Tasks")

    # Robot bodies with real-world radius in map units (meters)
    robot_ids = sorted(first["poses"].keys())
    robot_circles = {}
    robot_labels = {}
    for rid in robot_ids:
        x, y = first["poses"][rid]
        typ = first["profiles"][rid].type
        color = "#1f77b4" if typ == "UGV" else "#ff7f0e"
        c = Circle((x, y), radius=robot_radius_m, facecolor=color, edgecolor="black", linewidth=0.5, zorder=7)
        ax.add_patch(c)
        robot_circles[rid] = c
        lbl = ax.text(x + 1.2, y + 1.2, rid, fontsize=8, color="black", zorder=8, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75))
        robot_labels[rid] = lbl

    # Keep legend below the title to avoid overlap in presentation mode.
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.03), ncol=2, fontsize=8, frameon=True)

    # Right panel text
    txt = ax_info.text(
        0.02,
        0.98,
        "",
        va="top",
        ha="left",
        fontsize=10,
        family="monospace",
    )

    current = first
    current_t = float(first["t"])
    wall_prev = time.perf_counter()
    finished = False
    seen_task_ids = set()
    seen_done_task_ids = set()
    last_done_len = 0
    done_recent_xy = deque(maxlen=int(max(50, done_draw_max)))
    created_counts = {
        "deterring_total": 0,
        "patrolling_total": 0,
        "deterring_direct_detection": 0,
        "deterring_model_scored": 0,
    }
    completed_counts = {
        "deterring_total": 0,
        "patrolling_total": 0,
        "deterring_direct_detection": 0,
        "deterring_model_scored": 0,
    }
    arrival_sum_s = {
        "patrolling": 0.0,
        "deterring_direct_detection": 0.0,
        "deterring_model_scored": 0.0,
    }
    arrival_n = {
        "patrolling": 0,
        "deterring_direct_detection": 0,
        "deterring_model_scored": 0,
    }
    # Proxy for exposure reduction by source using completed task score.
    score_sum = {
        "deterring_direct_detection": 0.0,
        "deterring_model_scored": 0.0,
    }
    score_n = {
        "deterring_direct_detection": 0,
        "deterring_model_scored": 0,
    }

    def _apply_snapshot(snap):
        nonlocal last_done_len
        # Zones (if repartition ever happens)
        for patch, cell in zip(zone_patches, snap["cells"]):
            if patch is not None and cell:
                patch.set_xy(cell)

        # Robots
        for rid in robot_ids:
            if rid not in snap["poses"]:
                continue
            x, y = snap["poses"][rid]
            robot_circles[rid].center = (x, y)
            robot_labels[rid].set_position((x + 1.2, y + 1.2))

        # Events and tasks
        tp = snap.get("truth_pts", [])
        dp = snap.get("det_pts", [])
        truth_sc.set_offsets(np.array(tp) if tp else np.empty((0, 2)))
        det_sc.set_offsets(np.array(dp) if dp else np.empty((0, 2)))

        tasks_active = list(snap.get("tasks_active", []))
        tasks_done = list(snap.get("tasks_done", []))
        xd, yd, xp, yp, _, _ = _split_tasks(tasks_active, tasks_done)
        det_task_sc.set_offsets(np.c_[xd, yd] if xd else np.empty((0, 2)))
        pat_task_sc.set_offsets(np.c_[xp, yp] if xp else np.empty((0, 2)))
        if done_recent_xy:
            done_xy = np.array(done_recent_xy, dtype=float)
            done_sc.set_offsets(done_xy)
        else:
            done_sc.set_offsets(np.empty((0, 2)))

        # Cumulative creation counters: process active tasks once by id.
        for tr in tasks_active:
            tid = tr.get("id")
            if tid in seen_task_ids:
                continue
            seen_task_ids.add(tid)
            tclass, src = _task_class(tr)
            if tclass == "deterring":
                created_counts["deterring_total"] += 1
                if src == "model_scored":
                    created_counts["deterring_model_scored"] += 1
                else:
                    created_counts["deterring_direct_detection"] += 1
            elif tclass == "patrolling":
                created_counts["patrolling_total"] += 1

        # Process only newly completed tasks; avoids O(n^2) slowdown over long demos.
        if len(tasks_done) >= last_done_len:
            newly_done = tasks_done[last_done_len:]
        else:
            # Defensive reset if producer ever shrinks done history.
            newly_done = tasks_done
            seen_done_task_ids.clear()
            done_recent_xy.clear()
        last_done_len = len(tasks_done)

        # Completion/source metrics and time-to-arrival estimates.
        for tr in newly_done:
            tid = tr.get("id")
            if tid in seen_done_task_ids:
                continue
            seen_done_task_ids.add(tid)
            done_recent_xy.append((float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))

            # Ensure creation is counted even if task first appears as done.
            if tid not in seen_task_ids:
                seen_task_ids.add(tid)
                tclass_c, src_c = _task_class(tr)
                if tclass_c == "deterring":
                    created_counts["deterring_total"] += 1
                    if src_c == "model_scored":
                        created_counts["deterring_model_scored"] += 1
                    else:
                        created_counts["deterring_direct_detection"] += 1
                elif tclass_c == "patrolling":
                    created_counts["patrolling_total"] += 1

            tclass, src = _task_class(tr)
            if tclass == "deterring":
                completed_counts["deterring_total"] += 1
                key = "deterring_model_scored" if src == "model_scored" else "deterring_direct_detection"
                completed_counts[key] += 1
                sc = float(tr.get("score", 0.0))
                score_sum[key] += sc
                score_n[key] += 1
            else:
                completed_counts["patrolling_total"] += 1
                key = "patrolling"

            t_create = tr.get("time", None)
            try:
                dt_arr = float(snap["t"]) - float(t_create)
            except Exception:
                dt_arr = float("nan")
            if np.isfinite(dt_arr) and dt_arr >= 0.0:
                arrival_sum_s[key] += dt_arr
                arrival_n[key] += 1

        # Simple, audience-friendly dashboard
        m = snap.get("metrics_compact", {})
        progress = min(100.0, 100.0 * float(snap["t"]) / (24.0 * 3600.0))
        info = [
            "LIVE STATUS",
            "-----------",
            f"Sim Clock        : {_fmt_hms(float(snap['t']))}",
            f"Day Progress     : {progress:5.1f} %",
            f"Ground-Truth Birds: {len(tp):5d}",
            f"Detections       : {len(dp):5d}",
            f"Active Tasks     : {len(tasks_active):5d}",
            f"  - Deterring    : {len(xd):5d}",
            f"  - Patrol       : {len(xp):5d}",
            f"Completed Tasks  : {len(tasks_done):5d}",
            f"Done shown (cap) : {len(done_recent_xy):5d}",
            "",
            "TASK COUNTS (CUMULATIVE)",
            "------------------------",
            f"Deterring total  : {created_counts['deterring_total']:5d}",
            f"Patrolling total : {created_counts['patrolling_total']:5d}",
            f"Deterrence source:",
            f"  - Direct detect: {created_counts['deterring_direct_detection']:5d}",
            f"  - Model scored : {created_counts['deterring_model_scored']:5d}",
            "",
            "COMPLETION / ARRIVAL",
            "--------------------",
            f"Patrol completion  : {completed_counts['patrolling_total']:5d} / {max(created_counts['patrolling_total'],1):5d}",
            f"Det completion     : {completed_counts['deterring_total']:5d} / {max(created_counts['deterring_total'],1):5d}",
            f"Det direct comp    : {completed_counts['deterring_direct_detection']:5d} / {max(created_counts['deterring_direct_detection'],1):5d}",
            f"Det model comp     : {completed_counts['deterring_model_scored']:5d} / {max(created_counts['deterring_model_scored'],1):5d}",
            f"Mean ETA patrol(s) : {arrival_sum_s['patrolling']/max(arrival_n['patrolling'],1):7.2f}",
            f"Mean ETA det-dir(s): {arrival_sum_s['deterring_direct_detection']/max(arrival_n['deterring_direct_detection'],1):7.2f}",
            f"Mean ETA det-mod(s): {arrival_sum_s['deterring_model_scored']/max(arrival_n['deterring_model_scored'],1):7.2f}",
            "",
            "BENEFIT PROXY",
            "-------------",
            f"Det direct score   : {score_sum['deterring_direct_detection']/max(score_n['deterring_direct_detection'],1):7.3f}",
            f"Det model score    : {score_sum['deterring_model_scored']/max(score_n['deterring_model_scored'],1):7.3f}",
            "",
            "LEGEND",
            "------",
            "Green X  = Birds present",
            "Red X    = Detections",
            "Orange o = Deterring task",
            "Blue D   = Patrol task",
            "Gray .   = Completed task",
            "",
            "RUN METRICS",
            "-----------",
            f"Resp Time (s): {m.get('mean_response_time_s', float('nan')):7.2f}",
            f"Tasks Done   : {int(m.get('completed_tasks_total', 0)):7d}",
            f"Msgs Sent    : {int(m.get('boundary_message_count', 0)):7d}",
        ]
        txt.set_text("\n".join(info))

    _apply_snapshot(first)

    def update(_):
        nonlocal current, current_t, wall_prev, finished
        if finished:
            return []

        wall_now = time.perf_counter()
        wall_dt = max(0.0, wall_now - wall_prev)
        wall_prev = wall_now
        sim_advance_target = current_t + sim_speed * wall_dt

        # Advance simulation until we catch up with real-time playback target.
        steps = 0
        while current_t < sim_advance_target and steps < int(max_sim_steps_per_update):
            try:
                current = next(frames)
                current_t = float(current["t"])
                steps += 1
            except StopIteration:
                finished = True
                break

        _apply_snapshot(current)
        return []

    interval_ms = max(20, int(1000 / max(1, fps)))
    anim = FuncAnimation(fig, update, interval=interval_ms, blit=False, repeat=False)
    # Keep a strong reference so animation is not garbage-collected by matplotlib.
    fig._anim = anim
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="Live, non-technical 24h vineyard demo")
    parser.add_argument("--sim-speed", type=float, default=1.0, help="Sim seconds advanced per real second (1.0 = true realtime)")
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=321)
    parser.add_argument("--W", type=float, default=500.0)
    parser.add_argument("--H", type=float, default=500.0)
    parser.add_argument("--robot-radius-m", type=float, default=0.9)
    parser.add_argument("--done-draw-max", type=int, default=600, help="Max completed-task dots shown on map")
    parser.add_argument("--max-sim-steps-per-update", type=int, default=8, help="Cap sim frame advances per render tick")
    args = parser.parse_args()
    run_demo(
        sim_speed=args.sim_speed,
        fps=args.fps,
        dt=args.dt,
        seed=args.seed,
        W=args.W,
        H=args.H,
        robot_radius_m=args.robot_radius_m,
        done_draw_max=args.done_draw_max,
        max_sim_steps_per_update=args.max_sim_steps_per_update,
    )


if __name__ == "__main__":
    main()
