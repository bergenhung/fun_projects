#!/usr/bin/env python3
"""
Mega Millions Probability Analyzer
Analyzes draws from April 8, 2025 onward and generates statistically-weighted picks.

Two modes:
  • GUI mode  (default, when a display is available) — full charts + Generate Numbers tab.
  • CLI mode  (auto-used over SSH / when no display is found, or via --cli) — terminal
    prompts that only cover the "Generate Numbers" feature, no charts required.
"""

import io
import os
import sys
import itertools
from collections import Counter
from datetime import date

# ── Required dependencies (needed in both GUI and CLI mode) ──────────────────
try:
    import requests
    import pandas as pd
    import numpy as np
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install requests pandas numpy")
    sys.exit(1)

# ── Optional GUI dependencies (only needed when a display is available) ──────
GUI_LIBS_AVAILABLE = True
try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.gridspec import GridSpec
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
except ImportError:
    GUI_LIBS_AVAILABLE = False


# ─── CONFIG ───────────────────────────────────────────────────────────────────
CSV_URL    = "https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/Winning_Numbers/megamillions.csv"
START_DATE = date(2025, 4, 8)
MAIN_MIN, MAIN_MAX  = 1, 70
MB_MIN,   MB_MAX    = 1, 25

DARK_BG   = "#0d1117"
CARD_BG   = "#161b22"
ACCENT    = "#f7c948"       # gold
ACCENT2   = "#58a6ff"       # blue
RED_BALL  = "#e63946"
TEXT_COL  = "#e6edf3"
SUBTLE    = "#30363d"
GREEN     = "#3fb950"

# ─── DATA LOADING & ANALYSIS ─────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    """Download CSV, parse, filter to START_DATE onward."""
    resp = requests.get(CSV_URL, timeout=15)
    resp.raise_for_status()
    df = pd.read_csv(
        io.StringIO(resp.text),
        header=None,
        names=["game", "month", "day", "year", "n1", "n2", "n3", "n4", "n5", "mb", "mp"],
        usecols=range(11),
    )
    df["draw_date"] = pd.to_datetime(
        df[["year", "month", "day"]].rename(columns={"year": "year", "month": "month", "day": "day"})
    ).dt.date
    df = df[df["draw_date"] >= START_DATE].copy()
    df = df.sort_values("draw_date").reset_index(drop=True)
    # only keep draws with current-era number ranges
    main_cols = ["n1", "n2", "n3", "n4", "n5"]
    df = df[df[main_cols].apply(lambda r: r.between(MAIN_MIN, MAIN_MAX).all(), axis=1)]
    df = df[df["mb"].between(MB_MIN, MB_MAX)]
    return df


def analyze(df: pd.DataFrame) -> dict:
    """Return a dict of all probability tables and insights."""
    main_cols = ["n1", "n2", "n3", "n4", "n5"]

    # ── Per-position frequencies ──────────────────────────────────────────────
    pos_freq = {}
    for col in main_cols:
        pos_freq[col] = Counter(df[col].tolist())

    # ── Overall main-ball pool (position-agnostic) ────────────────────────────
    all_main = []
    for col in main_cols:
        all_main.extend(df[col].tolist())
    pool_freq   = Counter(all_main)
    pool_total  = sum(pool_freq.values())
    pool_prob   = {n: pool_freq[n] / pool_total for n in range(MAIN_MIN, MAIN_MAX + 1)}

    # ── Mega Ball frequencies ─────────────────────────────────────────────────
    mb_freq  = Counter(df["mb"].tolist())
    mb_total = sum(mb_freq.values())
    mb_prob  = {n: mb_freq[n] / mb_total for n in range(MB_MIN, MB_MAX + 1)}

    # ── Pair co-occurrence ────────────────────────────────────────────────────
    pair_counter = Counter()
    for _, row in df.iterrows():
        nums = sorted([row["n1"], row["n2"], row["n3"], row["n4"], row["n5"]])
        for pair in itertools.combinations(nums, 2):
            pair_counter[pair] += 1

    # ── Even / Odd split ──────────────────────────────────────────────────────
    eo_rows = []
    for _, row in df.iterrows():
        nums = [row["n1"], row["n2"], row["n3"], row["n4"], row["n5"]]
        evens = sum(1 for n in nums if n % 2 == 0)
        eo_rows.append(evens)
    eo_counter = Counter(eo_rows)

    # ── Low/High split  (1-35 low, 36-70 high) ───────────────────────────────
    lh_rows = []
    for _, row in df.iterrows():
        nums = [row["n1"], row["n2"], row["n3"], row["n4"], row["n5"]]
        low = sum(1 for n in nums if n <= 35)
        lh_rows.append(low)
    lh_counter = Counter(lh_rows)

    # ── Sum statistics ────────────────────────────────────────────────────────
    sums = df[main_cols].sum(axis=1)

    # ── Hot / Cold ───────────────────────────────────────────────────────────
    hot  = [n for n, _ in pool_freq.most_common(10)]
    cold = [n for n, _ in pool_freq.most_common()[-10:]]

    return dict(
        df=df,
        pos_freq=pos_freq,
        pool_freq=pool_freq,
        pool_prob=pool_prob,
        mb_freq=mb_freq,
        mb_prob=mb_prob,
        pair_counter=pair_counter,
        eo_counter=eo_counter,
        lh_counter=lh_counter,
        sums=sums,
        hot=hot,
        cold=cold,
        total_draws=len(df),
    )


