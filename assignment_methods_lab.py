from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Tuple
import math


ScoreFn = Callable[[str, int], float]
EligibleFn = Callable[[str, int], bool]
TaskTypeFn = Callable[[int], str]


@dataclass
class AssignmentRequest:
    tasks: List[dict]
    robots: List[str]
    capacity_by_robot: Dict[str, int]
    score_fn: ScoreFn
    eligible_fn: EligibleFn
    task_type_fn: TaskTypeFn | None = None
    neighbors_by_robot: Mapping[str, List[str]] | None = None
    cbba_max_rounds: int = 25
    cbba_epsilon: float = 1e-9
    protocol: Dict[str, float | str] = field(default_factory=dict)


@dataclass
class AssignmentResult:
    primary_by_task_idx: Dict[int, str] = field(default_factory=dict)
    debug: Dict = field(default_factory=dict)


def _safe_score(req: AssignmentRequest, rid: str, tidx: int) -> float:
    if not req.eligible_fn(rid, tidx):
        return float("-inf")
    s = float(req.score_fn(rid, tidx))
    return s if math.isfinite(s) else float("-inf")


def _is_better_candidate(
    s_a: float,
    rid_a: str,
    s_b: float | None,
    rid_b: str | None,
    eps: float = 1e-9,
) -> bool:
    if s_b is None or rid_b is None:
        return True
    if s_a > s_b + eps:
        return True
    if abs(s_a - s_b) <= eps and str(rid_a) < str(rid_b):
        return True
    return False


def _slots_from_capacity(robots: List[str], capacity_by_robot: Dict[str, int]) -> List[Tuple[str, int]]:
    slots: List[Tuple[str, int]] = []
    for rid in robots:
        cap = max(0, int(capacity_by_robot.get(rid, 0)))
        for k in range(cap):
            slots.append((rid, k))
    return slots


def _score_matrix(req: AssignmentRequest, slots: List[Tuple[str, int]]) -> Tuple[List[List[float]], int, int]:
    n = len(slots)
    m = len(req.tasks)
    mat = [[float("-inf") for _ in range(m)] for _ in range(n)]
    feasible = 0
    infeasible = 0
    for i, (rid, _k) in enumerate(slots):
        for j in range(m):
            s = _safe_score(req, rid, j)
            if math.isfinite(s):
                mat[i][j] = s
                feasible += 1
            else:
                infeasible += 1
    return mat, feasible, infeasible


def _edge_stats(req: AssignmentRequest) -> Tuple[int, int]:
    feasible = 0
    infeasible = 0
    for rid in req.robots:
        for j in range(len(req.tasks)):
            s = _safe_score(req, rid, j)
            if math.isfinite(s):
                feasible += 1
            else:
                infeasible += 1
    return feasible, infeasible


def _assignment_utility(req: AssignmentRequest, out: Dict[int, str]) -> float:
    total = 0.0
    for tidx, rid in out.items():
        s = _safe_score(req, rid, tidx)
        if math.isfinite(s):
            total += s
    return float(total)


def solve_frozen_greedy(req: AssignmentRequest) -> AssignmentResult:
    remaining = {rid: max(0, int(req.capacity_by_robot.get(rid, 0))) for rid in req.robots}
    out: Dict[int, str] = {}

    for j in range(len(req.tasks)):
        best_rid = None
        best_score = float("-inf")
        for rid in req.robots:
            if remaining.get(rid, 0) <= 0:
                continue
            s = _safe_score(req, rid, j)
            if not math.isfinite(s):
                continue
            if (s > best_score) or (s == best_score and (best_rid is None or str(rid) < str(best_rid))):
                best_score = s
                best_rid = rid
        if best_rid is not None:
            out[j] = best_rid
            remaining[best_rid] = remaining.get(best_rid, 0) - 1

    feasible_edges, infeasible_edges = _edge_stats(req)
    return AssignmentResult(
        primary_by_task_idx=out,
        debug={
            "method": "frozen_greedy",
            "assigned": len(out),
            "unmatched_tasks": max(0, len(req.tasks) - len(out)),
            "feasible_edges": int(feasible_edges),
            "infeasible_edges": int(infeasible_edges),
            "objective_utility": _assignment_utility(req, out),
        },
    )


