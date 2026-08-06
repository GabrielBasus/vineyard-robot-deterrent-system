# streamlit_app.py
#
# Live dashboard for the Python simulation using telemetry_sim.py.
#
# Usage:
#   1) Run your sim so it calls:
#          mon.flush_live('telemetry_live')
#      every few steps.
#   2) In another terminal:
#          pip install streamlit plotly pandas
#          streamlit run demos/streamlit_app.py
#
#   3) Set "Telemetry folder" in the sidebar if different from "telemetry_live".

import os
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    from demos._bootstrap import REPO_ROOT, resolve_repo_path
except ModuleNotFoundError:
    from _bootstrap import REPO_ROOT, resolve_repo_path

st.set_page_config(page_title="Vineyard Multi-Robot — Live Monitor",
                   layout="wide")

# ---------------------------- data loading ---------------------------- #

def _empty_df(cols):
    return pd.DataFrame(columns=cols)

def _read_csv(path, cols):
    try:
        if not os.path.exists(path):
            return _empty_df(cols)
        df = pd.read_csv(path)
        for c in cols:
            if c not in df.columns:
                df[c] = np.nan
        return df[cols]
    except Exception:
        return _empty_df(cols)

def load_data(data_dir: str):
    resolved_dir = str(resolve_repo_path(data_dir))
    poses = _read_csv(os.path.join(resolved_dir, "robot_poses.csv"),
                      ["t", "rid", "x", "y"])
    zones = _read_csv(os.path.join(resolved_dir, "zones.csv"),
                      ["t", "rid", "poly"])
    tasks = _read_csv(os.path.join(resolved_dir, "tasks.csv"),
                      ["t", "event", "id", "rid_primary", "rid_secondary",
                       "type", "x", "y", "score", "extra"])
    hots  = _read_csv(os.path.join(resolved_dir, "hotspots.csv"),
                      ["t", "rid", "rank", "x", "y", "score"])
    rdiag = _read_csv(
        os.path.join(resolved_dir, "robot_diagnostics.csv"),
        [
            "t", "rid", "battery", "state", "task",
            "goal_x", "goal_y", "eff_goal_x", "eff_goal_y",
            "dist_to_goal", "lane_cur", "lane_tgt", "at_headland",
        ],
    )
    return poses, zones, tasks, hots, rdiag

def parse_poly(s: str | float | None):
    if not isinstance(s, str) or not s:
        return None
    pts = []
    for tok in s.split("|"):
        parts = tok.strip().split()
        if len(parts) != 2:
            continue
        try:
            x, y = float(parts[0]), float(parts[1])
            pts.append((x, y))
        except ValueError:
            continue
    return pts if len(pts) >= 3 else None

def world_bounds(zones: pd.DataFrame, poses: pd.DataFrame):
    xs, ys = [], []
    for s in zones["poly"].dropna():
        poly = parse_poly(s)
        if not poly:
            continue
        for x, y in poly:
            xs.append(x)
            ys.append(y)
    xs += poses["x"].tolist()
    ys += poses["y"].tolist()
    if not xs or not ys:
        return (0, 100, 0, 100)
    return (min(xs) - 5, max(xs) + 5, min(ys) - 5, max(ys) + 5)

def active_tasks_df(tasks: pd.DataFrame) -> pd.DataFrame:
    """Return tasks whose last event is not complete/cancel."""
    if tasks.empty:
        return tasks
    tasks = tasks.copy()
    tasks = tasks.sort_values("t")
    last = tasks.groupby("id").tail(1)
    active = last[~last["event"].isin(["complete", "cancel"])]
    return active.sort_values("t", ascending=False)

