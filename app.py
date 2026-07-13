"""
Standalone data-exploration sandbox.

A throwaway Streamlit app for brainstorming what analytics are POSSIBLE from a
sample dataset. It is intentionally self-contained: it reads two CSVs from
./sample_data and does not import from or depend on any other application.

Run:  streamlit run app.py
"""
import ast
import json
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# --------------------------------------------------------------------------- #
# Config & style
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="Data Brainstorming Sandbox", layout="wide")

DATA_DIR = Path(__file__).parent / "sample_data"
TASKS_FILE = DATA_DIR / "tasks_table.csv"
GOLD_FILE = DATA_DIR / "goldtasks_table.csv"

TEMPLATE = "plotly_white"
# Muted, consistent palette.
C_CONF = "#6E8FB8"     # AI confidence (muted blue)
C_ACC = "#7FB09B"      # accuracy (muted green)
C_WARN = "#C98A8A"     # errors / disagreement (muted red)
C_NEUTRAL = "#9AA3B2"  # neutral grey
PALETTE = ["#6E8FB8", "#7FB09B", "#C9A88E", "#B98EA7", "#8E9DC9", "#A3B899",
           "#C98A8A", "#9AA3B2"]

CATEGORY_DIMS = ["type", "topic", "complexity"]


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _parse_llm_info(raw):
    """llm_info is a JSON string; return its dict (empty on failure)."""
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def _parse_votes(raw):
    """user_answers is a Python-list literal string; return a clean list."""
    try:
        val = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    if isinstance(val, (list, tuple)):
        return [v for v in val]
    return []


