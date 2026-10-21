#!/usr/bin/env python3
"""
Powerball Probability Analyzer
Analyzes draws from January 22, 2024 onward and generates statistically-weighted picks.
Covers: Num1–Num5, Powerball, and Power Play.

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
CSV_URL    = "https://www.texaslottery.com/export/sites/lottery/Games/Powerball/Winning_Numbers/powerball.csv"
START_DATE = date(2024, 1, 22)
MAIN_MIN, MAIN_MAX = 1, 69
PB_MIN,   PB_MAX   = 1, 26
PP_VALUES          = [2, 3, 4, 5, 10]   # valid Power Play multipliers

DARK_BG  = "#0d1117"
CARD_BG  = "#161b22"
ACCENT   = "#e8472a"     # Powerball red
ACCENT2  = "#58a6ff"     # blue
PP_COL   = "#f7c948"     # gold for Power Play
TEXT_COL = "#e6edf3"
SUBTLE   = "#30363d"
GREEN    = "#3fb950"
RED_BALL = "#e8472a"

# ─── DATA ────────────────────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    resp = requests.get(CSV_URL, timeout=15)
    resp.raise_for_status()
    df = pd.read_csv(
        io.StringIO(resp.text),
        header=None,
        names=["game", "month", "day", "year",
               "n1", "n2", "n3", "n4", "n5", "pb", "pp"],
        engine="python",
        on_bad_lines="skip",
    )
    df = df.dropna(subset=["game"])
    df = df[df["game"].astype(str).str.strip().str.lower() == "powerball"]

    for col in ["month", "day", "year", "n1", "n2", "n3", "n4", "n5", "pb", "pp"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna()

    df["draw_date"] = pd.to_datetime(
        df[["year", "month", "day"]].rename(
            columns={"year": "year", "month": "month", "day": "day"}
        )
    ).dt.date

    df = df[df["draw_date"] >= START_DATE].copy()
    df = df.sort_values("draw_date").reset_index(drop=True)

    # Validate current-era number ranges
    main_cols = ["n1", "n2", "n3", "n4", "n5"]
    df = df[df[main_cols].apply(lambda r: r.between(MAIN_MIN, MAIN_MAX).all(), axis=1)]
    df = df[df["pb"].between(PB_MIN, PB_MAX)]
    df["pp"] = df["pp"].astype(int)

    return df


def analyze(df: pd.DataFrame) -> dict:
    main_cols = ["n1", "n2", "n3", "n4", "n5"]

    # ── Per-position frequencies ──────────────────────────────────────────────
    pos_freq = {col: Counter(df[col].tolist()) for col in main_cols}

    # ── Overall pool (position-agnostic) ─────────────────────────────────────
    all_main   = [v for col in main_cols for v in df[col].tolist()]
    pool_freq  = Counter(all_main)
    pool_total = sum(pool_freq.values())
    pool_prob  = {n: pool_freq.get(n, 0) / pool_total
                  for n in range(MAIN_MIN, MAIN_MAX + 1)}

    # ── Powerball frequencies ─────────────────────────────────────────────────
    pb_freq  = Counter(df["pb"].tolist())
    pb_total = sum(pb_freq.values())
    pb_prob  = {n: pb_freq.get(n, 0) / pb_total
                for n in range(PB_MIN, PB_MAX + 1)}

    # ── Power Play frequencies ────────────────────────────────────────────────
    pp_freq  = Counter(df["pp"].tolist())
    pp_total = sum(pp_freq.values())
    pp_prob  = {v: pp_freq.get(v, 0) / pp_total for v in sorted(pp_freq)}

    # ── Pair co-occurrence ────────────────────────────────────────────────────
    pair_counter = Counter()
    for _, row in df.iterrows():
        nums = sorted(int(row[c]) for c in main_cols)
        for pair in itertools.combinations(nums, 2):
            pair_counter[pair] += 1

    # ── Even / Odd split ──────────────────────────────────────────────────────
    eo_counter = Counter(
        sum(1 for c in main_cols if int(row[c]) % 2 == 0)
        for _, row in df.iterrows()
    )

    # ── Low (1–34) / High (35–69) split ──────────────────────────────────────
    lh_counter = Counter(
        sum(1 for c in main_cols if int(row[c]) <= 34)
        for _, row in df.iterrows()
    )

    # ── Sum stats ────────────────────────────────────────────────────────────
    sums = df[main_cols].sum(axis=1)

    # ── Hot / Cold ───────────────────────────────────────────────────────────
    hot  = [n for n, _ in pool_freq.most_common(10)]
    cold = [n for n, _ in pool_freq.most_common()[-10:]]

    return dict(
        df=df,
        pos_freq=pos_freq,
        pool_freq=pool_freq,
        pool_prob=pool_prob,
        pb_freq=pb_freq,
        pb_prob=pb_prob,
        pp_freq=pp_freq,
        pp_prob=pp_prob,
        pair_counter=pair_counter,
        eo_counter=eo_counter,
        lh_counter=lh_counter,
        sums=sums,
        hot=hot,
        cold=cold,
        total_draws=len(df),
    )


def weighted_pick(prob_dict: dict, k: int) -> list:
    universe = list(prob_dict.keys())
    weights  = np.array([prob_dict[n] for n in universe], dtype=float)
    weights /= weights.sum()
    return list(np.random.choice(universe, size=k, replace=False, p=weights))


STRATEGIES = [
    "Weighted (historical prob)",
    "Uniform Random",
    "Hot Numbers Bias",
    "Cold Numbers Bias",
]
PP_MODES = ["Historical prob", "Uniform random"]


def build_probabilities(strategy: str, stats: dict) -> tuple:
    """Return (main_prob, powerball_prob) dicts for the given strategy name.
    Shared by both the GUI and CLI generators so results are consistent."""
    if strategy == "Uniform Random":
        mp = {n: 1 / MAIN_MAX for n in range(MAIN_MIN, MAIN_MAX + 1)}
        bp = {n: 1 / PB_MAX for n in range(PB_MIN, PB_MAX + 1)}
    elif strategy == "Hot Numbers Bias":
        raw = {n: (stats["pool_freq"].get(n, 0) + 1) ** 2
               for n in range(MAIN_MIN, MAIN_MAX + 1)}
        t = sum(raw.values())
        mp = {n: raw[n] / t for n in raw}
        bp = stats["pb_prob"]
    elif strategy == "Cold Numbers Bias":
        mx = max(stats["pool_freq"].get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)) + 1
        inv = {n: mx - stats["pool_freq"].get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)}
        t = sum(inv.values())
        mp = {n: inv[n] / t for n in inv}
        mx_pb = max(stats["pb_freq"].get(n, 0) for n in range(PB_MIN, PB_MAX + 1)) + 1
        inv_pb = {n: mx_pb - stats["pb_freq"].get(n, 0) for n in range(PB_MIN, PB_MAX + 1)}
        t_pb = sum(inv_pb.values())
        bp = {n: inv_pb[n] / t_pb for n in inv_pb}
    else:  # "Weighted (historical prob)"
        mp = stats["pool_prob"]
        bp = stats["pb_prob"]
    return mp, bp


def build_pp_probabilities(pp_mode: str, stats: dict) -> dict:
    """Return the Power Play probability dict for the given mode."""
    if pp_mode == "Uniform random":
        all_pp = sorted(stats["pp_freq"].keys())
        return {v: 1 / len(all_pp) for v in all_pp}
    return stats["pp_prob"]


def generate_pick(stats: dict, mp: dict, bp: dict, ppp: dict) -> tuple:
    main = sorted(weighted_pick(mp, 5))
    pb   = weighted_pick(bp, 1)[0]
    pp   = weighted_pick(ppp, 1)[0]
    return main, pb, pp


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
            self.title("Powerball Probability Analyzer")
            self.configure(bg=DARK_BG)
            try:
                if sys.platform == "win32":
                    self.state("zoomed")
                elif sys.platform == "darwin":
                    self.geometry("1400x880")
                else:
                    self.attributes("-zoomed", True)
            except Exception:
                self.geometry("1400x880")

            self.stats = None
            self._build_ui()
            self._load()

        def _build_ui(self):
            # Header
            hdr = tk.Frame(self, bg=CARD_BG, height=62)
            hdr.pack(fill="x")
            tk.Label(hdr, text="⚡  Powerball Probability Analyzer",
                     font=("Helvetica", 18, "bold"), fg=ACCENT, bg=CARD_BG,
                     pady=14).pack(side="left", padx=20)
            self.status_lbl = tk.Label(hdr, text="Loading…",
                                       font=("Helvetica", 11), fg=SUBTLE, bg=CARD_BG)
            self.status_lbl.pack(side="right", padx=20)

            # Notebook
            style = ttk.Style(self)
            style.theme_use("clam")
            style.configure("TNotebook",      background=DARK_BG, borderwidth=0)
            style.configure("TNotebook.Tab",  background=CARD_BG, foreground=TEXT_COL,
                            padding=[14, 8],  font=("Helvetica", 11))
            style.map("TNotebook.Tab",
                      background=[("selected", ACCENT)],
                      foreground=[("selected", "#fff")])

            self.nb = ttk.Notebook(self)
            self.nb.pack(fill="both", expand=True, padx=10, pady=(6, 10))

            self.tab_overview  = tk.Frame(self.nb, bg=DARK_BG)
            self.tab_positions = tk.Frame(self.nb, bg=DARK_BG)
            self.tab_pb        = tk.Frame(self.nb, bg=DARK_BG)
            self.tab_pp        = tk.Frame(self.nb, bg=DARK_BG)
            self.tab_relations = tk.Frame(self.nb, bg=DARK_BG)
            self.tab_generate  = tk.Frame(self.nb, bg=DARK_BG)

            self.nb.add(self.tab_overview,  text="📊  Overview")
            self.nb.add(self.tab_positions, text="🎱  Position Analysis")
            self.nb.add(self.tab_pb,        text="🔴  Powerball")
            self.nb.add(self.tab_pp,        text="⚡  Power Play")
            self.nb.add(self.tab_relations, text="🔗  Relationships")
            self.nb.add(self.tab_generate,  text="✨  Generate Numbers")

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
                self._build_pb()
                self._build_pp()
                self._build_relations()
                self._build_generate()
            except Exception as exc:
                messagebox.showerror("Load Error", str(exc))
                self.status_lbl.config(text="❌  Failed to load", fg=ACCENT)

        # ── Overview ──────────────────────────────────────────────────────────────
        def _build_overview(self):
            st  = self.stats
            fig = plt.Figure(figsize=(14, 8), facecolor=DARK_BG)
            gs  = GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)

            # ① Pool frequency bar
            ax1 = fig.add_subplot(gs[0, :])
            nums   = list(range(MAIN_MIN, MAIN_MAX + 1))
            counts = [st["pool_freq"].get(n, 0) for n in nums]
            colors = [PP_COL if n in st["hot"] else (ACCENT if n in st["cold"] else ACCENT2)
                      for n in nums]
            ax1.bar(nums, counts, color=colors, width=0.8)
            ax1.set_title(f"Main Ball Pool — Overall Frequency  ({START_DATE} → today)",
                          color=TEXT_COL, fontsize=12, pad=10)
            ax1.set_xlabel("Ball Number", color=TEXT_COL)
            ax1.set_ylabel("Times Drawn", color=TEXT_COL)
            ax1.set_facecolor(CARD_BG)
            ax1.tick_params(colors=TEXT_COL, labelsize=8)
            for sp in ax1.spines.values(): sp.set_color(SUBTLE)
            ax1.legend(handles=[
                mpatches.Patch(color=PP_COL,  label="Top-10 Hot"),
                mpatches.Patch(color=ACCENT,  label="Bottom-10 Cold"),
                mpatches.Patch(color=ACCENT2, label="Normal"),
            ], facecolor=CARD_BG, labelcolor=TEXT_COL, edgecolor=SUBTLE)

            # ② Even/Odd pie
            ax2 = fig.add_subplot(gs[1, 0])
            eo_labels = [f"{e}E/{5-e}O" for e in range(6)]
            eo_vals   = [st["eo_counter"].get(e, 0) for e in range(6)]
            wedge_c   = [ACCENT2, PP_COL, GREEN, ACCENT, "#c084fc", "#f97316"]
            ax2.pie(eo_vals, labels=eo_labels, colors=wedge_c,
                    autopct="%1.1f%%",
                    textprops={"color": TEXT_COL, "fontsize": 9},
                    wedgeprops={"edgecolor": DARK_BG})
            ax2.set_title("Even / Odd Split per Draw", color=TEXT_COL, fontsize=11, pad=8)

            # ③ Low/High pie
            ax3 = fig.add_subplot(gs[1, 1])
            lh_labels = [f"{l}Low/{5-l}High" for l in range(6)]
            lh_vals   = [st["lh_counter"].get(l, 0) for l in range(6)]
            ax3.pie(lh_vals, labels=lh_labels, colors=wedge_c,
                    autopct="%1.1f%%",
                    textprops={"color": TEXT_COL, "fontsize": 9},
                    wedgeprops={"edgecolor": DARK_BG})
            ax3.set_title("Low (1–34) / High (35–69) Split", color=TEXT_COL, fontsize=11, pad=8)

            self._embed(fig, self.tab_overview)

            # Stats strip
            frm  = tk.Frame(self.tab_overview, bg=DARK_BG)
            frm.pack(fill="x", padx=16, pady=(0, 8))
            sums = st["sums"]
            most_pp = st["pp_freq"].most_common(1)[0]
            items = [
                ("Total Draws Analyzed",  str(st["total_draws"])),
                ("Avg Sum of 5 Balls",    f"{sums.mean():.1f}"),
                ("Sweet-Spot Sum Range",  f"{int(sums.quantile(.25))}–{int(sums.quantile(.75))}"),
                ("Hottest Main Ball",     str(st["hot"][0])),
                ("Coldest Main Ball",     str(st["cold"][0])),
                ("Most Common Powerball", str(st["pb_freq"].most_common(1)[0][0])),
                ("Most Common Power Play",f"{most_pp[0]}x  ({most_pp[1]}×)"),
            ]
            for i, (lbl, val) in enumerate(items):
                card = tk.Frame(frm, bg=CARD_BG, padx=10, pady=8)
                card.grid(row=0, column=i, padx=5, sticky="ew")
                frm.columnconfigure(i, weight=1)
                tk.Label(card, text=val, font=("Helvetica", 13, "bold"),
                         fg=PP_COL, bg=CARD_BG).pack()
                tk.Label(card, text=lbl, font=("Helvetica", 8),
                         fg=TEXT_COL, bg=CARD_BG, wraplength=120).pack()

        # ── Positions ─────────────────────────────────────────────────────────────
        def _build_positions(self):
            st  = self.stats
            fig = plt.Figure(figsize=(14, 9), facecolor=DARK_BG)
            gs  = GridSpec(2, 3, figure=fig, hspace=0.55, wspace=0.4)
            pos_names = ["n1", "n2", "n3", "n4", "n5"]
            colors    = [PP_COL, ACCENT2, GREEN, ACCENT, "#c084fc"]

            for idx, (col, color) in enumerate(zip(pos_names, colors)):
                ax = fig.add_subplot(gs[idx // 3, idx % 3])
                freq  = st["pos_freq"][col]
                nums  = list(range(MAIN_MIN, MAIN_MAX + 1))
                vals  = [freq.get(n, 0) for n in nums]
                ax.bar(nums, vals, color=color, width=0.8, alpha=0.85)
                top3 = sorted(freq, key=freq.get, reverse=True)[:3]
                ax.set_title(f"Position {idx+1}  (Num{idx+1})",
                             color=TEXT_COL, fontsize=10, pad=6)
                ax.set_xlabel(f"Top-3: {top3}", color=TEXT_COL, fontsize=8)
                ax.set_facecolor(CARD_BG)
                ax.tick_params(colors=TEXT_COL, labelsize=7)
                for sp in ax.spines.values(): sp.set_color(SUBTLE)

            # Heatmap
            ax6 = fig.add_subplot(gs[1, 2])
            mat = np.zeros((5, MAIN_MAX))
            for i, col in enumerate(pos_names):
                for n, cnt in st["pos_freq"][col].items():
                    if 1 <= n <= MAIN_MAX:
                        mat[i, n - 1] = cnt
            im = ax6.imshow(mat, aspect="auto", cmap="YlOrRd", origin="upper")
            ax6.set_yticks(range(5))
            ax6.set_yticklabels([f"Pos {i+1}" for i in range(5)],
                                color=TEXT_COL, fontsize=8)
            ax6.set_xlabel("Ball Number (1–69)", color=TEXT_COL, fontsize=8)
            ax6.set_title("Position × Number Heatmap", color=TEXT_COL, fontsize=10, pad=6)
            ax6.tick_params(colors=TEXT_COL, labelsize=7)
            fig.colorbar(im, ax=ax6, fraction=0.04)

            self._embed(fig, self.tab_positions)

        # ── Powerball tab ─────────────────────────────────────────────────────────
        def _build_pb(self):
            st  = self.stats
            fig = plt.Figure(figsize=(13, 7), facecolor=DARK_BG)
            gs  = GridSpec(1, 2, figure=fig, wspace=0.35)

            # Bar
            ax1   = fig.add_subplot(gs[0])
            pbs   = list(range(PB_MIN, PB_MAX + 1))
            cnts  = [st["pb_freq"].get(n, 0) for n in pbs]
            top3  = [n for n, _ in st["pb_freq"].most_common(3)]
            bcols = [PP_COL if n in top3 else ACCENT for n in pbs]
            ax1.bar(pbs, cnts, color=bcols, width=0.7)
            ax1.set_title("Powerball Frequency (1–26)", color=TEXT_COL, fontsize=12, pad=10)
            ax1.set_xlabel("Powerball Number", color=TEXT_COL)
            ax1.set_ylabel("Times Drawn", color=TEXT_COL)
            ax1.set_facecolor(CARD_BG)
            ax1.tick_params(colors=TEXT_COL)
            ax1.set_xticks(pbs)
            for sp in ax1.spines.values(): sp.set_color(SUBTLE)
            ax1.legend(handles=[
                mpatches.Patch(color=PP_COL, label="Top-3"),
                mpatches.Patch(color=ACCENT, label="Others"),
            ], facecolor=CARD_BG, labelcolor=TEXT_COL, edgecolor=SUBTLE)

            # Probability pie
            ax2   = fig.add_subplot(gs[1])
            probs = [st["pb_prob"].get(n, 0) for n in pbs]
            cmap  = plt.get_cmap("plasma")
            pcols = [cmap(i / len(pbs)) for i in range(len(pbs))]
            _, texts, autos = ax2.pie(
                probs, labels=pbs, colors=pcols,
                autopct=lambda p: f"{p:.1f}%" if p > 4.5 else "",
                textprops={"color": TEXT_COL, "fontsize": 8},
                wedgeprops={"edgecolor": DARK_BG},
            )
            for a in autos: a.set_fontsize(7)
            ax2.set_title("Powerball Draw Probability", color=TEXT_COL, fontsize=12, pad=10)

            self._embed(fig, self.tab_pb)

            # Summary strip
            frm = tk.Frame(self.tab_pb, bg=DARK_BG)
            frm.pack(fill="x", padx=16, pady=(0, 8))
            top5  = st["pb_freq"].most_common(5)
            cold5 = st["pb_freq"].most_common()[-5:]
            items = [
                ("🔥 Top-5 Powerballs",  ", ".join(str(n) for n, _ in top5)),
                ("🧊 Cold-5 Powerballs", ", ".join(str(n) for n, _ in cold5)),
                ("📈 Highest Prob PB",   f"{top5[0][0]}  ({top5[0][1]/st['total_draws']*100:.1f}% of draws)"),
            ]
            for i, (lbl, val) in enumerate(items):
                card = tk.Frame(frm, bg=CARD_BG, padx=12, pady=8)
                card.grid(row=0, column=i, padx=8, sticky="ew")
                frm.columnconfigure(i, weight=1)
                tk.Label(card, text=val, font=("Helvetica", 12, "bold"),
                         fg=PP_COL, bg=CARD_BG, wraplength=280).pack()
                tk.Label(card, text=lbl, font=("Helvetica", 9),
                         fg=TEXT_COL, bg=CARD_BG).pack()

        # ── Power Play tab ────────────────────────────────────────────────────────
        def _build_pp(self):
            st  = self.stats
            fig = plt.Figure(figsize=(13, 7), facecolor=DARK_BG)
            gs  = GridSpec(1, 2, figure=fig, wspace=0.40)

            pp_vals  = sorted(st["pp_freq"].keys())
            pp_cnts  = [st["pp_freq"][v] for v in pp_vals]
            pp_total = st["total_draws"]

            # Bar
            ax1 = fig.add_subplot(gs[0])
            bar_colors = [PP_COL, ACCENT2, GREEN, ACCENT, "#c084fc", "#f97316"][:len(pp_vals)]
            bars = ax1.bar([str(v) + "x" for v in pp_vals], pp_cnts,
                           color=bar_colors, width=0.55, edgecolor=DARK_BG)
            for bar, cnt in zip(bars, pp_cnts):
                pct = cnt / pp_total * 100
                ax1.text(bar.get_x() + bar.get_width() / 2,
                         bar.get_height() + 0.2,
                         f"{pct:.1f}%", ha="center", va="bottom",
                         color=TEXT_COL, fontsize=10, fontweight="bold")
            ax1.set_title("Power Play Multiplier Frequency", color=TEXT_COL, fontsize=12, pad=10)
            ax1.set_xlabel("Power Play Value", color=TEXT_COL, fontsize=11)
            ax1.set_ylabel("Times Drawn", color=TEXT_COL)
            ax1.set_facecolor(CARD_BG)
            ax1.tick_params(colors=TEXT_COL, labelsize=11)
            for sp in ax1.spines.values(): sp.set_color(SUBTLE)

            # Pie
            ax2 = fig.add_subplot(gs[1])
            ax2.pie(pp_cnts,
                    labels=[f"{v}x" for v in pp_vals],
                    colors=bar_colors,
                    autopct="%1.1f%%",
                    startangle=140,
                    textprops={"color": TEXT_COL, "fontsize": 11},
                    wedgeprops={"edgecolor": DARK_BG, "linewidth": 1.5})
            ax2.set_title("Power Play Distribution", color=TEXT_COL, fontsize=12, pad=10)

            self._embed(fig, self.tab_pp)

            # Detail table
            frm = tk.Frame(self.tab_pp, bg=DARK_BG)
            frm.pack(fill="x", padx=20, pady=(0, 12))

            hdrs = ["Multiplier", "Times Drawn", "% of Draws", "Approx 1-in-N"]
            col_w = [140, 140, 140, 160]
            hrow  = tk.Frame(frm, bg=SUBTLE)
            hrow.pack(fill="x")
            for h, w in zip(hdrs, col_w):
                tk.Label(hrow, text=h, font=("Helvetica", 10, "bold"),
                         fg=PP_COL, bg=SUBTLE, width=w // 10, anchor="center",
                         pady=5).pack(side="left", padx=1)

            for v in pp_vals:
                cnt  = st["pp_freq"][v]
                pct  = cnt / pp_total * 100
                odds = round(pp_total / cnt) if cnt else "—"
                drow = tk.Frame(frm, bg=CARD_BG)
                drow.pack(fill="x", pady=1)
                for val, w in zip([f"{v}×", str(cnt), f"{pct:.1f}%", f"1 in {odds}"], col_w):
                    tk.Label(drow, text=val, font=("Helvetica", 10),
                             fg=TEXT_COL, bg=CARD_BG, width=w // 10,
                             anchor="center", pady=4).pack(side="left", padx=1)

            # Note on 10x
            note = ("* The 10× Power Play is only available when the jackpot is "
                    "≤ $150 million. Its frequency will be lower in this dataset "
                    "if many draws occurred with higher jackpots.")
            tk.Label(frm, text=note, font=("Helvetica", 8, "italic"),
                     fg=SUBTLE, bg=DARK_BG, wraplength=700, justify="left").pack(
                         anchor="w", padx=4, pady=(6, 0))

        # ── Relationships ─────────────────────────────────────────────────────────
        def _build_relations(self):
            st  = self.stats
            fig = plt.Figure(figsize=(14, 8), facecolor=DARK_BG)
            gs  = GridSpec(1, 2, figure=fig, wspace=0.40)

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
            for sp in ax1.spines.values(): sp.set_color(SUBTLE)

            # Sum histogram
            ax2 = fig.add_subplot(gs[1])
            sums = st["sums"]
            ax2.hist(sums, bins=28, color=GREEN, edgecolor=DARK_BG, linewidth=0.5)
            ax2.axvline(sums.mean(),   color=PP_COL,  linestyle="--",
                        linewidth=1.5, label=f"Mean {sums.mean():.0f}")
            ax2.axvline(sums.median(), color=ACCENT,  linestyle="--",
                        linewidth=1.5, label=f"Median {sums.median():.0f}")
            ax2.set_title("Distribution of Sum of 5 Main Balls",
                          color=TEXT_COL, fontsize=11, pad=10)
            ax2.set_xlabel("Sum", color=TEXT_COL)
            ax2.set_ylabel("Draw Count", color=TEXT_COL)
            ax2.set_facecolor(CARD_BG)
            ax2.tick_params(colors=TEXT_COL)
            for sp in ax2.spines.values(): sp.set_color(SUBTLE)
            ax2.legend(facecolor=CARD_BG, labelcolor=TEXT_COL, edgecolor=SUBTLE)

            self._embed(fig, self.tab_relations)

            # Top-50 pairs scrollable
            frm = tk.Frame(self.tab_relations, bg=DARK_BG)
            frm.pack(fill="x", padx=16, pady=(0, 10))
            tk.Label(frm, text="🔗  Top-50 Most Frequent Pairs",
                     font=("Helvetica", 11, "bold"), fg=PP_COL, bg=DARK_BG).pack(anchor="w")
            txt = scrolledtext.ScrolledText(frm, height=4, bg=CARD_BG, fg=TEXT_COL,
                                            font=("Courier", 9),
                                            insertbackground=TEXT_COL)
            txt.pack(fill="x")
            lines = [f"  {a:>2}-{b:<2}  ×{v}" for (a, b), v in st["pair_counter"].most_common(50)]
            txt.insert("end", "   |  ".join(lines))
            txt.config(state="disabled")

        # ── Generate ──────────────────────────────────────────────────────────────
        def _build_generate(self):
            outer = tk.Frame(self.tab_generate, bg=DARK_BG)
            outer.pack(fill="both", expand=True, padx=30, pady=20)

            tk.Label(outer, text="✨  Smart Powerball Number Generator",
                     font=("Helvetica", 18, "bold"), fg=ACCENT, bg=DARK_BG).pack(pady=(0, 4))
            tk.Label(outer,
                     text="Numbers are generated using weighted probability from historical draws.\n"
                          "Higher-frequency balls have a proportionally greater chance of selection.",
                     font=("Helvetica", 10), fg=TEXT_COL, bg=DARK_BG, justify="center").pack(pady=(0, 18))

            # Controls row
            ctrl = tk.Frame(outer, bg=DARK_BG)
            ctrl.pack(pady=(0, 18))

            tk.Label(ctrl, text="Tickets:", font=("Helvetica", 11),
                     fg=TEXT_COL, bg=DARK_BG).grid(row=0, column=0, padx=(0, 6))
            self.ticket_var = tk.IntVar(value=5)
            tk.Spinbox(ctrl, from_=1, to=20, textvariable=self.ticket_var,
                       width=4, font=("Helvetica", 12),
                       bg=CARD_BG, fg=PP_COL, insertbackground=PP_COL,
                       buttonbackground=SUBTLE).grid(row=0, column=1, padx=(0, 20))

            tk.Label(ctrl, text="Strategy:", font=("Helvetica", 11),
                     fg=TEXT_COL, bg=DARK_BG).grid(row=0, column=2, padx=(0, 6))
            self.strategy_var = tk.StringVar(value="Weighted (historical prob)")
            ttk.Combobox(ctrl, textvariable=self.strategy_var, state="readonly",
                         values=["Weighted (historical prob)",
                                 "Uniform Random",
                                 "Hot Numbers Bias",
                                 "Cold Numbers Bias"],
                         width=26, font=("Helvetica", 11)).grid(row=0, column=3, padx=(0, 20))

            tk.Label(ctrl, text="Power Play:", font=("Helvetica", 11),
                     fg=TEXT_COL, bg=DARK_BG).grid(row=0, column=4, padx=(0, 6))
            self.pp_mode_var = tk.StringVar(value="Historical prob")
            ttk.Combobox(ctrl, textvariable=self.pp_mode_var, state="readonly",
                         values=["Historical prob", "Uniform random"],
                         width=18, font=("Helvetica", 11)).grid(row=0, column=5)

            tk.Button(outer, text="⚡  Generate My Picks",
                      font=("Helvetica", 14, "bold"),
                      bg=ACCENT, fg="#fff", activebackground="#b53320",
                      relief="flat", padx=20, pady=10, cursor="hand2",
                      command=self._do_generate).pack(pady=(0, 20))

            self.result_frame = tk.Frame(outer, bg=DARK_BG)
            self.result_frame.pack(fill="both", expand=True)

        def _do_generate(self):
            if not self.stats:
                return
            for w in self.result_frame.winfo_children():
                w.destroy()

            st        = self.stats
            n_tickets = self.ticket_var.get()
            strategy  = self.strategy_var.get()
            pp_mode   = self.pp_mode_var.get()

            # Build main probability dict
            if strategy == "Uniform Random":
                mp = {n: 1 / MAIN_MAX for n in range(MAIN_MIN, MAIN_MAX + 1)}
                bp = {n: 1 / PB_MAX   for n in range(PB_MIN,   PB_MAX + 1)}
            elif strategy == "Hot Numbers Bias":
                raw = {n: (st["pool_freq"].get(n, 0) + 1) ** 2
                       for n in range(MAIN_MIN, MAIN_MAX + 1)}
                t = sum(raw.values())
                mp = {n: raw[n] / t for n in raw}
                bp = st["pb_prob"]
            elif strategy == "Cold Numbers Bias":
                mx = max(st["pool_freq"].get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)) + 1
                inv = {n: mx - st["pool_freq"].get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)}
                t   = sum(inv.values())
                mp  = {n: inv[n] / t for n in inv}
                mx_pb = max(st["pb_freq"].get(n, 0) for n in range(PB_MIN, PB_MAX + 1)) + 1
                inv_pb = {n: mx_pb - st["pb_freq"].get(n, 0) for n in range(PB_MIN, PB_MAX + 1)}
                t_pb   = sum(inv_pb.values())
                bp     = {n: inv_pb[n] / t_pb for n in inv_pb}
            else:  # Weighted
                mp = st["pool_prob"]
                bp = st["pb_prob"]

            # Power Play probability dict
            if pp_mode == "Uniform random":
                all_pp = sorted(st["pp_freq"].keys())
                ppp = {v: 1 / len(all_pp) for v in all_pp}
            else:
                ppp = st["pp_prob"]

            picks = [generate_pick(st, mp, bp, ppp) for _ in range(n_tickets)]

            cf = tk.Frame(self.result_frame, bg=DARK_BG)
            cf.pack(fill="both", expand=True)
            tk.Label(cf,
                     text=f"Generated {n_tickets} ticket(s)  —  Strategy: {strategy}  |  PP: {pp_mode}",
                     font=("Helvetica", 10, "italic"), fg=SUBTLE, bg=DARK_BG).pack(pady=(0, 10))

            for i, (main, pb, pp) in enumerate(picks):
                row = tk.Frame(cf, bg=CARD_BG, pady=10, padx=12)
                row.pack(fill="x", pady=4)

                tk.Label(row, text=f"Ticket {i+1:>2}", font=("Helvetica", 11, "bold"),
                         fg=SUBTLE, bg=CARD_BG, width=9).pack(side="left")

                for num in main:
                    self._ball(row, num, ACCENT2, "#fff")

                tk.Label(row, text=" + ", fg=SUBTLE, bg=CARD_BG,
                         font=("Helvetica", 13, "bold")).pack(side="left")
                self._ball(row, pb, ACCENT, "#fff")    # red Powerball

                tk.Label(row, text="  PP:", fg=SUBTLE, bg=CARD_BG,
                         font=("Helvetica", 11)).pack(side="left", padx=(6, 2))
                self._badge(row, f"{pp}×", PP_COL)    # gold Power Play badge

                # Quick stats
                s     = sum(main)
                evens = sum(1 for n in main if n % 2 == 0)
                lows  = sum(1 for n in main if n <= 34)
                info  = f"  Sum={s}  |  {evens}E/{5-evens}O  |  {lows}Low/{5-lows}High"
                tk.Label(row, text=info, font=("Courier", 9),
                         fg=TEXT_COL, bg=CARD_BG).pack(side="left", padx=8)

        # ── Helpers ───────────────────────────────────────────────────────────────
        def _ball(self, parent, number, bg_color, fg_color):
            frm = tk.Frame(parent, bg=bg_color, width=38, height=38)
            frm.pack(side="left", padx=3)
            frm.pack_propagate(False)
            tk.Label(frm, text=str(number), font=("Helvetica", 11, "bold"),
                     fg=fg_color, bg=bg_color).place(relx=0.5, rely=0.5, anchor="center")

        def _badge(self, parent, text, bg_color):
            frm = tk.Frame(parent, bg=bg_color, padx=6, pady=2)
            frm.pack(side="left", padx=2)
            tk.Label(frm, text=text, font=("Helvetica", 11, "bold"),
                     fg="#000", bg=bg_color).pack()

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
            n_tickets, strategy, pp_mode = self._prompt_inputs()
            self._generate_and_print(n_tickets, strategy, pp_mode)
            again = input(f"\n{Ansi.GRAY}Generate another batch? [y/N]: {Ansi.RESET}").strip().lower()
            if again != "y":
                break
        print(f"\n{Ansi.GOLD}Good luck! 🍀{Ansi.RESET}\n")

    def _banner(self):
        bar = "=" * 64
        print(f"\n{Ansi.BOLD}{Ansi.GOLD}{bar}")
        print("   ⚡  POWERBALL PROBABILITY ANALYZER  —  CLI / SSH MODE")
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
        pp_mode = prompt_choice("\nPower Play mode:", PP_MODES, default_idx=0)
        return n_tickets, strategy, pp_mode

    def _generate_and_print(self, n_tickets: int, strategy: str, pp_mode: str):
        mp, bp = build_probabilities(strategy, self.stats)
        ppp = build_pp_probabilities(pp_mode, self.stats)
        print(f"\n{Ansi.GRAY}Generated {n_tickets} ticket(s) — "
              f"Strategy: {strategy}  |  PP: {pp_mode}{Ansi.RESET}\n")
        for i in range(n_tickets):
            main, pb, pp = generate_pick(self.stats, mp, bp, ppp)
            self._print_ticket(i + 1, main, pb, pp)

    def _print_ticket(self, idx: int, main: list, pb: int, pp: int):
        main_str = "  ".join(f"{Ansi.BLUE}[{n:>2}]{Ansi.RESET}" for n in main)
        pb_str = f"{Ansi.RED}[{pb:>2}]{Ansi.RESET}"
        pp_str = f"{Ansi.GOLD}{pp}×{Ansi.RESET}"
        s = sum(main)
        evens = sum(1 for n in main if n % 2 == 0)
        lows = sum(1 for n in main if n <= 34)
        info = f"Sum={s}  {evens}E/{5-evens}O  {lows}Low/{5-lows}High"
        print(f"  Ticket {idx:>2}:  {main_str}  +  {pb_str}   PP:{pp_str}    "
              f"{Ansi.GRAY}{info}{Ansi.RESET}")


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Powerball Probability Analyzer")
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