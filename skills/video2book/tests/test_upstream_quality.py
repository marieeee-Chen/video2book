"""Selected upstream 730878a rule regressions (MIT); no auto-rewrite."""
import pytest
from src.core.deliverable_lint import lint_render, summarize_render, fatal_render_total

BROKEN_INLINE = (
    "# 行列式与方程组\n\n"
    "## 系数行列式的判定\n\n"
    "未知数前面的系数组成的行列式 $D \n"
    "eq 0$，这就决定了方程组具有唯一解。\n"
)

#: 显示公式断行：收尾 `$$` 落在行尾 → 阅读器会继续往后吞
BROKEN_DISPLAY = (
    "# 行列式与方程组\n\n"
    "## 矩阵记法与分块\n\n"
    "分块之后左上块与右下块各管一段：\n\n"
    "$$\\begin{vmatrix}1&0&1\\\\ 1&1&0\\\\ 0&1&1\\end{vmatrix}=1-0+1=2\n"
    "eq 0$$\n"
)

#: 级联：同一处断成三行（`$x_1 ` / `eq x_2 \implies f(x_1) ` / `eq f(x_2)$$`）
BROKEN_CASCADE = (
    "# 映射与函数\n\n"
    "## 单射与满射\n\n"
    "对任意 $x_1 \n"
    "eq x_2 \\implies f(x_1) \n"
    "eq f(x_2)$$ 都成立。\n"
)


def test_inline_formula_break_is_detected():
    assert len(lint_render(BROKEN_INLINE)["formula_breaks"]) == 1


def test_display_formula_break_is_detected():
    assert len(lint_render(BROKEN_DISPLAY)["formula_breaks"]) == 1


def test_cascade_counts_every_broken_line():
    """级联断两行就报两处：口径与 `--fix-formula-breaks` 的计数一致。"""
    assert len(lint_render(BROKEN_CASCADE)["formula_breaks"]) == 2


@pytest.mark.parametrize("broken_line", [
    "eq 0$",            # 行内公式
    "eq\\mathbf 0$",    # 断在转义命令前（无空格变体，按 `^eq ` 扫会漏掉这一种）
    "eq\\varnothing,",  # `eq` 后紧跟反斜杠
    "eq 1)",
])
def test_formula_break_variants_are_detected(broken_line: str):
    text = f"# 笔记\n\n## 一节\n\n公式 $x \n{broken_line}\n"
    assert len(lint_render(text)["formula_breaks"]) == 1, f"漏判: {broken_line!r}"


def test_formula_break_is_fatal():
    summary = summarize_render(lint_render(BROKEN_INLINE))
    assert summary["formula_breaks"] == 1
    assert fatal_render_total(summary) >= 1, "公式断裂没进致命项"


@pytest.mark.parametrize("line", [
    "equals 是「等于」的英文。",
    "equation (3) 给出了定义。",
])
def test_english_words_starting_with_eq_are_not_breaks(line: str):
    """`equals` / `equation` 以 `eq` 开头但不是断裂：判据要求 `eq` 后面不是字母。"""
    text = f"# 笔记\n\n## 一节\n\n前一行有内容。\n{line}\n"
    assert lint_render(text)["formula_breaks"] == [], f"英文词被误判: {line!r}"


def test_fenced_eq_line_is_not_a_break():
    """围栏里的 `eq` 可能是代码，一律不判。"""
    text = "# 笔记\n\n## 一节\n\n```python\neq = 1\n```\n"
    assert lint_render(text)["formula_breaks"] == [], "围栏内的 eq 行被计入"


def test_eq_line_after_blank_line_is_not_a_break():
    """上一行是空行说明这是段落起句，不是续行。"""
    text = "# 笔记\n\n## 一节\n\n上一段结束了。\n\neq 开头的独立段落。\n"
    assert lint_render(text)["formula_breaks"] == [], "段落起句被误判成断裂"


# ===========================================================================
# 六·五、思维链泄漏（写作模型自我对话落进产物）与同文件重复标题
# ===========================================================================
# 语料出处：2026-11-01 issue#2（宋浩高数 2.0 模块11）。写作子智能体在单次超长 Write 中
# 注意力崩坏，把自我对话原样写进长文并经整编流入教材，`check --deliver` 当时全绿。
# cot_leak 为致命项（泄漏文本不是知识内容，且模式高度特征化——发布仓 64 门课 4000+ 份
# 成品复扫只有坏样本命中）；duplicate_headings 为提示级（讲义存在合法的章节性重名，
# ≥2 就门禁会误杀）。