def weighted_pick(prob_dict: dict, k: int, exclude: set = None) -> list:
    """Pick k unique items with probability weights."""
    exclude   = exclude or set()
    universe  = [n for n in prob_dict if n not in exclude]
    weights   = [prob_dict[n] for n in universe]
    total     = sum(weights)
    weights   = [w / total for w in weights]
    return list(np.random.choice(universe, size=k, replace=False, p=weights))


STRATEGIES = [
    "Weighted (historical prob)",
    "Uniform Random",
    "Hot Numbers Bias",
    "Cold Numbers Bias",
]


def build_probabilities(strategy: str, stats: dict) -> tuple:
    """Return (main_prob, mega_ball_prob) dicts for the given strategy name.
    Shared by both the GUI and CLI generators so results are consistent."""
    if strategy == "Uniform Random":
        mp = {n: 1 / MAIN_MAX for n in range(MAIN_MIN, MAIN_MAX + 1)}
        bp = {n: 1 / MB_MAX for n in range(MB_MIN, MB_MAX + 1)}
    elif strategy == "Hot Numbers Bias":
        raw = {n: (stats["pool_freq"].get(n, 0) + 1) ** 2
               for n in range(MAIN_MIN, MAIN_MAX + 1)}
        total = sum(raw.values())
        mp = {n: raw[n] / total for n in raw}
        bp = stats["mb_prob"]
    elif strategy == "Cold Numbers Bias":
        mx = max(stats["pool_freq"].get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)) + 1
        inv = {n: mx - stats["pool_freq"].get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)}
        total = sum(inv.values())
        mp = {n: inv[n] / total for n in inv}
        mx_mb = max(stats["mb_freq"].get(n, 0) for n in range(MB_MIN, MB_MAX + 1)) + 1
        inv_mb = {n: mx_mb - stats["mb_freq"].get(n, 0) for n in range(MB_MIN, MB_MAX + 1)}
        total_mb = sum(inv_mb.values())
        bp = {n: inv_mb[n] / total_mb for n in inv_mb}
    else:  # "Weighted (historical prob)"
        mp = stats["pool_prob"]
        bp = stats["mb_prob"]
    return mp, bp


def generate_pick(main_prob: dict, mb_prob: dict) -> tuple:
    """Generate one 5+1 set using the given probability weights."""
    main = sorted(weighted_pick(main_prob, 5))
    mb   = weighted_pick(mb_prob, 1)[0]
    return main, mb


def has_display() -> bool:
    """Check whether a usable GUI display is available.
    Returns False (without raising) over SSH sessions with no X11/Wayland
    forwarding, or when GUI libraries (tkinter/matplotlib) aren't installed."""
    if not GUI_LIBS_AVAILABLE:
        return False
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return False
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


# ─── GUI ─────────────────────────────────────────────────────────────────────

