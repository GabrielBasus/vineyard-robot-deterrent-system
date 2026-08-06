from __future__ import annotations

import argparse
import csv
import html
import json
import math
from pathlib import Path
from typing import Any

from action_schema import task_action_kind, task_action_name
from DeterrentSystem import run_simulation_frames_persistent
from experiments.run_current_vs_main_benchmark import _filter_supported_kwargs


STATUS_ORDER = {
    "in_progress": 0,
    "assigned": 1,
    "completed": 2,
    "dropped": 3,
    "deduped": 4,
    "candidate": 5,
}

EVENT_COLUMNS = [
    "t",
    "event",
    "status",
    "uid",
    "task_id",
    "stream",
    "type",
    "action",
    "origin",
    "mode",
    "assigned_primary",
    "robot_id",
    "x",
    "y",
    "score",
    "utility",
    "p_event",
    "confidence",
    "predicted_deltaJ",
    "deltaJ_per_cost",
    "predictive_deadline_slack_s",
    "forecast_event_time",
    "release_time",
    "required_arrival_by_t",
    "predictive_opportunity_key",
    "candidate_key",
    "cluster_key",
    "dedupe_key",
    "source",
]


def _finite(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    return out if math.isfinite(out) else float(default)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _action_name(task: dict[str, Any]) -> str:
    action = task.get("action")
    if isinstance(action, dict):
        name = _text(action.get("name"))
        kind = _text(action.get("kind"))
        return f"{kind}/{name}".strip("/")
    try:
        return f"{task_action_kind(task)}/{task_action_name(task)}"
    except Exception:
        task_type = _text(task.get("type"))
        mode = _text(task.get("mode"))
        return f"{task_type}/{mode}".strip("/")


def _stream(task: dict[str, Any]) -> str:
    explicit = _text(task.get("stream"))
    if explicit:
        return explicit
    action = task.get("action")
    if isinstance(action, dict):
        if _text(action.get("kind")) == "deterring" and _text(action.get("name")) == "direct_detection":
            return "reactive"
        return "predictive"
    try:
        if task_action_kind(task) == "deterring" and task_action_name(task) == "direct_detection":
            return "reactive"
    except Exception:
        pass
    return "predictive"


def _uid(task: dict[str, Any], *, prefix: str = "task") -> str:
    task_id = task.get("id")
    if task_id not in (None, ""):
        return f"task:{task_id}"
    for key_name, key_prefix in (
        ("predictive_opportunity_key", "opp"),
        ("candidate_key", "cand"),
        ("cluster_key", "cluster"),
        ("dedupe_key", "dedupe"),
    ):
        value = _text(task.get(key_name))
        if value:
            return f"{key_prefix}:{value}"
    robot_id = _text(task.get("assigned_primary") or task.get("robot_id"))
    return (
        f"{prefix}:{_stream(task)}:{_text(task.get('type'))}:{_text(task.get('origin'))}:"
        f"{robot_id}:{_finite(task.get('x'), 0.0):.1f}:{_finite(task.get('y'), 0.0):.1f}:"
        f"{_finite(task.get('time'), 0.0):.1f}"
    )


def _row_from_task(
    task: dict[str, Any],
    *,
    t: float,
    event: str,
    status: str,
    source: str,
    prefix: str = "task",
) -> dict[str, Any]:
    return {
        "t": float(t),
        "event": str(event),
        "status": str(status),
        "uid": _uid(task, prefix=prefix),
        "task_id": task.get("id", ""),
        "stream": _stream(task),
        "type": _text(task.get("type")),
        "action": _action_name(task),
        "origin": _text(task.get("origin")),
        "mode": _text(task.get("mode")),
        "assigned_primary": _text(task.get("assigned_primary")),
        "robot_id": _text(task.get("robot_id")),
        "x": _finite(task.get("x")),
        "y": _finite(task.get("y")),
        "score": _finite(task.get("score")),
        "utility": _finite(task.get("utility")),
        "p_event": _finite(task.get("p_event")),
        "confidence": _finite(task.get("predictive_confidence", task.get("confidence"))),
        "predicted_deltaJ": _finite(task.get("predicted_deltaJ")),
        "deltaJ_per_cost": _finite(task.get("deltaJ_per_cost")),
        "predictive_deadline_slack_s": _finite(task.get("predictive_deadline_slack_s")),
        "forecast_event_time": _finite(task.get("forecast_event_time")),
        "release_time": _finite(task.get("release_time")),
        "required_arrival_by_t": _finite(task.get("required_arrival_by_t")),
        "predictive_opportunity_key": _text(task.get("predictive_opportunity_key")),
        "candidate_key": _text(task.get("candidate_key")),
        "cluster_key": _text(task.get("cluster_key")),
        "dedupe_key": _text(task.get("dedupe_key")),
        "source": str(source),
    }


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _safe_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json_value(v) for v in value]
    return value


