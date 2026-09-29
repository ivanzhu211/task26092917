# task26092917

IEP 修订稿三路合并库。两名工作人员从同一份定稿快照分别编辑，`merge` 将两份修订稿合并为下一份草稿。

## 用法

```python
from iep_merge import merge, MergeConflict

try:
    draft = merge(base, left, right)  # 不修改输入
except MergeConflict as exc:
    print("合并冲突:", exc.reason)
```

文档模型：`{"goals": [{"id", "title", "objectives": [{"id", "text", "metric"}]}]}`，ID 全局唯一，每个年度目标最多 5 个短期目标。

## 测试

```sh
python3 -m pytest tests/ -q
```