def _parse_choices(raw):
    """choices is a Python-dict literal string; return a dict."""
    try:
        val = ast.literal_eval(raw)
        return val if isinstance(val, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def _majority(votes):
    """Most common vote; None if empty. Ties resolve to first-most-common."""
    if not votes:
        return None
    return Counter(votes).most_common(1)[0][0]


# --------------------------------------------------------------------------- #
# Data loading (cached)
# --------------------------------------------------------------------------- #
def _is_split(votes):
    return len(votes) >= 2 and len(set(votes)) > 1


@st.cache_data(show_spinner=False)
def load_data():
    tasks = pd.read_csv(TASKS_FILE)
    gold = pd.read_csv(GOLD_FILE)

    # --- tasks_table: parse the trap columns ---
    info = tasks["llm_info"].apply(_parse_llm_info)
    votes = tasks["user_answers"].apply(_parse_votes)
    choices_parsed = tasks["choices"].apply(_parse_choices)
    human_majority = votes.apply(_majority)
    # submitted_answer is the ground truth for the pipeline tasks.
    tasks = tasks.assign(
        confidence=info.apply(lambda d: d.get("confidence")),
        adapter=info.apply(lambda d: d.get("adapter")),
        entropy=info.apply(lambda d: d.get("entropy")),
        margin=info.apply(lambda d: d.get("margin")),
        votes=votes,
        choices_parsed=choices_parsed,
        num_options=choices_parsed.apply(len),
        ai_correct=(tasks["llm_answer"] == tasks["submitted_answer"]),
        human_majority=human_majority,
        ai_human_conflict=((tasks["llm_answer"] != human_majority)
                           & human_majority.notna()),
        n_votes=votes.apply(len),
        nonunanimous=votes.apply(_is_split),
        # complexity is 1-4; keep as string for clean categorical axes.
        complexity=tasks["complexity"].astype(str),
    )

    # --- goldtasks_table: human votes vs correct_answer ---
    g_votes = gold["user_answers"].apply(_parse_votes)
    gold = gold.assign(
        votes=g_votes,
        n_votes=g_votes.apply(len),
        nonunanimous=g_votes.apply(_is_split),
        complexity=gold["complexity"].astype(str),
    )

    return tasks, gold


def _vote_accuracy(df, truth_col):
    """Vote-level accuracy: fraction of individual human votes == ground truth."""
    total = correct = 0
    for votes, truth in zip(df["votes"], df[truth_col]):
        for v in votes:
            total += 1
            correct += int(v == truth)
    return correct, total


def _per_category_vote_acc(df, truth_col, dim):
    rows = []
    for val, sub in df.groupby(dim):
        correct, total = _vote_accuracy(sub, truth_col)
        rows.append(
            {dim: val, "accuracy": (correct / total if total else 0), "votes": total}
        )
    return pd.DataFrame(rows).sort_values(dim)


def _sorted_categories(series):
    return sorted(series.dropna().unique().tolist(), key=lambda x: str(x))


# --------------------------------------------------------------------------- #
# File checks
# --------------------------------------------------------------------------- #
def _missing_files():
    problems = []
    if not DATA_DIR.exists():
        return [f"The data folder `{DATA_DIR}` does not exist."]
    if not TASKS_FILE.exists():
        problems.append(f"Missing file: `{TASKS_FILE}` (expected 1137 rows).")
    if not GOLD_FILE.exists():
        problems.append(f"Missing file: `{GOLD_FILE}` (expected 330 rows).")
    return problems


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
st.title("Data Brainstorming Sandbox")
st.info(
    "Standalone data-brainstorming sandbox for exploring what analytics are "
    "*possible* from a sample dataset — not a production tool, and not connected "
    "to any application.",
    icon="🧪",
)

problems = _missing_files()
if problems:
    st.error(
        "Could not find the sample data. This app expects a `sample_data/` "
        "folder in the project root containing `tasks_table.csv` and "
        "`goldtasks_table.csv`.\n\n- " + "\n- ".join(problems)
    )
    st.stop()

tasks, gold = load_data()

# --- Overview KPI cards ---
ai_correct_n = int(tasks["ai_correct"].sum())
ai_total = len(tasks)
ai_acc = ai_correct_n / ai_total if ai_total else 0
gold_correct, gold_votes = _vote_accuracy(gold, "correct_answer")
gold_human_acc = gold_correct / gold_votes if gold_votes else 0
mean_conf = tasks["confidence"].mean()

flagged_mask = (
    tasks["ai_human_conflict"]
    | (tasks["confidence"] < 0.7)
    | (tasks["status"] == "Pending Confirmation")
    | tasks["nonunanimous"]
)
n_flagged = int(flagged_mask.sum())

st.subheader("Overview")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Pipeline tasks", f"{ai_total:,}")
k2.metric("Gold tasks", f"{len(gold):,}")
k3.metric("AI accuracy", f"{ai_acc*100:.1f}%", help="mean(llm_answer == submitted_answer)")
k4.metric("Human accuracy (gold)", f"{gold_human_acc*100:.1f}%",
          help="Vote-level accuracy on gold tasks")
k5.metric("Flagged for review", f"{n_flagged:,}")
st.caption(
    "Top-level snapshot. AI ground truth = `submitted_answer`; gold ground "
    "truth = `correct_answer`. The degraded `confidence_level` column is ignored "
    "in favor of the real confidence parsed from `llm_info`."
)

st.divider()
ai_tab, task_tab = st.tabs(["AI Analytics", "Task Analytics"])

# =========================================================================== #
# AI ANALYTICS TAB
# =========================================================================== #
with ai_tab:
    st.header("AI Analytics")
    st.caption("Pipeline tasks only (`tasks_table.csv`).")

    # 1. Accuracy KPI
    c1, c2 = st.columns([1, 3])
    c1.metric("Overall AI accuracy", f"{ai_acc*100:.1f}%")
    c1.caption(f"{ai_correct_n:,} correct of {ai_total:,} tasks")
    c2.metric("Mean AI confidence", f"{mean_conf:.3f}")
    c2.caption("Real confidence from `llm_info` (range "
               f"{tasks['confidence'].min():.2f}–{tasks['confidence'].max():.2f}).")

    st.divider()

    # 2. Calibration curve
    st.subheader("Calibration: confidence vs. actual accuracy")
    bins = [i / 10 for i in range(11)]
    cal = tasks.dropna(subset=["confidence"])
    cal = cal.assign(conf_bin=pd.cut(cal["confidence"], bins=bins, include_lowest=True))
    grp = (
        cal.groupby("conf_bin", observed=True)
        .agg(mean_confidence=("confidence", "mean"),
             accuracy=("ai_correct", "mean"),
             count=("ai_correct", "size"))
        .reset_index()
        .dropna(subset=["mean_confidence"])
    )
    fig_cal = px.line(
        grp, x="mean_confidence", y="accuracy", markers=True,
        hover_data={"count": True, "mean_confidence": ":.3f", "accuracy": ":.3f"},
        template=TEMPLATE, title="Calibration curve (10 confidence bins)",
        labels={"mean_confidence": "Mean confidence (bin)", "accuracy": "Actual accuracy"},
    )
    fig_cal.update_traces(line_color=C_CONF, marker=dict(size=9, color=C_CONF))
    fig_cal.add_shape(type="line", x0=0, y0=0, x1=1, y1=1,
                      line=dict(color=C_NEUTRAL, dash="dash"))
    fig_cal.add_annotation(x=0.82, y=0.88, text="perfect calibration",
                           showarrow=False, font=dict(color=C_NEUTRAL, size=11))
    fig_cal.update_layout(xaxis_range=[0, 1], yaxis_range=[0, 1])
    st.plotly_chart(fig_cal, use_container_width=True)
    st.caption(
        "Each point is one confidence bin: x = average confidence, y = the share "
        "actually correct. Points on the dashed line are perfectly calibrated; "
        "below the line = overconfident, above = underconfident. Hover for bin size."
    )

    st.divider()

    # 3. Per-category confidence vs accuracy
    st.subheader("Per-category: confidence vs. accuracy")
    dim = st.selectbox("Break down by dimension", CATEGORY_DIMS + ["adapter"],
                       key="ai_dim")
    agg = (
        tasks.groupby(dim)
        .agg(**{"Mean confidence": ("confidence", "mean"),
                "Accuracy": ("ai_correct", "mean"),
                "count": ("ai_correct", "size")})
        .reset_index()
        .sort_values(dim)
    )
    long = agg.melt(id_vars=[dim, "count"],
                    value_vars=["Mean confidence", "Accuracy"],
                    var_name="metric", value_name="value")
    fig_cat = px.bar(
        long, x=dim, y="value", color="metric", barmode="group",
        template=TEMPLATE, title=f"Confidence vs. accuracy by {dim}",
        color_discrete_map={"Mean confidence": C_CONF, "Accuracy": C_ACC},
        labels={"value": "Value (0–1)", "metric": ""},
        hover_data={"count": True},
    )
    fig_cat.update_layout(yaxis_range=[0, 1])
    st.plotly_chart(fig_cat, use_container_width=True)
    st.caption(
        f"For each `{dim}` value, blue = the model's mean confidence and green = "
        "its actual accuracy. A tall blue bar over a short green one means "
        "overconfidence in that slice."
    )

# =========================================================================== #
# TASK ANALYTICS TAB
# =========================================================================== #
with task_tab:
    st.header("Task Analytics")

    # 4. Human accuracy
    st.subheader("Human accuracy")
    tasks_h_correct, tasks_h_total = _vote_accuracy(tasks, "submitted_answer")
    tasks_human_acc = tasks_h_correct / tasks_h_total if tasks_h_total else 0
    h1, h2 = st.columns(2)
    h1.metric("Gold human accuracy", f"{gold_human_acc*100:.1f}%")
    h1.caption(f"{gold_correct:,} of {gold_votes:,} individual gold votes "
               "match `correct_answer`.")
    h2.metric("Pipeline human accuracy", f"{tasks_human_acc*100:.1f}%")
    h2.caption(f"{tasks_h_correct:,} of {tasks_h_total:,} pipeline votes "
               "match `submitted_answer`.")

    hdim = st.selectbox("Break down human accuracy by", CATEGORY_DIMS, key="human_dim")
    gold_cat = _per_category_vote_acc(gold, "correct_answer", hdim).assign(source="Gold")
    tasks_cat = _per_category_vote_acc(tasks, "submitted_answer", hdim).assign(
        source="Pipeline")
    both = pd.concat([gold_cat, tasks_cat], ignore_index=True)
    fig_h = px.bar(
        both, x=hdim, y="accuracy", color="source", barmode="group",
        template=TEMPLATE, title=f"Human accuracy by {hdim}",
        color_discrete_map={"Gold": C_ACC, "Pipeline": C_CONF},
        labels={"accuracy": "Vote-level accuracy"}, hover_data={"votes": True},
    )
    fig_h.update_layout(yaxis_range=[0, 1])
    st.plotly_chart(fig_h, use_container_width=True)
    st.caption(
        "Share of individual human votes that match the ground truth, split by "
        "gold vs. pipeline tasks. Hover shows the number of votes behind each bar."
    )

    st.divider()

    # 5. Review queue
    st.subheader("Review queue")

    def _reasons(r):
        out = []
        if r["ai_human_conflict"]:
            out.append("AI vs human conflict")
        if r["confidence"] < 0.7:
            out.append("Low confidence (<0.7)")
        if r["status"] == "Pending Confirmation":
            out.append("Pending confirmation")
        if r["nonunanimous"]:
            out.append("Non-unanimous votes")
        return "; ".join(out)

    rq = tasks.assign(flag_reason=tasks.apply(_reasons, axis=1))
    rq = rq[rq["flag_reason"] != ""]

    reason_options = [
        "AI vs human conflict",
        "Low confidence (<0.7)",
        "Pending confirmation",
        "Non-unanimous votes",
    ]
    fcol1, fcol2 = st.columns([2, 1])
    chosen = fcol1.multiselect("Filter by flag reason", reason_options,
                               default=reason_options)
    topic_choices = _sorted_categories(rq["topic"])
    chosen_topics = fcol2.multiselect("Filter by topic", topic_choices,
                                      default=topic_choices)

    if chosen:
        rq = rq[rq["flag_reason"].apply(lambda s: any(c in s for c in chosen))]
    rq = rq[rq["topic"].isin(chosen_topics)]
    rq = rq.sort_values("confidence", ascending=True)

    st.caption(f"{len(rq):,} task(s) flagged for attention. Sorted by confidence "
               "(lowest first). Click a column header to re-sort.")
    display_cols = ["task_id", "topic", "type", "complexity", "llm_answer",
                    "human_majority", "submitted_answer", "confidence", "flag_reason"]
    st.dataframe(
        rq[display_cols].rename(columns={"submitted_answer": "ground_truth"}),
        use_container_width=True, hide_index=True,
        column_config={
            "confidence": st.column_config.NumberColumn("confidence", format="%.3f"),
        },
    )

    st.divider()

    # 6. Difficulty (illustrative heuristic)
    st.subheader("Difficulty (illustrative heuristic)")
    ddim = st.radio("View by", ["topic", "complexity"], horizontal=True, key="diff_dim")

    def _difficulty(df, dim):
        rows = []
        for val, sub in df.groupby(dim):
            ai_err = 1 - sub["ai_correct"].mean()
            multi = sub[sub["n_votes"] >= 2]
            dis = multi["nonunanimous"].mean() if len(multi) else 0
            rows.append({dim: val, "AI error rate": ai_err,
                         "Human disagreement rate": dis})
        return pd.DataFrame(rows).sort_values(dim)

    diff = _difficulty(tasks, ddim)
    diff_long = diff.melt(id_vars=[ddim], var_name="metric", value_name="rate")
    fig_d = px.bar(
        diff_long, x=ddim, y="rate", color="metric", barmode="group",
        template=TEMPLATE, title=f"AI error vs. human disagreement by {ddim}",
        color_discrete_map={"AI error rate": C_WARN,
                            "Human disagreement rate": C_NEUTRAL},
        labels={"rate": "Rate (0–1)", "metric": ""},
    )
    fig_d.update_layout(yaxis_range=[0, 1])
    st.plotly_chart(fig_d, use_container_width=True)
    st.caption(
        "Illustrative difficulty proxy for brainstorming only. AI error rate = "
        "1 − AI accuracy; human disagreement rate = share of multi-vote tasks "
        "whose votes aren't unanimous. Not a validated metric."
    )

    st.divider()

    # 7. Inventory
    st.subheader("Inventory")
    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Pipeline tasks", f"{len(tasks):,}")
    i2.metric("Gold tasks", f"{len(gold):,}")
    i3.metric("Topics", f"{tasks['topic'].nunique()}")
    i4.metric("Pending confirmation", f"{int((tasks['status']=='Pending Confirmation').sum())}")

    inv1, inv2 = st.columns(2)
    status_counts = tasks["status"].value_counts().reset_index()
    status_counts.columns = ["status", "count"]
    fig_status = px.bar(status_counts, x="status", y="count", template=TEMPLATE,
                        title="Pipeline tasks by status",
                        color_discrete_sequence=[C_CONF])
    inv1.plotly_chart(fig_status, use_container_width=True)
    inv1.caption("How pipeline tasks split across workflow statuses.")

    opt = tasks["num_options"].value_counts().sort_index().reset_index()
    opt.columns = ["num_options", "count"]
    opt = opt.assign(num_options=opt["num_options"].astype(str))
    fig_opt = px.bar(opt, x="num_options", y="count", template=TEMPLATE,
                     title="Answer options per task (from parsed choices)",
                     color_discrete_sequence=[C_ACC])
    inv2.plotly_chart(fig_opt, use_container_width=True)
    inv2.caption("Distribution of how many answer choices tasks offer (2 / 3 / 4).")

    with st.expander("Counts by type, topic, and complexity (both tables)"):
        for d in CATEGORY_DIMS:
            t_tbl = tasks[d].value_counts().rename("pipeline")
            g_tbl = gold[d].value_counts().rename("gold")
            merged = pd.concat([t_tbl, g_tbl], axis=1).fillna(0).astype(int)
            merged.index.name = d
            st.write(f"**By {d}**")
            st.dataframe(merged, use_container_width=True)

    st.divider()

    # 8. Volume
    st.subheader("Volume")
    overlay = st.checkbox("Overlay gold tasks", value=False, key="vol_overlay")
    for d in CATEGORY_DIMS:
        t_counts = tasks[d].value_counts().reset_index()
        t_counts.columns = [d, "count"]
        t_counts["source"] = "Pipeline"
        frames = [t_counts]
        if overlay:
            g_counts = gold[d].value_counts().reset_index()
            g_counts.columns = [d, "count"]
            g_counts["source"] = "Gold"
            frames.append(g_counts)
        vol = pd.concat(frames, ignore_index=True).sort_values(d)
        fig_v = px.bar(
            vol, x=d, y="count", color="source", barmode="group",
            template=TEMPLATE, title=f"Task count by {d}",
            color_discrete_map={"Pipeline": C_CONF, "Gold": C_ACC},
        )
        st.plotly_chart(fig_v, use_container_width=True)
        st.caption(f"Number of tasks per `{d}` value"
                   + (" (pipeline vs. gold)." if overlay else " (pipeline)."))