def _sort_visible(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        STATUS_ORDER.get(str(row.get("status")), 99),
        -_finite(row.get("t"), 0.0),
        str(row.get("stream", "")),
        str(row.get("uid", "")),
    )


def _update_lifecycle(
    lifecycle: dict[str, dict[str, Any]],
    event_rows: list[dict[str, Any]],
    row: dict[str, Any],
) -> None:
    uid = str(row["uid"])
    prev = lifecycle.get(uid)
    if prev is not None and prev.get("status") == row.get("status") and prev.get("event") == row.get("event"):
        prev.update(row)
        return
    lifecycle[uid] = dict(row)
    event_rows.append(dict(row))


def build_task_stream(
    *,
    sim_kwargs: dict[str, Any],
    sample_every_s: float,
    history_window_s: float,
    max_rows_per_frame: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lifecycle: dict[str, dict[str, Any]] = {}
    event_rows: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    active_uids_previous: set[str] = set()
    done_uids: set[str] = set()
    completed_seen: set[str] = set()
    dedupe_seen: set[str] = set()
    next_sample_t = -float("inf")

    runner_kwargs = _filter_supported_kwargs(run_simulation_frames_persistent, sim_kwargs)
    for snap in run_simulation_frames_persistent(**runner_kwargs):
        t = float(snap.get("t", 0.0))
        active_tasks = list(snap.get("tasks_active", []) or [])
        done_tasks = list(snap.get("tasks_done", []) or [])
        active_uids: set[str] = set()
        done_this_frame: set[str] = set()

        gen = dict(snap.get("task_generation_structured") or {})
        gen_t = _finite(gen.get("now_t"), float("nan"))
        gen_is_current = math.isfinite(gen_t) and abs(gen_t - t) <= 1e-9
        if gen_is_current:
            for candidate in list(gen.get("candidate_preview", []) or []):
                row = _row_from_task(
                    dict(candidate),
                    t=t,
                    event="candidate",
                    status="candidate",
                    source="task_generation",
                    prefix="candidate",
                )
                _update_lifecycle(lifecycle, event_rows, row)

            diag = dict(gen.get("diag_counts") or {})
            for deduped in list(diag.get("deduped_task_preview", []) or []):
                dedupe_id = f"{deduped.get('dedupe_key', '')}:{deduped.get('time', '')}"
                if dedupe_id in dedupe_seen:
                    continue
                dedupe_seen.add(dedupe_id)
                row = _row_from_task(
                    dict(deduped),
                    t=t,
                    event="deduped",
                    status="deduped",
                    source="task_generator_dedupe",
                    prefix="deduped",
                )
                _update_lifecycle(lifecycle, event_rows, row)

        dispatch = dict(snap.get("dispatch_structured") or {})
        dispatch_t = _finite(dispatch.get("now_t"), float("nan"))
        dispatch_is_current = math.isfinite(dispatch_t) and abs(dispatch_t - t) <= 1e-9
        if dispatch_is_current:
            for accepted in list(dispatch.get("accepted_preview", []) or []):
                row = _row_from_task(
                    dict(accepted),
                    t=t,
                    event="assigned",
                    status="assigned",
                    source="dispatch",
                    prefix="assigned",
                )
                _update_lifecycle(lifecycle, event_rows, row)

        for task in active_tasks:
            row = _row_from_task(
                dict(task),
                t=t,
                event="active",
                status="in_progress",
                source="active_tasks",
            )
            active_uids.add(str(row["uid"]))
            _update_lifecycle(lifecycle, event_rows, row)

        for task in done_tasks:
            row = _row_from_task(
                dict(task),
                t=t,
                event="complete",
                status="completed",
                source="tasks_done",
            )
            uid = str(row["uid"])
            done_uids.add(uid)
            if uid not in completed_seen:
                completed_seen.add(uid)
                done_this_frame.add(uid)
                _update_lifecycle(lifecycle, event_rows, row)

        dropped_now = active_uids_previous - active_uids - done_uids
        for uid in sorted(dropped_now):
            previous = dict(lifecycle.get(uid, {}))
            if not previous:
                continue
            previous.update({"t": t, "event": "dropped", "status": "dropped", "source": "active_disappeared"})
            _update_lifecycle(lifecycle, event_rows, previous)

        active_uids_previous = set(active_uids)

        should_sample = t + 1e-9 >= next_sample_t or gen_is_current or dispatch_is_current or bool(done_this_frame)
        if should_sample:
            cutoff_t = t - max(float(history_window_s), 0.0)
            visible = []
            for row in lifecycle.values():
                row_t = _finite(row.get("t"), -float("inf"))
                status = str(row.get("status"))
                if status == "in_progress" or row_t >= cutoff_t:
                    visible.append(dict(row))
            visible.sort(key=_sort_visible)
            visible = visible[: max(int(max_rows_per_frame), 1)]
            counts: dict[str, int] = {}
            for row in visible:
                counts[str(row.get("status", "unknown"))] = counts.get(str(row.get("status", "unknown")), 0) + 1
            frames.append(
                {
                    "t": float(t),
                    "counts": counts,
                    "rows": visible,
                }
            )
            next_sample_t = t + max(float(sample_every_s), 1.0)

    return event_rows, frames


def write_events_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVENT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in EVENT_COLUMNS})


