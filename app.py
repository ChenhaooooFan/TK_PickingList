"""
NailVesta 拣货单汇总工具
========================
将 TikTok Shop 导出的拣货 PDF 解析为按库位排序的产品汇总表,并自动对账。

【输入】拣货 PDF(必选) + 产品图册 CSV(可选,含 SKU/库位 两列)
【输出】对账面板、按库位排序的明细表、B链产品汇总、可下载 CSV

【对账公式】期望件数 = PDF 标注 Item quantity + bundle 拆分多出件数
           实际件数 = 所有提取 SKU 件数总和(含 NF001/NB001/Choose Sets/B链)

【特殊 SKU】
- NF001 免费赠品 / NB001 收纳册:无尺寸,独立成行(灰色)
- Choose N Sets:占位 SKU,按段落汇总成"混合套装"一行(灰色)
- B链产品(工具包/折叠盒/美甲册):单独汇总在 B链区域

【维护】新款上架只需更新 sku_data.py,详见该文件顶部说明。
【依赖】streamlit, pandas, pymupdf
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field

import fitz
import pandas as pd
import streamlit as st

from sku_data import SKU_NAMES, NEW_SKUS, SIZELESS_SKUS, B_CHAIN_SKU_MAP

# ============================================================================
# 页面配置 + 全局样式
# ============================================================================
st.set_page_config(
    page_title="NailVesta 拣货单工具",
    page_icon="💅",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CSS = """
