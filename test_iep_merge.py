"""iep_merge 的自动化测试。"""
import copy
import unittest

from iep_merge import ConflictError, merge


def obj(id_, text="text", metric="metric"):
    return {"id": id_, "text": text, "metric": metric}


def goal(id_, title="title", objectives=None):
    return {"id": id_, "title": title, "objectives": objectives or []}


def doc(goals):
    return {"goals": goals}


class MergeTest(unittest.TestCase):
    def test_different_fields_and_same_gap_inserts(self):
        # 两边分别修改同一短期目标的不同字段，并在同一间隙插入不同 ID
        base = doc([goal("g1", objectives=[obj("o1"), obj("o2")])])
        left = doc([goal("g1", objectives=[
            obj("o1", text="left text"),
            obj("new-b"),
            obj("o2"),
        ])])
        right = doc([goal("g1", objectives=[
            obj("o1", metric="right metric"),
            obj("new-a"),
            obj("o2"),
        ])])

        merged = merge(base, left, right)
        objectives = merged["goals"][0]["objectives"]
        by_id = {o["id"]: o for o in objectives}

        # 两个字段的修改都保留
        self.assertEqual(by_id["o1"]["text"], "left text")
        self.assertEqual(by_id["o1"]["metric"], "right metric")
        # 两个新增都保留，插入顺序确定：无直接约束时取字典序最小排列
        self.assertEqual([o["id"] for o in objectives],
                         ["o1", "new-a", "new-b", "o2"])
        # 交换 left/right 结果一致
        swapped = merge(base, right, left)
        self.assertEqual(merged, swapped)

    def test_objective_limit_exceeded(self):
        # base 有 4 个短期目标，两边各新增 1 个，合并后 6 个必须失败
        base = doc([goal("g1", objectives=[obj(f"o{i}") for i in range(4)])])
        left = doc([goal("g1", objectives=[obj(f"o{i}") for i in range(4)]
                    + [obj("new-l")])])
        right = doc([goal("g1", objectives=[obj(f"o{i}") for i in range(4)]
                     + [obj("new-r")])])
        base_snapshot = copy.deepcopy(base)
        left_snapshot = copy.deepcopy(left)
        right_snapshot = copy.deepcopy(right)

        with self.assertRaises(ConflictError):
            merge(base, left, right)

        # 输入保持不变
        self.assertEqual(base, base_snapshot)
        self.assertEqual(left, left_snapshot)
        self.assertEqual(right, right_snapshot)

    def test_same_field_conflict(self):
        base = doc([goal("g1", objectives=[obj("o1")])])
        left = doc([goal("g1", objectives=[obj("o1", text="a")])])
        right = doc([goal("g1", objectives=[obj("o1", text="b")])])
        with self.assertRaises(ConflictError):
            merge(base, left, right)

    def test_same_field_same_value_merges(self):
        base = doc([goal("g1", objectives=[obj("o1")])])
        left = doc([goal("g1", objectives=[obj("o1", text="same")])])
        right = doc([goal("g1", objectives=[obj("o1", text="same")])])
        merged = merge(base, left, right)
        self.assertEqual(
            merged["goals"][0]["objectives"][0]["text"], "same")

    def test_delete_goal_vs_edit_objective_conflicts(self):
        base = doc([goal("g1", objectives=[obj("o1")]), goal("g2")])
        left = doc([goal("g2")])  # 删除 g1
        right = doc([goal("g1", objectives=[obj("o1", text="edited")]),
                     goal("g2")])
        with self.assertRaises(ConflictError):
            merge(base, left, right)

    def test_delete_goal_vs_sibling_reorder_is_deleted(self):
        # 兄弟相对顺序变化不算子树修改：另一边仅重排目标，删除仍生效
        base = doc([goal("g1"), goal("g2"), goal("g3")])
        left = doc([goal("g2"), goal("g3")])  # 删除 g1
        right = doc([goal("g3"), goal("g2"), goal("g1")])  # 仅重排
        merged = merge(base, left, right)
        # 删除生效；right 反转了 g2/g3 这对节点，按规则采用反转后顺序
        self.assertEqual([g["id"] for g in merged["goals"]], ["g3", "g2"])

    def test_both_delete(self):
        base = doc([goal("g1"), goal("g2")])
        left = doc([goal("g2")])
        right = doc([goal("g2")])
        merged = merge(base, left, right)
        self.assertEqual([g["id"] for g in merged["goals"]], ["g2"])

    def test_identical_addition_merges(self):
        base = doc([goal("g1")])
        new_goal = goal("g-new", title="n", objectives=[obj("o1")])
        left = doc([goal("g1"), copy.deepcopy(new_goal)])
        right = doc([goal("g1"), copy.deepcopy(new_goal)])
        merged = merge(base, left, right)
        self.assertEqual([g["id"] for g in merged["goals"]], ["g1", "g-new"])

    def test_conflicting_addition_same_id(self):
        base = doc([goal("g1")])
        left = doc([goal("g1"), goal("g-new", title="a")])
        right = doc([goal("g1"), goal("g-new", title="b")])
        with self.assertRaises(ConflictError):
            merge(base, left, right)

    def test_base_pair_reversal_wins(self):
        # 一边反转 base 中已有节点顺序，另一边未调整，采用反转后顺序
        base = doc([goal("g1", objectives=[obj("o1"), obj("o2"), obj("o3")])])
        left = doc([goal("g1", objectives=[obj("o2"), obj("o1"), obj("o3")])])
        right = copy.deepcopy(base)
        merged = merge(base, left, right)
        self.assertEqual(
            [o["id"] for o in merged["goals"][0]["objectives"]],
            ["o2", "o1", "o3"])

    def test_opposite_new_node_orders_conflict(self):
        # 两个新增节点在两边顺序相反
        base = doc([goal("g1", objectives=[obj("o1")])])
        left = doc([goal("g1", objectives=[obj("o1"), obj("n1"), obj("n2")])])
        right = doc([goal("g1", objectives=[obj("o1"), obj("n2"), obj("n1")])])
        with self.assertRaises(ConflictError):
            merge(base, left, right)

    def test_no_mutation_of_inputs(self):
        base = doc([goal("g1", objectives=[obj("o1")])])
        left = doc([goal("g1", objectives=[obj("o1"), obj("n1")])])
        right = doc([goal("g1", "t2", [obj("o1", metric="m")])])
        snapshots = [copy.deepcopy(d) for d in (base, left, right)]
        merge(base, left, right)
        self.assertEqual([base, left, right], snapshots)


if __name__ == "__main__":
    unittest.main()