if GUI_LIBS_AVAILABLE:

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Mega Millions Probability Analyzer")
            self.configure(bg=DARK_BG)
            try:
                if sys.platform == "win32":
                    self.state("zoomed")
                elif sys.platform == "darwin":
                    # macOS — no native maximize; set a large geometry instead
                    self.geometry("1400x860")
                else:
                    # Linux / X11
                    self.attributes("-zoomed", True)
            except Exception:
                self.geometry("1400x860")

            self.stats = None
            self._build_ui()
            self._load()

        # ── Layout skeleton ───────────────────────────────────────────────────────
        def _build_ui(self):
            # Top header bar
            hdr = tk.Frame(self, bg=CARD_BG, height=60)
            hdr.pack(fill="x")
            tk.Label(hdr, text="🎰  Mega Millions Probability Analyzer",
                     font=("Helvetica", 18, "bold"), fg=ACCENT, bg=CARD_BG,
                     pady=14).pack(side="left", padx=20)
            self.status_lbl = tk.Label(hdr, text="Loading…", font=("Helvetica", 11),
                                       fg=SUBTLE, bg=CARD_BG)
            self.status_lbl.pack(side="right", padx=20)

            # Notebook (tabs)
            style = ttk.Style(self)
            style.theme_use("clam")
            style.configure("TNotebook",        background=DARK_BG, borderwidth=0)
            style.configure("TNotebook.Tab",    background=CARD_BG, foreground=TEXT_COL,
                             padding=[14, 8],   font=("Helvetica", 11))
            style.map("TNotebook.Tab",
                      background=[("selected", ACCENT)],
                      foreground=[("selected", "#000")])

            self.nb = ttk.Notebook(self)
            self.nb.pack(fill="both", expand=True, padx=10, pady=(6, 10))

            self.tab_overview  = tk.Frame(self.nb, bg=DARK_BG)
            self.tab_positions = tk.Frame(self.nb, bg=DARK_BG)
            self.tab_mb        = tk.Frame(self.nb, bg=DARK_BG)
            self.tab_relations = tk.Frame(self.nb, bg=DARK_BG)
            self.tab_generate  = tk.Frame(self.nb, bg=DARK_BG)

            self.nb.add(self.tab_overview,  text="📊  Overview")
            self.nb.add(self.tab_positions, text="🎱  Position Analysis")
            self.nb.add(self.tab_mb,        text="🔴  Mega Ball")
            self.nb.add(self.tab_relations, text="🔗  Relationships")
            self.nb.add(self.tab_generate,  text="✨  Generate Numbers")

        # ── Data load ─────────────────────────────────────────────────────────────
        def _load(self):
            self.status_lbl.config(text="⏳  Downloading data…")
            self.update()
            try:
                df = load_data()
                self.stats = analyze(df)
                self.status_lbl.config(
                    text=f"✅  {self.stats['total_draws']} draws  |  {START_DATE} → today",
                    fg=GREEN)
                self._build_overview()
                self._build_positions()
                self._build_mb()
                self._build_relations()
                self._build_generate()
            except Exception as exc:
                messagebox.showerror("Load Error", str(exc))
                self.status_lbl.config(text="❌  Failed to load", fg=RED_BALL)

        # ── Overview tab ──────────────────────────────────────────────────────────
        def _build_overview(self):
            st = self.stats
            fig = plt.Figure(figsize=(14, 8), facecolor=DARK_BG)
            gs  = GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)

            # ① All-pool frequency bar
            ax1 = fig.add_subplot(gs[0, :])
            nums   = list(range(MAIN_MIN, MAIN_MAX + 1))
            counts = [st["pool_freq"].get(n, 0) for n in nums]
            colors = [ACCENT if n in st["hot"] else (RED_BALL if n in st["cold"] else ACCENT2)
                      for n in nums]
            ax1.bar(nums, counts, color=colors, width=0.8)
            ax1.set_title("Main Ball Pool — Overall Frequency (Apr 8 2025 → now)",
                          color=TEXT_COL, fontsize=12, pad=10)
            ax1.set_xlabel("Ball Number", color=TEXT_COL)
            ax1.set_ylabel("Times Drawn", color=TEXT_COL)
            ax1.set_facecolor(CARD_BG)
            ax1.tick_params(colors=TEXT_COL, labelsize=8)
            for spine in ax1.spines.values(): spine.set_color(SUBTLE)
            gold_p  = mpatches.Patch(color=ACCENT,  label="Top-10 Hot")
            red_p   = mpatches.Patch(color=RED_BALL, label="Bottom-10 Cold")
            blue_p  = mpatches.Patch(color=ACCENT2,  label="Normal")
            ax1.legend(handles=[gold_p, red_p, blue_p], facecolor=CARD_BG,
                       labelcolor=TEXT_COL, edgecolor=SUBTLE)

            # ② Even/Odd distribution
            ax2 = fig.add_subplot(gs[1, 0])
            eo_labels = [f"{e}E/{5-e}O" for e in range(6)]
            eo_vals   = [st["eo_counter"].get(e, 0) for e in range(6)]
            wedge_colors = [ACCENT2, ACCENT, GREEN, RED_BALL, "#c084fc", "#f97316"]
            ax2.pie(eo_vals, labels=eo_labels, colors=wedge_colors,
                    autopct="%1.1f%%", textprops={"color": TEXT_COL, "fontsize": 9},
                    wedgeprops={"edgecolor": DARK_BG})
            ax2.set_title("Even / Odd Split per Draw", color=TEXT_COL, fontsize=11, pad=8)
            ax2.set_facecolor(CARD_BG)

            # ③ Low/High distribution
            ax3 = fig.add_subplot(gs[1, 1])
            lh_labels = [f"{l}Low/{5-l}High" for l in range(6)]
            lh_vals   = [st["lh_counter"].get(l, 0) for l in range(6)]
            ax3.pie(lh_vals, labels=lh_labels, colors=wedge_colors,
                    autopct="%1.1f%%", textprops={"color": TEXT_COL, "fontsize": 9},
                    wedgeprops={"edgecolor": DARK_BG})
            ax3.set_title("Low (1-35) / High (36-70) Split", color=TEXT_COL, fontsize=11, pad=8)
            ax3.set_facecolor(CARD_BG)

            self._embed(fig, self.tab_overview)

            # Stats summary strip
            frm = tk.Frame(self.tab_overview, bg=DARK_BG)
            frm.pack(fill="x", padx=16, pady=(0, 8))
            sums = st["sums"]
            stats_items = [
                ("Total Draws Analyzed",  str(st["total_draws"])),
                ("Avg Sum of 5 Balls",    f"{sums.mean():.1f}"),
                ("Most Common Sum Range", f"{int(sums.quantile(.25))}–{int(sums.quantile(.75))}"),
                ("Hottest Main Ball",     str(st["hot"][0])),
                ("Coldest Main Ball",     str(st["cold"][0])),
                ("Most Common MB",        str(st["mb_freq"].most_common(1)[0][0])),
            ]
            for i, (lbl, val) in enumerate(stats_items):
                card = tk.Frame(frm, bg=CARD_BG, padx=12, pady=8)
                card.grid(row=0, column=i, padx=6, sticky="ew")
                frm.columnconfigure(i, weight=1)
                tk.Label(card, text=val, font=("Helvetica", 15, "bold"),
                         fg=ACCENT, bg=CARD_BG).pack()
                tk.Label(card, text=lbl, font=("Helvetica", 9),
                         fg=TEXT_COL, bg=CARD_BG).pack()

        # ── Position analysis tab ─────────────────────────────────────────────────
        def _build_positions(self):
            st = self.stats
            fig = plt.Figure(figsize=(14, 9), facecolor=DARK_BG)
            gs  = GridSpec(2, 3, figure=fig, hspace=0.55, wspace=0.4)
            pos_names = ["n1", "n2", "n3", "n4", "n5"]
            colors    = [ACCENT, ACCENT2, GREEN, RED_BALL, "#c084fc"]

            for idx, (col, color) in enumerate(zip(pos_names, colors)):
                ax = fig.add_subplot(gs[idx // 3, idx % 3])
                freq = st["pos_freq"][col]
                nums = list(range(MAIN_MIN, MAIN_MAX + 1))
                vals = [freq.get(n, 0) for n in nums]
                ax.bar(nums, vals, color=color, width=0.8, alpha=0.85)
                ax.set_title(f"Position {idx+1}  (Num{idx+1})",
                             color=TEXT_COL, fontsize=10, pad=6)
                ax.set_facecolor(CARD_BG)
                ax.tick_params(colors=TEXT_COL, labelsize=7)
                for spine in ax.spines.values(): spine.set_color(SUBTLE)
                top3 = sorted(freq, key=freq.get, reverse=True)[:3]
                ax.set_xlabel(f"Top-3: {top3}", color=TEXT_COL, fontsize=8)

            # 6th panel: heatmap of position vs number
            ax6 = fig.add_subplot(gs[1, 2])
            mat = np.zeros((5, MAIN_MAX))
            for i, col in enumerate(pos_names):
                for n, cnt in st["pos_freq"][col].items():
                    if 1 <= n <= MAIN_MAX:
                        mat[i, n - 1] = cnt
            im = ax6.imshow(mat, aspect="auto", cmap="YlOrRd", origin="upper")
            ax6.set_yticks(range(5))
            ax6.set_yticklabels([f"Pos {i+1}" for i in range(5)], color=TEXT_COL, fontsize=8)
            ax6.set_xlabel("Ball Number (1–70)", color=TEXT_COL, fontsize=8)
            ax6.set_title("Position × Number Heatmap", color=TEXT_COL, fontsize=10, pad=6)
            ax6.tick_params(colors=TEXT_COL, labelsize=7)
            fig.colorbar(im, ax=ax6, fraction=0.04)

            self._embed(fig, self.tab_positions)

        # ── Mega Ball tab ─────────────────────────────────────────────────────────
        def _build_mb(self):
            st = self.stats
            fig = plt.Figure(figsize=(13, 7), facecolor=DARK_BG)
            gs  = GridSpec(1, 2, figure=fig, wspace=0.35)

            # Bar chart
            ax1 = fig.add_subplot(gs[0])
            mbs    = list(range(MB_MIN, MB_MAX + 1))
            counts = [st["mb_freq"].get(n, 0) for n in mbs]
            top3mb = sorted(st["mb_freq"], key=st["mb_freq"].get, reverse=True)[:3]
            bar_colors = [ACCENT if n in top3mb else RED_BALL for n in mbs]
            ax1.bar(mbs, counts, color=bar_colors, width=0.7)
            ax1.set_title("Mega Ball Frequency (1–25)", color=TEXT_COL, fontsize=12, pad=10)
            ax1.set_xlabel("Mega Ball Number", color=TEXT_COL)
            ax1.set_ylabel("Times Drawn", color=TEXT_COL)
            ax1.set_facecolor(CARD_BG)
            ax1.tick_params(colors=TEXT_COL)
            for spine in ax1.spines.values(): spine.set_color(SUBTLE)
            ax1.set_xticks(mbs)

            gold_p = mpatches.Patch(color=ACCENT,  label="Top-3")
            red_p  = mpatches.Patch(color=RED_BALL, label="Others")
            ax1.legend(handles=[gold_p, red_p], facecolor=CARD_BG,
                       labelcolor=TEXT_COL, edgecolor=SUBTLE)

            # Pie chart of probability
            ax2 = fig.add_subplot(gs[1])
            probs = [st["mb_prob"].get(n, 0) for n in mbs]
            cmap  = plt.get_cmap("plasma")
            pie_colors = [cmap(i / len(mbs)) for i in range(len(mbs))]
            wedges, texts, autotexts = ax2.pie(
                probs, labels=mbs, colors=pie_colors,
                autopct=lambda p: f"{p:.1f}%" if p > 4 else "",
                textprops={"color": TEXT_COL, "fontsize": 8},
                wedgeprops={"edgecolor": DARK_BG},
            )
            for at in autotexts:
                at.set_fontsize(7)
            ax2.set_title("Mega Ball Draw Probability", color=TEXT_COL, fontsize=12, pad=10)

            self._embed(fig, self.tab_mb)

            # Text summary
            frm = tk.Frame(self.tab_mb, bg=DARK_BG)
            frm.pack(fill="x", padx=16, pady=(0, 8))
            top5mb = st["mb_freq"].most_common(5)
            cold5mb = st["mb_freq"].most_common()[-5:]
            items = [
                ("🔥 Top-5 Mega Balls",  ", ".join(str(n) for n, _ in top5mb)),
                ("🧊 Cold-5 Mega Balls", ", ".join(str(n) for n, _ in cold5mb)),
                ("📈 Highest Prob MB",   f"{top5mb[0][0]}  ({top5mb[0][1]/st['total_draws']*100:.1f}% of draws)"),
            ]
            for i, (lbl, val) in enumerate(items):
                card = tk.Frame(frm, bg=CARD_BG, padx=12, pady=8)
                card.grid(row=0, column=i, padx=8, sticky="ew")
                frm.columnconfigure(i, weight=1)
                tk.Label(card, text=val, font=("Helvetica", 12, "bold"),
                         fg=ACCENT, bg=CARD_BG, wraplength=260).pack()
                tk.Label(card, text=lbl, font=("Helvetica", 9),
                         fg=TEXT_COL, bg=CARD_BG).pack()

        # ── Relationships tab ─────────────────────────────────────────────────────
        def _build_relations(self):
            st = self.stats

            fig = plt.Figure(figsize=(14, 8), facecolor=DARK_BG)
            gs  = GridSpec(1, 2, figure=fig, wspace=0.4)

            # Top-20 pairs
            ax1 = fig.add_subplot(gs[0])
            top_pairs = st["pair_counter"].most_common(20)
            labels    = [f"{a}-{b}" for (a, b), _ in top_pairs]
            vals      = [v for _, v in top_pairs]
            y_pos     = range(len(labels))
            ax1.barh(list(y_pos), vals, color=ACCENT2, height=0.65)
            ax1.set_yticks(list(y_pos))
            ax1.set_yticklabels(labels, color=TEXT_COL, fontsize=9)
            ax1.invert_yaxis()
            ax1.set_title("Top-20 Most Co-Occurring Pairs", color=TEXT_COL, fontsize=11, pad=10)
            ax1.set_xlabel("Times Appeared Together", color=TEXT_COL)
            ax1.set_facecolor(CARD_BG)
            ax1.tick_params(colors=TEXT_COL)
            for spine in ax1.spines.values(): spine.set_color(SUBTLE)

            # Sum distribution histogram
            ax2 = fig.add_subplot(gs[1])
            sums = st["sums"]
            ax2.hist(sums, bins=25, color=GREEN, edgecolor=DARK_BG, linewidth=0.5)
            ax2.axvline(sums.mean(),   color=ACCENT,   linestyle="--", linewidth=1.5, label=f"Mean {sums.mean():.0f}")
            ax2.axvline(sums.median(), color=RED_BALL,  linestyle="--", linewidth=1.5, label=f"Median {sums.median():.0f}")
            ax2.set_title("Distribution of Sum of 5 Main Balls", color=TEXT_COL, fontsize=11, pad=10)
            ax2.set_xlabel("Sum", color=TEXT_COL)
            ax2.set_ylabel("Draw Count", color=TEXT_COL)
            ax2.set_facecolor(CARD_BG)
            ax2.tick_params(colors=TEXT_COL)
            for spine in ax2.spines.values(): spine.set_color(SUBTLE)
            ax2.legend(facecolor=CARD_BG, labelcolor=TEXT_COL, edgecolor=SUBTLE)

            self._embed(fig, self.tab_relations)

            # Scrollable text with pair data
            frm = tk.Frame(self.tab_relations, bg=DARK_BG)
            frm.pack(fill="x", padx=16, pady=(0, 10))
            tk.Label(frm, text="🔗  Top-50 Most Frequent Pairs",
                     font=("Helvetica", 11, "bold"), fg=ACCENT, bg=DARK_BG).pack(anchor="w")
            txt = scrolledtext.ScrolledText(frm, height=5, bg=CARD_BG, fg=TEXT_COL,
                                            font=("Courier", 9), insertbackground=TEXT_COL)
            txt.pack(fill="x")
            lines = [f"  {a:>2}-{b:<2}  appeared {v:>2}×" for (a, b), v in st["pair_counter"].most_common(50)]
            txt.insert("end", "   |  ".join(lines))
            txt.config(state="disabled")

        # ── Generate Numbers tab ──────────────────────────────────────────────────
        def _build_generate(self):
            outer = tk.Frame(self.tab_generate, bg=DARK_BG)
            outer.pack(fill="both", expand=True, padx=30, pady=20)

            tk.Label(outer, text="✨  Smart Number Generator",
                     font=("Helvetica", 18, "bold"), fg=ACCENT, bg=DARK_BG).pack(pady=(0, 4))
            tk.Label(outer,
                     text="Numbers are generated using weighted probability from historical draws.\n"
                          "Higher-frequency balls have a proportionally greater chance of selection.",
                     font=("Helvetica", 10), fg=TEXT_COL, bg=DARK_BG, justify="center").pack(pady=(0, 18))

            # How many tickets
            row0 = tk.Frame(outer, bg=DARK_BG)
            row0.pack(pady=(0, 14))
            tk.Label(row0, text="Number of tickets:", font=("Helvetica", 11),
                     fg=TEXT_COL, bg=DARK_BG).pack(side="left", padx=(0, 8))
            self.ticket_var = tk.IntVar(value=5)
            spin = tk.Spinbox(row0, from_=1, to=20, textvariable=self.ticket_var,
                              width=4, font=("Helvetica", 12),
                              bg=CARD_BG, fg=ACCENT, insertbackground=ACCENT,
                              buttonbackground=SUBTLE)
            spin.pack(side="left")

            # Strategy selector
            row1 = tk.Frame(outer, bg=DARK_BG)
            row1.pack(pady=(0, 18))
            tk.Label(row1, text="Strategy:", font=("Helvetica", 11),
                     fg=TEXT_COL, bg=DARK_BG).pack(side="left", padx=(0, 8))
            self.strategy_var = tk.StringVar(value="Weighted (historical prob)")
            strat_menu = ttk.Combobox(row1, textvariable=self.strategy_var, state="readonly",
                                      values=["Weighted (historical prob)",
                                              "Uniform Random",
                                              "Hot Numbers Bias",
                                              "Cold Numbers Bias"],
                                      width=28, font=("Helvetica", 11))
            strat_menu.pack(side="left")

            # Generate button
            btn = tk.Button(outer, text="🎰  Generate My Picks",
                            font=("Helvetica", 14, "bold"),
                            bg=ACCENT, fg="#000", activebackground="#d4a72c",
                            relief="flat", padx=20, pady=10, cursor="hand2",
                            command=self._do_generate)
            btn.pack(pady=(0, 20))

            # Results area
            self.result_frame = tk.Frame(outer, bg=DARK_BG)
            self.result_frame.pack(fill="both", expand=True)

        def _do_generate(self):
            if not self.stats:
                return
            # clear old results
            for w in self.result_frame.winfo_children():
                w.destroy()

            n_tickets = self.ticket_var.get()
            strategy  = self.strategy_var.get()
            st = self.stats

            # Build prob dicts based on strategy
            if strategy == "Uniform Random":
                mp = {n: 1/MAIN_MAX for n in range(MAIN_MIN, MAIN_MAX + 1)}
                bp = {n: 1/MB_MAX   for n in range(MB_MIN, MB_MAX + 1)}
            elif strategy == "Hot Numbers Bias":
                total = sum(st["pool_freq"].get(n, 0) + 1 for n in range(MAIN_MIN, MAIN_MAX + 1))
                mp = {n: (st["pool_freq"].get(n, 0) + 1) / total for n in range(MAIN_MIN, MAIN_MAX + 1)}
                # square weights → more extreme bias
                raw = {n: mp[n]**2 for n in mp}
                t2 = sum(raw.values())
                mp = {n: raw[n]/t2 for n in raw}
                bp = st["mb_prob"]
            elif strategy == "Cold Numbers Bias":
                max_cnt = max(st["pool_freq"].get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)) + 1
                inv = {n: max_cnt - st["pool_freq"].get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)}
                t3  = sum(inv.values())
                mp  = {n: inv[n] / t3 for n in inv}
                max_mb = max(st["mb_freq"].get(n, 0) for n in range(MB_MIN, MB_MAX + 1)) + 1
                inv_mb = {n: max_mb - st["mb_freq"].get(n, 0) for n in range(MB_MIN, MB_MAX + 1)}
                t4     = sum(inv_mb.values())
                bp     = {n: inv_mb[n] / t4 for n in inv_mb}
            else:  # Weighted
                mp = st["pool_prob"]
                bp = st["mb_prob"]

            picks = []
            for _ in range(n_tickets):
                main = sorted(weighted_pick(mp, 5))
                mb   = weighted_pick(bp, 1)[0]
                picks.append((main, mb))

            # Display
            canvas_frame = tk.Frame(self.result_frame, bg=DARK_BG)
            canvas_frame.pack(fill="both", expand=True)

            tk.Label(canvas_frame,
                     text=f"Generated {n_tickets} ticket(s) — Strategy: {strategy}",
                     font=("Helvetica", 11, "italic"), fg=SUBTLE, bg=DARK_BG).pack(pady=(0, 10))

            for i, (main, mb) in enumerate(picks):
                row = tk.Frame(canvas_frame, bg=CARD_BG, pady=10, padx=12)
                row.pack(fill="x", pady=4)

                tk.Label(row, text=f"Ticket {i+1:>2}", font=("Helvetica", 11, "bold"),
                         fg=SUBTLE, bg=CARD_BG, width=9).pack(side="left")

                for num in main:
                    self._ball(row, num, ACCENT2, "#000")

                tk.Label(row, text=" + ", fg=SUBTLE, bg=CARD_BG,
                         font=("Helvetica", 13, "bold")).pack(side="left")
                self._ball(row, mb, RED_BALL, "#fff")

                # Quick insight
                s = sum(main)
                evens = sum(1 for n in main if n % 2 == 0)
                lows  = sum(1 for n in main if n <= 35)
                info  = f"  Sum={s}  |  {evens}E/{5-evens}O  |  {lows}Low/{5-lows}High"
                tk.Label(row, text=info, font=("Courier", 9),
                         fg=TEXT_COL, bg=CARD_BG).pack(side="left", padx=10)

        def _ball(self, parent, number, bg_color, fg_color):
            """Render a circular-looking ball label."""
            frm = tk.Frame(parent, bg=bg_color, width=38, height=38)
            frm.pack(side="left", padx=3)
            frm.pack_propagate(False)
            tk.Label(frm, text=str(number), font=("Helvetica", 11, "bold"),
                     fg=fg_color, bg=bg_color).place(relx=0.5, rely=0.5, anchor="center")

        # ── Helper ────────────────────────────────────────────────────────────────
        def _embed(self, fig, parent):
            canvas = FigureCanvasTkAgg(fig, master=parent)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)


