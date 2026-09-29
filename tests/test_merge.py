import copy

import pytest

from iep_merge import MergeConflict, merge


def make_doc(goals):
    return {"goals": goals}


def make_goal(goal_id, title, objectives):
    return {"id": goal_id, "title": title, "objectives": objectives}


def make_obj(obj_id, text, metric):
    return {"id": obj_id, "text": text, "metric": metric}


def objective_ids(doc, goal_index=0):
    return [o["id"] for o in doc["goals"][goal_index]["objectives"]]


def test_disjoint_field_edits_and_same_gap_inserts():
    base = make_doc([
        make_goal("g1", "Goal 1", [
            make_obj("o1", "read", "80% accuracy"),
            make_obj("o2", "write", "3 sentences"),
        ])
    ])
    left = copy.deepcopy(base)
    right = copy.deepcopy(base)

    # Each side edits a different field of the same objective o1.
    left["goals"][0]["objectives"][0]["text"] = "read aloud"
    right["goals"][0]["objectives"][0]["metric"] = "90% accuracy"

    # Each side inserts a different new objective into the same gap (between o1 and o2).
    left["goals"][0]["objectives"].insert(1, make_obj("oa", "left-new", "weekly"))
    right["goals"][0]["objectives"].insert(1, make_obj("ob", "right-new", "daily"))

    merged = merge(base, left, right)

    by_id = {o["id"]: o for o in merged["goals"][0]["objectives"]}
    assert by_id["o1"] == make_obj("o1", "read aloud", "90% accuracy")
    assert by_id["oa"] == make_obj("oa", "left-new", "weekly")
    assert by_id["ob"] == make_obj("ob", "right-new", "daily")
    # Both inserts sit between o1 and o2; oa vs ob is unconstrained, so the
    # lexicographically smallest id sequence wins.
    assert objective_ids(merged) == ["o1", "oa", "ob", "o2"]

    # Swapping left and right must not change the outcome.
    assert merge(base, right, left) == merged


def test_objective_limit_exceeded_and_inputs_untouched():
    base = make_doc([
        make_goal("g1", "Goal 1", [
            make_obj("o1", "a", "m1"),
            make_obj("o2", "b", "m2"),
            make_obj("o3", "c", "m3"),
            make_obj("o4", "d", "m4"),
        ])
    ])
    left = copy.deepcopy(base)
    right = copy.deepcopy(base)
    left["goals"][0]["objectives"].append(make_obj("o5", "e", "m5"))
    right["goals"][0]["objectives"].append(make_obj("o6", "f", "m6"))

    snapshot = (copy.deepcopy(base), copy.deepcopy(left), copy.deepcopy(right))

    with pytest.raises(MergeConflict):
        merge(base, left, right)

    assert (base, left, right) == snapshot


def test_same_field_conflicting_edits():
    base = make_doc([make_goal("g1", "t", [make_obj("o1", "a", "m")])])
    left = copy.deepcopy(base)
    right = copy.deepcopy(base)
    left["goals"][0]["objectives"][0]["text"] = "x"
    right["goals"][0]["objectives"][0]["text"] = "y"
    with pytest.raises(MergeConflict):
        merge(base, left, right)


def test_same_field_same_edit_merges():
    base = make_doc([make_goal("g1", "t", [make_obj("o1", "a", "m")])])
    left = copy.deepcopy(base)
    right = copy.deepcopy(base)
    left["goals"][0]["objectives"][0]["text"] = "x"
    right["goals"][0]["objectives"][0]["text"] = "x"
    merged = merge(base, left, right)
    assert merged["goals"][0]["objectives"][0]["text"] == "x"


def test_delete_goal_vs_edit_objective_conflicts():
    base = make_doc([make_goal("g1", "t", [make_obj("o1", "a", "m")])])
    left = make_doc([])  # deletes g1
    right = copy.deepcopy(base)
    right["goals"][0]["objectives"][0]["text"] = "edited"
    with pytest.raises(MergeConflict):
        merge(base, left, right)


def test_delete_vs_untouched_removes_node():
    base = make_doc([
        make_goal("g1", "t1", []),
        make_goal("g2", "t2", []),
    ])
    left = make_doc([copy.deepcopy(base["goals"][1])])  # deletes g1
    right = copy.deepcopy(base)
    merged = merge(base, left, right)
    assert [g["id"] for g in merged["goals"]] == ["g2"]


def test_both_add_same_id_different_content_conflicts():
    base = make_doc([make_goal("g1", "t", [])])
    left = copy.deepcopy(base)
    right = copy.deepcopy(base)
    left["goals"][0]["objectives"].append(make_obj("n1", "left", "m"))
    right["goals"][0]["objectives"].append(make_obj("n1", "right", "m"))
    with pytest.raises(MergeConflict):
        merge(base, left, right)


def test_both_add_same_id_same_content_merges():
    base = make_doc([make_goal("g1", "t", [])])
    left = copy.deepcopy(base)
    right = copy.deepcopy(base)
    new_obj = make_obj("n1", "same", "m")
    left["goals"][0]["objectives"].append(copy.deepcopy(new_obj))
    right["goals"][0]["objectives"].append(copy.deepcopy(new_obj))
    merged = merge(base, left, right)
    assert merged["goals"][0]["objectives"] == [new_obj]


def test_one_branch_reversal_wins_over_untouched_branch():
    base = make_doc([make_goal("g1", "t", [
        make_obj("o1", "a", "m1"),
        make_obj("o2", "b", "m2"),
        make_obj("o3", "c", "m3"),
    ])])
    left = copy.deepcopy(base)
    right = copy.deepcopy(base)
    # Left swaps o1 and o2; right leaves the list untouched.
    objs = left["goals"][0]["objectives"]
    objs[0], objs[1] = objs[1], objs[0]
    merged = merge(base, left, right)
    assert objective_ids(merged) == ["o2", "o1", "o3"]
    assert merge(base, right, left) == merged


def test_opposite_new_node_order_requirements_conflict():
    base = make_doc([make_goal("g1", "t", [])])
    left = make_doc([make_goal("g1", "t", [make_obj("na", "x", "m"), make_obj("nb", "y", "m")])])
    right = make_doc([make_goal("g1", "t", [make_obj("nb", "y", "m"), make_obj("na", "x", "m")])])
    with pytest.raises(MergeConflict):
        merge(base, left, right)
