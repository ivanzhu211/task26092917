"""Three-way merge for IEP draft documents.

Document model (plain dicts):
    document  := {"goals": [goal, ...]}
    goal      := {"id": str, "title": str, "objectives": [objective, ...]}
    objective := {"id": str, "text": str, "metric": str}
"""

from __future__ import annotations

import copy
import heapq
from typing import Any

from iep_merge.errors import MergeConflict

Document = dict[str, Any]
Node = dict[str, Any]

MAX_OBJECTIVES_PER_GOAL = 5


def _subtree_equal(a: Node, b: Node, scalar_fields: tuple[str, ...], children_key: str | None) -> bool:
    """Ordered recursive content comparison of two nodes."""
    for field in scalar_fields:
        if a[field] != b[field]:
            return False
    if children_key is None:
        return True
    ca, cb = a[children_key], b[children_key]
    if len(ca) != len(cb):
        return False
    return all(
        _subtree_equal(x, y, _CHILD_SCALAR_FIELDS[children_key], _CHILD_CHILDREN_KEY[children_key])
        for x, y in zip(ca, cb)
    )


_GOAL_SCALAR_FIELDS = ("title",)
_OBJECTIVE_SCALAR_FIELDS = ("text", "metric")
_CHILD_SCALAR_FIELDS = {"objectives": _OBJECTIVE_SCALAR_FIELDS}
_CHILD_CHILDREN_KEY = {"objectives": None}


def merge(base: Document, left: Document, right: Document) -> Document:
    """Merge two independent revisions of a common base snapshot.

    Returns the merged draft document. Raises MergeConflict on failure.
    Never mutates the inputs.
    """
    goals = _merge_list(
        base["goals"],
        left["goals"],
        right["goals"],
        scalar_fields=_GOAL_SCALAR_FIELDS,
        children_key="objectives",
        max_items=None,
        where="goals",
    )
    return {"goals": goals}


def _merge_list(
    base_items: list[Node],
    left_items: list[Node],
    right_items: list[Node],
    scalar_fields: tuple[str, ...],
    children_key: str | None,
    max_items: int | None,
    where: str,
) -> list[Node]:
    base_by_id = {n["id"]: n for n in base_items}
    left_by_id = {n["id"]: n for n in left_items}
    right_by_id = {n["id"]: n for n in right_items}

    surviving: dict[str, Node] = {}
    for node_id in base_by_id.keys() | left_by_id.keys() | right_by_id.keys():
        b = base_by_id.get(node_id)
        l = left_by_id.get(node_id)
        r = right_by_id.get(node_id)
        if b is not None:
            if l is None and r is None:
                continue  # deleted on both sides
            if l is None or r is None:
                kept = r if l is None else l
                if _subtree_equal(b, kept, scalar_fields, children_key):
                    continue  # deleted on one side, untouched on the other
                raise MergeConflict(
                    f"{where}: node {node_id!r} deleted on one side but modified on the other"
                )
            surviving[node_id] = _merge_existing(b, l, r, scalar_fields, children_key, node_id, where)
        else:
            if l is not None and r is not None:
                if not _subtree_equal(l, r, scalar_fields, children_key):
                    raise MergeConflict(
                        f"{where}: node {node_id!r} added on both sides with different content"
                    )
                surviving[node_id] = copy.deepcopy(l)
            else:
                surviving[node_id] = copy.deepcopy(l if l is not None else r)

    if max_items is not None and len(surviving) > max_items:
        raise MergeConflict(
            f"{where}: merged list has {len(surviving)} items, exceeds limit of {max_items}"
        )

    order = _resolve_order(
        [n["id"] for n in base_items],
        [n["id"] for n in left_items],
        [n["id"] for n in right_items],
        set(surviving),
        where,
    )
    return [surviving[node_id] for node_id in order]


def _merge_existing(
    b: Node, l: Node, r: Node, scalar_fields: tuple[str, ...], children_key: str | None, node_id: str, where: str
) -> Node:
    merged: Node = {"id": node_id}
    for field in scalar_fields:
        bv, lv, rv = b[field], l[field], r[field]
        if lv == rv:
            merged[field] = lv
        elif lv == bv:
            merged[field] = rv
        elif rv == bv:
            merged[field] = lv
        else:
            raise MergeConflict(
                f"{where}: field {field!r} of node {node_id!r} changed to different values"
            )
    if children_key is not None:
        merged[children_key] = _merge_list(
            b[children_key],
            l[children_key],
            r[children_key],
            scalar_fields=_CHILD_SCALAR_FIELDS[children_key],
            children_key=_CHILD_CHILDREN_KEY[children_key],
            max_items=MAX_OBJECTIVES_PER_GOAL,
            where=f"{where}/{node_id}",
        )
    return merged


def _resolve_order(
    base_ids: list[str],
    left_ids: list[str],
    right_ids: list[str],
    surviving: set[str],
    where: str,
) -> list[str]:
    base_pos = {node_id: i for i, node_id in enumerate(base_ids)}
    branch_positions = [
        {node_id: i for i, node_id in enumerate(left_ids)},
        {node_id: i for i, node_id in enumerate(right_ids)},
    ]

    must_precede: dict[str, set[str]] = {node_id: set() for node_id in surviving}

    ids = sorted(surviving)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            a_in_base = a in base_pos
            b_in_base = b in base_pos
            if a_in_base and b_in_base:
                first, second = (a, b) if base_pos[a] < base_pos[b] else (b, a)
                reversed_by_branch = any(
                    first in pos and second in pos and pos[first] > pos[second]
                    for pos in branch_positions
                )
                before, after = (second, first) if reversed_by_branch else (first, second)
                must_precede[before].add(after)
            else:
                required: tuple[str, str] | None = None
                for pos in branch_positions:
                    if a in pos and b in pos:
                        pair = (a, b) if pos[a] < pos[b] else (b, a)
                        if required is not None and required != pair:
                            raise MergeConflict(
                                f"{where}: branches require opposite order of {a!r} and {b!r}"
                            )
                        required = pair
                if required is not None:
                    must_precede[required[0]].add(required[1])

    indegree = {node_id: 0 for node_id in surviving}
    for before, afters in must_precede.items():
        for after in afters:
            indegree[after] += 1

    heap = [node_id for node_id in surviving if indegree[node_id] == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        node_id = heapq.heappop(heap)
        order.append(node_id)
        for after in must_precede[node_id]:
            indegree[after] -= 1
            if indegree[after] == 0:
                heapq.heappush(heap, after)

    if len(order) != len(surviving):
        raise MergeConflict(f"{where}: relative order requirements are cyclic")
    return order
