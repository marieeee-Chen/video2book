"""Normalize article bodies consistently for assembly and validation."""
import re
from pathlib import Path

from .heading_numbers import plan_heading_cleanup


def read_article_body(article: Path, *, preserve_header: bool = False) -> str:
    """读模块长文正文：剥掉抬头（H1 / 引用块 / 分隔线），并把章内标题降一级、剥掉手写序号。

    为什么必须剥抬头：本书的章标题由本块接管，长文的 H1 与元信息引用块留在正文里会
    与章标题打架（旧实现只剥一行，多行引用块的第二行 `>` 会残留成章首的孤立引用）。
    为什么必须降级：长文的 `##` 与本书的章标题同级，不降级会与章标题并列成两个同层标题。
    """
    # errors="replace"：个别长文混入非 UTF-8 字节时不让整次整编崩掉；
    # 去 BOM：带 BOM 的长文首行是 \ufeff# 篇名，不去会漏过抬头剥离与去号规则。
    text = article.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")

    # Normalize any unescaped literal \n in markdown text
    norm_lines = []
    in_c = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_c = not in_c
            norm_lines.append(line)
        elif not in_c and r"\n" in line:
            norm_lines.extend(line.replace(r"\n", "\n").splitlines())
        else:
            norm_lines.append(line)
    text = "\n".join(norm_lines)

    head_lines = text.strip().splitlines()
    head_idx = 0
    while not preserve_header and head_idx < len(head_lines):
        head_text = head_lines[head_idx].strip()
        if (
            not head_text
            or head_text.startswith(">")
            or re.match(r"^#\s", head_text)          # 长文 H1（篇名）：由章标题接管
            or re.fullmatch(r"-{3,}", head_text)      # 抬头与正文之间的分隔线
        ):
            head_idx += 1
            continue
        break
    body = "\n".join(head_lines[head_idx:])

    # 先剥号、再降级（##→###、###→####）：存量长文标题带 `## 2.1 …` 这类手写序号，
    # 不剥会与阅读器的自动编号叠成双号；新长文已由提示词要求不写序号，所以这一步幂等。
    # 剥号走**文档级计划**：只有成序的标题才剥，孤立数字（`## 80 小时…`）动都不动。
    # 围栏判定与上面的归一化循环保持同一口径（strip 后判定）：列表项内缩进的围栏
    # 也是围栏，漏认会让围栏内的 `##` 被误降级、状态在两循环间失步。
    chunk = body.strip()
    strip_targets = {
        item["line"]: item["after"] for item in plan_heading_cleanup(chunk)["auto"]
    }
    demoted = []
    in_code = False
    for line_no, line in enumerate(chunk.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
        if not in_code:
            line = strip_targets.get(line_no, line)
            if line.startswith("#### "):
                line = "#" + line  # becomes #####
            elif line.startswith("### "):
                line = "#" + line  # becomes ####
            elif line.startswith("## "):
                line = "#" + line  # becomes ###
        demoted.append(line)
    return "\n".join(demoted)