def write_html(path: Path, *, frames: list[dict[str, Any]], title: str) -> None:
    safe_frames = _safe_json_value(frames)
    payload = json.dumps(safe_frames, allow_nan=False)
    escaped_title = html.escape(title)
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      --bg: #f5efe4;
      --ink: #211d18;
      --muted: #756b5f;
      --panel: #fffaf0;
      --line: #d9c8ad;
      --blue: #d8ebff;
      --blue-line: #2d6ea3;
      --green: #ddf4df;
      --green-line: #2f8f46;
      --red: #ffe1dc;
      --red-line: #b94a3b;
      --purple: #eadfff;
      --purple-line: #7650b5;
      --gray: #ece8df;
      --gray-line: #8a8175;
    }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at 20% 0%, rgba(69, 122, 77, 0.18), transparent 30rem),
        linear-gradient(120deg, #f7f0df, #efe4d0 55%, #f9f5ec);
      color: var(--ink);
      font-family: Georgia, "Times New Roman", serif;
    }}
    header {{
      padding: 1.4rem 1.8rem 0.8rem;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 250, 240, 0.76);
      backdrop-filter: blur(8px);
      position: sticky;
      top: 0;
      z-index: 2;
    }}
    h1 {{
      margin: 0 0 0.35rem;
      font-size: clamp(1.4rem, 2.7vw, 2.4rem);
      letter-spacing: -0.03em;
    }}
    .controls {{
      display: grid;
      grid-template-columns: auto minmax(12rem, 1fr) auto auto;
      gap: 0.75rem;
      align-items: center;
      margin-top: 1rem;
    }}
    button, input, select {{
      font: inherit;
    }}
    button {{
      border: 1px solid var(--ink);
      background: var(--ink);
      color: white;
      border-radius: 999px;
      padding: 0.45rem 0.9rem;
      cursor: pointer;
    }}
    input[type="range"] {{
      width: 100%;
    }}
    main {{
      padding: 1.2rem 1.8rem 2rem;
    }}
    .legend, .counts {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.55rem;
      margin: 0.75rem 0;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-left-width: 0.4rem;
      border-radius: 999px;
      background: var(--panel);
      padding: 0.32rem 0.7rem;
      font-size: 0.9rem;
    }}
    .in_progress {{ border-left-color: var(--blue-line); background: var(--blue); }}
    .assigned {{ border-left-color: var(--blue-line); background: var(--blue); }}
    .completed {{ border-left-color: var(--green-line); background: var(--green); }}
    .dropped {{ border-left-color: var(--red-line); background: var(--red); }}
    .deduped {{ border-left-color: var(--purple-line); background: var(--purple); }}
    .candidate {{ border-left-color: var(--gray-line); background: var(--gray); }}
    .table-wrap {{
      overflow: auto;
      border: 1px solid var(--line);
      background: rgba(255, 250, 240, 0.82);
      box-shadow: 0 16px 50px rgba(52, 42, 27, 0.10);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1200px;
      font-family: "Courier New", monospace;
      font-size: 0.86rem;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #342a1b;
      color: white;
      text-align: left;
      padding: 0.5rem;
      z-index: 1;
    }}
    td {{
      border-top: 1px solid rgba(92, 75, 51, 0.18);
      padding: 0.42rem 0.5rem;
      white-space: nowrap;
    }}
    tr.in_progress td, tr.assigned td {{ background: var(--blue); }}
    tr.completed td {{ background: var(--green); }}
    tr.dropped td {{ background: var(--red); }}
    tr.deduped td {{ background: var(--purple); }}
    tr.candidate td {{ background: var(--gray); }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 800px) {{
      .controls {{ grid-template-columns: 1fr; }}
      main, header {{ padding-left: 1rem; padding-right: 1rem; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escaped_title}</h1>
    <div class="muted">Use the slider or play button to step through task generation, assignment, active execution, completion, dropping, and deduplication.</div>
    <div class="controls">
      <button id="play">Play</button>
      <input id="slider" type="range" min="0" max="0" value="0" step="1">
      <strong id="timeLabel">t = 0s</strong>
      <label>Speed <select id="speed"><option value="900">Slow</option><option value="450" selected>Medium</option><option value="160">Fast</option></select></label>
    </div>
  </header>
  <main>
    <div class="legend">
      <span class="pill in_progress">blue: in progress / assigned</span>
      <span class="pill completed">green: completed</span>
      <span class="pill dropped">red: dropped</span>
      <span class="pill deduped">purple: deduped</span>
      <span class="pill candidate">gray: generated candidate</span>
    </div>
    <div id="counts" class="counts"></div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>status</th><th>event</th><th>uid</th><th>id</th><th>stream</th><th>action</th><th>origin</th><th>mode</th>
            <th>assigned</th><th>robot</th><th>x</th><th>y</th><th>score</th><th>utility</th><th>p_event</th><th>conf</th>
            <th>deltaJ</th><th>dJ/cost</th><th>slack</th><th>event_t</th><th>release</th><th>opp_key</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </main>
  <script>
    const frames = {payload};
    const slider = document.getElementById('slider');
    const tbody = document.getElementById('tbody');
    const timeLabel = document.getElementById('timeLabel');
    const play = document.getElementById('play');
    const speed = document.getElementById('speed');
    const counts = document.getElementById('counts');
    let timer = null;
    slider.max = Math.max(frames.length - 1, 0);
    function fmt(v, digits = 2) {{
      if (v === null || v === undefined || v === '') return '';
      if (typeof v === 'number') return Number.isFinite(v) ? v.toFixed(digits) : '';
      return String(v);
    }}
    function esc(v) {{
      return String(v ?? '').replace(/[&<>"']/g, s => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[s]));
    }}
    function render(index) {{
      const frame = frames[index] || {{t: 0, rows: [], counts: {{}}}};
      timeLabel.textContent = `t = ${{fmt(frame.t, 0)}}s`;
      counts.innerHTML = Object.entries(frame.counts || {{}})
        .map(([k, v]) => `<span class="pill ${{esc(k)}}">${{esc(k)}}: ${{v}}</span>`)
        .join('');
      tbody.innerHTML = (frame.rows || []).map(r => `
        <tr class="${{esc(r.status)}}">
          <td>${{esc(r.status)}}</td><td>${{esc(r.event)}}</td><td>${{esc(r.uid)}}</td><td>${{esc(r.task_id)}}</td>
          <td>${{esc(r.stream)}}</td><td>${{esc(r.action)}}</td><td>${{esc(r.origin)}}</td><td>${{esc(r.mode)}}</td>
          <td>${{esc(r.assigned_primary)}}</td><td>${{esc(r.robot_id)}}</td><td>${{fmt(r.x, 1)}}</td><td>${{fmt(r.y, 1)}}</td>
          <td>${{fmt(r.score, 3)}}</td><td>${{fmt(r.utility, 3)}}</td><td>${{fmt(r.p_event, 3)}}</td><td>${{fmt(r.confidence, 3)}}</td>
          <td>${{fmt(r.predicted_deltaJ, 3)}}</td><td>${{fmt(r.deltaJ_per_cost, 3)}}</td><td>${{fmt(r.predictive_deadline_slack_s, 1)}}</td>
          <td>${{fmt(r.forecast_event_time, 0)}}</td><td>${{fmt(r.release_time, 0)}}</td><td>${{esc(r.predictive_opportunity_key)}}</td>
        </tr>
      `).join('');
    }}
    function stop() {{
      if (timer !== null) window.clearInterval(timer);
      timer = null;
      play.textContent = 'Play';
    }}
    play.addEventListener('click', () => {{
      if (timer !== null) {{
        stop();
        return;
      }}
      play.textContent = 'Pause';
      timer = window.setInterval(() => {{
        let next = Number(slider.value) + 1;
        if (next >= frames.length) {{
          stop();
          next = frames.length - 1;
        }}
        slider.value = String(next);
        render(next);
      }}, Number(speed.value));
    }});
    slider.addEventListener('input', () => render(Number(slider.value)));
    render(0);
  </script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def _params_from_testbench_config(path: Path, system_key: str) -> dict[str, Any]:
    from testbench.run_testbench import _shared_runner_params

    config = json.loads(path.read_text(encoding="utf-8"))
    params = _shared_runner_params(dict(config.get("scenario") or {}))
    for system in list(config.get("systems") or []):
        if str(system.get("key")) == str(system_key):
            params.update(dict(system.get("params") or {}))
            return params
    raise ValueError(f"System {system_key!r} was not found in {path}")


def _default_params(args: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {
        "seed": int(args.seed),
        "T_end": float(args.duration_s),
        "dt": float(args.dt),
        "fps": 1,
        "Nrobots": int(args.robots),
        "uav_fraction": 0.0,
        "task_replan_period_s": float(args.task_replan_period_s),
        "arrival_radius_m": 3.0,
        "simulation_mode": "proposed",
        "enable_patrolling": True,
        "enable_intervention_feedback": True,
        "include_fallback_patrol": True,
        "enable_model_scored_deterring": bool(args.enable_model_scored_deterring),
        "use_ground_truth": True,
        "mu_true": float(args.mu_true),
        "alpha_true": float(args.alpha_true),
        "bird_detection_prob": float(args.bird_detection_prob),
        "detect_range_m": float(args.detect_range_m),
        "warmup_s": float(args.warmup_s),
        "report_metrics_end": False,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }
    system = str(args.system).strip()
    if system == "unc":
        params["dispatch_policy"] = "unc"
    elif system:
        params["planner_profile"] = system
    if args.planner_profile:
        params["planner_profile"] = str(args.planner_profile)
    if args.dispatch_policy:
        params["dispatch_policy"] = str(args.dispatch_policy)
    return params


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an interactive task-stream table for the vineyard simulator.")
    parser.add_argument("--outdir", type=Path, default=Path("results/task_stream_viewer"))
    parser.add_argument("--testbench-config", type=Path, default=None)
    parser.add_argument("--system-key", default="unc")
    parser.add_argument("--system", default="res_0p25", help="unc, res_0p25, res_rand_0p25, or any planner profile.")
    parser.add_argument("--planner-profile", default="")
    parser.add_argument("--dispatch-policy", default="")
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--duration-s", type=float, default=900.0)
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument("--robots", type=int, default=2)
    parser.add_argument("--mu-true", type=float, default=5e-6)
    parser.add_argument("--alpha-true", type=float, default=0.30)
    parser.add_argument("--warmup-s", type=float, default=0.0)
    parser.add_argument("--bird-detection-prob", type=float, default=1.0)
    parser.add_argument("--detect-range-m", type=float, default=30.0)
    parser.add_argument("--task-replan-period-s", type=float, default=45.0)
    parser.add_argument("--enable-model-scored-deterring", action="store_true")
    parser.add_argument("--sample-every-s", type=float, default=10.0)
    parser.add_argument("--history-window-s", type=float, default=180.0)
    parser.add_argument("--max-rows-per-frame", type=int, default=80)
    args = parser.parse_args()

    if args.testbench_config is not None:
        sim_kwargs = _params_from_testbench_config(Path(args.testbench_config), str(args.system_key))
        sim_kwargs["seed"] = int(args.seed)
        sim_kwargs["T_end"] = float(args.duration_s)
        sim_kwargs["dt"] = float(args.dt)
    else:
        sim_kwargs = _default_params(args)

    event_rows, frames = build_task_stream(
        sim_kwargs=sim_kwargs,
        sample_every_s=float(args.sample_every_s),
        history_window_s=float(args.history_window_s),
        max_rows_per_frame=int(args.max_rows_per_frame),
    )

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    events_csv = outdir / "task_stream_events.csv"
    frames_json = outdir / "task_stream_frames.json"
    html_path = outdir / "task_stream_view.html"
    manifest_path = outdir / "task_stream_manifest.json"
    write_events_csv(events_csv, event_rows)
    frames_json.write_text(json.dumps(_safe_json_value(frames), indent=2, allow_nan=False), encoding="utf-8")
    write_html(html_path, frames=frames, title=f"Task Stream Viewer - {args.system or args.system_key}")
    manifest_path.write_text(
        json.dumps(
            {
                "event_count": len(event_rows),
                "frame_count": len(frames),
                "outputs": {
                    "html": str(html_path),
                    "events_csv": str(events_csv),
                    "frames_json": str(frames_json),
                },
                "sim_kwargs": _safe_json_value(sim_kwargs),
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    print(f"[task-stream-viewer] wrote {html_path}")
    print(f"[task-stream-viewer] events {events_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