COT_LEAK_LINES = [
    "I need to fix this. I need to be careful here. I'm producing a messy document.",
    "Let me just clean it up and rewrite it from scratch.",
    "The generator might be going off the rails. I'm producing garbage.",
    "I will now write a clean, final version.",
    "This is clearly going wrong badly. I've been repeating nonsensical content.",
    "I have the content. Let me now write the correct final article. I need to be careful:",
    "I attempted to edit with old_string, but I Write tool only has file_path and content parameters.",
]


@pytest.mark.parametrize("line", COT_LEAK_LINES)
def test_cot_leak_line_is_fatal(line: str):
    """issue#2 真实泄漏行必须逐条命中并计入致命项。"""
    text = _doc("# 测试笔记", "## 数组的连续布局", line)
    lint = lint_render(text)
    assert len(lint["cot_leaks"]) == 1, f"思维链泄漏漏判: {line!r}"
    assert fatal_render_total(summarize_render(lint)) >= 1, "思维链泄漏没进致命项"


@pytest.mark.parametrize("line", [
    "The equation $x^2+y^2=R^2$ describes a sphere.",
    "We need to be careful about the coordinate system when rotating around the z-axis.",
    "Let me show you how this formula works in three dimensions.",  # Let me + 非元动作
    "First we write a clean derivation, then we check the boundary conditions.",  # 无第一人称元动作
])
def test_legitimate_english_is_not_cot_leak(line: str):
    """讲义里合法的英文术语句与教学句不得误伤——判据要求第一人称与写作元动作同现。"""
    text = _doc("# 测试笔记", "## 数组的连续布局", line)
    assert lint_render(text)["cot_leaks"] == [], f"合法英文被误判: {line!r}"


def test_fenced_cot_leak_is_not_counted():
    """围栏里的英文是待讲解的示例代码，不算泄漏。"""
    text = _doc("# 测试笔记", "## 数组的连续布局",
                "```text\nI'm producing garbage because I'm writing too much text inline.\n```")
    assert lint_render(text)["cot_leaks"] == [], "围栏内的英文被计入泄漏"


def test_duplicate_same_level_headings_are_reported():
    """同文件同级标题重名 ≥2 报 1 处（按组计）。"""
    text = _doc("# 测试笔记", "## 圆锥面", PLAIN_BODY, "## 圆锥面", PLAIN_BODY)
    dups = lint_render(text)["duplicate_headings"]
    assert len(dups) == 1 and dups[0]["count"] == 2, f"重名标题漏判: {dups}"


def test_duplicate_headings_across_levels_and_names():
    """不同级、不同名不算重名；多组重名逐组各报一处。"""
    text = _doc("# 测试笔记", "## 甲", PLAIN_BODY, "### 甲", PLAIN_BODY,  # 级别不同不算
                "## 乙", PLAIN_BODY, "## 乙", PLAIN_BODY, "## 乙", PLAIN_BODY)  # 同级同名 ×3
    dups = lint_render(text)["duplicate_headings"]
    assert [d["count"] for d in dups] == [3], f"跨级/多组口径漂移: {dups}"


def test_duplicate_headings_whitelist_and_fence():
    """白名单讲题小节（每章一节）不判；围栏里的示例标题不判。"""
    text = _doc("# 测试笔记",
                "## 本讲提到的题目", PLAIN_BODY, "## 本讲提到的题目", PLAIN_BODY,
                "```text\n## 速查卡\n## 速查卡\n```")
    assert lint_render(text)["duplicate_headings"] == [], "白名单/围栏标题被误判"


def test_duplicate_headings_summary_is_warning_only():
    """重复标题是提示项：不计入致命总数（cot_leaks 才是门禁）。"""
    text = _doc("# 测试笔记", "## 甲", PLAIN_BODY, "## 甲", PLAIN_BODY)
    summary = summarize_render(lint_render(text))
    assert summary["duplicate_headings"] == 1
    assert fatal_render_total(summary) == 0, "重复标题混进了致命总数"


# ── 修复内核 ────────────────────────────────────────────────────────────────



PLAIN_BODY = "数组在内存里连续存放，按下标访问的代价是常数时间。"
def _doc(*blocks):
    return "\n\n".join(blocks) + "\n"