def make_map(zones, poses, tasks, hots, rdiag):
    xmin, xmax, ymin, ymax = world_bounds(zones, poses)
    fig = go.Figure()

    # zones as line loops (latest per rid)
    if not zones.empty:
        latest_z = zones.sort_values("t").groupby("rid").tail(1)
        for _, row in latest_z.iterrows():
            poly = parse_poly(row["poly"])
            if not poly:
                continue
            xs = [p[0] for p in poly] + [poly[0][0]]
            ys = [p[1] for p in poly] + [poly[0][1]]
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines",
                name=f"zone:{row['rid']}",
                line=dict(width=2)
            ))

    # robot positions (latest per rid)
    if not poses.empty:
        last_pose = poses.sort_values("t").groupby("rid").tail(1)
        labels = last_pose["rid"].astype(str)
        if not rdiag.empty:
            last_diag = rdiag.sort_values("t").groupby("rid").tail(1).set_index("rid")
            labels = [
                f"{rid} ({last_diag.loc[rid, 'state']})" if rid in last_diag.index else rid
                for rid in last_pose["rid"].astype(str).tolist()
            ]
        fig.add_trace(go.Scatter(
            x=last_pose["x"], y=last_pose["y"],
            mode="markers+text",
            text=labels,
            textposition="top center",
            marker=dict(size=10),
            name="robots"
        ))

    # active tasks
    a = active_tasks_df(tasks)
    if not a.empty:
        fig.add_trace(go.Scatter(
            x=a["x"], y=a["y"],
            mode="markers",
            marker=dict(size=9, symbol="diamond"),
            name="active tasks"
        ))

    # hotspots (last few per rid)
    if not hots.empty:
        latest_h = hots.sort_values("t").groupby("rid").tail(3)
        fig.add_trace(go.Scatter(
            x=latest_h["x"], y=latest_h["y"],
            mode="markers",
            marker=dict(size=7, symbol="x"),
            name="hotspots"
        ))

    fig.update_layout(
        height=650,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0)
    )
    fig.update_xaxes(range=[xmin, xmax], scaleanchor="y", scaleratio=1)
    fig.update_yaxes(range=[ymin, ymax])
    return fig

# ----------------------------- UI layout ----------------------------- #

st.title("🍇 Vineyard Multi-Robot — Live Monitor")

data_dir = st.sidebar.text_input("Telemetry folder", value=str(REPO_ROOT / "telemetry_live"))
refresh_ms = st.sidebar.slider("Refresh every (ms)", 200, 3000, 800, 50)
target_sim_s = st.sidebar.number_input("Target sim time (s)", min_value=1, value=24 * 3600, step=60)

col_map, col_tasks = st.columns([2, 1], gap="large")

poses, zones, tasks, hots, rdiag = load_data(data_dir)

# Simulation progress bar (based on latest telemetry timestamp).
t_candidates = []
if not poses.empty:
    t_candidates.append(float(poses["t"].max()))
if not tasks.empty:
    t_candidates.append(float(tasks["t"].max()))
if not hots.empty:
    t_candidates.append(float(hots["t"].max()))
if not rdiag.empty:
    t_candidates.append(float(rdiag["t"].max()))
latest_t = max(t_candidates) if t_candidates else 0.0
progress = min(max(latest_t / float(target_sim_s), 0.0), 1.0)
st.sidebar.markdown("### Simulation Progress")
st.sidebar.progress(progress)
st.sidebar.caption(f"{latest_t:.0f}s / {float(target_sim_s):.0f}s ({progress*100:.1f}%)")

with col_map:
    st.subheader("Live Map")
    fig = make_map(zones, poses, tasks, hots, rdiag)
    st.plotly_chart(fig, use_container_width=True)

with col_tasks:
    st.subheader("Active tasks")
    a = active_tasks_df(tasks)
    st.caption(f"{len(a)} active")
    if not a.empty:
        st.dataframe(
            a[["t", "id", "type", "x", "y", "score", "rid_primary", "rid_secondary", "event"]],
            height=600
        )
    else:
        st.write("No active tasks.")

st.subheader("Robot diagnostics")
if not rdiag.empty:
    latest_diag = rdiag.sort_values("t").groupby("rid").tail(1)
    st.dataframe(
        latest_diag[
            [
                "t", "rid", "battery", "state", "task", "dist_to_goal",
                "goal_x", "goal_y", "eff_goal_x", "eff_goal_y",
                "lane_cur", "lane_tgt", "at_headland",
            ]
        ].sort_values("rid"),
        use_container_width=True,
        height=280,
    )
else:
    st.caption("No robot diagnostics yet. Make sure simulation calls mon.robot_diag(...).")

st.sidebar.markdown("---")
st.sidebar.caption("Dashboard auto-refreshes based on your slider.")

# naive auto-refresh via sleep+rerun
time.sleep(refresh_ms / 1000.0)
st.rerun()