<style>
    /* 隐藏默认元素 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}
    header[data-testid="stHeader"] {background: transparent;}
    /* === 全局背景:奶油白 → 莓粉 渐变 === */
    .stApp {
        background:
            radial-gradient(circle at 0% 0%, #fff5f7 0%, transparent 50%),
            radial-gradient(circle at 100% 0%, #fef0f5 0%, transparent 50%),
            radial-gradient(circle at 50% 100%, #fdf3f8 0%, transparent 50%),
            #fefcfb;
    }
    /* === 主容器 === */
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 4rem;
        max-width: 1180px;
    }
    /* === Hero 标题区 === */
    .hero-wrap {
        background: linear-gradient(135deg, #ffffff 0%, #fff8f5 50%, #fef2f5 100%);
        border-radius: 28px;
        padding: 40px 48px;
        margin-bottom: 28px;
        box-shadow:
            0 4px 24px rgba(232, 165, 180, 0.12),
            0 1px 3px rgba(232, 165, 180, 0.08);
        border: 1px solid rgba(232, 165, 180, 0.18);
        position: relative;
        overflow: hidden;
    }
    .hero-wrap::before {
        content: '';
        position: absolute;
        top: -50%;
        right: -10%;
        width: 300px;
        height: 300px;
        background: radial-gradient(circle, rgba(255, 200, 215, 0.25) 0%, transparent 70%);
        pointer-events: none;
    }
    .hero-title {
        font-size: 34px;
        font-weight: 700;
        background: linear-gradient(135deg, #d4849a 0%, #c46e89 50%, #b8859e 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0 0 8px 0;
        letter-spacing: -0.5px;
        position: relative;
    }
    .hero-subtitle {
        font-size: 15px;
        color: #8a7170;
        margin: 0;
        font-weight: 400;
        letter-spacing: 0.2px;
        position: relative;
    }
    .hero-tag {
        display: inline-block;
        background: linear-gradient(135deg, #fdd9e0 0%, #fce4ec 100%);
        color: #b85a78;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        margin-bottom: 14px;
        text-transform: uppercase;
    }
    /* === 卡片样式 === */
    .nv-card {
        background: white;
        border-radius: 20px;
        padding: 24px 28px;
        margin-bottom: 18px;
        box-shadow: 0 2px 12px rgba(232, 165, 180, 0.08);
        border: 1px solid rgba(232, 165, 180, 0.12);
    }
    /* === 维护提醒条 === */
    .reminder-bar {
        background: linear-gradient(90deg, #fef5e7 0%, #fef0f0 100%);
        border-left: 4px solid #e8a5a5;
        border-radius: 12px;
        padding: 12px 18px;
        margin-bottom: 22px;
        font-size: 13px;
        color: #7a5a5e;
        line-height: 1.6;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .reminder-bar code {
        background: rgba(212, 132, 154, 0.12);
        color: #b85a78;
        padding: 1px 7px;
        border-radius: 5px;
        font-size: 12px;
        font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
    }
    /* === 文件上传区美化 === */
    [data-testid="stFileUploader"] {
        background: linear-gradient(135deg, #ffffff 0%, #fef8f9 100%);
        border-radius: 16px;
        padding: 4px;
    }
    [data-testid="stFileUploader"] section {
        background: rgba(255, 245, 247, 0.5) !important;
        border: 2px dashed rgba(212, 132, 154, 0.35) !important;
        border-radius: 14px !important;
        padding: 24px !important;
        transition: all 0.3s ease;
    }
    [data-testid="stFileUploader"] section:hover {
        border-color: rgba(212, 132, 154, 0.6) !important;
        background: rgba(255, 235, 240, 0.4) !important;
    }
    [data-testid="stFileUploader"] button {
        background: linear-gradient(135deg, #e8a5a5 0%, #d4849a 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 8px 18px !important;
        font-weight: 500 !important;
        font-size: 13px !important;
        box-shadow: 0 2px 6px rgba(212, 132, 154, 0.25) !important;
        transition: all 0.2s ease !important;
    }
    [data-testid="stFileUploader"] button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 10px rgba(212, 132, 154, 0.35) !important;
    }
    [data-testid="stFileUploaderFile"] {
        background: linear-gradient(135deg, #fef0f5 0%, #fff5f7 100%);
        border-radius: 10px;
        padding: 8px 12px !important;
    }
    /* === Radio 美化 === */
    [data-testid="stRadio"] label {
        font-size: 14px !important;
        color: #6b4f55 !important;
        font-weight: 500 !important;
    }
    [data-testid="stRadio"] [role="radiogroup"] {
        gap: 8px !important;
    }
    [data-testid="stRadio"] [role="radiogroup"] label {
        background: white;
        padding: 8px 16px;
        border-radius: 10px;
        border: 1px solid rgba(212, 132, 154, 0.2);
        transition: all 0.2s ease;
        cursor: pointer;
    }
    [data-testid="stRadio"] [role="radiogroup"] label:hover {
        border-color: rgba(212, 132, 154, 0.5);
        background: #fef8f9;
    }
    /* === KPI 数字卡 === */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        gap: 14px;
        margin-bottom: 20px;
    }
    .kpi-card {
        background: white;
        border-radius: 16px;
        padding: 18px 22px;
        border: 1px solid rgba(232, 165, 180, 0.12);
        box-shadow: 0 2px 10px rgba(232, 165, 180, 0.06);
        transition: all 0.2s ease;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 18px rgba(232, 165, 180, 0.14);
    }
    .kpi-label {
        font-size: 11px;
        color: #a8888a;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
        margin-bottom: 6px;
    }
    .kpi-value {
        font-size: 30px;
        font-weight: 700;
        color: #6b4f55;
        line-height: 1;
        margin-bottom: 4px;
        letter-spacing: -0.5px;
    }
    .kpi-sub {
        font-size: 12px;
        color: #a8888a;
        font-weight: 400;
    }
    .kpi-card.success { border-left: 4px solid #a8d5ba; }
    .kpi-card.success .kpi-value { color: #4a8061; }
    .kpi-card.primary { border-left: 4px solid #d4849a; }
    .kpi-card.primary .kpi-value { color: #b85a78; }
    .kpi-card.muted { border-left: 4px solid #d4c5c0; }
    .kpi-card.warning { border-left: 4px solid #e8c587; }
    .kpi-card.warning .kpi-value { color: #b58a3a; }
    .kpi-card.bchain { border-left: 4px solid #a5c8e8; }
    .kpi-card.bchain .kpi-value { color: #3a6a8a; }
    /* === 对账状态条 === */
    .status-bar {
        border-radius: 16px;
        padding: 16px 22px;
        margin: 12px 0 22px 0;
        font-weight: 500;
        font-size: 14px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .status-bar.success {
        background: linear-gradient(135deg, #f0f9f3 0%, #e6f5ec 100%);
        color: #4a8061;
        border: 1px solid rgba(168, 213, 186, 0.4);
    }
    .status-bar.error {
        background: linear-gradient(135deg, #fef0f0 0%, #fde6e6 100%);
        color: #b85a5a;
        border: 1px solid rgba(232, 165, 165, 0.4);
    }
    .status-bar.warning {
        background: linear-gradient(135deg, #fef9ec 0%, #fdf3d9 100%);
        color: #8a6a2a;
        border: 1px solid rgba(232, 197, 135, 0.4);
    }
    .status-bar.info {
        background: linear-gradient(135deg, #f5f0f5 0%, #ede5ec 100%);
        color: #6a4f60;
        border: 1px solid rgba(180, 150, 170, 0.3);
    }
    .status-icon {
        font-size: 20px;
    }
    /* === 明细块小标题 === */
    .detail-section {
        background: linear-gradient(135deg, #fefaf9 0%, #fdf5f7 100%);
        border-radius: 12px;
        padding: 14px 18px;
        margin: 12px 0;
        border: 1px solid rgba(232, 165, 180, 0.1);
    }
    .detail-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 5px 0;
        font-size: 13px;
        color: #6b4f55;
    }
    .detail-row:not(:last-child) {
        border-bottom: 1px dashed rgba(212, 132, 154, 0.18);
    }
    .detail-label { color: #8a7170; }
    .detail-value { font-weight: 600; color: #6b4f55; }
    .detail-value.pink { color: #b85a78; }
    .detail-value.blue { color: #3a6a8a; }
    .detail-section-title {
        font-size: 12px;
        font-weight: 700;
        color: #b85a78;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }
    /* === DataFrame 表格美化 === */
    [data-testid="stDataFrame"] {
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid rgba(232, 165, 180, 0.18);
        box-shadow: 0 2px 12px rgba(232, 165, 180, 0.06);
    }
    /* === 下载按钮 === */
    [data-testid="stDownloadButton"] button {
        background: linear-gradient(135deg, #d4849a 0%, #c46e89 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 10px 24px !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        box-shadow: 0 3px 10px rgba(196, 110, 137, 0.25) !important;
        transition: all 0.25s ease !important;
        letter-spacing: 0.3px;
    }
    [data-testid="stDownloadButton"] button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(196, 110, 137, 0.35) !important;
    }
    /* === Streamlit 默认 alert 美化兜底 === */
    [data-testid="stAlert"] {
        border-radius: 14px !important;
        border: none !important;
    }
    /* === 分隔线 === */
    .nv-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent 0%, rgba(212, 132, 154, 0.25) 50%, transparent 100%);
        margin: 28px 0;
        border: none;
    }
    /* === 段落小标题 === */
    .section-header {
        font-size: 18px;
        font-weight: 700;
        color: #6b4f55;
        margin: 24px 0 14px 0;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .section-header::before {
        content: '';
        width: 4px;
        height: 18px;
        background: linear-gradient(180deg, #d4849a 0%, #c46e89 100%);
        border-radius: 2px;
    }
    /* === B链产品区域 === */
    .bchain-wrap {
        background: linear-gradient(135deg, #f0f6fb 0%, #e8f2f8 100%);
        border-radius: 20px;
        padding: 24px 28px;
        margin-top: 8px;
        border: 1px solid rgba(165, 200, 232, 0.35);
        box-shadow: 0 2px 12px rgba(100, 160, 210, 0.07);
    }
    .bchain-header {
        font-size: 18px;
        font-weight: 700;
        color: #2e5f80;
        margin: 0 0 16px 0;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .bchain-header::before {
        content: '';
        width: 4px;
        height: 18px;
        background: linear-gradient(180deg, #6baed4 0%, #3a82aa 100%);
        border-radius: 2px;
    }
</style>
"""

# ============================================================================
# UI 小组件(替代散落各处的重复 HTML 块)
# ============================================================================
def html(s: str):
    st.markdown(s, unsafe_allow_html=True)


def section_header(title: str):
    html(f'<div class="section-header">{title}</div>')


def status_bar(kind: str, icon: str, body: str):
    """kind: success / error / warning / info"""
    html(
        f'<div class="status-bar {kind}">'
        f'<span class="status-icon">{icon}</span><div>{body}</div></div>'
    )


def kpi_grid(cards):
    """cards: [(css_class, label, value, sub), ...]"""
    inner = "".join(
        f'<div class="kpi-card {cls}">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-sub">{sub}</div></div>'
        for cls, label, value, sub in cards
    )
    html(f'<div class="kpi-grid">{inner}</div>')


def detail_section(title: str, rows):
    """rows: [(label, value_html_class, value_text), ...]"""
    inner = "".join(
        f'<div class="detail-row"><span class="detail-label">{label}</span>'
        f'<span class="detail-value {cls}">{value}</span></div>'
        for label, cls, value in rows
    )
    html(
        f'<div class="detail-section">'
        f'<div class="detail-section-title">{title}</div>{inner}</div>'
    )


# ============================================================================
# PDF 解析
# ============================================================================
SKU_BUNDLE = re.compile(r'((?:[A-Z]{3}\d{3}|NF001){1,4}-[SML])', re.DOTALL)
QTY_AFTER = re.compile(r'\b([1-9]\d{0,2})\b')
QTY_WITH_TRACKING = re.compile(r'\b([1-9]\d{0,2})\s+\d{15,20}\b')
ITEM_QTY_RE = re.compile(r"Item\s+quantity[:：]?\s*(\d+)", re.I)
NF_ONLY = re.compile(r'\bNF001\b')
NB_ONLY = re.compile(r'\bNB001\b')
CHOOSE_SETS_RE = re.compile(r'Choose\s+\d+\s+Sets', re.I)
B_CHAIN_RE = re.compile(r'\b(' + '|'.join(B_CHAIN_SKU_MAP) + r')\b')
ORPHAN_DIGIT_RE = re.compile(
    r'(?P<prefix>(?:[A-Z]{3}\d{3}|NM001){0,3}[A-Z]{3}\d{2})'
    r'\s*[\r\n]+\s*(?P<d>\d)\s*-\s*(?P<size>[SML])'
)
CHOOSE_SETS_KEY = "__CHOOSE_SETS__"


@dataclass
class ParseResult:
    """一份拣货 PDF 的全部提取结果"""
    expected_total: int = 0                                # PDF 标注 Item quantity
    sku_counts: dict = field(default_factory=lambda: defaultdict(int))
    bundle_extra: int = 0                                  # bundle 拆分多出的件数
    mystery_units: int = 0                                 # NF001 赠品件数
    binder_units: int = 0                                  # NB001 收纳册件数
    choose_sets_units: int = 0                             # Choose Sets 件数
    b_chain_counts: dict = field(default_factory=lambda: defaultdict(int))

    @property
    def b_chain_total(self) -> int:
        return sum(self.b_chain_counts.values())

    @property
    def b_chain_agg(self) -> dict:
        agg = defaultdict(int)
        for sku, qty in self.b_chain_counts.items():
            agg[B_CHAIN_SKU_MAP[sku]] += qty
        return dict(agg)

    @property
    def total_qty(self) -> int:
        return sum(self.sku_counts.values()) + self.b_chain_total

    @property
    def expected_with_bundle(self) -> int:
        return self.expected_total + self.bundle_extra


def normalize_text(t: str) -> str:
    """清理软连字符/零宽空格/不换行空格,统一破折号"""
    return (t.replace("\u00ad", "").replace("\u200b", "")
             .replace("\u00a0", " ").replace("\u2013", "-").replace("\u2014", "-"))


def fix_orphan_digit_before_size(txt: str) -> str:
    """修复 PDF 换行把 SKU 最后一位数字挤到下一行的情况,如 NPF01\\n4-M → NPF014-M"""
    def _join(m):
        return f"{m.group('prefix')}{m.group('d')}-{m.group('size')}"
    prev, cur = None, txt
    while prev != cur:
        prev, cur = cur, ORPHAN_DIGIT_RE.sub(_join, cur)
    return cur


def qty_near(text: str, pos: int, window: int) -> int:
    """在 pos 之后 window 个字符内找数量,找不到按 1 计"""
    m = QTY_AFTER.search(text[pos: pos + window])
    return int(m.group(1)) if m else 1


def parse_code_parts(code: str):
    """把 bundle 编码拆成单个 SKU 列表,如 NPF014NPJ016 → [NPF014, NPJ016]"""
    parts, i, n = [], 0, len(code)
    while i < n:
        if code.startswith('NM001', i):
            parts.append('NM001'); i += 5; continue
        seg = code[i: i + 6]
        if re.fullmatch(r'[A-Z]{3}\d{3}', seg):
            parts.append(seg); i += 6; continue
        return None
    return parts if 1 <= len(parts) <= 4 else None


def expand_bundle(counter: dict, sku_with_size: str, qty: int):
    """把 bundle SKU 拆到 counter 里,返回 (拆分多出件数, NF001 件数)"""
    s = re.sub(r'\s+', '', sku_with_size)
    if '-' not in s:
        counter[s] += qty
        return 0, (qty if s == 'NF001' else 0)
    code, size = s.split('-', 1)
    parts = parse_code_parts(code)
    if not parts:
        counter[s] += qty
        return 0, (qty if code == 'NF001' else 0)
    mystery = 0
    for p in parts:
        counter[f"{p}-{size}"] += qty
        if p == 'NF001':
            mystery += qty
    return (len(parts) - 1) * qty, mystery


def count_choose_sets_items(text: str) -> int:
    """统计 Choose N Sets 段落里的件数(占位 SKU 无款式信息,只能按段汇总)"""
    positions = [m.start() for m in CHOOSE_SETS_RE.finditer(text)]
    if not positions:
        return 0
    positions.append(len(text))
    total = 0
    for start, end in zip(positions, positions[1:]):
        block = text[start:end]
        m_sku = re.search(r'\b[A-Z]{3}\d{3}-[SML]\b', block)
        if m_sku:
            block = block[: m_sku.start()]
        for m in QTY_WITH_TRACKING.finditer(block):
            total += int(m.group(1))
    return total


def parse_pdf(raw: bytes) -> ParseResult:
    """解析拣货 PDF,返回全部提取结果"""
    doc = fitz.open(stream=raw, filetype="pdf")
    text = normalize_text("\n".join(p.get_text("text") for p in doc))

    r = ParseResult()
    m_total = ITEM_QTY_RE.search(text)
    r.expected_total = int(m_total.group(1)) if m_total else 0

    text = fix_orphan_digit_before_size(text)

    # 1) 带尺寸的 SKU(含 bundle)
    for m in SKU_BUNDLE.finditer(text):
        qty = qty_near(text, m.end(), 50)
        extra, myst = expand_bundle(r.sku_counts, m.group(1), qty)
        r.bundle_extra += extra
        r.mystery_units += myst

    # 2) 独立成行的 NF001(免费赠品,无尺寸)
    for m in NF_ONLY.finditer(text):
        if '-' in text[m.end(): m.end() + 3]:   # NF001-M 已在上面处理过
            continue
        qty = qty_near(text, m.end(), 80)
        r.sku_counts['NF001'] += qty
        r.mystery_units += qty

    # 3) 独立成行的 NB001(收纳册,无尺寸)
    for m in NB_ONLY.finditer(text):
        qty = qty_near(text, m.end(), 80)
        r.sku_counts['NB001'] += qty
        r.binder_units += qty

    # 4) Choose N Sets 混合套装
    r.choose_sets_units = count_choose_sets_items(text)
    if r.choose_sets_units:
        r.sku_counts[CHOOSE_SETS_KEY] += r.choose_sets_units

    # 5) B链产品(优先匹配"数量+运单号"的组合,更可靠)
    for m in B_CHAIN_RE.finditer(text):
        after = text[m.end(): m.end() + 300]
        mq = QTY_WITH_TRACKING.search(after)
        qty = int(mq.group(1)) if mq else qty_near(text, m.end(), 300)
        r.b_chain_counts[m.group(1)] += qty

    return r


# ============================================================================
# 汇总表构建
# ============================================================================
LOC_SPECIAL = "无库位(特殊款)"
LOC_UNKNOWN = "未识别库位"


def sku_name(prefix: str) -> str:
    if prefix == CHOOSE_SETS_KEY:
        return "Choose 2 Sets(混合套装)"
    return SKU_NAMES.get(prefix, "❓未识别")


def location_sort_key(loc: str):
    if not loc or loc == LOC_UNKNOWN:
        return (99, 99, 99)
    m = re.match(r'^([AB])-(\d{2})-(\d{2})$', loc)
    if not m:
        return (98, 0, 0)
    return (0 if m.group(1) == 'A' else 1, int(m.group(2)), int(m.group(3)))


def build_summary(sku_counts: dict, sku_to_location: dict) -> pd.DataFrame:
    """把 SKU 计数汇总成 库位/产品名/S/M/L/Total 表"""
    df = pd.DataFrame(list(sku_counts.items()), columns=["Seller SKU", "Qty"])
    df["SKU Prefix"] = df["Seller SKU"].str.split("-").str[0]
    df["Size"] = df["Seller SKU"].str.split("-").str[1]
    df["Product Name"] = df["SKU Prefix"].map(sku_name)

    sized = df[df["Size"].notna()]
    if not sized.empty:
        pivot = sized.pivot_table(
            index=["SKU Prefix", "Product Name"], columns="Size",
            values="Qty", aggfunc="sum", fill_value=0,
        ).reset_index()
        for sz in ["S", "M", "L"]:
            if sz not in pivot.columns:
                pivot[sz] = 0
        pivot["Total"] = pivot["S"] + pivot["M"] + pivot["L"]
    else:
        pivot = pd.DataFrame(columns=["SKU Prefix", "Product Name", "S", "M", "L", "Total"])

    nosized = df[df["Size"].isna()]
    if not nosized.empty:
        extra = pd.DataFrame({
            "SKU Prefix": nosized["SKU Prefix"].values,
            "Product Name": nosized["Product Name"].values,
            "S": 0, "M": 0, "L": 0,
            "Total": nosized["Qty"].values,
        })
        pivot = pd.concat([pivot, extra], ignore_index=True)

    def map_location(prefix):
        if prefix in SIZELESS_SKUS or prefix == CHOOSE_SETS_KEY:
            return LOC_SPECIAL
        return sku_to_location.get(prefix, LOC_UNKNOWN)

    pivot["库位"] = pivot["SKU Prefix"].map(map_location)
    return pivot[["库位", "Product Name", "SKU Prefix", "S", "M", "L", "Total"]]


def sort_summary(pivot: pd.DataFrame, by_location: bool) -> pd.DataFrame:
    """特殊款永远排在最后;其余按库位动线或产品名 A-Z 排"""
    p = pivot.copy()
    p["_special"] = p["SKU Prefix"].isin(SIZELESS_SKUS | {CHOOSE_SETS_KEY}).astype(int)
    if by_location:
        p["_key"] = p["库位"].map(location_sort_key)
    else:
        p["_key"] = p["Product Name"].str.lower()
    p = p.sort_values(["_special", "_key", "Product Name"]).reset_index(drop=True)
    return p.drop(columns=["_special", "_key"])


def build_csv(pivot: pd.DataFrame, b_chain_agg: dict) -> bytes:
    """合并 CSV:美甲拣货 + 空行 + B链产品段"""
    if not b_chain_agg:
        return pivot.to_csv(index=False).encode("utf-8-sig")
    cols = pivot.columns.tolist()
    empty = pd.DataFrame([[""] * len(cols)], columns=cols)
    label = pd.DataFrame([["─── B链产品 ───"] + [""] * (len(cols) - 1)], columns=cols)
    b_rows = pd.DataFrame(
        [[name] + [""] * (len(cols) - 2) + [qty] for name, qty in sorted(b_chain_agg.items())],
        columns=cols,
    )
    combined = pd.concat([pivot, empty, label, b_rows], ignore_index=True)
    return combined.to_csv(index=False).encode("utf-8-sig")


# ============================================================================
# 页面渲染
# ============================================================================
def render_header():
    html(CSS)
    html("""
    <div class="hero-wrap">
        <span class="hero-tag">✨ NailVesta Warehouse Tool</span>
        <h1 class="hero-title">拣货单汇总工具 💅</h1>
        <p class="hero-subtitle">
            Smart picking & reconciliation · 智能拆分 bundle、自动对账、按库位排序
        </p>
    </div>
    <div class="reminder-bar">
        <span style="font-size:18px;">📢</span>
        <div>
            <strong>新款上架提醒</strong>:有新款 SKU 上架时,请及时更新 GitHub 代码中的
            <code>sku_data.py</code>(<code>SKU_NAMES</code> / <code>NEW_SKUS</code> /
            <code>B_CHAIN_SKU_MAP</code>),push 后线上自动同步。
        </div>
    </div>
    """)


def render_uploaders():
    """文件上传区,返回 (库位映射 dict, PDF 文件)"""
    section_header("📁 文件上传")
    col1, col2 = st.columns(2)
    with col1:
        html('<div style="font-size:13px; color:#8a7170; margin-bottom:6px; font-weight:500;">'
             '📚 产品图册 CSV<span style="color:#c4c4c4; font-weight:400;"> · 可选</span></div>')
        catalog_file = st.file_uploader(
            " ", type=["csv"], key="catalog", label_visibility="collapsed",
            help="包含 SKU 与库位列。上传后会按库位排序拣货单",
        )
    with col2:
        html('<div style="font-size:13px; color:#8a7170; margin-bottom:6px; font-weight:500;">'
             '📤 拣货 PDF<span style="color:#d4849a; font-weight:600;"> · 必选</span></div>')
        pdf_file = st.file_uploader(
            " ", type=["pdf"], label_visibility="collapsed",
            help="TikTok Shop 后台导出的拣货 PDF",
        )

    sku_to_location = {}
    if catalog_file:
        try:
            catalog = pd.read_csv(catalog_file, dtype=str)
            if 'SKU' in catalog.columns and '库位' in catalog.columns:
                catalog['SKU'] = catalog['SKU'].str.strip()
                catalog['库位'] = catalog['库位'].fillna('').str.strip()
                valid = catalog[catalog['库位'] != '']
                sku_to_location = dict(zip(valid['SKU'], valid['库位']))
                status_bar("success", "✅",
                           f"已加载 <strong>{len(sku_to_location)}</strong> 个 SKU 的库位映射")
            else:
                st.warning("⚠️ 图册缺少 'SKU' 或 '库位' 列")
        except Exception as e:
            st.error(f"读取图册失败: {e}")
    return sku_to_location, pdf_file


def render_reconciliation(r: ParseResult, pivot: pd.DataFrame):
    """对账状态条 + KPI 卡 + 提取明细"""
    section_header("📊 对账结果")

    if r.expected_total == 0:
        status_bar("warning", "⚠️", "未识别到 PDF 中的 Item quantity,无法进行对账校验")
    elif r.total_qty in (r.expected_with_bundle, r.expected_total):
        bundle_note = f" + bundle 拆分 {r.bundle_extra}" if r.bundle_extra else ""
        status_bar("success", "✨",
                   f"<strong>对账成功</strong> · PDF 标注 {r.expected_total}{bundle_note}"
                   f" = 实际提取 {r.total_qty} 件 ✅")
    else:
        diff = r.total_qty - r.expected_with_bundle
        status_bar("error", "❌",
                   f"<strong>对账不一致</strong> · 期望 {r.expected_with_bundle},"
                   f"实际 {r.total_qty},差 {diff:+d} 件")

    special = pivot["库位"] == LOC_SPECIAL
    kpi_grid([
        ("primary", "PDF 标注", r.expected_total, "Item quantity"),
        ("success", "实际提取", r.total_qty, "含 bundle + B链"),
        ("", "普通甲片", int(pivot.loc[~special, "Total"].sum()), "有库位"),
        ("muted", "特殊款", int(pivot.loc[special, "Total"].sum()), "无尺寸/无库位"),
        ("bchain", "B链产品", r.b_chain_total, "工具包/折叠盒/册"),
    ])
    detail_section("📋 提取明细", [
        ("🎁 Free Giveaway (NF001)", "pink", f"{r.mystery_units} 件"),
        ("📒 Organizer Binder (NB001)", "pink", f"{r.binder_units} 件"),
        ("🎀 Choose Sets(混合套装)", "pink", f"{r.choose_sets_units} 件"),
        ("🔗 bundle 拆分多出件数", "", f"+{r.bundle_extra} 件"),
        ("🛍️ B链产品合计", "blue", f"{r.b_chain_total} 件"),
    ])


def render_warnings(r: ParseResult, pivot: pd.DataFrame):
    """未识别 SKU / 缺库位 / 特殊款提示"""
    unknown = sorted({
        sku.split("-")[0]
        for sku in r.sku_counts
        if sku.split("-")[0] not in SKU_NAMES and sku != CHOOSE_SETS_KEY
    })
    if unknown:
        chips = " ".join(
            f'<code style="background:#fde6e6; color:#b85a5a; padding:3px 9px; '
            f'border-radius:6px; font-size:12px; margin:2px;">{p}</code>'
            for p in unknown
        )
        status_bar("error", "🚨",
                   f"<strong>发现 {len(unknown)} 个未识别的 SKU 前缀</strong><br>"
                   f'<div style="margin:6px 0;">{chips}</div>'
                   '<span style="font-size:12px; opacity:0.85;">请尽快在 GitHub 仓库中更新 '
                   '<code style="background:rgba(184,90,90,0.12); padding:1px 5px; '
                   'border-radius:4px;">sku_data.py</code>,push 后重新部署</span>')

    no_loc = pivot[pivot["库位"] == LOC_UNKNOWN]
    if not no_loc.empty:
        names = "、".join(no_loc["Product Name"])
        status_bar("warning", "⚠️",
                   f"<strong>{len(no_loc)} 个款式没有库位信息</strong>(需补充图册 CSV):{names}")

    special = pivot[pivot["库位"] == LOC_SPECIAL]
    if not special.empty:
        names = "、".join(special["Product Name"])
        status_bar("info", "ℹ️",
                   f"<strong>{len(special)} 类无尺寸/特殊款</strong>不参与库位拣货:"
                   f"{names}(需单独处理)")


def render_table(r: ParseResult, pivot: pd.DataFrame):
    """排序选择 + 明细表 + 图例 + 下载按钮"""
    html('<div class="nv-divider"></div>')
    section_header("📋 拣货明细表")
    sort_mode = st.radio(
        "排序方式",
        ["📦 按库位顺序(拣货模式)", "🔤 按字母顺序(A-Z)"],
        horizontal=True, label_visibility="collapsed",
        help="拣货模式:从 A-01-01 顺着货架走一遍即可。字母顺序:按产品名 A-Z 排列,方便查找",
    )
    pivot = sort_summary(pivot, by_location=sort_mode.startswith("📦"))
    new_names = {SKU_NAMES[p] for p in NEW_SKUS if p in SKU_NAMES}
    display = pivot[["库位", "Product Name", "S", "M", "L", "Total"]]

    def highlight_row(row):
        if row["库位"] == LOC_UNKNOWN:
            color = '#fef5e7'
        elif row["库位"] == LOC_SPECIAL:
            color = '#f5f0f5'
        elif row["Product Name"] in new_names:
            color = '#fff0f5'
        else:
            return [''] * len(row)
        return [f'background-color: {color}'] * len(row)

    styled = display.style.apply(highlight_row, axis=1).set_properties(**{
        'font-size': '13px', 'color': '#6b4f55',
    })
    st.dataframe(styled, use_container_width=True, hide_index=True,
                 height=min(600, 50 + len(display) * 35))

    legend = [("#fff0f5", "rgba(212,132,154,0.3)", "新款"),
              ("#fef5e7", "rgba(232,197,135,0.4)", "缺库位信息"),
              ("#f5f0f5", "rgba(180,150,170,0.3)", "无尺寸特殊款")]
    items = "".join(
        f'<div style="display:flex; align-items:center; gap:6px;">'
        f'<span style="width:14px; height:14px; background:{bg}; border:1px solid {bd}; '
        f'border-radius:3px;"></span><span>{name}</span></div>'
        for bg, bd, name in legend
    )
    html(f'<div style="display:flex; gap:18px; flex-wrap:wrap; padding:10px 0; '
         f'font-size:12px; color:#8a7170;">{items}</div>')

    html('<div style="margin-top:18px;"></div>')
    b_chain_agg = r.b_chain_agg
    st.download_button(
        "📥 下载拣货明细 CSV（含 B链）" if b_chain_agg else "📥 下载产品明细 CSV",
        data=build_csv(display, b_chain_agg),
        file_name="product_summary_named.csv",
        mime="text/csv",
    )


def render_b_chain(b_chain_agg: dict):
    if not b_chain_agg:
        return
    html('<div class="nv-divider"></div>')
    html('<div class="bchain-wrap"><div class="bchain-header">🛍️ B链产品</div>')
    b_df = pd.DataFrame(sorted(b_chain_agg.items()), columns=["产品名称", "数量"])
    st.dataframe(b_df, use_container_width=True, hide_index=True,
                 height=50 + len(b_df) * 38)
    html('</div>')


def main():
    render_header()
    sku_to_location, pdf_file = render_uploaders()

    if not pdf_file:
        html("""
        <div class="nv-card" style="text-align:center; padding: 50px 30px;
             background: linear-gradient(135deg, #ffffff 0%, #fef8f9 100%);">
            <div style="font-size: 48px; margin-bottom: 12px;">📤</div>
            <div style="font-size: 16px; color: #8a7170; font-weight: 500;">等待上传拣货 PDF</div>
            <div style="font-size: 13px; color: #b0a0a0; margin-top: 6px;">
                上传后将自动解析、拆分 bundle 并按库位排序
            </div>
        </div>
        """)
        return

    result = parse_pdf(pdf_file.read())
    if not result.sku_counts:
        status_bar("error", "❌", "未识别到任何 SKU。请确认 PDF 为可复制文本(非扫描件)")
        return

    pivot = build_summary(result.sku_counts, sku_to_location)
    render_reconciliation(result, pivot)
    render_warnings(result, pivot)
    render_table(result, pivot)
    render_b_chain(result.b_chain_agg)


if __name__ == "__main__":
    main()
