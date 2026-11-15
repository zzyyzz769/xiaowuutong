"""校务通 Streamlit 前端。启动：python -m streamlit run app.py"""

import hashlib
import html
import re
from datetime import date, datetime, time

import streamlit as st
import streamlit.components.v1 as components

from rag_core import GROUPS, ROLE_ACCESS, ROLE_NAMES, CampusRAG


st.set_page_config(page_title="校务通 · 校园工作台", page_icon="🎓", layout="wide")
st.markdown(
    """
    <style>
    :root {
        color-scheme: only light;
        --campus-blue: #0064E6;
        --campus-blue-soft: #edf5ff;
        --campus-ink: #252a31;
        --campus-muted: #5c6673;
        --campus-line: #d9dee5;
        --campus-paper: #ffffff;
        --campus-canvas: #f4f6f8;
    }
    html, body, .stApp, [data-testid="stAppViewContainer"],
    [data-testid="stBottom"], [data-testid="stBottom"] > div {
        background: var(--campus-canvas) !important;
        color-scheme: only light;
    }
    html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                     "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
        -webkit-font-smoothing: antialiased;
    }
    .stApp, .stApp p, .stApp li, .stApp label,
    [data-testid="stMarkdownContainer"], [data-testid="stText"] {
        color: var(--campus-ink);
    }
    .stApp p, .stApp li { line-height: 1.65; }
    [data-testid="stHeader"] {
        background: var(--campus-canvas) !important;
        color: var(--campus-ink) !important;
    }
    [data-testid="stHeader"] [data-testid="stToolbar"],
    [data-testid="stHeader"] [data-testid="stToolbar"] button,
    [data-testid="stHeader"] .stAppDeployButton button {
        color: var(--campus-muted) !important;
        background: transparent !important;
    }
    .stAppViewContainer > .main .block-container {
        max-width: 1440px;
        padding: 1.6rem 2.4rem 4rem;
    }
    [data-testid="stSidebar"], [data-testid="stSidebar"] > div,
    [data-testid="stSidebarContent"] {
        background: #f8fafc !important;
        color: var(--campus-ink) !important;
    }
    [data-testid="stSidebar"] { border-right: 1px solid var(--campus-line); }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.2rem; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: var(--campus-ink); }
    h1, h2, h3, h4 { color: var(--campus-ink); letter-spacing: -.02em; }
    h2 { font-size: 1.55rem !important; font-weight: 650 !important; }
    h3 { font-size: 1.22rem !important; font-weight: 650 !important; }
    .stCaption, [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p {
        color: var(--campus-muted) !important;
        font-size: .86rem !important;
    }
    .workspace-brand {
        display: flex; align-items: baseline; gap: 12px; margin: 0 0 6px;
    }
    .workspace-brand strong { font-size: 1.65rem; letter-spacing: -.04em; }
    .workspace-brand span { color: var(--campus-muted); font-size: .72rem; letter-spacing: .16em; }
    .workspace-head {
        display: flex; justify-content: space-between; align-items: flex-end;
        gap: 24px; padding: 5px 0 22px; margin-bottom: 22px;
        border-bottom: 1px solid var(--campus-line);
    }
    .workspace-head h1 { font-size: 2rem; line-height: 1.2; margin: 0 0 8px; font-weight: 680; }
    .workspace-head p { margin: 0; color: var(--campus-muted); font-size: .95rem; }
    .local-status {
        flex: none; color: #0053bd; background: var(--campus-blue-soft);
        border: 1px solid #c9defa; border-radius: 999px;
        padding: 6px 12px; font-size: .78rem; font-weight: 600;
    }
    .login-panel { padding: 4px 0 20px; }
    .login-kicker, .section-kicker {
        color: #0053bd; font-size: .76rem; font-weight: 700;
        letter-spacing: .1em; margin: 6px 0;
    }
    .login-panel h2 { margin: 4px 0 8px; font-size: 1.75rem !important; }
    .login-intro { color: var(--campus-muted); margin-bottom: 20px; line-height: 1.7; }
    .user-badge {
        display: flex; align-items: center; justify-content: space-between; gap: 12px;
        padding: 12px 14px; margin-bottom: 8px; border: 1px solid var(--campus-line);
        border-radius: 10px; background: var(--campus-paper); color: var(--campus-ink);
    }
    .user-badge span { color: #0053bd; font-size: .8rem; font-weight: 650; }
    .quick-title { font-size: 1.05rem; font-weight: 650; margin: 0 0 4px; }
    .quick-copy { color: var(--campus-muted); font-size: .9rem; min-height: 46px; line-height: 1.65; }
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
        border: 1px solid #cbd3dc !important; border-radius: 8px;
        background: var(--campus-paper) !important; color: var(--campus-ink) !important;
        min-height: 2.65rem; box-shadow: none !important;
        transition: border-color .2s ease, color .2s ease, background .2s ease;
    }
    .stButton > button p, .stDownloadButton > button p, .stFormSubmitButton > button p {
        color: inherit !important;
    }
    button[data-testid="stBaseButton-primary"] p,
    button[data-testid="stBaseButton-primaryFormSubmit"] p {
        color: #ffffff !important;
    }
    .stButton > button:hover, .stDownloadButton > button:hover,
    .stFormSubmitButton > button:hover {
        border-color: var(--campus-blue) !important; color: #0053bd !important;
        background: var(--campus-blue-soft) !important;
    }
    .stButton > button[kind^="primary"], .stFormSubmitButton > button[kind^="primary"],
    button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
        background: var(--campus-blue) !important; border-color: var(--campus-blue) !important;
        color: #ffffff !important;
    }
    .stButton > button[kind^="primary"]:hover, .stFormSubmitButton > button[kind^="primary"]:hover,
    button[data-testid="stBaseButton-primary"]:hover,
    button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background: #0053bd !important; color: #ffffff !important;
    }
    div[data-testid="stForm"] {
        border: 0 !important; background: transparent !important; box-shadow: none !important;
    }
    button:focus-visible, input:focus-visible, textarea:focus-visible {
        outline: 3px solid rgba(0,100,230,.28) !important; outline-offset: 2px;
    }
    [data-testid="stMetric"] {
        background: var(--campus-paper); padding: 16px 18px;
        border: 1px solid var(--campus-line); border-radius: 10px;
    }
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"] p { color: var(--campus-ink) !important; }
    [data-testid="stMetricValue"] { font-weight: 650; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--campus-paper) !important; border-color: var(--campus-line) !important;
        border-radius: 10px !important; box-shadow: 0 4px 16px rgba(37,42,49,.035);
    }
    [data-testid="stRadio"] [role="radiogroup"] { gap: 7px; }
    [data-testid="stRadio"] [role="radiogroup"] label {
        background: var(--campus-paper); border: 1px solid var(--campus-line);
        border-radius: 8px; padding: 8px 13px; margin: 0; min-height: 40px;
        cursor: pointer; transition: border-color .2s ease, color .2s ease, background .2s ease;
    }
    [data-testid="stRadio"] [role="radiogroup"] label > div:has(input[type="radio"]),
    [data-testid="stRadioOption"] > div > div:first-child {
        display: none !important;
    }
    [data-testid="stRadio"] [role="radiogroup"] label p { color: var(--campus-ink) !important; }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] { gap: 4px; }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label {
        width: 100%; background: transparent; border-color: transparent;
        padding: 9px 12px; margin: 0;
    }
    [data-testid="stRadio"] [role="radiogroup"] label:hover { border-color: #9dbfdf; }
    [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
        border-color: #b8d3f7; background: var(--campus-blue-soft);
    }
    [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) p {
        color: #0053bd !important; font-weight: 650;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
        border-color: #c9defa;
    }
    [data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label {
        color: #3f4956 !important; font-weight: 500;
    }
    /* 输入区域固定为浅色，覆盖浏览器深色模式及 Streamlit 新旧两套组件结构。 */
    div[data-baseweb="input"], div[data-baseweb="textarea"],
    div[data-baseweb="base-input"], div[data-baseweb="select"] > div,
    [data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"],
    [data-testid="stNumberInputContainer"], [data-testid="stDateInputField"],
    [data-testid="stTextArea"] > div, [data-testid="stTextArea"] > div > div,
    [data-testid="stTimeInput"] > div, [data-testid="stTimeInput"] div[role="group"],
    [data-testid="stDateInput"] div[role="group"],
    [data-testid="stSelectbox"] div[role="group"],
    [data-testid="stMultiSelect"] div[role="group"] {
        background-color: var(--campus-paper) !important; color: var(--campus-ink) !important;
        border-color: #cbd3dc !important; border-radius: 8px !important;
    }
    input, textarea, select, [role="combobox"], [contenteditable="true"],
    [data-baseweb="select"] span, [data-baseweb="select"] input {
        color: var(--campus-ink) !important;
        -webkit-text-fill-color: var(--campus-ink) !important;
        caret-color: var(--campus-ink) !important; opacity: 1 !important;
    }
    input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]) {
        background-color: transparent !important;
    }
    textarea, [data-testid="stTextArea"] textarea,
    [data-testid="stChatInput"] textarea {
        background-color: var(--campus-paper) !important;
    }
    input::placeholder, textarea::placeholder, [contenteditable="true"]:empty::before {
        color: #77818d !important; -webkit-text-fill-color: #77818d !important; opacity: 1 !important;
    }
    [data-testid="stTextInputRootElement"] button, [data-testid="stTextInputRootElement"] button *,
    [data-testid="stSelectbox"] button, [data-testid="stSelectbox"] button *,
    [data-testid="stTimeInput"] button, [data-testid="stTimeInput"] button * {
        color: var(--campus-muted) !important; background: transparent !important;
    }
    [data-testid="stSelectbox"] [role="group"] *,
    [data-testid="stMultiSelect"] [role="group"] *,
    [data-testid="stTimeInput"] [role="group"] * {
        color: var(--campus-ink) !important; -webkit-text-fill-color: var(--campus-ink) !important;
    }
    [data-testid="stTextAreaInstructions"], [data-testid="stTextAreaInstructions"] * {
        color: var(--campus-muted) !important; background: transparent !important;
        border: 0 !important; box-shadow: none !important;
    }
    input:focus, textarea:focus, select:focus, [contenteditable="true"]:focus,
    div[data-baseweb="select"] > div:focus-within,
    [data-testid="stTextInputRootElement"]:focus-within,
    [data-testid="stTextArea"]:focus-within > div {
        border-color: var(--campus-blue) !important; box-shadow: 0 0 0 1px var(--campus-blue) !important;
    }
    [data-baseweb="popover"], [data-baseweb="popover"] *,
    [data-baseweb="menu"], [data-baseweb="menu"] ul,
    [role="listbox"], [role="option"], [role="option"] * {
        background-color: var(--campus-paper) !important; color: var(--campus-ink) !important;
        -webkit-text-fill-color: var(--campus-ink) !important;
    }
    [data-testid="stExpander"], [data-testid="stExpander"] details,
    [data-testid="stExpander"] summary {
        background: var(--campus-paper); color: var(--campus-ink) !important;
        border-color: var(--campus-line) !important;
    }
    [data-testid="stAlert"], [data-testid="stAlertContainer"] {
        background: #eef4fb !important; color: #263445 !important;
        border: 1px solid #d5e1ef !important; border-radius: 9px !important;
    }
    [data-testid="stAlert"] p, [data-testid="stAlert"] span,
    [data-testid="stAlert"] div, [data-testid="stAlert"] a {
        color: #263445 !important;
    }
    [data-testid="stAlert"]:has([kind="warning"]), [data-testid="stAlertContainer"]:has([kind="warning"]) {
        background: #fff7da !important; border-color: #ead992 !important;
    }
    [data-testid="stAlert"]:has([kind="error"]), [data-testid="stAlertContainer"]:has([kind="error"]) {
        background: #fff0ed !important; border-color: #efc7bf !important;
    }
    [data-testid="stAlert"]:has([kind="success"]), [data-testid="stAlertContainer"]:has([kind="success"]) {
        background: #edf8f1 !important; border-color: #c7e5d2 !important;
    }
    [data-testid="stCodeBlock"], [data-testid="stCodeBlock"] pre,
    [data-testid="stCode"] pre, pre {
        background: #f1f4f7 !important; color: #263445 !important;
        border: 1px solid var(--campus-line); border-radius: 8px;
    }
    code { color: #263445 !important; }
    [data-testid="stText"] pre {
        background: transparent !important; border: 0; padding: 0;
        white-space: pre-wrap; color: var(--campus-ink) !important;
        font-family: inherit; line-height: 1.75;
    }
    .usage-note {
        padding: 12px 15px; margin-bottom: 14px; border: 1px solid #d5e1ef;
        border-radius: 9px; background: #f7faff; color: #4a5665;
        font-size: .9rem; line-height: 1.75;
    }
    .usage-note strong { color: #263445; }
    .message-label {
        font-size: .78rem; font-weight: 700; letter-spacing: .04em;
        margin-bottom: 7px; color: #5c6673;
    }
    .message-label.user { color: #0053bd; }
    .question-text { font-size: 1rem; font-weight: 600; line-height: 1.7; white-space: pre-wrap; }
    .answer-text {
        color: var(--campus-ink); font-size: 1rem; line-height: 1.8;
        white-space: pre-wrap; overflow-wrap: anywhere;
    }
    .schedule-preview-wrap { overflow-x: auto; border: 1px solid var(--campus-line); border-radius: 8px; }
    .schedule-preview-table { width: 100%; border-collapse: collapse; background: #ffffff; color: var(--campus-ink); font-size: .86rem; }
    .schedule-preview-table th { background: #eef4fb; color: #263445; font-weight: 650; text-align: left; }
    .schedule-preview-table th, .schedule-preview-table td { padding: 9px 10px; border-bottom: 1px solid var(--campus-line); white-space: nowrap; }
    .schedule-preview-table tr:last-child td { border-bottom: 0; }
    .week-schedule-wrap {
        overflow-x: auto; border: 1px solid var(--campus-line); border-radius: 12px;
        background: #ffffff; box-shadow: 0 4px 16px rgba(37,42,49,.035);
    }
    .week-schedule {
        width: 100%; min-width: 1080px; border-collapse: separate; border-spacing: 0;
        table-layout: fixed; background: #ffffff; color: var(--campus-ink);
    }
    .week-schedule th, .week-schedule td {
        border-right: 1px solid #e2e7ed; border-bottom: 1px solid #e2e7ed;
        padding: 8px; text-align: center; vertical-align: middle;
    }
    .week-schedule tr:last-child th, .week-schedule tr:last-child td { border-bottom: 0; }
    .week-schedule th:last-child, .week-schedule td:last-child { border-right: 0; }
    .week-schedule thead th {
        position: sticky; top: 0; z-index: 2; background: #eef4fb; color: #263445;
        padding: 12px 8px; font-size: .9rem; font-weight: 650;
    }
    .week-schedule thead th:first-child {
        left: 0; z-index: 4; width: 112px; min-width: 112px;
    }
    .week-schedule thead th.today { background: #dceaff; color: #0053bd; }
    .week-schedule tbody td { min-height: 104px; height: 112px; vertical-align: top; }
    .week-schedule .period-cell {
        position: sticky; left: 0; z-index: 1; width: 112px; min-width: 112px;
        background: #f8fafc; vertical-align: middle;
    }
    .week-schedule .period-cell strong { display: block; color: #334155; font-size: .88rem; }
    .week-schedule .period-cell small { display: block; margin-top: 7px; color: #6b7684; line-height: 1.55; }
    .week-course {
        margin: 0 0 7px; padding: 9px 8px; border-left: 3px solid #3b82f6;
        border-radius: 6px; background: #edf5ff; text-align: left; color: #252a31;
    }
    .week-course:last-child { margin-bottom: 0; }
    .week-course strong { display: block; color: #174f96; font-size: .88rem; line-height: 1.5; }
    .week-course span { display: block; margin-top: 3px; color: #5c6673; font-size: .74rem; line-height: 1.45; }
    .week-empty { color: #c1c8d0; }
    [data-testid="stChatMessage"] { background: var(--campus-paper); color: var(--campus-ink); }
    div[data-testid="stChatInput"] {
        position: sticky; bottom: 0; z-index: 20; background: var(--campus-canvas) !important;
        padding: .6rem 0 .2rem;
    }
    div[data-testid="stChatInput"] > div,
    div[data-testid="stChatInput"] [data-testid="stChatInputRootElement"] {
        background: var(--campus-paper) !important; border-color: #cbd3dc !important;
    }
    [data-testid="stProgressBar"] > div > div { background-color: var(--campus-blue); }
    [data-testid="stProgressBar"] p { color: var(--campus-muted) !important; }
    [data-testid="stDataFrame"], [data-testid="stTable"] { background: var(--campus-paper); }
    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploaderDropzone"],
    [data-testid="stFileUploaderDropzone"] div,
    [data-testid="stFileUploaderFile"], [data-testid="stFileChip"] {
        background-color: #f8fafc !important; color: var(--campus-ink) !important;
        border-color: #b8c4d1 !important;
    }
    [data-testid="stFileUploaderDropzone"] {
        border: 1px dashed #b8c4d1 !important;
    }
    [data-testid="stFileChip"] { border-style: solid !important; }
    [data-testid="stFileUploaderDropzone"] *, [data-testid="stFileUploaderFile"] *,
    [data-testid="stFileChip"] *, [data-testid="stFileChipName"],
    [data-testid="stFileUploaderFileName"], [data-testid="stFileUploaderFileSize"] {
        color: var(--campus-ink) !important; -webkit-text-fill-color: var(--campus-ink) !important;
    }
    [data-testid="stFileUploaderDropzone"] button,
    [data-testid="stFileUploaderDropzone"] button * {
        background-color: var(--campus-paper) !important; color: var(--campus-ink) !important;
        -webkit-text-fill-color: var(--campus-ink) !important;
    }
    mark { background: #f1df55; color: #252a31; padding: 1px 2px; }
    ::selection { background: #c9defa; color: #20242a; }
    @media (max-width: 768px) {
        .stAppViewContainer > .main .block-container { padding: 1rem 1rem 3rem; }
        .workspace-head { align-items: flex-start; flex-direction: column; gap: 12px; }
        .workspace-head h1 { font-size: 1.65rem; }
        .quick-copy { min-height: 0; }
        [data-testid="stRadio"] [role="radiogroup"] label { padding: 8px 10px; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_rag(llm_model: str, embedding_model: str, base_url: str) -> CampusRAG:
    return CampusRAG(
        llm_model=llm_model,
        embedding_model=embedding_model,
        ollama_base_url=base_url,
    )


@st.cache_data(ttl=5, show_spinner=False)
def get_installed_models(base_url: str) -> tuple[list[str], str]:
    """短时间缓存本机模型列表，避免每次界面刷新都请求 Ollama。"""
    try:
        return CampusRAG.list_ollama_models(base_url), ""
    except Exception as exc:
        return [], str(exc)


def role_text(role: str) -> str:
    return ROLE_NAMES.get(role, role)


def on_model_change() -> None:
    """切换生成模型时移除旧组件状态，避免历史消息与原文预览交叉更新。"""
    st.session_state.pop("preview", None)
    st.session_state.pop("qa_csv", None)


def plain_answer(text: str) -> str:
    """历史消息使用稳定纯文本渲染，保留结构但移除 Markdown 标记。"""
    return rag.clean_answer(text).replace("**", "").strip()


def render_weekly_schedule(
    schedule: list[dict], period_times: dict[str, list[str]] | None = None
) -> None:
    """把课程清单整理成左侧节次、顶部星期的周课表，并使用个人作息。"""
    if period_times is None:
        period_times = {
            str(section): list(CampusRAG._schedule_section_times((section, section)))
            for section in range(1, 13)
        }
    slots = [
        (
            f"{first}—{first + 1}",
            period_times[str(first)][0], period_times[str(first + 1)][1],
        )
        for first in (1, 3, 5, 7, 9, 11)
    ]

    def minutes(value: str) -> int:
        hour, minute = str(value).split(":", 1)
        return int(hour) * 60 + int(minute)

    grid: dict[str, dict[int, list[dict]]] = {
        slot[0]: {day: [] for day in range(1, 8)} for slot in slots
    }
    grid["其他时间"] = {day: [] for day in range(1, 8)}
    for item in schedule:
        start, end = minutes(item["start_time"]), minutes(item["end_time"])
        best_slot, best_overlap = "其他时间", 0
        for label, slot_start, slot_end in slots:
            overlap = max(0, min(end, minutes(slot_end)) - max(start, minutes(slot_start)))
            if overlap > best_overlap:
                best_slot, best_overlap = label, overlap
        grid[best_slot][int(item["weekday"])].append(item)

    today = datetime.now().isoweekday()
    headers = "".join(
        f"<th class='{'today' if day == today else ''}'>星期{'一二三四五六日'[day - 1]}</th>"
        for day in range(1, 8)
    )
    body_rows = []
    for label, slot_start, slot_end in slots + [("其他时间", "", "")]:
        cells = []
        for day in range(1, 8):
            courses = grid[label][day]
            if not courses:
                cells.append("<td><span class='week-empty'>—</span></td>")
                continue
            course_cards = []
            for item in courses:
                details = [f"{html.escape(item['start_time'])}—{html.escape(item['end_time'])}"]
                if item.get("location"):
                    details.append(html.escape(item["location"]))
                if item.get("teacher"):
                    details.append("教师：" + html.escape(item["teacher"]))
                week_kind = {"all": "每周", "odd": "单周", "even": "双周"}.get(
                    item.get("week_type", "all"), "每周"
                )
                details.append(
                    f"{item.get('start_week', 1)}—{item.get('end_week', 53)}周 · {week_kind}"
                )
                course_cards.append(
                    "<div class='week-course'>"
                    f"<strong>{html.escape(item['course_name'])}</strong>"
                    + "".join(f"<span>{detail}</span>" for detail in details)
                    + "</div>"
                )
            cells.append("<td>" + "".join(course_cards) + "</td>")
        time_label = f"<small>{slot_start}<br>{slot_end}</small>" if slot_start else "<small>按原时间</small>"
        body_rows.append(
            f"<tr><th class='period-cell'><strong>第{label}节</strong>{time_label}</th>"
            if label != "其他时间" else
            f"<tr><th class='period-cell'><strong>{label}</strong>{time_label}</th>"
        )
        body_rows[-1] += "".join(cells) + "</tr>"
    st.markdown(
        "<div class='week-schedule-wrap'><table class='week-schedule'>"
        f"<thead><tr><th>节次</th>{headers}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    if any(grid["其他时间"].values()):
        st.caption("无法对应个人作息节次的课程已放在“其他时间”行，课程原始时间保持不变。")


def show_moderation_result(result: dict, success_text: str = "发布成功。") -> None:
    status = result.get("status", "visible")
    if status in {"visible", "delivered"}:
        st.success(success_text + (" 本地 AI 辅助审核通过。" if result.get("ai_used") else " 规则检查通过。"))
    elif status == "review":
        st.warning("内容已提交，但需要管理员复核后才会公开或送达。原因：" + (result.get("reason") or "需要人工确认"))
    else:
        st.error("内容已拦截，不会公开展示或送达。原因：" + (result.get("reason") or "命中安全规则"))
    if result.get("notice"):
        st.caption(result["notice"])


def contact_user(username: str) -> None:
    st.session_state.message_recipient = username
    open_page("校园社区", "站内私信")


def highlight_document(text: str, snippet: str) -> str:
    """转义全部文档内容，仅把命中的原文片段包装为黄色 mark。"""
    safe_text = html.escape(text)
    safe_snippet = html.escape(snippet.strip())
    if safe_snippet and safe_snippet in safe_text:
        safe_text = safe_text.replace(
            safe_snippet, f"<mark id='active-highlight'>{safe_snippet}</mark>", 1
        )
    else:
        safe_text = (
            "<p><mark>未能在当前页面自动定位完整切片，以下展示对应原文。</mark></p>"
            + safe_text
        )
    return (
        "<div style='white-space:pre-wrap;line-height:1.8;max-height:560px;"
        "overflow:auto;padding:16px;border:1px solid #ddd;border-radius:8px;"
        "background:#fafafa;color:#222'>"
        + safe_text
        + "</div>"
    )


# 登录只使用默认模型配置；登录后可在侧边栏调整。
rag = get_rag("qwen2.5:7b", "bge-m3", "http://localhost:11434")
if "user" not in st.session_state:
    st.session_state.user = None

st.markdown(
    "<div class='workspace-brand'><strong>校务通</strong><span>CAMPUS WORKSPACE</span></div>",
    unsafe_allow_html=True,
)
st.caption("本地智能校务 · 校园社区 · 学习与生活服务")

if not st.session_state.user:
    _, login_column, _ = st.columns([0.45, 1.1, 0.45])
    with login_column:
        if st.session_state.get("login_notice"):
            st.info(st.session_state.pop("login_notice"))
        with st.container(border=True):
            st.markdown(
                "<div class='login-panel'><div class='login-kicker'>欢迎回来</div>"
                "<h2>登录校务通</h2><div class='login-intro'>"
                "登录后使用教务问答、办事清单和校园服务。不同身份只能查看自己权限范围内的资料。"
                "</div></div>",
                unsafe_allow_html=True,
            )
            with st.form("login_form"):
                username = st.text_input("用户名", placeholder="请输入用户名")
                password = st.text_input("密码", type="password", placeholder="请输入密码")
                submitted = st.form_submit_button("登录", type="primary", use_container_width=True)
            if submitted:
                try:
                    authenticated = rag.authenticate(username, password)
                    if authenticated:
                        st.session_state.user = authenticated
                        st.session_state.pop("qa_csv", None)
                        st.rerun()
                    else:
                        st.error("用户名或密码错误。连续失败 5 次会锁定 5 分钟。")
                except ValueError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"登录暂时失败：{exc}")
        with st.expander("首次运行的本地演示账户"):
            st.code(
                "学生：student / Student@123\n"
                "辅导员：counselor / Counselor@123\n"
                "管理员：admin / Admin@123"
            )
            st.warning("演示密码仅用于初次登录，请登录后立即修改。")
    st.stop()

user = st.session_state.user

if user.get("must_change_password"):
    _, password_column, _ = st.columns([0.35, 1.3, 0.35])
    with password_column:
        with st.container(border=True):
            st.subheader("首次登录，请先修改默认密码")
            st.caption("为了保护本机账户，修改完成后才能进入其他功能。新密码至少 8 位，且不能与默认密码相同。")
            with st.form("required_password_form"):
                old_password = st.text_input("当前默认密码", type="password")
                new_password = st.text_input("新密码（至少 8 位）", type="password")
                confirm_password = st.text_input("再次输入新密码", type="password")
                submitted = st.form_submit_button("修改密码并进入系统", type="primary", use_container_width=True)
            if submitted:
                if new_password != confirm_password:
                    st.error("两次输入的新密码不一致。")
                else:
                    try:
                        rag.change_password(user, old_password, new_password)
                        st.session_state.user["must_change_password"] = False
                        st.session_state.password_changed_notice = True
                        st.rerun()
                    except Exception as exc:
                        st.error(f"修改失败：{exc}")
        if st.button("退出登录", key="required_password_logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    st.stop()

nav_groups = {
    "智能校务": ["工作台", "教务问答", "办事向导"],
    "校园生活": ["消息中心", "校园社区", "校园服务"],
    "知识管理": ["我的知识库", "知识治理", "评测中心", "版本对比"],
    "运营管理": ["数据看板"],
}
if user["role"] == "admin":
    nav_groups["运营管理"] += ["文档管理", "自动诊断", "审计日志", "系统维护"]

# 页面按钮在侧栏控件之后执行，因此先暂存目标，在下一次脚本运行、控件创建前应用。
pending_navigation = st.session_state.pop("pending_navigation", None)
if pending_navigation:
    pending_page, pending_subpage = pending_navigation
    for group_name, pages in nav_groups.items():
        if pending_page in pages:
            st.session_state.nav_group = group_name
            st.session_state.nav_page = pending_page
            break
    if pending_page == "校园社区" and pending_subpage:
        st.session_state.community_page = pending_subpage
    if pending_page == "校园服务" and pending_subpage:
        st.session_state.service_page = pending_subpage


def open_page(target: str, subpage: str = "") -> None:
    st.session_state.pending_navigation = (target, subpage)
    st.rerun()


page_descriptions = {
    "工作台": "常用入口、今日安排和最近动态，一眼找到下一步要做的事。",
    "消息中心": "集中查看私信、评论回复、活动报名和内容审核结果。",
    "教务问答": "从权限范围内的制度中找依据，给出结论、要点和可信来源。",
    "办事向导": "把条件、材料、步骤和时间整理成一份可以勾选的办理清单。",
    "校园社区": "论坛交流、失物招领、二手交易、树洞和站内私信。",
    "校园服务": "管理课表、报名校园活动，并生成个人学业规划。",
    "我的知识库": "集中查看当前角色有权访问的全部制度文档。",
    "知识治理": "阅读文档摘要，核对日期和新旧规定差异。",
    "数据看板": "查看热门问题、无资料问题和知识库使用情况。",
    "评测中心": "用人工标注的问题检查系统找资料的准确程度。",
    "版本对比": "比较同一问题在不同模型和检索方式下的回答。",
    "文档管理": "批量导入、预检、重建索引并维护制度版本。",
    "自动诊断": "检查权限隔离、索引一致性和检索服务。",
    "审计日志": "查看角色访问记录并导出脱敏日志。",
    "系统维护": "备份或恢复本机完整数据，并添加或清除明确标注的演示内容。",
}

unread_count = rag.get_unread_count(user)

with st.sidebar:
    st.markdown(
        f"<div class='user-badge'><strong>{html.escape(user['username'])}</strong>"
        f"<span>{html.escape(role_text(user['role']))}</span></div>",
        unsafe_allow_html=True,
    )
    allowed_names = "、".join(GROUPS[g] for g in ROLE_ACCESS[user["role"]])
    st.caption(f"当前可访问：{allowed_names}")
    if unread_count:
        st.info(f"消息中心有 {unread_count} 条未读消息")
    st.markdown("<div class='section-kicker'>功能导航</div>", unsafe_allow_html=True)
    nav_group = st.selectbox(
        "功能分区", list(nav_groups), key="nav_group", label_visibility="collapsed"
    )
    if st.session_state.get("nav_page") not in nav_groups[nav_group]:
        st.session_state.nav_page = nav_groups[nav_group][0]
    page = st.radio(
        "选择功能", nav_groups[nav_group], key="nav_page", label_visibility="collapsed",
        format_func=lambda name: (
            f"{name}（{unread_count} 条未读）"
            if name == "消息中心" and unread_count else name
        ),
    )
    st.divider()

    with st.expander("本地模型设置"):
        base_url = st.text_input("Ollama 地址", value="http://localhost:11434")
        installed_models, model_check_error = get_installed_models(base_url)
        answer_models = [
            name for name in installed_models
            if "embed" not in name.lower() and name.lower() not in {"bge-m3", "bge-m3:latest"}
        ]
        preferred_models = ["qwen2.5:7b", "qwen2.5:3b", "qwen:1.8b"]
        model_options = preferred_models + [
            name for name in answer_models if name not in preferred_models
        ]
        if "qwen2.5:7b" in answer_models:
            default_model = "qwen2.5:7b"
        elif "qwen2.5:3b" in answer_models:
            default_model = "qwen2.5:3b"
        else:
            default_model = answer_models[0] if answer_models else "qwen2.5:7b"
        llm_model = st.selectbox(
            "本地回答模型",
            model_options,
            index=model_options.index(default_model),
            on_change=on_model_change,
        )
        if model_check_error:
            st.warning("没有读取到本机模型列表。请先启动 Ollama；启动后页面会自动重新检测。")
        elif not answer_models:
            st.warning("本机还没有可用的回答模型。可先运行 ollama pull qwen2.5:3b，再刷新页面。")
        elif llm_model not in answer_models:
            st.warning(f"模型“{llm_model}”尚未安装，请运行 ollama pull {llm_model}，或选择上方已安装模型。")
        else:
            st.caption(f"已检测到本机模型“{llm_model}”，可直接使用。")
        if llm_model == "qwen2.5:7b":
            st.caption("推荐：总结和理解追问的效果更好，需要较多内存。")
        elif llm_model == "qwen2.5:3b":
            st.caption("低配置备用：占用资源较少，但总结能力弱于 7b。")
        elif llm_model == "qwen:1.8b":
            st.caption("仅作旧版兼容，更容易重复或漏答，不建议日常使用。")
        embedding_model = st.text_input("嵌入模型", value="bge-m3")
        st.caption("更换嵌入模型后，需要重新向量化全部现有文档。")
        rag = get_rag(llm_model, embedding_model, base_url)

    with st.expander("问答偏好"):
        top_k = st.slider("最多显示来源数", 1, 5, 3)
        retrieval_mode = st.radio(
            "检索模式",
            ["hybrid", "vector", "bm25"],
            format_func=lambda value: {
                "hybrid": "两种方式一起找", "vector": "按意思找（向量）", "bm25": "按关键词找（BM25）"
            }[value],
        )
        use_rerank = st.checkbox("找到资料后再精细排序（BGE Rerank）", value=False)
        if use_rerank:
            st.caption("第一次使用需要下载排序模型，之后可在本地运行；不开启也能正常问答。")

    st.divider()
    if st.button("生成我的问答 CSV", use_container_width=True):
        try:
            st.session_state.qa_csv = rag.export_qa_csv(user)
            st.success("CSV 已生成，仅包含当前账户的问答。")
        except Exception as exc:
            st.error(f"导出失败：{exc}")
    if st.session_state.get("qa_csv"):
        st.download_button(
            "下载问答记录 CSV",
            data=st.session_state.qa_csv,
            file_name="校务通_问答记录.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption("已嵌入当前账户的零宽溯源水印")

    if st.button("导出我的全部记录", use_container_width=True):
        try:
            with st.spinner("正在整理个人课表、问答和活动记录……"):
                st.session_state.personal_export = rag.export_personal_data(user)
            st.success("个人数据包已生成。")
        except Exception as exc:
            st.error(f"导出失败：{exc}")
    if st.session_state.get("personal_export"):
        st.download_button(
            "下载个人数据 ZIP", data=st.session_state.personal_export,
            file_name=f"校务通_{user['username']}_个人数据.zip", mime="application/zip",
            use_container_width=True,
        )
        st.caption("只含自己的课表、问答和活动报名，不含其他用户资料。")

    with st.expander("修改密码"): 
        with st.form("password_form"):
            old_password = st.text_input("原密码", type="password")
            new_password = st.text_input("新密码（至少 8 位）", type="password")
            change = st.form_submit_button("确认修改")
        if change:
            try:
                rag.change_password(user, old_password, new_password)
                st.session_state.user["must_change_password"] = False
                st.success("密码已修改。")
            except Exception as exc:
                st.error(str(exc))

    if st.button("退出登录", use_container_width=True):
        st.session_state.clear()
        st.rerun()


def show_sources(sources: list[dict], record_id: int) -> None:
    if not sources:
        return
    with st.expander(f"答案依据（{len(sources)} 条，已提取关键句）"):
        for source in sources:
            page = f"第 {source['page']} 页" if source.get("page") else "全文"
            st.markdown(
                f"**[资料{source['id']}] {source['source']} · {page}**"
            )
            matched = source.get("matched") or []
            source_note = []
            if matched:
                source_note.append("命中词：" + "、".join(matched))
            if source.get("academic_year"):
                source_note.append(source["academic_year"])
            source_note.append(source.get("status") or "现行有效")
            if source.get("confidence") is not None:
                source_note.append(f"匹配分 {source['confidence']}/100")
            if source_note:
                st.caption(" · ".join(source_note))
            if source.get("is_current") is False:
                st.warning("该来源不是现行有效版本，请优先核对最新制度。")
            evidence = source.get("evidence") or source["content"][:240] + "……"
            st.markdown(f"> {evidence}")

            preview_key = f"{record_id}_{source['id']}"
            if st.button(
                "定位到原文",
                key=f"source_{record_id}_{source['id']}",
            ):
                try:
                    opened = rag.open_source(
                        user,
                        source["group"],
                        source["source"],
                        source.get("page"),
                    )
                    snippet = source.get("highlight") or evidence
                    opened_text = opened.get("text") or ""
                    saved_text = source.get("content") or ""
                    display_text = opened_text or saved_text
                    st.session_state.preview = {
                        "key": preview_key,
                        "title": f"{source['group_name']}/{source['source']}",
                        "location": opened["location"],
                        "html": highlight_document(display_text, snippet) if display_text else "",
                        "notice": opened.get("notice") or "",
                        "using_saved_text": not opened_text and bool(saved_text),
                        "file_bytes": opened.get("file_bytes"),
                        "file_name": opened.get("file_name") or source["source"],
                    }
                except Exception as exc:
                    st.error(f"原文打开失败：{exc}")

            current = st.session_state.get("preview")
            if current and current.get("key") == preview_key:
                if current.get("notice"):
                    st.warning(current["notice"])
                if current.get("using_saved_text"):
                    st.caption("当前显示问答时已经保存的来源切片；未重新识别扫描页。")
                if current.get("html"):
                    st.caption(f"原文位置：{current['location']}，黄色部分为关键句")
                    components.html(
                        current["html"]
                        + "<script>const el=document.getElementById('active-highlight');"
                          "if(el){el.scrollIntoView({block:'center'});}</script>",
                        height=560,
                        scrolling=True,
                    )
                if current.get("file_bytes"):
                    st.download_button(
                        f"下载原始 PDF（{current['location']}）",
                        data=current["file_bytes"],
                        file_name=current["file_name"],
                        mime="application/pdf",
                        key=f"download_source_{record_id}_{source['id']}",
                    )
                if st.button("关闭原文", key=f"close_{record_id}_{source['id']}"):
                    st.session_state.pop("preview", None)
                    st.rerun()
            st.divider()


def render_study_plan(plan_text: str) -> None:
    """把模型返回的表格和文字分开渲染，避免动态 Markdown 表格引发 React 节点冲突。"""
    lines = str(plan_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    table_start = next(
        (
            index
            for index in range(len(lines) - 1)
            if lines[index].strip().startswith("|")
            and lines[index].strip().endswith("|")
            and lines[index + 1].strip().startswith("|")
            and re.fullmatch(
                r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?",
                lines[index + 1].strip(),
            )
        ),
        None,
    )
    if table_start is None:
        st.text(str(plan_text or "没有可显示的规划内容。"))
        return

    table_end = table_start + 2
    while table_end < len(lines):
        line = lines[table_end].strip()
        if not (line.startswith("|") and line.endswith("|")):
            break
        table_end += 1

    def split_row(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    headers = split_row(lines[table_start])
    rows = [split_row(line) for line in lines[table_start + 2:table_end]]
    rows = [row[:len(headers)] + [""] * max(0, len(headers) - len(row)) for row in rows]
    before = "\n".join(lines[:table_start]).strip()
    after = "\n".join(lines[table_end:]).strip()
    if before:
        st.text(before)
    if headers and rows:
        st.table([dict(zip(headers, row)) for row in rows])
    if after:
        st.text(after)


def show_answer_meta(record: dict) -> None:
    confidence = int(record.get("confidence", 0))
    mode_names = {"hybrid": "混合", "vector": "纯向量", "bm25": "纯 BM25"}
    mode = mode_names.get(record.get("retrieval_mode"), record.get("retrieval_mode") or "旧版")
    rerank = "＋Rerank" if record.get("rerank_used") else ""
    latency_ms = int(record.get("latency_ms", 0) or 0)
    latency_text = (
        f" · 实际耗时 {latency_ms / 1000:.2f} 秒" if latency_ms else " · 旧记录未保存耗时"
    )
    st.caption(
        f"{record['created_at']} · {record.get('model') or '旧版模型'} · {mode}{rerank}{latency_text}"
    )
    st.progress(confidence / 100, text=f"检索匹配置信度：{confidence}/100")
    if confidence < 60:
        st.warning("知识库匹配度较低，回答仅供参考，请仔细核对原文。")
    trust_score = int(record.get("trust_score", 0))
    trust_explanation = record.get("trust_explanation") or "旧问答没有保存这项信息。"
    if record.get("sources"):
        st.progress(trust_score / 100, text=f"回答参考可信度：{trust_score}/100")
        st.caption(trust_explanation + "。该分数只反映资料支持情况，不等于事实正确率。")
    else:
        st.caption("回答参考可信度：未计算（没有可直接使用的资料）。")

    feedback = record.get("feedback", "")
    if feedback:
        st.caption("已反馈：" + ("有用" if feedback == "useful" else "无用"))
    col1, col2, _ = st.columns([1, 1, 5])
    with col1:
        if st.button("有用", key=f"useful_{record['id']}"):
            rag.set_feedback(user, int(record["id"]), "useful")
            st.rerun()
    with col2:
        if st.button("无用", key=f"useless_{record['id']}"):
            rag.set_feedback(user, int(record["id"]), "useless")
            st.rerun()


def render_documents() -> None:
    docs = rag.list_documents(user)
    if not docs:
        st.info("当前权限范围内还没有文档。")
        return
    rows = [
        {
            "分组": d["group_name"],
            "文件名": d["filename"],
            "学年度": d.get("academic_year") or "未设置",
            "版本状态": d.get("status") or "现行有效",
            "生效日期": d.get("effective_date") or "未设置",
            "失效日期": d.get("expiry_date") or "未设置",
            "大小（KB）": d["size_kb"],
            "修改时间": d["modified"],
        }
        for d in docs
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


st.markdown(
    f"""<div class="workspace-head">
    <div><h1>{html.escape(page)}</h1><p>{html.escape(page_descriptions.get(page, ''))}</p></div>
    <div class="local-status">本地运行 · {html.escape(role_text(user['role']))}</div>
    </div>""",
    unsafe_allow_html=True,
)

if page == "工作台":
    if st.session_state.pop("password_changed_notice", False):
        st.success("密码已修改，请妥善保管新密码。")
    try:
        stats = rag.get_stats(user)
    except Exception:
        stats = {"documents": 0, "today_qa": 0}
    workbench_settings = rag.get_user_settings(user)
    today_courses = rag.get_schedule(
        user, date.today().isoweekday(), week=workbench_settings["current_week"]
    )
    active_activities = sum(a["status"] == "published" for a in rag.get_activities(user))
    overview = st.columns(4)
    overview[0].metric("可访问文档", stats.get("documents", 0))
    overview[1].metric("今日问答", stats.get("today_qa", 0))
    overview[2].metric("今日课程", len(today_courses))
    overview[3].metric("进行中活动", active_activities)

    st.markdown("<div class='section-kicker'>常用功能</div>", unsafe_allow_html=True)
    all_quick_items = [
        ("教务问答", "查制度、问流程，直接查看结论和原文依据。", "去问一个问题", ""),
        ("办事向导", "把办事条件、材料和步骤整理成清单。", "生成办理清单", ""),
        ("校园社区", "查看论坛热议、失物招领和二手信息。", "进入校园论坛", "校园论坛"),
        ("校园服务", "查看今日课表、下一节课和空教室参考。", "打开我的课表", "我的课表"),
        ("消息中心", "查看私信、评论回复、活动和审核结果。", "查看我的消息", ""),
    ]
    favorites = workbench_settings.get("favorites", [])
    quick_items = (
        [item for item in all_quick_items if item[0] in favorites]
        if favorites else all_quick_items[:4]
    )
    quick_cols = st.columns(min(4, len(quick_items)))
    for index, (target, copy, button_text, subpage) in enumerate(quick_items):
        with quick_cols[index % len(quick_cols)]:
            with st.container(border=True):
                st.markdown(f"<div class='quick-title'>{target}</div><div class='quick-copy'>{copy}</div>", unsafe_allow_html=True)
                if st.button(button_text, key=f"quick_{target}", use_container_width=True):
                    open_page(target, subpage)
    with st.expander("收藏我常用的功能"):
        st.caption("最多收藏 5 项；保存后，工作台只显示这些入口。取消全部收藏即可恢复默认四项。")
        selected_favorites = st.multiselect(
            "常用功能", [item[0] for item in all_quick_items], default=favorites,
            key="workbench_favorites",
        )
        if st.button("保存常用功能", key="save_workbench_favorites"):
            if len(selected_favorites) > 5:
                st.error("最多收藏 5 项。")
            else:
                rag.set_favorites(user, selected_favorites)
                st.rerun()

    st.markdown("<div class='section-kicker'>今日动态</div>", unsafe_allow_html=True)
    recent_col, schedule_col = st.columns([1.25, 1])
    with recent_col:
        st.markdown("**最近问答**")
        recent_records = rag.get_qa_records(user, limit=3)
        if not recent_records:
            st.caption("还没有问答记录，点击上方“去问一个问题”开始。")
        for record in recent_records:
            with st.container(border=True):
                st.markdown(f"**{record['question']}**")
                st.caption(record["created_at"])
                st.text(plain_answer(record["answer"])[:150] + "……")
                if st.button("继续查看", key=f"recent_qa_{record['id']}"):
                    open_page("教务问答")
    with schedule_col:
        st.markdown("**接下来的课程**")
        upcoming = rag.get_upcoming_classes(user)
        if not upcoming:
            st.caption("今天没有尚未开始的已录入课程。")
        for course in upcoming[:3]:
            with st.container(border=True):
                st.markdown(f"**{course['course_name']}**")
                st.caption(f"{course['start_time']} · {course['location'] or '地点未填写'} · 约 {course['minutes']} 分钟后")
        if st.button("管理本周课表", use_container_width=True):
            open_page("校园服务", "我的课表")

if page == "教务问答":
    st.markdown(
        "<div class='usage-note'><strong>怎么用：</strong>直接输入想问的事情，回答会按结论和要点排列，"
        "并附上可查看的原文。接着问“那需要什么材料？”也可以。历史问答在中间单独滚动，"
        "最新回答在最上方，下方输入框保持可见。</div>",
        unsafe_allow_html=True,
    )
    if st.session_state.get("rerank_notice"):
        st.warning(st.session_state.pop("rerank_notice"))
    if st.session_state.get("generation_notice"):
        st.warning(st.session_state.pop("generation_notice"))
    records = list(reversed(rag.get_qa_records(user, limit=30)))
    with st.container(height=520, border=False):
        if not records:
            st.info("请输入问题开始咨询。系统只会检索当前角色有权访问的知识库。")
        # 最新记录置顶，提交后无需先滚到最底部；records 仍保持时间顺序供追问使用。
        for record in reversed(records):
            with st.container(border=True):
                st.markdown("<div class='message-label user'>你的问题</div>", unsafe_allow_html=True)
                st.markdown(
                    f"<div class='question-text'>{html.escape(record['question'])}</div>",
                    unsafe_allow_html=True,
                )
                resolved = record.get("resolved_question") or record["question"]
                if resolved != record["question"]:
                    st.caption(f"追问已理解为：{resolved}")
            with st.container(border=True):
                st.markdown("<div class='message-label'>校务通回答</div>", unsafe_allow_html=True)
                st.markdown(
                    f"<div class='answer-text'>{html.escape(plain_answer(record['answer']))}</div>",
                    unsafe_allow_html=True,
                )
                show_sources(record["sources"], int(record["id"]))
                st.divider()
                show_answer_meta(record)

    question = st.chat_input("请输入要查询的教务制度、办理条件或流程")
    if question:
        try:
            with st.spinner("正在权限范围内检索并生成回答……"):
                result = rag.ask(
                    user,
                    question,
                    top_k=top_k,
                    retrieval_mode=retrieval_mode,
                    use_rerank=use_rerank,
                    history=[{"question": item["question"]} for item in records[-2:]],
                )
            if result.get("rerank_notice"):
                st.session_state.rerank_notice = result["rerank_notice"]
            if result.get("generation_notice"):
                st.session_state.generation_notice = result["generation_notice"]
            st.session_state.pop("qa_csv", None)
            st.rerun()
        except Exception as exc:
            st.error(f"处理失败：{exc}")

if page == "办事向导":
    st.subheader("引导式事务办理")
    st.caption(
        "使用说明：输入“缓考”“转专业”等具体事项，系统会从你有权查看的制度中整理条件、材料、步骤和时间。"
        "你可以勾选已经准备好的材料，再导出办理清单。资料没写清楚的部分会留空，不会自动补写。"
    )
    with st.form("transaction_guide_form"):
        guide_topic = st.text_input(
            "要办理什么事？", placeholder="例如：缓考怎么办理", max_chars=500
        )
        guide_submitted = st.form_submit_button("生成办理向导", type="primary")
    if guide_submitted:
        try:
            with st.spinner("正在查找制度并整理办理信息……"):
                st.session_state.guide_result = rag.build_transaction_guide(
                    user, guide_topic, top_k=6,
                    retrieval_mode=retrieval_mode, use_rerank=use_rerank,
                )
            st.session_state.pop("guide_export", None)
        except Exception as exc:
            st.error(f"生成向导失败：{exc}")

    guide = st.session_state.get("guide_result")
    if guide:
        if guide.get("rerank_notice"):
            st.warning(guide["rerank_notice"])
        st.info(guide["message"])
        if not guide.get("found"):
            st.warning("暂时无法生成清单，请补充相关制度后再试。")
        else:
            metric_cols = st.columns(2)
            metric_cols[0].metric("资料匹配", f"{guide.get('confidence', 0)}/100")
            metric_cols[1].metric("回答参考可信度", f"{guide.get('trust_score', 0)}/100")
            st.caption(
                str(guide.get("trust_explanation", ""))
                + "。可信度只反映资料支持情况，不等于事实正确率。"
            )
            guide_key = hashlib.sha1(
                (str(guide.get("created_at", "")) + str(guide.get("topic", ""))).encode("utf-8")
            ).hexdigest()[:12]
            section_titles = {
                "conditions": "1. 先看是否符合条件",
                "materials": "2. 勾选已经准备好的材料",
                "steps": "3. 按原文顺序办理",
                "deadlines": "4. 核对截止信息",
            }
            for section_key, title in section_titles.items():
                st.markdown(f"**{title}**")
                items = guide.get("sections", {}).get(section_key, [])
                if not items:
                    st.caption("所引资料没有明确说明这一项，请向负责部门核实。")
                    continue
                for index, item in enumerate(items):
                    refs = "、".join(f"资料{ref}" for ref in item.get("source_ids", []))
                    if section_key == "materials":
                        st.checkbox(
                            f"{item['text']}（{refs}）",
                            key=f"guide_material_{guide_key}_{index}",
                        )
                    else:
                        st.write(f"{index + 1}. {item['text']}（{refs}）")
            missing_materials = 0
            material_items = guide.get("sections", {}).get("materials", [])
            for index in range(len(material_items)):
                if not st.session_state.get(f"guide_material_{guide_key}_{index}", False):
                    missing_materials += 1
            if material_items:
                if missing_materials:
                    st.warning(f"还有 {missing_materials} 项材料未勾选，请核对是否已准备。")
                else:
                    st.success("清单中的材料均已勾选，请继续核对原件和具体要求。")
            if st.button("生成办理清单 TXT", key=f"make_guide_{guide_key}"):
                checked_materials = [
                    index for index in range(len(material_items))
                    if st.session_state.get(f"guide_material_{guide_key}_{index}", False)
                ]
                st.session_state.guide_export = rag.export_transaction_guide(
                    user, guide, checked_materials
                )
            if st.session_state.get("guide_export"):
                st.download_button(
                    "下载办理清单",
                    data=st.session_state.guide_export,
                    file_name=f"校务通_{str(guide.get('topic', '办理清单'))[:30]}_清单.txt",
                    mime="text/plain",
                    key=f"download_guide_{guide_key}",
                )
            show_sources(guide.get("sources", []), f"guide_{guide_key}")

if page == "消息中心":
    st.subheader("我的站内消息")
    st.caption("私信、评论回复、活动报名和审核结果会集中出现在这里。消息只保存在本机；点击消息可标记已读并前往对应功能。")
    notifications = rag.get_notifications(user)
    header_cols = st.columns([3, 1])
    header_cols[0].write(f"共 {len(notifications)} 条消息，其中 {unread_count} 条未读。")
    if header_cols[1].button(
        "全部标为已读", use_container_width=True, disabled=not unread_count
    ):
        rag.mark_all_notifications_read(user)
        st.rerun()
    if not notifications:
        st.info("暂时没有消息。收到私信、评论回复或审核结果后会在这里显示。")
    for notice in notifications:
        is_unread = not notice.get("read_at")
        with st.container(border=True):
            title = ("【未读】" if is_unread else "") + notice["title"]
            st.markdown(f"**{html.escape(title)}**")
            st.caption(f"{notice['kind']} · {notice['created_at']}" + (" · 未读" if is_unread else " · 已读"))
            if notice.get("content"):
                st.write(notice["content"])
            if notice.get("link"):
                if st.button(
                    "查看并前往相关页面" if is_unread else "再次查看相关页面",
                    key=f"open_notification_{notice['id']}",
                ):
                    if is_unread:
                        rag.mark_notification_read(user, int(notice["id"]))
                    target, _, subpage = notice["link"].partition("|")
                    if target == "消息中心":
                        st.rerun()
                    open_page(target, subpage)
            elif is_unread and st.button("标为已读", key=f"read_notification_{notice['id']}"):
                rag.mark_notification_read(user, int(notice["id"]))
                st.rerun()

if page == "校园社区":
    community_names = ["校园论坛", "失物招领", "二手交易", "心情树洞", "站内私信"]
    if user["role"] == "admin":
        community_names.append("内容审核")
    community_page = st.radio(
        "社区功能", community_names, key="community_page", horizontal=True,
        label_visibility="collapsed",
    )

    if community_page == "校园论坛":
        st.subheader("校园论坛")
        st.caption("可以发求助、选课交流、组队和生活帖，支持评论、楼中楼回复、点赞、收藏和热门排序。违规内容会进入拦截或人工复核，不会直接公开。")
        with st.expander("发布新帖子"):
            with st.form("new_forum_post"):
                post_category = st.selectbox("分类", ["求助", "选课交流", "组队", "吐槽", "校园生活", "其他"])
                post_title = st.text_input("标题", max_chars=80)
                post_content = st.text_area("正文", max_chars=5000, height=140)
                post_image = st.file_uploader("可选图片（不超过 5 MB）", type=["png", "jpg", "jpeg", "webp"], key="forum_image")
                if st.form_submit_button("发布帖子", type="primary"):
                    try:
                        result = rag.create_forum_post(
                            user, post_category, post_title, post_content,
                            post_image.getvalue() if post_image else None,
                            "." + post_image.name.rsplit(".", 1)[-1] if post_image and "." in post_image.name else "",
                        )
                        show_moderation_result(result, "帖子已发布。")
                    except Exception as exc:
                        st.error(f"发布失败：{exc}")
        filter_cols = st.columns(2)
        forum_category = filter_cols[0].selectbox("查看分类", ["全部", "求助", "选课交流", "组队", "吐槽", "校园生活", "其他"])
        forum_sort_label = filter_cols[1].selectbox("排序方式", ["最新发布", "热门帖子", "我的收藏"])
        forum_sort = {"最新发布": "latest", "热门帖子": "hot", "我的收藏": "favorite"}[forum_sort_label]
        posts = rag.get_forum_posts(user, forum_category, forum_sort)
        if not posts:
            st.info("这里还没有帖子。")
        for post in posts:
            with st.container(border=True):
                st.markdown(f"**{post['title']}**")
                st.caption(f"#{post['id']} · {post['category']} · {post['username']} · {post['created_at']}")
                if post["status"] != "visible":
                    st.warning(f"你的帖子当前状态：{post['status']}；{post.get('moderation_reason') or '等待复核'}")
                st.text(post["content"])
                if post.get("image_path"):
                    try:
                        st.image(post["image_path"], use_container_width=True)
                    except Exception:
                        st.caption("图片文件暂时无法显示。")
                action_cols = st.columns([1, 1, 5])
                if action_cols[0].button(
                    f"{'♥' if post['liked'] else '♡'} {post['like_count']}", key=f"like_post_{post['id']}"
                ):
                    rag.toggle_forum_reaction(user, post["id"], "like")
                    st.rerun()
                if action_cols[1].button(
                    "★ 已收藏" if post["favorited"] else "☆ 收藏", key=f"favorite_post_{post['id']}"
                ):
                    rag.toggle_forum_reaction(user, post["id"], "favorite")
                    st.rerun()
                st.caption(f"评论 {post['comment_count']} 条")
                with st.expander("查看评论与回复"):
                    comments = rag.get_forum_comments(user, post["id"])
                    for comment in comments:
                        prefix = f"回复 #{comment['parent_id']} · " if comment.get("parent_id") else ""
                        st.markdown(f"**{comment['username']}**：{comment['content']}")
                        st.caption(f"#{comment['id']} · {prefix}{comment['created_at']}")
                    with st.form(f"comment_form_{post['id']}"):
                        reply_options = ["不回复特定评论"] + [f"回复 #{c['id']}：{c['content'][:20]}" for c in comments]
                        reply_choice = st.selectbox("回复位置", reply_options)
                        comment_text = st.text_area("写评论", max_chars=1500, height=80)
                        if st.form_submit_button("提交评论"):
                            parent_id = None
                            if reply_choice != "不回复特定评论":
                                parent_id = int(reply_choice.split("#", 1)[1].split("：", 1)[0])
                            try:
                                result = rag.add_forum_comment(user, post["id"], comment_text, parent_id)
                                show_moderation_result(result, "评论已发布。")
                            except Exception as exc:
                                st.error(f"评论失败：{exc}")

    if community_page == "失物招领":
        st.subheader("失物招领")
        st.caption("发布丢失或捡到的物品，处理完成后可标记为已解决。联系发布者请使用站内私信，不必公开手机号。")
        with st.expander("发布物品信息"):
            with st.form("lost_found_form"):
                lf_kind_label = st.radio("信息类型", ["丢失", "捡到"], horizontal=True)
                lf_category = st.selectbox("物品分类", ["校园卡", "书籍", "雨伞", "电子产品", "证件钥匙", "其他"])
                lf_title = st.text_input("物品名称", max_chars=80)
                lf_description = st.text_area("特征描述", max_chars=1500)
                lf_location = st.text_input("丢失或捡到地点", max_chars=120)
                lf_date = st.date_input("发生日期", value=date.today())
                if st.form_submit_button("发布信息", type="primary"):
                    try:
                        rag.create_lost_found_item(
                            user, "lost" if lf_kind_label == "丢失" else "found", lf_category,
                            lf_title, lf_description, lf_location, lf_date.isoformat(),
                        )
                        st.success("物品信息已发布。")
                    except Exception as exc:
                        st.error(f"发布失败：{exc}")
        lf_filters = st.columns(2)
        lf_kind = lf_filters[0].selectbox("查看信息", ["全部", "丢失", "捡到"], key="lf_filter")
        lf_resolved = lf_filters[1].checkbox("包含已解决", key="lf_resolved")
        lf_items = rag.get_lost_found_items(
            user, {"全部": "all", "丢失": "lost", "捡到": "found"}[lf_kind], lf_resolved
        )
        if not lf_items:
            st.info("暂无相关物品信息。")
        for item in lf_items:
            with st.container(border=True):
                st.markdown(f"**{'丢失' if item['kind'] == 'lost' else '捡到'} · {item['title']}**")
                st.caption(f"{item['category']} · {item['location']} · {item['happened_at']} · 发布者 {item['username']}")
                st.text(item["description"])
                st.caption("状态：" + ("已解决" if item["status"] == "resolved" else "等待处理"))
                cols = st.columns(2)
                if item["username"] != user["username"]:
                    if cols[0].button("联系发布者", key=f"lf_contact_{item['id']}"):
                        contact_user(item["username"])
                elif cols[0].button(
                    "重新开放" if item["status"] == "resolved" else "标记已解决", key=f"lf_status_{item['id']}"
                ):
                    rag.set_lost_found_status(user, item["id"], "open" if item["status"] == "resolved" else "resolved")
                    st.rerun()

    if community_page == "二手交易":
        st.subheader("校内二手交易")
        st.caption("可发布教材、数码和生活用品。风险提示只用于发现可疑信息，不能保证交易安全；请当面验货，不先交保证金，不点击陌生链接。系统不提供在线支付。")
        with st.expander("发布商品"):
            with st.form("market_form"):
                market_title = st.text_input("商品名称", max_chars=80)
                market_category = st.selectbox("商品分类", ["教材书籍", "数码产品", "交通工具", "生活用品", "其他"])
                market_price = st.number_input("价格（元）", min_value=0.0, max_value=1000000.0, step=1.0)
                market_description = st.text_area("成色、规格和交易说明", max_chars=2000)
                if st.form_submit_button("发布商品", type="primary"):
                    try:
                        result = rag.create_market_item(user, market_title, market_category, market_price, market_description)
                        show_moderation_result(result, "商品已发布。")
                    except Exception as exc:
                        st.error(f"发布失败：{exc}")
        include_closed = st.checkbox("包含已售出和已下架商品", key="market_closed")
        market_items = rag.get_market_items(user, include_closed)
        if not market_items:
            st.info("暂无商品。")
        for item in market_items:
            with st.container(border=True):
                st.markdown(f"**{item['title']} · ¥{item['price']:.2f}**")
                st.caption(f"{item['category']} · 发布者 {item['username']} · {item['created_at']}")
                if item["risk_status"] != "visible":
                    st.warning(f"你的商品正在复核或已拦截：{item['risk_reason']}")
                st.text(item["description"])
                status_name = {"active": "在售", "sold": "已售出", "closed": "已下架"}.get(item["status"], item["status"])
                st.caption("状态：" + status_name)
                cols = st.columns(3)
                if item["username"] != user["username"]:
                    if cols[0].button("私信卖家", key=f"market_contact_{item['id']}"):
                        contact_user(item["username"])
                else:
                    if cols[0].button("标记已售出", key=f"market_sold_{item['id']}", disabled=item["status"] != "active"):
                        rag.set_market_status(user, item["id"], "sold")
                        st.rerun()
                    if cols[1].button("下架", key=f"market_close_{item['id']}", disabled=item["status"] != "active"):
                        rag.set_market_status(user, item["id"], "closed")
                        st.rerun()

    if community_page == "心情树洞":
        st.subheader("匿名树洞与心情打卡")
        st.caption("树洞对其他用户只显示匿名编号；心情记录仅自己可见。这里提供一般性情绪支持，不进行抑郁、焦虑等疾病诊断，也不能替代学校心理中心或专业医疗服务。")
        mood_cols = st.columns(2)
        with mood_cols[0]:
            with st.form("mood_post_form"):
                mood_content = st.text_area("匿名说点什么", max_chars=2000, height=120)
                if st.form_submit_button("匿名发布"):
                    try:
                        result = rag.create_mood_post(user, mood_content)
                        show_moderation_result(result, "树洞已发布。")
                        if result.get("crisis"):
                            st.error(result["support_message"])
                    except Exception as exc:
                        st.error(f"发布失败：{exc}")
        with mood_cols[1]:
            with st.form("mood_checkin_form"):
                mood_score = st.slider("今天的心情", 1, 5, 3, format="%d 分")
                mood_note = st.text_area("记录此刻感受（仅自己可见）", max_chars=1000, height=120)
                if st.form_submit_button("完成打卡"):
                    try:
                        checkin = rag.create_mood_checkin(user, mood_score, mood_note)
                        if checkin["crisis"]:
                            st.error(checkin["response"])
                        else:
                            st.info(checkin["response"])
                    except Exception as exc:
                        st.error(f"打卡失败：{exc}")
        st.markdown("**匿名树洞**")
        for post in rag.get_mood_posts(user):
            with st.container(border=True):
                st.caption(f"{post['alias']} · {post['created_at']}")
                st.text(post["content"])
        with st.expander("我的心情打卡历史"):
            checkins = rag.get_mood_checkins(user)
            if checkins:
                for item in checkins:
                    st.caption(f"{item['created_at']} · {item['mood_score']} 分")
                    st.text(item["note"] or "未填写文字")
                    st.info(item["response"])
            else:
                st.caption("还没有打卡记录。")

    if community_page == "站内私信":
        st.subheader("站内私信")
        st.caption("只能查看自己发送或接收的私信。可疑链接、诈骗和严重辱骂会被拦截或进入管理员复核；普通私信不会出现在公共页面。")
        directory = rag.list_user_directory(user)
        if not directory:
            st.info("暂无可联系的其他账户。")
        else:
            directory_map = {item["username"]: item for item in directory}
            if st.session_state.get("message_recipient") not in directory_map:
                st.session_state.message_recipient = next(iter(directory_map))
            recipient = st.selectbox(
                "选择联系人", list(directory_map), key="message_recipient",
                format_func=lambda name: f"{name} · {directory_map[name]['role_name']}",
            )
            with st.form("private_message_form"):
                message_content = st.text_area("私信内容", max_chars=2000, height=100)
                if st.form_submit_button("发送私信", type="primary"):
                    try:
                        result = rag.send_private_message(user, recipient, message_content)
                        show_moderation_result(result, "私信已送达。")
                    except Exception as exc:
                        st.error(f"发送失败：{exc}")
            st.markdown(f"**与 {recipient} 的会话**")
            messages = rag.get_private_messages(user, recipient)
            if not messages:
                st.info("还没有会话内容。")
            for message in messages:
                own = message["sender"] == user["username"]
                with st.chat_message("user" if own else "assistant"):
                    st.text(message["content"])
                    st.caption(("我" if own else message["sender"]) + " · " + message["created_at"])

    if user["role"] == "admin":
        if community_page == "内容审核":
            st.subheader("社区内容安全复核")
            st.caption("这里只列出被拦截或需要复核的帖子、评论、商品、树洞和私信。通过后才会公开或送达；拒绝会保持隐藏。普通私信不在这里展示。")
            queue = rag.get_moderation_queue(user)
            if not queue:
                st.success("当前没有待复核内容。")
            for item in queue:
                with st.container(border=True):
                    st.markdown(f"**{item['type']} #{item['id']} · {item['status']}**")
                    st.caption(f"提交人 {item['author']} · {item['created_at']} · {item['reason'] or '模型建议复核'}")
                    st.text(item["content"])
                    cols = st.columns(2)
                    if cols[0].button("通过并展示／送达", key=f"approve_{item['table']}_{item['id']}"):
                        rag.review_moderation_item(user, item["table"], item["id"], True)
                        st.rerun()
                    if cols[1].button("拒绝并保持隐藏", key=f"reject_{item['table']}_{item['id']}"):
                        rag.review_moderation_item(user, item["table"], item["id"], False)
                        st.rerun()

if page == "校园服务":
    service_page = st.radio(
        "校园服务功能", ["我的课表", "活动报名", "学业规划"],
        key="service_page", horizontal=True, label_visibility="collapsed",
    )

    if service_page == "我的课表":
        st.subheader("课表、上课提醒与空教室参考")
        st.caption("可手动录入或批量导入课程，支持周次、单双周、编辑和冲突检查。提醒按本机时间计算，只在打开本页面时显示，不会发送系统推送；空教室只根据已录入课表估算，不是学校教务处的实时教室数据。")
        schedule_settings = rag.get_user_settings(user)
        if st.session_state.get("schedule_clear_notice"):
            st.success(st.session_state.pop("schedule_clear_notice"))
        with st.expander("当前周、学期与个人作息设置"): 
            st.caption("当前周用于计算今天和下一节课；作息只用于节次换算与网格展示，是你自己的参考设置，不是学校官方作息。")
            with st.form("schedule_settings_form"):
                setting_cols = st.columns(2)
                current_week = setting_cols[0].number_input(
                    "当前是第几周", min_value=1, max_value=53,
                    value=int(schedule_settings["current_week"]),
                )
                semester = setting_cols[1].text_input(
                    "学期名称（可选）", value=schedule_settings.get("semester", ""),
                    placeholder="例如：2026 春季学期", max_chars=40,
                )
                period_rows = [
                    {"节次": section, "开始时间": schedule_settings["period_times"][str(section)][0],
                     "结束时间": schedule_settings["period_times"][str(section)][1]}
                    for section in range(1, 13)
                ]
                edited_periods = st.data_editor(
                    period_rows, key="period_times_editor", hide_index=True,
                    use_container_width=True, disabled=["节次"],
                    column_config={
                        "节次": st.column_config.NumberColumn("节次"),
                        "开始时间": st.column_config.TextColumn("开始时间（HH:MM）", required=True),
                        "结束时间": st.column_config.TextColumn("结束时间（HH:MM）", required=True),
                    },
                )
                if st.form_submit_button("保存当前周和作息", type="primary"):
                    rows = (
                        edited_periods.to_dict("records") if hasattr(edited_periods, "to_dict")
                        else list(edited_periods)
                    )
                    period_times = {
                        str(int(row["节次"])): [str(row["开始时间"]), str(row["结束时间"])]
                        for row in rows
                    }
                    try:
                        rag.update_schedule_settings(user, current_week, semester, period_times)
                        st.success("设置已保存，按节次导入的课程时间也已同步更新。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"保存失败：{exc}")
        view_week = st.number_input(
            "查看第几周的课表", min_value=1, max_value=53,
            value=int(schedule_settings["current_week"]), key="schedule_view_week",
        )
        upcoming = rag.get_upcoming_classes(user)
        if upcoming:
            next_class = upcoming[0]
            st.info(
                f"下一节：{next_class['course_name']} · {next_class['start_time']} · "
                f"{next_class['location'] or '地点未填写'} · 约 {next_class['minutes']} 分钟后开始"
            )
        else:
            st.caption("今天暂时没有尚未开始的已录入课程。")
        all_schedule = rag.get_schedule(user)
        schedule = rag.get_schedule(user, week=int(view_week))
        conflicts = rag.get_schedule_conflicts(user, week=int(view_week))
        if conflicts:
            st.error(f"第 {int(view_week)} 周发现 {len(conflicts)} 组时间重叠，请检查课程安排。")
            for conflict in conflicts:
                st.warning(
                    f"星期{'一二三四五六日'[conflict['weekday'] - 1]}："
                    f"《{conflict['first']}》与《{conflict['second']}》在 {conflict['time']} 重叠。"
                )
        else:
            st.caption(f"第 {int(view_week)} 周未发现已录入课程的时间重叠。")
        if schedule:
            render_weekly_schedule(schedule, schedule_settings["period_times"])
        elif all_schedule:
            st.info(f"第 {int(view_week)} 周没有课程；可以切换周次查看其他安排。")
        else:
            st.info("还没有课程，请先手动添加或导入 CSV／PDF。")
        schedule_cols = st.columns(2)
        with schedule_cols[0]:
            with st.expander("手动添加课程"):
                with st.form("schedule_form"):
                    course_name = st.text_input("课程名称", max_chars=100)
                    weekday = st.selectbox("星期", list(range(1, 8)), format_func=lambda value: "星期" + "一二三四五六日"[value - 1])
                    start_time = st.time_input("开始时间", value=time(8, 0))
                    end_time = st.time_input("结束时间", value=time(9, 40))
                    location = st.text_input("上课地点", max_chars=100)
                    teacher = st.text_input("教师（可选）", max_chars=60)
                    week_cols = st.columns(3)
                    start_week = week_cols[0].number_input("开始周", 1, 53, 1)
                    end_week = week_cols[1].number_input("结束周", 1, 53, 16)
                    week_type_label = week_cols[2].selectbox("上课周", ["每周", "单周", "双周"])
                    course_semester = st.text_input(
                        "学期（可选）", value=schedule_settings.get("semester", ""), max_chars=40
                    )
                    if st.form_submit_button("添加课程", type="primary"):
                        try:
                            rag.add_schedule_entry(
                                user, course_name, weekday, start_time.strftime("%H:%M"),
                                end_time.strftime("%H:%M"), location, teacher,
                                start_week=start_week, end_week=end_week,
                                week_type={"每周": "all", "单周": "odd", "双周": "even"}[week_type_label],
                                semester=course_semester,
                            )
                            st.success("课程已添加。")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"添加失败：{exc}")
        with schedule_cols[1]:
            with st.expander("批量导入课表（CSV／PDF）"):
                notice = st.session_state.pop("schedule_import_notice", None)
                if notice:
                    st.success(
                        f"成功导入 {notice['success']} 条课程；跳过 {notice.get('duplicates', 0)} 条重复课程。"
                    )
                    for error in notice.get("errors", []):
                        st.warning(error)
                st.caption(
                    "CSV 必填：课程、星期、开始时间、结束时间；可选：地点、教师、开始周、结束周、单双周、学期、开始节次、结束节次。"
                    "PDF 会先显示识别结果，确认后才导入；只有节次也可以导入，并标为参考时间。重复课程自动跳过，扫描版 PDF 可尝试本地 OCR。"
                )
                template = (
                    "课程,星期,开始时间,结束时间,地点,教师,开始周,结束周,单双周,学期,开始节次,结束节次\n"
                    "高等数学,1,08:00,09:40,教学楼A101,张老师,1,16,每周,2026春季学期,1,2\n"
                )
                st.download_button("下载 CSV 课表模板", data=("\ufeff" + template).encode("utf-8"), file_name="校务通_课表模板.csv", mime="text/csv")
                schedule_file = st.file_uploader(
                    "选择课表文件", type=["csv", "pdf"], key="schedule_import_file",
                    help="PDF 建议包含清晰表格；支持具体时间，也支持“第1—2节”等节次。",
                )
                if schedule_file and schedule_file.name.lower().endswith(".pdf"):
                    schedule_ocr = st.checkbox(
                        "这是扫描版 PDF，尝试本地 OCR",
                        key="schedule_pdf_ocr",
                        help="只识别本页文字过少的 PDF；首次使用 OCR 需安装相应本地组件。",
                    )
                    if st.button("解析并预览 PDF", type="primary", use_container_width=True):
                        try:
                            with st.spinner("正在本地读取 PDF，请稍候……"):
                                parsed = rag.parse_schedule_pdf(
                                    user, schedule_file.getvalue(), use_ocr=schedule_ocr
                                )
                            st.session_state.schedule_pdf_preview = {
                                "fingerprint": hashlib.sha256(schedule_file.getvalue()).hexdigest(),
                                "filename": schedule_file.name,
                                "result": parsed,
                            }
                        except Exception as exc:
                            st.session_state.pop("schedule_pdf_preview", None)
                            st.error(f"PDF 解析失败：{exc}")
                    preview_state = st.session_state.get("schedule_pdf_preview")
                    fingerprint = hashlib.sha256(schedule_file.getvalue()).hexdigest()
                    if preview_state and preview_state.get("fingerprint") == fingerprint:
                        preview = preview_state["result"]
                        entries = preview.get("entries", [])
                        st.info(
                            f"共读取 {preview.get('pages', 0)} 页，识别出 {len(entries)} 条课程。"
                            + (f" OCR 处理页：{preview.get('ocr_pages', [])}" if preview.get("ocr_pages") else "")
                        )
                        for warning in preview.get("warnings", []):
                            st.warning(warning)
                        if entries:
                            preview_rows = "".join(
                                "<tr>"
                                f"<td>{html.escape(item['course_name'])}</td>"
                                f"<td>{'一二三四五六日'[item['weekday'] - 1]}</td>"
                                f"<td>{html.escape(item['start_time'])}</td>"
                                f"<td>{html.escape(item['end_time'])}</td>"
                                f"<td>{html.escape(('第' + item.get('section_range', '') + '节（参考）') if item.get('time_source') == 'section' else 'PDF 原时间')}</td>"
                                f"<td>{html.escape(item.get('location', ''))}</td>"
                                f"<td>{html.escape(item.get('teacher', ''))}</td>"
                                f"<td>{item.get('start_week', 1)}—{item.get('end_week', 53)}周 "
                                f"{ {'all': '每周', 'odd': '单周', 'even': '双周'}.get(item.get('week_type', 'all'), '每周') }</td>"
                                f"<td>{item.get('source_page', '')}</td>"
                                "</tr>"
                                for item in entries[:100]
                            )
                            st.markdown(
                                "<div class='schedule-preview-wrap'><table class='schedule-preview-table'>"
                                "<thead><tr><th>课程</th><th>星期</th><th>开始</th><th>结束</th>"
                                "<th>节次／依据</th><th>地点</th><th>教师</th><th>周次</th><th>PDF 页码</th></tr></thead>"
                                f"<tbody>{preview_rows}</tbody></table></div>",
                                unsafe_allow_html=True,
                            )
                            if len(entries) > 100:
                                st.caption("预览仅显示前 100 条，确认后会导入全部已识别课程。")
                        if preview.get("errors"):
                            with st.expander(f"查看 {len(preview['errors'])} 条未识别记录"):
                                for error in preview["errors"]:
                                    st.warning(error)
                        if st.button(
                            "确认导入以上课程", key="confirm_schedule_pdf",
                            disabled=not entries, use_container_width=True,
                        ):
                            imported = rag.import_schedule_entries(user, entries, source="PDF")
                            st.session_state.schedule_import_notice = imported
                            st.session_state.pop("schedule_pdf_preview", None)
                            st.rerun()
                elif schedule_file:
                    if st.button("导入 CSV 课表", type="primary", use_container_width=True):
                        try:
                            imported = rag.import_schedule_csv(user, schedule_file.getvalue())
                            st.session_state.schedule_import_notice = imported
                            st.rerun()
                        except Exception as exc:
                            st.error(f"导入失败：{exc}")
        if all_schedule:
            entry_map = {item["id"]: item for item in all_schedule}
            selected_entry_id = st.selectbox(
                "选择要编辑或删除的课程", list(entry_map),
                format_func=lambda item_id: (
                    f"{entry_map[item_id]['course_name']} · "
                    f"星期{'一二三四五六日'[entry_map[item_id]['weekday'] - 1]} "
                    f"{entry_map[item_id]['start_time']} · "
                    f"{entry_map[item_id].get('start_week', 1)}—{entry_map[item_id].get('end_week', 53)}周"
                ),
                key="schedule_action_entry",
            )
            selected_entry = entry_map[selected_entry_id]
            with st.expander("编辑所选课程"):
                st.caption("可以修改课程、时间、地点、教师和周次。手动保存后，以这里填写的具体时间为准。")
                with st.form(f"edit_schedule_{selected_entry_id}"):
                    edit_name = st.text_input("课程名称", value=selected_entry["course_name"], max_chars=100)
                    edit_day = st.selectbox(
                        "星期", list(range(1, 8)), index=int(selected_entry["weekday"]) - 1,
                        format_func=lambda value: "星期" + "一二三四五六日"[value - 1],
                    )
                    edit_time_cols = st.columns(2)
                    edit_start = edit_time_cols[0].time_input(
                        "开始时间", value=datetime.strptime(selected_entry["start_time"], "%H:%M").time()
                    )
                    edit_end = edit_time_cols[1].time_input(
                        "结束时间", value=datetime.strptime(selected_entry["end_time"], "%H:%M").time()
                    )
                    edit_location = st.text_input("上课地点", value=selected_entry["location"], max_chars=100)
                    edit_teacher = st.text_input("教师", value=selected_entry["teacher"], max_chars=60)
                    edit_week_cols = st.columns(3)
                    edit_start_week = edit_week_cols[0].number_input(
                        "开始周", 1, 53, int(selected_entry.get("start_week", 1))
                    )
                    edit_end_week = edit_week_cols[1].number_input(
                        "结束周", 1, 53, int(selected_entry.get("end_week", 53))
                    )
                    current_week_type = selected_entry.get("week_type", "all")
                    edit_week_type = edit_week_cols[2].selectbox(
                        "上课周", ["每周", "单周", "双周"],
                        index={"all": 0, "odd": 1, "even": 2}.get(current_week_type, 0),
                    )
                    edit_semester = st.text_input(
                        "学期", value=selected_entry.get("semester", ""), max_chars=40
                    )
                    if st.form_submit_button("保存课程修改", type="primary"):
                        try:
                            rag.update_schedule_entry(
                                user, selected_entry_id, edit_name, edit_day,
                                edit_start.strftime("%H:%M"), edit_end.strftime("%H:%M"),
                                edit_location, edit_teacher, edit_start_week, edit_end_week,
                                {"每周": "all", "单周": "odd", "双周": "even"}[edit_week_type],
                                edit_semester,
                            )
                            st.success("课程已更新。")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"修改失败：{exc}")
            action_cols = st.columns(2)
            if action_cols[0].button("删除所选课程", use_container_width=True):
                rag.delete_schedule_entry(user, selected_entry_id)
                st.rerun()
            with action_cols[1]:
                with st.expander("清空课表并重新导入"):
                    st.warning("会删除当前账户的全部课程，其他账户和文档不受影响。")
                    confirm_clear = st.checkbox("我确认清空自己的全部课程", key="confirm_clear_schedule")
                    if st.button(
                        "确认清空全部课程", disabled=not confirm_clear, use_container_width=True
                    ):
                        removed = rag.clear_schedule(user)
                        st.session_state.pop("schedule_pdf_preview", None)
                        st.session_state.schedule_clear_notice = (
                            f"已清空 {removed} 条课程，现在可以重新导入。"
                        )
                        st.rerun()
        st.markdown("**查询空教室参考**")
        with st.form("free_room_form"):
            room_cols = st.columns(3)
            room_weekday = room_cols[0].selectbox("星期", list(range(1, 8)), format_func=lambda value: "星期" + "一二三四五六日"[value - 1], key="room_weekday")
            room_start = room_cols[1].time_input("开始", value=time(10, 0))
            room_end = room_cols[2].time_input("结束", value=time(11, 0))
            if st.form_submit_button("查询"):
                st.session_state.free_rooms = rag.find_free_rooms(
                    user, room_weekday, room_start.strftime("%H:%M"), room_end.strftime("%H:%M")
                )
        free_rooms = st.session_state.get("free_rooms")
        if free_rooms:
            if free_rooms["free"]:
                st.success("课表中未显示占用的教室：" + "、".join(free_rooms["free"]))
            else:
                st.warning("已知教室在该时段都有课程记录，或尚未录入教室信息。")
            st.caption("已占用：" + ("、".join(free_rooms["occupied"]) or "无"))

    if service_page == "活动报名":
        st.subheader("校园活动报名")
        st.caption("管理员发布竞赛、讲座和志愿活动；学生可在线报名、取消报名并查看人数。报名记录保存在本机。")
        if user["role"] == "admin":
            with st.expander("管理员发布活动"):
                with st.form("activity_form"):
                    activity_title = st.text_input("活动名称", max_chars=100)
                    activity_description = st.text_area("活动介绍", max_chars=3000)
                    activity_location = st.text_input("活动地点", max_chars=120)
                    activity_date = st.date_input("活动日期", value=date.today())
                    time_cols = st.columns(2)
                    activity_start_time = time_cols[0].time_input("开始时间", value=time(14, 0))
                    activity_end_time = time_cols[1].time_input("结束时间", value=time(16, 0))
                    activity_capacity = st.number_input("人数上限", min_value=1, max_value=100000, value=50)
                    if st.form_submit_button("发布活动", type="primary"):
                        try:
                            rag.create_activity(
                                user, activity_title, activity_description, activity_location,
                                datetime.combine(activity_date, activity_start_time).isoformat(timespec="minutes"),
                                datetime.combine(activity_date, activity_end_time).isoformat(timespec="minutes"),
                                activity_capacity,
                            )
                            st.success("活动已发布。")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"发布失败：{exc}")
        activities = rag.get_activities(user)
        if not activities:
            st.info("暂无活动。")
        for activity in activities:
            with st.container(border=True):
                st.markdown(f"**{activity['title']}**")
                st.caption(
                    f"{activity['starts_at']} 至 {activity['ends_at']} · {activity['location']} · "
                    f"已报名 {activity['enrolled_count']}/{activity['capacity']}"
                    + (" · 已取消" if activity["status"] == "cancelled" else "")
                )
                st.text(activity["description"])
                cols = st.columns(3)
                if activity["enrolled"]:
                    if cols[0].button("取消报名", key=f"cancel_activity_{activity['id']}"):
                        try:
                            rag.cancel_activity_enrollment(user, activity["id"])
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                elif cols[0].button(
                    "立即报名", key=f"enroll_activity_{activity['id']}", disabled=activity["status"] != "published"
                ):
                    try:
                        rag.enroll_activity(user, activity["id"])
                        st.success("报名成功。")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                if user["role"] == "admin":
                    if cols[1].button(
                        "恢复活动" if activity["status"] == "cancelled" else "取消活动",
                        key=f"activity_status_{activity['id']}",
                    ):
                        rag.set_activity_status(user, activity["id"], "published" if activity["status"] == "cancelled" else "cancelled")
                        st.rerun()
                    with st.expander("查看报名名单"):
                        participants = rag.get_activity_participants(user, activity["id"])
                        st.dataframe(participants, use_container_width=True, hide_index=True)

    if service_page == "学业规划":
        st.subheader("本地 AI 学业规划表")
        st.caption("输入年级、专业和目标，本地模型会生成阶段规划。能查到本校资料时会优先参考；查不到时只提供通用建议，不把建议写成学校硬性规定。")
        with st.form("study_plan_form"):
            plan_cols = st.columns(3)
            plan_grade = plan_cols[0].text_input("年级", placeholder="例如：大二")
            plan_major = plan_cols[1].text_input("专业", placeholder="例如：网络空间安全")
            plan_goal = plan_cols[2].selectbox("目标", ["就业", "考研", "保研准备", "竞赛", "综合提升"])
            if st.form_submit_button("生成我的规划", type="primary"):
                try:
                    with st.spinner("本地模型正在整理规划，较慢电脑可能需要等待……"):
                        st.session_state.latest_study_plan = rag.generate_study_plan(
                            user, plan_grade, plan_major, plan_goal
                        )
                except Exception as exc:
                    st.error(f"生成失败：{exc}")
        latest_plan = st.session_state.get("latest_study_plan")
        if latest_plan:
            if latest_plan.get("notice"):
                st.warning(latest_plan["notice"])
            render_study_plan(latest_plan["plan"])
            if latest_plan.get("sources"):
                with st.expander("查看参考的本校资料"):
                    for source in latest_plan["sources"]:
                        st.caption(f"{source['source']} · " + (f"第 {source['page']} 页" if source.get("page") else "全文"))
                        st.text(source["evidence"])
        with st.expander("我的历史规划"):
            plans = rag.get_study_plans(user)
            if not plans:
                st.caption("还没有历史规划。")
            for plan in plans:
                st.markdown(f"**#{plan['id']} · {plan['grade']} · {plan['major']} · {plan['goal']}**")
                st.caption(f"{plan['created_at']} · {plan['model']}")
                st.text(plan["plan_text"])

if page == "我的知识库":
    st.subheader("当前角色可访问的文档")
    render_documents()

if page == "知识治理":
    st.subheader("文档摘要、时间与新旧规定核对")
    st.caption(
        "这里帮助你快速读懂一份制度：查看主要内容、关键点、文中日期，以及和其他文件可能不一致的地方。"
        "“待核对”只表示两处原文值得比较，不代表系统已经判定哪份文件无效。"
    )
    governance_docs = rag.list_documents(user)
    if not governance_docs:
        st.info("当前权限范围内还没有文档。")
    else:
        governance_map = {doc["doc_id"]: doc for doc in governance_docs}
        governance_id = st.selectbox(
            "选择文档", list(governance_map),
            format_func=lambda key: (
                f"{governance_map[key]['group_name']}/{governance_map[key]['filename']}"
                f"（{governance_map[key].get('status', '现行有效')}）"
            ),
            key="governance_document",
        )
        governance_doc = governance_map[governance_id]
        if user["role"] == "admin":
            governance_ocr = st.checkbox(
                "分析扫描版 PDF 时识别页面文字", key="governance_ocr",
                help="仅文字过少的 PDF 页面需要开启，处理时间会更长。",
            )
            if st.button("分析或重新分析这份文档", type="primary"):
                try:
                    with st.spinner("本地模型正在写摘要，同时检查全文日期和新旧规定……"):
                        rag.analyze_document_governance(
                            user, governance_doc["group"], governance_doc["filename"],
                            use_ocr=governance_ocr,
                        )
                    st.success("分析完成，结果已保存在本机。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"分析失败：{exc}")
        else:
            st.caption("分析结果由管理员生成；你只能查看自己有权访问的文档。")
        governance = rag.get_document_governance(
            user, governance_doc["group"], governance_doc["filename"]
        )
        if not governance:
            st.info("这份文档还没有分析结果，请由管理员点击“分析或重新分析这份文档”。")
        else:
            st.caption(f"上次分析：{governance['analyzed_at']}。文档更新后需要重新分析。")
            if governance.get("analysis_notice"):
                st.warning(governance["analysis_notice"])
            st.markdown("**这份文件主要讲什么**")
            st.write(governance["summary"])
            st.markdown("**关键点**")
            for index, point in enumerate(governance.get("key_points", []), start=1):
                st.write(f"{index}. {point}")
            st.markdown("**文中识别到的时间**")
            dates = governance.get("detected_dates", [])
            if dates:
                st.dataframe([
                    {
                        "时间": item["date"], "所在页": item.get("page") or "全文",
                        "原文上下文": item["context"],
                    } for item in dates
                ], use_container_width=True, hide_index=True)
            else:
                st.caption("没有识别到明确日期，仍请自行检查“日前”“期限内”等相对时间。")
            st.markdown("**新旧规定待核对项**")
            conflicts = governance.get("conflicts", [])
            if not conflicts:
                st.success("本次未发现附有双方原文的明显疑点；这不等于完成正式合规审查。")
            for index, conflict in enumerate(conflicts, start=1):
                with st.expander(f"待核对 {index}：{conflict['reason']}"):
                    left, right = st.columns(2)
                    current_page = f"第 {conflict['current_page']} 页" if conflict.get("current_page") else "全文"
                    other_page = f"第 {conflict['other_page']} 页" if conflict.get("other_page") else "全文"
                    with left:
                        st.markdown(f"**当前文件 · {current_page}**")
                        st.text(conflict.get("current_excerpt") or "请打开当前文件核对版本状态。")
                        if conflict.get("current_values"):
                            st.caption("当前数字：" + "、".join(conflict["current_values"]))
                    with right:
                        st.markdown(
                            f"**{conflict['other_group_name']}/{conflict['other_filename']} · {other_page}**"
                        )
                        st.text(conflict.get("other_excerpt") or "请打开另一份文件核对版本状态。")
                        if conflict.get("other_values"):
                            st.caption("另一份数字：" + "、".join(conflict["other_values"]))

if page == "数据看板":
    st.subheader("问答与知识库使用情况")
    st.caption(
        "使用说明：查看大家常问什么、哪些问题找不到资料，以及哪些文件最常被引用。"
        "看板不显示其他用户名；普通账户只能看到自己的汇总，管理员才能看到全校汇总。"
    )
    dashboard_days = st.selectbox("统计范围", [7, 30, 90], index=1, format_func=lambda value: f"最近 {value} 天")
    if st.button("刷新看板") or "dashboard_data" not in st.session_state:
        try:
            st.session_state.dashboard_data = rag.get_operations_dashboard(user, dashboard_days)
        except Exception as exc:
            st.error(f"看板加载失败：{exc}")
    dashboard = st.session_state.get("dashboard_data")
    if dashboard:
        st.caption(f"数据范围：{dashboard['scope']} · 最近 {dashboard['days']} 天")
        cols = st.columns(5)
        cols[0].metric("提问总数", dashboard["total_questions"])
        cols[1].metric("找到资料", dashboard["answered"])
        cols[2].metric("找到资料比例", f"{dashboard['answer_rate'] * 100:.1f}%")
        cols[3].metric("平均参考可信度", f"{dashboard['average_trust']}/100")
        average_latency = dashboard.get("average_latency_ms", 0)
        cols[4].metric(
            "平均实际耗时", f"{average_latency / 1000:.2f} 秒" if average_latency else "暂无记录"
        )
        st.caption(
            f"耗时统计覆盖 {dashboard.get('latency_count', 0)} 条新记录；旧版问答没有耗时数据，不参与平均。"
        )
        left, right = st.columns(2)
        with left:
            st.markdown("**热门问题 TOP10**")
            if dashboard["hot_questions"]:
                st.dataframe([
                    {"问题": item["question"], "提问次数": item["count"]}
                    for item in dashboard["hot_questions"]
                ], use_container_width=True, hide_index=True)
            else:
                st.info("所选时间范围内还没有提问。")
        with right:
            st.markdown("**没有找到资料的问题**")
            if dashboard["unanswered_questions"]:
                st.dataframe([
                    {"时间": item["created_at"], "问题": item["question"]}
                    for item in dashboard["unanswered_questions"]
                ], use_container_width=True, hide_index=True)
                st.caption("可据此补充缺失制度；模糊问题也可能因为没有资料而被计入。")
            else:
                st.success("所选时间范围内没有无资料问题。")
        st.markdown("**每天提问数量**")
        st.bar_chart(dashboard["daily_counts"], x="date", y="count")
        with st.expander("查看一天中的提问时间分布"):
            st.bar_chart(dashboard["hourly_counts"], x="hour", y="count")
        st.markdown("**最常被引用的来源**")
        if dashboard["source_usage"]:
            st.dataframe([
                {"文档": item["source"], "分组": item["group_name"], "被问答使用次数": item["count"]}
                for item in dashboard["source_usage"]
            ], use_container_width=True, hide_index=True)
        else:
            st.info("还没有来源使用记录。")

if page == "评测中心":
    st.subheader("检索问答评测中心")
    st.caption(
        "这是给校务通自己做的小测验：你先告诉它正确答案在哪份文件、哪一页，"
        "再让它自己找一遍，看看找得准不准。这里只检查找资料的能力，不评价回答写得好不好。"
    )
    with st.expander("功能说明与填写方法"):
        st.markdown(
            "1. 填一个问题，再填正确答案所在的完整文件名和页码；不知道页码可以留空。\n"
            "2. 正常问题保持“应当找到资料”勾选；如果想测试没有资料时会不会乱找，就取消勾选。\n"
            "3. 点击“开始评测”。换一种找资料的方式再测一次，就能比较哪种方式更适合你的文档。\n\n"
            "**结果怎么看：**“第 1 条找对率”越高，说明正确答案越常排在第一位；"
            "“前 3 条找到率”越高，说明正确答案越常出现在前三条；“正确来源排名得分”越接近 1，"
            "说明正确答案整体排得越靠前；“没有资料时不乱答率”越高越好。"
        )
    default_cases = st.session_state.setdefault("eval_cases", [
        {"question": "", "expected_source": "", "expected_page": None, "should_answer": True},
        {"question": "", "expected_source": "", "expected_page": None, "should_answer": True},
        {"question": "", "expected_source": "", "expected_page": None, "should_answer": False},
    ])
    edited_cases = st.data_editor(
        default_cases,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "question": st.column_config.TextColumn("问题", required=True),
            "expected_source": st.column_config.TextColumn("期望文件名（可空）"),
            "expected_page": st.column_config.NumberColumn("期望页码（可空）", min_value=1),
            "should_answer": st.column_config.CheckboxColumn("应当找到资料", default=True),
        },
        key="evaluation_editor",
    )
    cases = (
        edited_cases.to_dict("records") if hasattr(edited_cases, "to_dict")
        else list(edited_cases)
    )
    current_mode_name = {
        "hybrid": "两种方式一起找", "vector": "按意思找", "bm25": "按关键词找"
    }[retrieval_mode]
    st.info(
        f"本次会使用左侧选择的“{current_mode_name}”，"
        f"精细排序{'已开启' if use_rerank else '未开启'}。"
        "如果这道题在知识库中没有答案，请取消“应当找到资料”。"
    )
    if st.button("开始评测", type="primary"):
        try:
            with st.spinner("正在逐条执行真实检索……"):
                st.session_state.last_evaluation = rag.evaluate_retrieval(
                    user, cases, retrieval_mode=retrieval_mode, use_rerank=use_rerank
                )
        except Exception as exc:
            st.error(f"评测失败：{exc}")

    evaluation = st.session_state.get("last_evaluation")
    if evaluation:
        st.markdown(f"**本次评测 #{evaluation['run_id']}**")
        cols = st.columns(5)
        cols[0].metric("第 1 条找对率", f"{evaluation['recall_1'] * 100:.1f}%")
        cols[1].metric("前 3 条找到率", f"{evaluation['recall_3'] * 100:.1f}%")
        cols[2].metric("正确来源排名得分", f"{evaluation['mrr']:.3f}")
        refusal_text = (
            f"{evaluation['refusal_accuracy'] * 100:.1f}%"
            if evaluation["refusal_case_count"] else "—"
        )
        cols[3].metric("没有资料时不乱答率", refusal_text)
        cols[4].metric("平均检索耗时", f"{evaluation['avg_latency_ms']:.0f} ms")
        detail_rows = [{
            "问题": item["question"],
            "期望来源": item["expected_source"] or "无资料问题",
            "命中排名": item["rank"] or "未命中",
            "返回来源": "；".join(
                f"{s['source']} 第{s['page']}页" if s.get("page") else s["source"]
                for s in item["sources"]
            ) or "无",
            "耗时（ms）": item["latency_ms"],
            "异常": item["error"],
        } for item in evaluation["details"]]
        st.dataframe(detail_rows, use_container_width=True, hide_index=True)

    previous_runs = rag.get_evaluation_runs(user, limit=20)
    if previous_runs:
        with st.expander("查看历史评测"):
            selected_run = st.selectbox(
                "选择评测批次", previous_runs,
                format_func=lambda run: (
                    f"#{run['id']} · {run['created_at']} · "
                    f"前 3 条找到率 {run['recall_3'] * 100:.1f}%"
                ),
            )
            st.write({
                "问题数": selected_run["case_count"],
                "第 1 条找对率": f"{selected_run['recall_1'] * 100:.1f}%",
                "前 3 条找到率": f"{selected_run['recall_3'] * 100:.1f}%",
                "正确来源排名得分": f"{selected_run['mrr']:.3f}",
                "平均耗时（ms）": round(selected_run["avg_latency_ms"], 1),
            })

if page == "版本对比":
    st.subheader("同一问题的回答版本对比")
    all_records = rag.get_qa_records(user, limit=200)
    questions = sorted({record["question"] for record in all_records})
    if not questions:
        st.info("暂无可对比的问答版本。")
    else:
        selected_question = st.selectbox("选择历史问题", questions)
        versions = list(reversed([
            record for record in all_records if record["question"] == selected_question
        ]))
        for version in versions:
            title = (
                f"#{version['id']} · {version['created_at']} · "
                f"{version.get('model') or '旧版'} · "
                f"{version.get('retrieval_mode', 'hybrid')} · "
                f"置信度 {version.get('confidence', 0)}"
            )
            with st.expander(title, expanded=len(versions) == 1):
                st.text(plain_answer(version["answer"]))
                st.caption(
                    "Rerank：" + ("开启" if version.get("rerank_used") else "关闭")
                    + "；反馈：" + (version.get("feedback") or "未反馈")
                )

if user["role"] == "admin":
    if page == "文档管理":
        st.subheader("批量导入")
        group_labels = {name: key for key, name in GROUPS.items()}
        target_group = group_labels[
            st.selectbox("上传到权限分组", list(group_labels.keys()))
        ]
        enable_ocr = st.checkbox(
            "识别扫描版 PDF 中的文字（OCR）",
            value=False,
            help="仅识别文字过少的页面；需安装 pymupdf、rapidocr_onnxruntime、numpy 和 pillow。",
        )
        st.caption(
            "使用说明：能正常选中文字的 PDF 不用开启。如果文件像照片一样、无法选中文字，"
            "勾选后再导入，系统会自动读出页面内容并保留页码。导入后请抽查数字、日期和表格是否识别正确。"
        )
        uploads = st.file_uploader(
            "可一次选择多个 PDF / TXT / DOCX",
            type=["pdf", "txt", "docx"],
            accept_multiple_files=True,
        )
        st.caption("支持 Word DOCX 的正文和表格；旧版 DOC 请先另存为 DOCX。单份文件最大 50 MB。")
        with st.expander("设置本批文档的版本信息"):
            st.caption(
                "用于区分不同学年的制度。填写学年度和日期，现行文件保持勾选；"
                "上传新版后，请将旧版设为历史版本。日期格式为 YYYY-MM-DD，也可留空。"
            )
            academic_year = st.text_input("学年度", placeholder="例如：2025—2026 学年")
            date_cols = st.columns(2)
            effective_date = date_cols[0].text_input("生效日期", placeholder="YYYY-MM-DD")
            expiry_date = date_cols[1].text_input("失效日期", placeholder="YYYY-MM-DD")
            is_current = st.checkbox("作为现行有效版本", value=True)
            replaces = st.text_input("替代的旧文档", placeholder="可填写旧文件名，也可留空")
        blocked_names: set[str] = set()
        if uploads:
            existing_names = {
                doc["filename"] for doc in rag.list_documents(user)
                if doc["group"] == target_group
            }
            duplicate_names = [upload.name for upload in uploads if upload.name in existing_names]
            if duplicate_names:
                st.warning(
                    "以下同名文件会被覆盖并重新整理：" + "、".join(duplicate_names)
                    + "。如需保留旧版，请先修改文件名。"
                )
            st.markdown("**上传预检**")
            cache = st.session_state.setdefault("preflight_cache", {})
            for upload in uploads:
                content = upload.getvalue()
                digest = hashlib.sha256(
                    target_group.encode("utf-8") + upload.name.encode("utf-8") + content
                    + str(enable_ocr).encode("ascii")
                ).hexdigest()
                if digest not in cache:
                    cache[digest] = rag.preflight_document(
                        user, target_group, upload.name, content, allow_ocr=enable_ocr
                    )
                check = cache[digest]
                if not check["ok"]:
                    blocked_names.add(upload.name)
                    st.error(f"{upload.name}：{check['warning']}（只跳过此文件）")
                elif check["warning"]:
                    st.warning(f"{upload.name}：{check['warning']}（仍可继续导入）")
                else:
                    st.success(f"{upload.name}：预检通过，提取到 {check['char_count']} 个字符")

        def run_import_tasks(items: list[dict]) -> None:
            task_rows = []
            failed_items = []
            for item in items:
                name = item["name"]
                try:
                    with st.status(f"{name}：正在入库", expanded=True) as task_status:
                        st.write("1. 保存原文件")
                        filename = rag.save_document(
                            user, target_group, name, item["content"]
                        )
                        st.write("2. 保存版本与有效期")
                        rag.set_document_metadata(
                            user, target_group, filename, academic_year,
                            effective_date, expiry_date, is_current, replaces,
                        )
                        st.write("3. 读取内容并整理成可搜索的资料")
                        count = rag.index_document(
                            user, target_group, filename, use_ocr=enable_ocr
                        )
                        task_status.update(
                            label=f"{filename}：完成，写入 {count} 个切片",
                            state="complete",
                        )
                    task_rows.append({"文件": filename, "状态": "完成", "详情": f"{count} 个切片"})
                except Exception as exc:
                    task_rows.append({"文件": name, "状态": "失败", "详情": str(exc)})
                    failed_items.append(item)
                    st.error(f"{name} 导入失败：{exc}")
            st.session_state.import_tasks = task_rows
            st.session_state.failed_imports = failed_items

        st.caption(
            "导入说明：点击后可以看到每份文件的处理进度，包括保存文件、记录版本、读取内容和整理成可搜索的资料。"
            "某一份失败不会影响其他文件；处理好失败原因后，点击“仅重试失败文件”即可。"
            "失败文件只在这次打开页面期间保留，重启程序后需要重新选择。"
        )
        if st.button("保存并逐篇向量化", type="primary"):
            ready_uploads = [
                upload for upload in (uploads or []) if upload.name not in blocked_names
            ]
            if not uploads:
                st.warning("请先选择文件。")
            elif not ready_uploads:
                st.warning("当前文件都未通过预检，请先处理文件问题。")
            else:
                run_import_tasks([
                    {"name": upload.name, "content": upload.getvalue()}
                    for upload in ready_uploads
                ])

        if st.session_state.get("import_tasks"):
            st.markdown("**最近一次入库任务**")
            st.dataframe(
                st.session_state.import_tasks, use_container_width=True, hide_index=True
            )
        failed_imports = st.session_state.get("failed_imports") or []
        if failed_imports:
            st.warning(f"有 {len(failed_imports)} 个文件失败，原文件内容仍保留在本次会话中。")
            if st.button("仅重试失败文件"):
                run_import_tasks(failed_imports)

        st.divider()
        st.subheader("单文档管理")
        docs = rag.list_documents(user)
        if not docs:
            st.info("暂无文档。")
        else:
            doc_map = {
                d["doc_id"]: d for d in docs
            }
            selected_id = st.selectbox(
                "选择要单独操作的文档",
                list(doc_map.keys()),
                format_func=lambda key: (
                    f"{doc_map[key]['group_name']}/{doc_map[key]['filename']}"
                ),
            )
            selected = doc_map[selected_id]
            with st.expander("编辑所选文档的版本与有效期"):
                st.caption(
                    "修改后，回答会优先参考现在正在使用的文件，并在旧文件来源旁显示提醒。"
                    "只修改这些日期和状态即可，不需要重新处理文档内容。"
                )
                with st.form(f"metadata_{selected_id}"): 
                    edit_year = st.text_input(
                        "学年度", value=selected.get("academic_year", "")
                    )
                    edit_dates = st.columns(2)
                    edit_effective = edit_dates[0].text_input(
                        "生效日期", value=selected.get("effective_date", "")
                    )
                    edit_expiry = edit_dates[1].text_input(
                        "失效日期", value=selected.get("expiry_date", "")
                    )
                    edit_current = st.checkbox(
                        "现行有效", value=selected.get("is_current", True)
                    )
                    edit_replaces = st.text_input(
                        "替代的旧文档", value=selected.get("replaces", "")
                    )
                    if st.form_submit_button("保存版本信息"):
                        try:
                            rag.set_document_metadata(
                                user, selected["group"], selected["filename"],
                                edit_year, edit_effective, edit_expiry,
                                edit_current, edit_replaces,
                            )
                            st.success("版本信息已保存。")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"保存失败：{exc}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("仅重新向量化此文档", use_container_width=True):
                    try:
                        with st.spinner("正在更新当前文档的向量……"):
                            count = rag.index_document(
                                user, selected["group"], selected["filename"], use_ocr=enable_ocr
                            )
                        st.success(f"已完成，当前文档共 {count} 个切片。")
                    except Exception as exc:
                        st.error(f"重建失败：{exc}")
            with col2:
                confirm = st.checkbox("确认同时删除原文件和对应向量")
                if st.button("删除此文档", use_container_width=True, disabled=not confirm):
                    try:
                        rag.delete_document(user, selected["group"], selected["filename"])
                        st.success("文档及其向量已删除。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"删除失败：{exc}")

    if page == "系统维护":
        st.subheader("本机数据备份与恢复")
        st.caption("完整备份包含数据库、原始文档和本地向量库。备份含账户密码哈希和私人内容，请妥善保存，不要上传到公开仓库。")
        if st.button("生成完整备份", type="primary"):
            try:
                with st.spinner("正在检查数据库并打包本机数据，文件较多时需要等待……"):
                    st.session_state.system_backup = rag.create_full_backup(user)
                st.success("备份已生成，请下载并保存到安全位置。")
            except Exception as exc:
                st.error(f"备份失败：{exc}")
        if st.session_state.get("system_backup"):
            st.download_button(
                "下载完整备份 ZIP", data=st.session_state.system_backup,
                file_name=f"校务通_完整备份_{datetime.now():%Y%m%d_%H%M%S}.zip",
                mime="application/zip",
            )
        with st.expander("从完整备份恢复（会替换当前数据）"):
            st.warning("恢复会替换当前数据库、文档和向量库。系统会检查路径安全和数据库完整性，失败时尝试回滚；仍建议先下载一份当前备份。")
            restore_file = st.file_uploader("选择校务通完整备份 ZIP", type=["zip"], key="restore_backup_file")
            confirm_restore = st.checkbox("我确认用备份替换当前本机数据", key="confirm_restore_backup")
            if st.button(
                "开始恢复", disabled=not restore_file or not confirm_restore,
                key="start_restore_backup",
            ):
                try:
                    with st.spinner("正在校验并恢复备份……"):
                        rag.restore_full_backup(user, restore_file.getvalue())
                    get_rag.clear()
                    st.session_state.clear()
                    st.session_state.login_notice = "备份已恢复，请使用备份中的账户和新密码重新登录。"
                    st.rerun()
                except Exception as exc:
                    st.error(f"恢复失败，现有数据已保留或已回滚：{exc}")

        st.divider()
        st.subheader("演示数据")
        st.caption("只生成名称中带“【演示】”的课程、帖子和活动，不生成虚假的问答、使用量或评测成绩。可以随时单独清除，不影响其他数据。")
        demo_status = rag.get_demo_data_status(user)
        if demo_status["count"]:
            st.warning(
                f"当前有 {demo_status['count']} 条演示数据："
                + "、".join(f"{item['name']} {item['count']} 条" for item in demo_status["items"])
            )
        else:
            st.info("当前没有由系统创建的演示数据。")
        demo_cols = st.columns(2)
        if demo_cols[0].button(
            "添加演示数据", use_container_width=True, disabled=bool(demo_status["count"])
        ):
            try:
                created = rag.create_demo_data(user)
                st.success(f"已添加 {created['count']} 条带“【演示】”标记的内容。")
                st.rerun()
            except Exception as exc:
                st.error(f"添加失败：{exc}")
        confirm_demo_clear = st.checkbox("确认只清除演示数据", key="confirm_demo_clear")
        if demo_cols[1].button(
            "一键清除演示数据", use_container_width=True,
            disabled=not demo_status["count"] or not confirm_demo_clear,
        ):
            try:
                removed = rag.clear_demo_data(user)
                st.success(f"已清除 {removed} 条演示数据。")
                st.rerun()
            except Exception as exc:
                st.error(f"清除失败：{exc}")

    if page == "自动诊断":
        st.subheader("权限与检索自动诊断")
        st.caption("检查不会删除你的文件或搜索内容；测试学生能否打开无权限文件时，会留下一条检查记录。")
        with st.expander("功能说明与结果解读"):
            st.markdown(
                "点击“运行全部诊断”，系统会自动检查：不同身份能看哪些文件、学生是否无法打开无权限文件、"
                "文件是否放错分组、文件删除后是否还能被搜到，以及两种找资料的方式是否正常。\n\n"
                "- **通过**：这一项没有发现异常。\n"
                "- **失败**：按照后面的说明检查文件、权限或模型服务。\n"
                "- **跳过**：目前没有足够文件做这项测试，例如没有管理员文件时，就不能测试学生是否会被拦截。\n\n"
                "这些检查用来帮助发现问题，不能保证系统完全没有其他问题。"
            )
        if st.button("运行全部诊断", type="primary"): 
            with st.spinner("正在执行权限、索引一致性和双路检索检查……"):
                st.session_state.diagnostic_checks = rag.run_diagnostics(user)
        checks = st.session_state.get("diagnostic_checks") or []
        if checks:
            passed = sum(item["结果"] == "通过" for item in checks)
            failed = sum(item["结果"] == "失败" for item in checks)
            skipped = sum(item["结果"] == "跳过" for item in checks)
            cols = st.columns(3)
            cols[0].metric("通过", passed)
            cols[1].metric("失败", failed)
            cols[2].metric("跳过", skipped)
            st.dataframe(checks, use_container_width=True, hide_index=True)
            if failed:
                st.error("存在失败项，请根据说明检查权限或索引。")
            else:
                st.success("未发现失败项。")

    if page == "审计日志":
        st.subheader("角色访问审计日志")
        role_filter_label = st.selectbox(
            "按角色筛选", ["全部角色", "学生", "辅导员", "管理员"]
        )
        label_to_role = {None: None, "全部角色": None, **{v: k for k, v in ROLE_NAMES.items()}}
        if st.button("生成脱敏审计日志 CSV"):
            try:
                st.session_state.audit_csv = rag.export_audit_csv(user)
                st.success("已生成：用户与敏感信息脱敏，并嵌入当前管理员水印。")
            except Exception as exc:
                st.error(f"审计日志导出失败：{exc}")
        if st.session_state.get("audit_csv"):
            st.download_button(
                "下载审计日志 CSV",
                data=st.session_state.audit_csv,
                file_name="校务通_脱敏审计日志.csv",
                mime="text/csv",
            )

        logs = rag.get_audit_logs(user, role=label_to_role[role_filter_label], limit=300)
        if logs:
            rows = [
                {
                    "时间": row["created_at"],
                    "用户名": row["username"],
                    "角色": role_text(row["role"]),
                    "操作": row["action"],
                    "资源": row["resource"],
                    "详情": row["detail"],
                }
                for row in logs
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("暂无审计记录。")