# ─── CLI / SSH MODE ────────────────────────────────────────────────────────
# No display required — this entire section only touches the standard library
# plus the data/analysis functions above (which have no GUI dependencies).

class Ansi:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GOLD   = "\033[38;5;220m"
    BLUE   = "\033[38;5;75m"
    RED    = "\033[38;5;203m"
    GREEN  = "\033[38;5;83m"
    GRAY   = "\033[38;5;245m"


def _ansi_enabled() -> bool:
    return sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"


if not _ansi_enabled():
    for _attr in list(vars(Ansi)):
        if not _attr.startswith("_"):
            setattr(Ansi, _attr, "")


def prompt_int(label: str, default: int, lo: int, hi: int) -> int:
    while True:
        raw = input(f"{label} [{lo}-{hi}, default {default}]: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
            if lo <= val <= hi:
                return val
        except ValueError:
            pass
        print(f"  Please enter a whole number between {lo} and {hi}.")


def prompt_choice(label: str, options: list, default_idx: int = 0) -> str:
    print(label)
    for i, opt in enumerate(options, 1):
        tag = "  (default)" if (i - 1) == default_idx else ""
        print(f"   {i}) {opt}{tag}")
    while True:
        raw = input(f"  Choice [1-{len(options)}, default {default_idx + 1}]: ").strip()
        if not raw:
            return options[default_idx]
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        print(f"  Please enter a number between 1 and {len(options)}.")


class CLIApp:
    """Headless / SSH-friendly mode.

    Only covers the 'Generate Numbers' feature via terminal prompts —
    no charts, no tkinter, no display required. Safe to run over a
    plain SSH session."""

    def __init__(self):
        self.stats = None

    def run(self):
        self._banner()
        self._load()
        if not self.stats:
            return
        while True:
            n_tickets, strategy = self._prompt_inputs()
            self._generate_and_print(n_tickets, strategy)
            again = input(f"\n{Ansi.GRAY}Generate another batch? [y/N]: {Ansi.RESET}").strip().lower()
            if again != "y":
                break
        print(f"\n{Ansi.GOLD}Good luck! 🍀{Ansi.RESET}\n")

    def _banner(self):
        bar = "=" * 64
        print(f"\n{Ansi.BOLD}{Ansi.GOLD}{bar}")
        print("   🎰  MEGA MILLIONS PROBABILITY ANALYZER  —  CLI / SSH MODE")
        print(f"{bar}{Ansi.RESET}\n")

    def _load(self):
        print("⏳  Downloading and analyzing historical draw data…")
        try:
            df = load_data()
            self.stats = analyze(df)
            print(f"{Ansi.GREEN}✅  Loaded {self.stats['total_draws']} draws "
                  f"({START_DATE} → today){Ansi.RESET}\n")
        except Exception as exc:
            print(f"{Ansi.RED}❌  Failed to load data: {exc}{Ansi.RESET}\n")

    def _prompt_inputs(self):
        print(f"{Ansi.BOLD}— Generate Numbers —{Ansi.RESET}")
        n_tickets = prompt_int("How many tickets?", default=5, lo=1, hi=20)
        strategy = prompt_choice("\nSelect a generation strategy:", STRATEGIES, default_idx=0)
        return n_tickets, strategy

    def _generate_and_print(self, n_tickets: int, strategy: str):
        mp, bp = build_probabilities(strategy, self.stats)
        print(f"\n{Ansi.GRAY}Generated {n_tickets} ticket(s) — Strategy: {strategy}{Ansi.RESET}\n")
        for i in range(n_tickets):
            main, mb = generate_pick(mp, bp)
            self._print_ticket(i + 1, main, mb)

    def _print_ticket(self, idx: int, main: list, mb: int):
        main_str = "  ".join(f"{Ansi.BLUE}[{n:>2}]{Ansi.RESET}" for n in main)
        mb_str = f"{Ansi.RED}[{mb:>2}]{Ansi.RESET}"
        s = sum(main)
        evens = sum(1 for n in main if n % 2 == 0)
        lows = sum(1 for n in main if n <= 35)
        info = f"Sum={s}  {evens}E/{5-evens}O  {lows}Low/{5-lows}High"
        print(f"  Ticket {idx:>2}:  {main_str}  +  {mb_str}    {Ansi.GRAY}{info}{Ansi.RESET}")


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mega Millions Probability Analyzer")
    parser.add_argument("--cli", action="store_true",
                        help="Force terminal/SSH mode (no display required)")
    parser.add_argument("--gui", action="store_true",
                        help="Force GUI mode")
    args = parser.parse_args()

    if args.cli:
        want_gui = False
    elif args.gui:
        want_gui = True
    else:
        want_gui = has_display()   # auto-detect: SSH without X11 → CLI automatically

    if want_gui and has_display():
        App().mainloop()
    else:
        if want_gui and not has_display():
            print("⚠️  GUI requested but no usable display was found "
                  "(SSH session without X11/Wayland forwarding?).")
            print("    Falling back to terminal mode.\n")
        CLIApp().run()