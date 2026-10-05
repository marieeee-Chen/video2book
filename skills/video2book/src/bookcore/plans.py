"""Domain-neutral volume coverage validation, extracted from video2book."""
from typing import Any, Dict, List, Sequence, Tuple


def validate_volume_plan(
    plan: Sequence[Dict[str, Any]], blocks: Sequence[Dict[str, Any]], vague_titles=()
) -> Tuple[bool, str]:
    """校验分册规划：块**恰好被认领一次**、册名非空且能看出内容、`volume_id` 合法且唯一。"""
    if not plan:
        return False, "分册规划为空"
    known = [int(b.get("block_id") or 0) for b in blocks]
    claimed: List[int] = []
    ids: List[int] = []
    for index, volume in enumerate(plan, 1):
        title = str(volume.get("volume_title") or "").strip()
        if not title:
            return False, f"第 {index} 册缺少 volume_title（册名要能看出内容）"
        if title in vague_titles:
            return False, f"第 {index} 册用了空泛册名「{title}」，请写成能看出内容的主题名"
        raw_id = volume.get("volume_id")
        if raw_id is not None:
            try:
                vid = int(raw_id)
            except (TypeError, ValueError):
                return False, f"第 {index} 册的 volume_id 非法：{raw_id!r}（应为从 1 开始的整数）"
            if vid < 1:
                return False, f"第 {index} 册的 volume_id 必须 >= 1，收到 {vid}"
            ids.append(vid)
        raw = volume.get("blocks")
        if not isinstance(raw, list) or not raw:
            return False, f"第 {index} 册未认领任何块"
        for item in raw:
            try:
                claimed.append(int(item))
            except (TypeError, ValueError):
                return False, f"第 {index} 册的块编号非法：{item!r}"
    dup_ids = sorted({v for v in ids if ids.count(v) > 1})
    if dup_ids:
        return False, f"volume_id 重复：{dup_ids}（每册的 volume_id 必须唯一）"
    unknown = sorted({b for b in claimed if b not in known})
    if unknown:
        return False, f"分册规划引用了不存在的块编号: {unknown}"
    duplicated = sorted({b for b in claimed if claimed.count(b) > 1})
    if duplicated:
        return False, f"同一块被多册重复认领: {duplicated}"
    missing = sorted(set(known) - set(claimed))
    if missing:
        return False, f"未被任何册认领的块: {missing}"
    return True, f"分册规划有效（{len(plan)} 册 / {len(blocks)} 个块）"
