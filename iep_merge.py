"""IEP 修订稿三路合并库。

文档模型：
- 文档: {"goals": [goal, ...]}
- 年度目标 goal: {"id": str, "title": str, "objectives": [objective, ...]}
- 短期目标 objective: {"id": str, "text": str, "metric": str}
"""

from __future__ import annotations

import copy
import heapq
from typing import Any, Callable

Document = dict[str, Any]
Goal = dict[str, Any]
Objective = dict[str, Any]

MAX_OBJECTIVES_PER_GOAL = 5


class ConflictError(Exception):
    """合并失败（字段、增删或顺序冲突）时抛出。"""


def merge(base: Document, left: Document, right: Document) -> Document:
    """三路合并，成功返回新草稿，失败抛出 ConflictError。不修改输入。"""
    goals = _merge_goal_list(base["goals"], left["goals"], right["goals"], "goals")
    return {"goals": goals}


def _merge_scalar(base_val: str, left_val: str, right_val: str, where: str) -> str:
    if left_val == right_val:
        return left_val
    if left_val == base_val:
        return right_val
    if right_val == base_val:
        return left_val
    raise ConflictError(f"字段冲突: {where}")


def _merge_goal_list(
    base_list: list[Goal], left_list: list[Goal], right_list: list[Goal], path: str
) -> list[Goal]:
    return _merge_node_list(base_list, left_list, right_list, _merge_goal, path)


def _merge_objective_list(
    base_list: list[Objective],
    left_list: list[Objective],
    right_list: list[Objective],
    path: str,
) -> list[Objective]:
    return _merge_node_list(base_list, left_list, right_list, _merge_objective, path)


def _merge_goal(base_node: Goal, left_node: Goal, right_node: Goal, path: str) -> Goal:
    goal_id = base_node["id"]
    title = _merge_scalar(
        base_node["title"], left_node["title"], right_node["title"],
        f"{path}/{goal_id}.title",
    )
    objectives = _merge_objective_list(
        base_node["objectives"], left_node["objectives"], right_node["objectives"],
        f"{path}/{goal_id}.objectives",
    )
    if len(objectives) > MAX_OBJECTIVES_PER_GOAL:
        raise ConflictError(
            f"短期目标数量超限: {path}/{goal_id} 合并后有 {len(objectives)} 个"
        )
    return {"id": goal_id, "title": title, "objectives": objectives}


def _merge_objective(
    base_node: Objective, left_node: Objective, right_node: Objective, path: str
) -> Objective:
    obj_id = base_node["id"]
    return {
        "id": obj_id,
        "text": _merge_scalar(
            base_node["text"], left_node["text"], right_node["text"],
            f"{path}/{obj_id}.text",
        ),
        "metric": _merge_scalar(
            base_node["metric"], left_node["metric"], right_node["metric"],
            f"{path}/{obj_id}.metric",
        ),
    }


def _merge_node_list(
    base_list: list[dict],
    left_list: list[dict],
    right_list: list[dict],
    merge_existing: Callable[[dict, dict, dict, str], dict],
    path: str,
) -> list[dict]:
    base_by_id = {node["id"]: node for node in base_list}
    left_by_id = {node["id"]: node for node in left_list}
    right_by_id = {node["id"]: node for node in right_list}

    surviving: dict[str, dict] = {}

    # base 中已存在的节点：合并、删除或报冲突
    for node_id, base_node in base_by_id.items():
        left_node = left_by_id.get(node_id)
        right_node = right_by_id.get(node_id)
        if left_node is not None and right_node is not None:
            surviving[node_id] = merge_existing(
                base_node, left_node, right_node, path
            )
        elif left_node is not None:  # right 删除
            if left_node != base_node:
                raise ConflictError(f"删除与修改冲突: {path}/{node_id}")
        elif right_node is not None:  # left 删除
            if right_node != base_node:
                raise ConflictError(f"删除与修改冲突: {path}/{node_id}")
        # 双边删除：直接丢弃

    # 新增节点
    for node_id, left_node in left_by_id.items():
        if node_id in base_by_id:
            continue
        right_node = right_by_id.get(node_id)
        if right_node is not None:
            if right_node != left_node:
                raise ConflictError(f"双边新增同 ID 但内容不同: {path}/{node_id}")
            surviving[node_id] = copy.deepcopy(left_node)
        else:
            surviving[node_id] = copy.deepcopy(left_node)
    for node_id, right_node in right_by_id.items():
        if node_id in base_by_id or node_id in left_by_id:
            continue
        surviving[node_id] = copy.deepcopy(right_node)

    ordered_ids = _resolve_order(surviving.keys(), base_list, left_list, right_list, path)
    return [surviving[node_id] for node_id in ordered_ids]


def _resolve_order(
    surviving_ids,
    base_list: list[dict],
    left_list: list[dict],
    right_list: list[dict],
    path: str,
) -> list[str]:
    """根据三路相对顺序约束求最终顺序；多解取 ID 序列字典序最小者。"""
    ids = list(surviving_ids)
    base_pos = _positions(base_list)
    left_pos = _positions(left_list)
    right_pos = _positions(right_list)

    edges: set[tuple[str, str]] = set()
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if a in base_pos and b in base_pos:
                # 双方都存在于 base：默认 base 顺序，任一分支反转则采用反转后顺序
                base_order = (a, b) if base_pos[a] < base_pos[b] else (b, a)
                constraint = base_order
                for pos in (left_pos, right_pos):
                    if a in pos and b in pos:
                        branch = (a, b) if pos[a] < pos[b] else (b, a)
                        if branch != base_order:
                            constraint = branch
                edges.add(constraint)
            else:
                # 至少一个是新增节点：每个同时包含二者的分支都产生约束
                for pos in (left_pos, right_pos):
                    if a in pos and b in pos:
                        edges.add((a, b) if pos[a] < pos[b] else (b, a))

    return _topological_sort(ids, edges, path)


def _positions(node_list: list[dict]) -> dict[str, int]:
    return {node["id"]: index for index, node in enumerate(node_list)}


def _topological_sort(
    ids: list[str], edges: set[tuple[str, str]], path: str
) -> list[str]:
    """Kahn 算法 + 最小堆，得到字典序最小的合法排列；有环则报顺序冲突。"""
    indegree = {node_id: 0 for node_id in ids}
    successors: dict[str, list[str]] = {node_id: [] for node_id in ids}
    for before, after in edges:
        successors[before].append(after)
        indegree[after] += 1

    heap = [node_id for node_id in ids if indegree[node_id] == 0]
    heapq.heapify(heap)
    result: list[str] = []
    while heap:
        node_id = heapq.heappop(heap)
        result.append(node_id)
        for nxt in successors[node_id]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(heap, nxt)
    if len(result) != len(ids):
        raise ConflictError(f"顺序冲突: {path} 不存在满足全部相对顺序要求的排列")
    return result