def _hungarian_min(cost: List[List[float]]) -> Tuple[List[int], float]:
    n = len(cost)
    m = len(cost[0]) if n > 0 else 0
    if n == 0 or m == 0:
        return [], 0.0

    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        minv = [float("inf")] * (m + 1)
        used = [False] * (m + 1)
        j0 = 0
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(0, m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assign = [-1] * n
    for j in range(1, m + 1):
        if p[j] != 0:
            assign[p[j] - 1] = j - 1

    total = 0.0
    for i, j in enumerate(assign):
        if j >= 0:
            total += cost[i][j]
    return assign, total


def solve_hungarian(req: AssignmentRequest) -> AssignmentResult:
    slots = _slots_from_capacity(req.robots, req.capacity_by_robot)
    if not slots or not req.tasks:
        return AssignmentResult(
            primary_by_task_idx={},
            debug={
                "method": "hungarian",
                "assigned": 0,
                "unmatched_tasks": len(req.tasks),
                "feasible_edges": 0,
                "infeasible_edges": len(slots) * len(req.tasks),
                "objective_utility": 0.0,
            },
        )

    profit, feasible_edges, infeasible_edges = _score_matrix(req, slots)
    n = len(slots)
    m_real = len(req.tasks)
    m = max(m_real, n)

    finite_vals = [v for row in profit for v in row if math.isfinite(v)]
    if not finite_vals:
        return AssignmentResult(
            primary_by_task_idx={},
            debug={
                "method": "hungarian",
                "assigned": 0,
                "slots": len(slots),
                "unmatched_tasks": m_real,
                "feasible_edges": int(feasible_edges),
                "infeasible_edges": int(infeasible_edges),
                "objective_utility": 0.0,
                "failures": 1,
            },
        )

    max_profit = max([0.0] + finite_vals)
    huge = 1e9

    cost = [[0.0 for _ in range(m)] for _ in range(n)]
    for i in range(n):
        for j in range(m):
            if j < m_real:
                p = profit[i][j]
                if math.isfinite(p):
                    cost[i][j] = max_profit - p
                else:
                    cost[i][j] = huge
            else:
                cost[i][j] = max_profit

    assign_row_to_col, _ = _hungarian_min(cost)

    out: Dict[int, str] = {}
    used_tasks = set()
    for i, col in enumerate(assign_row_to_col):
        if col < 0 or col >= m_real:
            continue
        rid, _k = slots[i]
        s = _safe_score(req, rid, col)
        if not math.isfinite(s):
            continue
        if col in used_tasks:
            continue
        out[col] = rid
        used_tasks.add(col)

    return AssignmentResult(
        primary_by_task_idx=out,
        debug={
            "method": "hungarian",
            "assigned": len(out),
            "slots": len(slots),
            "unmatched_tasks": max(0, m_real - len(out)),
            "feasible_edges": int(feasible_edges),
            "infeasible_edges": int(infeasible_edges),
            "objective_utility": _assignment_utility(req, out),
            "failures": 0,
        },
    )


def solve_auction(req: AssignmentRequest, epsilon: float = 1e-3, max_iter: int = 200000) -> AssignmentResult:
    slots = _slots_from_capacity(req.robots, req.capacity_by_robot)
    if not slots or not req.tasks:
        return AssignmentResult(primary_by_task_idx={}, debug={"method": "auction", "assigned": 0, "converged": True})

    n = len(slots)
    m = len(req.tasks)
    prices = [0.0] * m
    owner_by_task: List[int | None] = [None] * m
    task_by_slot: List[int | None] = [None] * n
    queue = list(range(n))

    iters = 0
    bid_updates = 0
    while queue and iters < max_iter:
        i = queue.pop(0)
        rid, _k = slots[i]

        cand: List[Tuple[float, float, int]] = []
        for j in range(m):
            s = _safe_score(req, rid, j)
            if not math.isfinite(s):
                continue
            net = s - prices[j]
            cand.append((net, s, j))

        if not cand:
            iters += 1
            continue

        cand.sort(key=lambda x: (x[0], x[1], -x[2]), reverse=True)
        best_net, _best_score, j_star = cand[0]
        second_net = cand[1][0] if len(cand) > 1 else (best_net - 1.0)
        bid = max(epsilon, best_net - second_net + epsilon)

        prices[j_star] += bid
        prev_owner = owner_by_task[j_star]
        owner_by_task[j_star] = i
        task_by_slot[i] = j_star
        if prev_owner is not None and prev_owner != i:
            task_by_slot[prev_owner] = None
            queue.append(prev_owner)
        bid_updates += 1
        iters += 1

    out: Dict[int, str] = {}
    for j, owner in enumerate(owner_by_task):
        if owner is None:
            continue
        rid, _k = slots[owner]
        s = _safe_score(req, rid, j)
        if math.isfinite(s):
            out[j] = rid

    feasible_edges, infeasible_edges = _edge_stats(req)
    return AssignmentResult(
        primary_by_task_idx=out,
        debug={
            "method": "auction",
            "assigned": len(out),
            "unmatched_tasks": max(0, len(req.tasks) - len(out)),
            "iters": iters,
            "converged": (len(queue) == 0),
            "max_iter": max_iter,
            "epsilon": float(epsilon),
            "bid_updates": int(bid_updates),
            "feasible_edges": int(feasible_edges),
            "infeasible_edges": int(infeasible_edges),
            "objective_utility": _assignment_utility(req, out),
            "failures": 0 if len(queue) == 0 else 1,
        },
    )


def solve_cbba_centralized(req: AssignmentRequest, max_rounds: int = 25) -> AssignmentResult:
    tasks_n = len(req.tasks)
    if tasks_n == 0:
        return AssignmentResult(primary_by_task_idx={}, debug={"method": "cbba_centralized", "assigned": 0, "rounds": 0})

    capacities = {rid: max(0, int(req.capacity_by_robot.get(rid, 0))) for rid in req.robots}
    winner: Dict[int, str] = {}
    rounds = 0
    conflicts_resolved = 0
    bid_updates = 0

    for r in range(max_rounds):
        rounds = r + 1
        proposals: Dict[int, Tuple[float, str]] = {}
        per_task_proposal_count: Dict[int, int] = {}

        for rid in req.robots:
            cap = capacities.get(rid, 0)
            if cap <= 0:
                continue
            bids: List[Tuple[float, int]] = []
            for j in range(tasks_n):
                s = _safe_score(req, rid, j)
                if math.isfinite(s):
                    bids.append((s, j))
            bids.sort(key=lambda z: (z[0], -z[1]), reverse=True)
            picked = bids[:cap]
            for s, j in picked:
                per_task_proposal_count[j] = per_task_proposal_count.get(j, 0) + 1
                cur = proposals.get(j)
                if cur is None or _is_better_candidate(s, rid, cur[0], cur[1], req.cbba_epsilon):
                    proposals[j] = (s, rid)
                    bid_updates += 1

        new_winner = {j: rid for j, (_s, rid) in proposals.items()}
        conflicts_resolved += sum(1 for j, c in per_task_proposal_count.items() if c > 1)

        if new_winner == winner:
            break
        winner = new_winner

    out = dict(winner)
    feasible_edges, infeasible_edges = _edge_stats(req)
    return AssignmentResult(
        primary_by_task_idx=out,
        debug={
            "method": "cbba_centralized",
            "assigned": len(out),
            "rounds": int(rounds),
            "rounds_to_convergence": int(rounds),
            "converged": bool(rounds < max_rounds or len(out) == 0),
            "max_rounds": int(max_rounds),
            "conflicts_resolved": int(conflicts_resolved),
            "bid_updates": int(bid_updates),
            "message_passes": 0,
            "message_updates": 0,
            "failures": 0,
            "unmatched_tasks": max(0, tasks_n - len(out)),
            "feasible_edges": int(feasible_edges),
            "infeasible_edges": int(infeasible_edges),
            "objective_utility": _assignment_utility(req, out),
        },
    )


def _neighbors_for_req(req: AssignmentRequest) -> Dict[str, List[str]]:
    robots = [str(rid) for rid in req.robots]
    robot_set = set(robots)
    if req.neighbors_by_robot is None:
        return {rid: [r for r in robots if r != rid] for rid in robots}

    nbrs: Dict[str, List[str]] = {}
    for rid in robots:
        raw = list(req.neighbors_by_robot.get(rid, []))
        cleaned = sorted({str(n) for n in raw if str(n) in robot_set and str(n) != rid})
        nbrs[rid] = cleaned
    return nbrs


def solve_cbba_decentralized(req: AssignmentRequest) -> AssignmentResult:
    tasks_n = len(req.tasks)
    if tasks_n == 0:
        return AssignmentResult(
            primary_by_task_idx={},
            debug={"method": "cbba_decentralized", "assigned": 0, "rounds": 0, "converged": True},
        )

    robots = [str(rid) for rid in req.robots]
    capacities = {rid: max(0, int(req.capacity_by_robot.get(rid, 0))) for rid in robots}
    eps = float(max(1e-12, req.cbba_epsilon))
    max_rounds = int(max(1, req.cbba_max_rounds))
    neighbors = _neighbors_for_req(req)

    local_views: Dict[str, List[Tuple[float, str] | None]] = {rid: [None] * tasks_n for rid in robots}
    bundles: Dict[str, List[int]] = {rid: [] for rid in robots}

    rounds = 0
    converged = False
    conflicts_resolved = 0
    bid_updates = 0
    message_passes = 0
    message_updates = 0
    failures = 0

    for r in range(max_rounds):
        rounds = r + 1
        changed = False

        # Bundle build phase (local only).
        for rid in sorted(robots):
            cap = capacities.get(rid, 0)
            if cap <= 0:
                continue
            bundle = bundles[rid]
            local = local_views[rid]
            while len(bundle) < cap:
                best_score = None
                best_task = None
                for j in range(tasks_n):
                    if j in bundle:
                        continue
                    s = _safe_score(req, rid, j)
                    if not math.isfinite(s):
                        continue
                    cur = local[j]
                    if cur is not None and not _is_better_candidate(s, rid, cur[0], cur[1], eps):
                        continue
                    if best_task is None:
                        best_score = s
                        best_task = j
                    elif _is_better_candidate(s, rid, best_score, rid, eps) or (
                        abs(s - float(best_score)) <= eps and j < int(best_task)
                    ):
                        best_score = s
                        best_task = j
                if best_task is None:
                    break
                prev = local[best_task]
                local[best_task] = (float(best_score), rid)
                bundle.append(int(best_task))
                bid_updates += 1
                if prev != local[best_task]:
                    changed = True

        # Consensus phase: robots communicate winner tables to neighbors.
        for sender in sorted(robots):
            sender_view = local_views[sender]
            for recv in neighbors.get(sender, []):
                if recv not in local_views:
                    continue
                message_passes += 1
                recv_view = local_views[recv]
                for j, cand in enumerate(sender_view):
                    if cand is None:
                        continue
                    cur = recv_view[j]
                    if cur is None or _is_better_candidate(cand[0], cand[1], cur[0], cur[1], eps):
                        recv_view[j] = cand
                        message_updates += 1
                        changed = True

        # Bundle repair phase.
        for rid in sorted(robots):
            bundle = bundles[rid]
            if not bundle:
                continue
            local = local_views[rid]
            new_bundle = []
            for j in bundle:
                winner = local[j]
                if winner is not None and winner[1] == rid:
                    new_bundle.append(j)
                else:
                    conflicts_resolved += 1
                    changed = True
            bundles[rid] = new_bundle

        if not changed:
            converged = True
            break

    if not converged:
        failures += 1

    # Aggregate converged winner table and enforce per-robot capacity.
    best_by_task: Dict[int, Tuple[float, str]] = {}
    for rid in sorted(robots):
        for j, cand in enumerate(local_views[rid]):
            if cand is None:
                continue
            cur = best_by_task.get(j)
            if cur is None or _is_better_candidate(cand[0], cand[1], cur[0], cur[1], eps):
                best_by_task[j] = cand

    per_robot_tasks: Dict[str, List[Tuple[float, int]]] = {rid: [] for rid in robots}
    for j in sorted(best_by_task.keys()):
        s, rid = best_by_task[j]
        if not math.isfinite(s):
            continue
        if math.isfinite(_safe_score(req, rid, j)):
            per_robot_tasks[rid].append((s, j))

    out: Dict[int, str] = {}
    dropped_due_capacity = 0
    for rid in sorted(robots):
        cap = capacities.get(rid, 0)
        if cap <= 0:
            dropped_due_capacity += len(per_robot_tasks[rid])
            continue
        lst = sorted(per_robot_tasks[rid], key=lambda z: (-z[0], z[1]))
        keep = lst[:cap]
        dropped_due_capacity += max(0, len(lst) - len(keep))
        for _s, j in keep:
            if j not in out:
                out[j] = rid

    if dropped_due_capacity > 0:
        failures += int(dropped_due_capacity)

    feasible_edges, infeasible_edges = _edge_stats(req)
    mean_degree = 0.0
    if robots:
        mean_degree = float(sum(len(neighbors.get(rid, [])) for rid in robots)) / float(len(robots))
    return AssignmentResult(
        primary_by_task_idx=out,
        debug={
            "method": "cbba_decentralized",
            "assigned": len(out),
            "rounds": int(rounds),
            "rounds_to_convergence": int(rounds),
            "converged": bool(converged),
            "max_rounds": int(max_rounds),
            "conflicts_resolved": int(conflicts_resolved),
            "bid_updates": int(bid_updates),
            "message_passes": int(message_passes),
            "message_updates": int(message_updates),
            "failures": int(failures),
            "dropped_due_capacity": int(dropped_due_capacity),
            "unmatched_tasks": max(0, tasks_n - len(out)),
            "feasible_edges": int(feasible_edges),
            "infeasible_edges": int(infeasible_edges),
            "mean_neighbor_degree": float(mean_degree),
            "objective_utility": _assignment_utility(req, out),
        },
    )


def solve_assignment(method: str, request: AssignmentRequest) -> AssignmentResult:
    m = str(method).strip().lower()
    if m in ("frozen", "frozen_greedy", "greedy"):
        return solve_frozen_greedy(request)
    if m in ("hungarian", "munkres"):
        return solve_hungarian(request)
    if m in ("auction", "auction_based"):
        return solve_auction(request)
    if m in ("cbba_centralized", "cbba_cent", "cbba_legacy"):
        return solve_cbba_centralized(request, max_rounds=request.cbba_max_rounds)
    if m in ("cbba", "cbba_decentralized"):
        return solve_cbba_decentralized(request)
    raise ValueError(f"Unsupported assignment method: {method}")
