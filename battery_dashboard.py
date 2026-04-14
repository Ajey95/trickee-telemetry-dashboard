"""
⚡ Trickee — CAN Flash Fleet Dashboard
Multi-vehicle battery intelligence from real GreenFuel e-rickshaw telemetry.
12 vehicles · 30-second CAN Bus resolution · Sep–Apr (10 months)
"""

import os, time, glob
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG & THEME
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Trickee · Fleet Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

BG     = "#0a0e1a"
CARD   = "#111827"
CARD2  = "#1a2235"
GREEN  = "#00ff9f"
CYAN   = "#00d4ff"
GOLD   = "#f59e0b"
RED    = "#ef4444"
DIM    = "#6b7280"
WHITE  = "#f9fafb"
PURPLE = "#8b5cf6"

DARK_LAYOUT = dict(
    paper_bgcolor=CARD, plot_bgcolor=CARD,
    font=dict(color=WHITE, family="Inter, sans-serif"),
    margin=dict(l=12, r=12, t=36, b=12),
)

ANNO = lambda text, color, y: dict(
    text=text, x=1.01, xref="paper", y=y, yref="y",
    showarrow=False, font=dict(color=color, size=10), xanchor="left"
)

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Space+Grotesk:wght@500;700&display=swap');
  html, body, [class*="css"] {{
      font-family: 'Inter', sans-serif;
      background-color: {BG};
      color: {WHITE};
  }}
  .block-container {{ padding: 1.2rem 2rem 2rem; background: {BG}; }}
  [data-testid="stSidebar"] {{ background: {CARD}; border-right: 1px solid #1f2937; }}
  .stTabs [data-baseweb="tab-list"] {{ background: {CARD2}; border-radius: 10px; gap:4px; padding:4px; }}
  .stTabs [data-baseweb="tab"] {{ background: transparent; color: {DIM}; border-radius: 8px; font-size:13px; font-weight:500; padding: 6px 16px; }}
  .stTabs [aria-selected="true"] {{ background: {BG}; color: {WHITE}; }}
  .stSlider [data-testid="stSlider"] > div {{ color: {GREEN}; }}
  div[data-testid="metric-container"] {{
      background: {CARD2}; border-radius: 12px; padding: 16px 18px;
      border: 1px solid #1f2937;
  }}
  div[data-testid="metric-container"] label {{ color: {DIM} !important; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }}
  div[data-testid="metric-container"] [data-testid="metric-value"] {{ font-size: 28px; font-weight: 700; color: {WHITE}; }}
  .kpi-card {{ background:{CARD2}; border:1px solid #1f2937; border-radius:12px; padding:16px; }}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
#  DATA PATHS (Hugging Face Datasets)
# ─────────────────────────────────────────────────────────────────────────────
# CHANGE THIS TO YOUR HUGGING FACE USERNAME:
HF_USER = "Ajeya95"  

HF_BASE_URL = f"https://huggingface.co/datasets/{HF_USER}/EV-Telemetry/resolve/main"

VEHICLES = sorted([
    "CGF24D0001", "CGF24D0002", "CGF24D0005", "CGF24D0006", 
    "CGF24D0009", "CGF24D0010", "CGF24D0013", "CGF24D0014",
    "CGF24D0017", "CGF24D0018", "CGF24D0021", "CGF24D0022"
])

CELL_COLS = [f"cell_voltage_{i:02d}" for i in range(1, 17)]
TEMP_COLS = ["cell_temperature_01", "cell_temperature_02", "cell_temperature_03"]
ALERT_COLS = [
    "alert_cell_over_voltage", "alert_cell_under_voltage",
    "alert_over_temp", "alert_under_temp",
    "alert_thermal_runaway", "alert_short_circuit",
    "alert_over_current_discharging", "alert_for_cell_difference",
]
ALERT_LABELS = ["Cell OV", "Cell UV", "Over Temp", "Under Temp",
                "Thermal Runaway", "Short Circuit", "Overcurrent Dis.", "Cell Diff"]

# ─────────────────────────────────────────────────────────────────────────────
#  DATA LOADER  — Blazing fast pre-processed Parquet from Hugging Face
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Loading vehicle data…")
def load_vehicle(vehicle_id: str, sample: int = 1) -> pd.DataFrame:
    """Load pre-processed CAN Parquet from Hugging Face."""
    
    url = f"{HF_BASE_URL}/{vehicle_id}_can.parquet"
    
    # FOR LOCAL TESTING BEFORE UPLOADING TO HF, UNCOMMENT THIS LINE:
    # url = os.path.join(r"C:\Users\sister\Downloads\Trickee\battery_data\hf_export", f"{vehicle_id}_can.parquet")
    
    try:
        df = pd.read_parquet(url)
        # It's already sampled by 10x in prep script, but we can sample more here if requested
        if sample > 1:
            df = df.iloc[::sample].reset_index(drop=True)
        
        # Prevent catastrophic KeyError in Deep Dive tab
        if "current" in df.columns and "battery_voltage" in df.columns:
            df["power"] = df["current"] * df["battery_voltage"]
            
        return df
    except Exception as e:
        print(f"Failed to load {url}: {e}")
        return pd.DataFrame()

def load_all_fleet(sample: int = 5) -> dict:
    # No @st.cache_data needed here since load_vehicle is already cached.
    # Caching this large dict of DataFrames causes Streamlit MemoryErrors.
    fleet = {}
    for v in VEHICLES:
        fleet[v] = load_vehicle(v, sample)
    return fleet


# ─────────────────────────────────────────────────────────────────────────────
#  SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
if "step"    not in st.session_state: st.session_state.step    = 0
if "playing" not in st.session_state: st.session_state.playing = False
if "spd"     not in st.session_state: st.session_state.spd     = 2.0

# ─────────────────────────────────────────────────────────────────────────────
#  SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"<h2 style='color:{GREEN};font-family:Space Grotesk;margin:0'>⚡ Trickee</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{DIM};font-size:12px;margin-top:2px'>CAN Flash Fleet · 12 Vehicles</p>", unsafe_allow_html=True)
    st.divider()

    view = st.radio("📊 View Mode",
                    ["🏢 Fleet Manager", "🗺️ GPS Fleet Map", "🚗 Vehicle Deep Dive"],
                    label_visibility="collapsed")

    st.divider()
    st.markdown(f"<p style='color:{DIM};font-size:11px;text-transform:uppercase;letter-spacing:1px'>DATA RESOLUTION</p>", unsafe_allow_html=True)
    sample_n = st.select_slider("Sample every N rows", options=[1, 2, 5], value=1,
                                help="1=5-min intervals (recommended), 5=25-min")

    st.divider()
    st.markdown(f"<p style='color:{DIM};font-size:11px;text-transform:uppercase;letter-spacing:1px'>REPLAY ENGINE</p>", unsafe_allow_html=True)

    # Load fleet (cached)
    fleet = load_all_fleet(sample_n)

    # Use first vehicle to determine replay length
    anchor_df = fleet[VEHICLES[0]]
    N = len(anchor_df)

    step = st.slider("⏱ Timeline", 0, max(N - 1, 1), st.session_state.step, key="slider_main")
    st.session_state.step = step

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("⏮", use_container_width=True): st.session_state.step = 0; st.session_state.playing = False
    with col_b:
        lbl = "⏸" if st.session_state.playing else "▶"
        if st.button(lbl, use_container_width=True): st.session_state.playing = not st.session_state.playing
    with col_c:
        if st.button("⏭", use_container_width=True): st.session_state.step = N - 1; st.session_state.playing = False

    st.session_state.spd = st.slider("Speed ×", 0.5, 8.0, st.session_state.spd, 0.5)

    st.divider()
    if view in ("🚗 Vehicle Deep Dive", "🗺️ GPS Fleet Map"):
        sel_vehicle = st.selectbox("Select Vehicle", VEHICLES)

    st.markdown(f"""
    <div style='background:{CARD2};border-radius:10px;padding:12px;margin-top:8px;border:1px solid #1f2937'>
        <p style='color:{DIM};font-size:10px;text-transform:uppercase;letter-spacing:1px;margin:0 0 6px'>Fleet</p>
        <p style='color:{WHITE};font-size:13px;font-weight:600;margin:0'>GreenFuel EV · India</p>
        <p style='color:{DIM};font-size:11px;margin:2px 0 0'>{len(VEHICLES)} vehicles · 48V LFP · 16S</p>
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def safe_row(df, step, total_steps):
    """Return the row proportional to the replay position across any-length df."""
    if df.empty or total_steps == 0: return None
    frac = step / max(total_steps - 1, 1)
    idx  = int(round(frac * (len(df) - 1)))
    idx  = max(0, min(idx, len(df) - 1))
    return df.iloc[idx]

def color_soc(soc):
    if soc >= 60: return GREEN
    if soc >= 30: return GOLD
    return RED

def color_temp(t):
    if pd.isna(t): return DIM
    if t < 38: return GREEN
    if t < 45: return GOLD
    return RED

@st.cache_resource(show_spinner="Loading GPS data…")
def load_gps(vehicle_id: str, sample: int = 1) -> pd.DataFrame:
    """Load pre-processed GPS Parquet from Hugging Face."""
    url = f"{HF_BASE_URL}/{vehicle_id}_gps.parquet"
    
    # FOR LOCAL TESTING BEFORE UPLOADING TO HF, UNCOMMENT THIS LINE:
    # url = os.path.join(r"C:\Users\sister\Downloads\Trickee\battery_data\hf_export", f"{vehicle_id}_gps.parquet")
    
    try:
        df = pd.read_parquet(url)
        if sample > 1:
            df = df.iloc[::sample].reset_index(drop=True)
        return df
    except:
        return pd.DataFrame()

def load_all_gps(sample: int = 20) -> pd.DataFrame:
    # No @st.cache_data needed here either to avoid MemoryError.
    frames = []
    for v in VEHICLES:
        gdf = load_gps(v, sample)
        if not gdf.empty:
            frames.append(gdf)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def sparkline(series, color, height=60):
    s = series.dropna()
    fig = go.Figure(go.Scatter(y=s, mode="lines", line=dict(color=color, width=1.5),
                               fill="tozeroy", fillcolor=color.replace(")", ",0.08)").replace("rgb","rgba")))
    fig.update_layout(height=height, margin=dict(l=0,r=0,t=0,b=0),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig

# ─────────────────────────────────────────────────────────────────────────────
#  FLEET MANAGER VIEW
# ─────────────────────────────────────────────────────────────────────────────
def FleetManagerView():
    step = st.session_state.step

    # Collect current state for all vehicles — normalized so all vehicles stay in sync
    rows = []
    for v, df in fleet.items():
        r = safe_row(df, step, N)
        if r is not None:
            rows.append(r)

    if not rows:
        st.warning("No data loaded."); return

    # ── HEADER ────────────────────────────────────────────────────────────────
    ts = rows[0]["time"] if "time" in rows[0] else "—"
    ts_str = pd.Timestamp(ts).strftime("%b %d, %Y  %H:%M") if ts != "—" else "—"
    st.markdown(f"""
    <div style='display:flex;align-items:center;gap:16px;margin-bottom:16px'>
      <h1 style='font-family:Space Grotesk;font-size:22px;font-weight:700;color:{WHITE};margin:0'>
        🏢 Fleet Intelligence Dashboard
      </h1>
      <span style='background:{CARD2};border:1px solid #1f2937;border-radius:8px;
             padding:4px 12px;font-size:12px;color:{DIM}'>
        Step {step+1}/{N} &nbsp;·&nbsp; {len(VEHICLES)} Vehicles &nbsp;·&nbsp; {ts_str}
      </span>
    </div>
    """, unsafe_allow_html=True)

    # ── KPI ROW ───────────────────────────────────────────────────────────────
    avg_soc  = np.mean([r["soc"] for r in rows])
    avg_soh  = np.mean([r["soh"] for r in rows])
    charging = sum(1 for r in rows if r.get("charge_label") == "Charging")
    discharging = sum(1 for r in rows if r.get("charge_label") == "Discharging")
    avg_cycles = np.mean([r["charge_cycle"] for r in rows])
    min_soh_v  = min(rows, key=lambda r: r["soh"])

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Fleet Avg SOC", f"{avg_soc:.1f}%")
    k2.metric("Fleet Avg SOH", f"{avg_soh:.1f}%")
    k3.metric("Charging Now", int(charging))
    k4.metric("Discharging", int(discharging))
    k5.metric("Avg Charge Cycles", f"{avg_cycles:.0f}")

    st.divider()

    # ── TABS ──────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Fleet Status", "🔋 Battery Health", "🔬 Cell Analysis",
        "🌡️ Thermal Monitor", "🚨 Fault Monitor"
    ])

    # ── TAB 1: Fleet Status ────────────────────────────────────────────────────
    with tab1:
        c1, c2 = st.columns([3, 2])

        with c1:
            # SOC bar chart
            vids  = [r["vehicle_id"] for r in rows]
            socs  = [r["soc"] for r in rows]
            clrs  = [color_soc(s) for s in socs]
            lbls  = [r.get("charge_label","—") for r in rows]
            fig_soc = go.Figure(go.Bar(
                x=vids, y=socs, marker_color=clrs,
                text=[f"{s:.0f}%" for s in socs], textposition="auto",
                customdata=lbls,
                hovertemplate="%{x}<br>SOC: %{y:.1f}%<br>State: %{customdata}<extra></extra>"
            ))
            fig_soc.add_hline(y=20, line=dict(color=RED, dash="dash", width=1),
                              annotation_text="Low SOC threshold")
            fig_soc.update_layout(**DARK_LAYOUT, height=300,
                                  title="State of Charge — All Vehicles",
                                  yaxis=dict(range=[0,105], title="SOC (%)"),
                                  xaxis=dict(title=""))
            st.plotly_chart(fig_soc, use_container_width=True)

        with c2:
            # State distribution pie
            states = {"Charging": charging, "Discharging": discharging,
                      "Idle": len(rows) - charging - discharging}
            fig_pie = go.Figure(go.Pie(
                labels=list(states.keys()),
                values=list(states.values()),
                hole=0.55,
                marker=dict(colors=[GREEN, CYAN, DIM]),
            ))
            fig_pie.update_traces(textfont=dict(color=WHITE, size=12))
            fig_pie.update_layout(**DARK_LAYOUT, height=300,
                                  title="Fleet State Distribution",
                                  showlegend=True,
                                  legend=dict(font=dict(color=DIM, size=11)))
            st.plotly_chart(fig_pie, use_container_width=True)

        # Vehicle cards
        st.markdown(f"<p style='color:{DIM};font-size:11px;text-transform:uppercase;letter-spacing:1px'>Vehicle Cards</p>", unsafe_allow_html=True)
        cols = st.columns(min(len(rows), 4))
        for i, r in enumerate(rows):
            col = cols[i % 4]
            soc = r["soc"]
            state = r.get("charge_label","—")
            state_icon = {"Charging":"🔌","Discharging":"🏃","Idle":"💤"}.get(state,"❓")
            soc_color = color_soc(soc)
            col.markdown(f"""
            <div class='kpi-card' style='margin-bottom:8px;border-left:3px solid {soc_color}'>
              <p style='color:{DIM};font-size:10px;margin:0'>{r["vehicle_id"]}</p>
              <p style='color:{soc_color};font-size:22px;font-weight:700;margin:2px 0'>{soc:.0f}%</p>
              <p style='color:{WHITE};font-size:11px;margin:0'>{state_icon} {state}</p>
              <p style='color:{DIM};font-size:10px;margin:2px 0 0'>V: {r["battery_voltage"]:.2f}V · I: {r["current"]:.1f}A</p>
            </div>
            """, unsafe_allow_html=True)

    # ── TAB 2: Battery Health ──────────────────────────────────────────────────
    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            # SOH bar chart
            sohs = [r["soh"] for r in rows]
            fig_soh = go.Figure(go.Bar(
                x=vids, y=sohs,
                marker_color=[GREEN if s > 85 else (GOLD if s > 70 else RED) for s in sohs],
                text=[f"{s}%" for s in sohs], textposition="auto",
            ))
            fig_soh.add_hline(y=80, line=dict(color=GOLD, dash="dash", width=1),
                              annotation_text="Service threshold")
            fig_soh.update_layout(**DARK_LAYOUT, height=320,
                                  title="State of Health (SOH)",
                                  yaxis=dict(range=[50,105], title="SOH (%)"))
            st.plotly_chart(fig_soh, use_container_width=True)

        with c2:
            # Charge cycles
            cycles = [r["charge_cycle"] for r in rows]
            fig_cyc = go.Figure(go.Bar(
                x=vids, y=cycles,
                marker_color=[PURPLE if c < 300 else (GOLD if c < 600 else RED) for c in cycles],
                text=[f"{int(c)}" for c in cycles], textposition="auto",
            ))
            fig_cyc.add_hline(y=500, line=dict(color=GOLD, dash="dash", width=1),
                              annotation_text="Warranty watch (500)")
            fig_cyc.update_layout(**DARK_LAYOUT, height=320,
                                  title="Charge Cycle Count",
                                  yaxis=dict(title="Cycles"))
            st.plotly_chart(fig_cyc, use_container_width=True)

        # Pack voltage comparison
        voltages = [r["battery_voltage"] for r in rows]
        fig_v = go.Figure(go.Bar(
            x=vids, y=voltages,
            marker_color=CYAN,
            text=[f"{v:.2f}V" for v in voltages], textposition="auto",
        ))
        fig_v.update_layout(**DARK_LAYOUT, height=260,
                            title="Pack Voltage — All Vehicles",
                            yaxis=dict(title="Voltage (V)"))
        st.plotly_chart(fig_v, use_container_width=True)

    # ── TAB 3: Cell Analysis ───────────────────────────────────────────────────
    with tab3:
        # Cell voltage heatmap — all vehicles × 16 cells
        heat_data = []
        for r in rows:
            row_vals = [r.get(c, np.nan) for c in CELL_COLS]
            heat_data.append(row_vals)

        fig_heat = go.Figure(go.Heatmap(
            z=heat_data,
            x=[f"C{i}" for i in range(1, 17)],
            y=vids,
            colorscale=[[0,"#ef4444"],[0.4,"#f59e0b"],[0.7,"#00d4ff"],[1.0,"#00ff9f"]],
            colorbar=dict(title="Volts", tickfont=dict(color=DIM)),
            text=[[f"{v:.3f}" for v in row] for row in heat_data],
            texttemplate="%{text}",
            hoverongaps=False,
        ))
        fig_heat.update_layout(**DARK_LAYOUT, height=380,
                               title="Cell Voltage Heatmap — 12 Vehicles × 16 Cells  (Green = Balanced | Red = Low)")
        st.plotly_chart(fig_heat, use_container_width=True)

        # Imbalance bar
        imbalances = [r.get("cell_imbalance_mv", 0) for r in rows]
        clr_imb = [GREEN if v < 20 else (GOLD if v < 50 else RED) for v in imbalances]
        fig_imb = go.Figure(go.Bar(
            x=vids, y=imbalances,
            marker_color=clr_imb,
            text=[f"{v:.1f} mV" for v in imbalances], textposition="auto",
        ))
        fig_imb.add_hline(y=20, line=dict(color=GREEN, dash="dot", width=1), annotation_text="Healthy <20 mV")
        fig_imb.add_hline(y=50, line=dict(color=RED, dash="dash", width=1), annotation_text="Action >50 mV")
        fig_imb.update_layout(**DARK_LAYOUT, height=280,
                              title="Pack Imbalance (Max – Min Cell Voltage)",
                              yaxis=dict(title="Imbalance (mV)"))
        st.plotly_chart(fig_imb, use_container_width=True)

    # ── TAB 4: Thermal Monitor ─────────────────────────────────────────────────
    with tab4:
        cols_t = st.columns(3)
        for i, tc in enumerate(TEMP_COLS):
            with cols_t[i]:
                temps = [r.get(tc, np.nan) for r in rows]
                fig_t = go.Figure(go.Bar(
                    x=vids, y=temps,
                    marker_color=[color_temp(t) for t in temps],
                    text=[f"{t:.0f}°C" if not np.isnan(t) else "–" for t in temps],
                    textposition="auto",
                ))
                # Named threshold lines
                fig_t.add_hline(y=45, line=dict(color=RED,  dash="dash", width=1.5),
                                annotation_text="🔴 Critical 45°C",
                                annotation_position="top left",
                                annotation_font=dict(color=RED, size=10))
                fig_t.add_hline(y=38, line=dict(color=GOLD, dash="dot",  width=1.5),
                                annotation_text="🟡 Monitor 38°C",
                                annotation_position="bottom right",
                                annotation_font=dict(color=GOLD, size=10))
                fig_t.update_layout(**DARK_LAYOUT, height=280,
                                    title=f"Temperature Sensor {i+1} (°C)",
                                    yaxis=dict(range=[0, 65]))
                st.plotly_chart(fig_t, use_container_width=True)

        # Thermal abuse scatter — all vehicles
        scatter_t, scatter_c, scatter_id = [], [], []
        for r in rows:
            t1 = r.get("cell_temperature_01", np.nan)
            cur = r.get("current", 0)
            if not np.isnan(t1):
                scatter_t.append(t1)
                scatter_c.append(abs(cur))
                scatter_id.append(r["vehicle_id"])

        fig_abuse = go.Figure()
        # Warranty risk zone
        fig_abuse.add_shape(type="rect", x0=38, x1=70, y0=30, y1=120,
                           fillcolor="rgba(239,68,68,0.08)", line_width=0)
        fig_abuse.add_annotation(text="⚠️ Warranty Risk Zone", x=53, y=110,
                                 showarrow=False, font=dict(color=RED, size=11))
        # Threshold lines
        fig_abuse.add_vline(x=38, line=dict(color=GOLD, dash="dot", width=1))
        fig_abuse.add_vline(x=45, line=dict(color=RED,  dash="dash", width=1))
        fig_abuse.add_annotation(text="Monitor 38°C", x=38.5, y=5,
                                 showarrow=False, font=dict(color=GOLD, size=9), xanchor="left")
        fig_abuse.add_annotation(text="Critical 45°C", x=45.5, y=5,
                                 showarrow=False, font=dict(color=RED, size=9), xanchor="left")

        fig_abuse.add_scatter(x=scatter_t, y=scatter_c, mode="markers+text",
                              text=scatter_id, textposition="top center",
                              marker=dict(size=18, color=[
                                  RED if t > 45 else (GOLD if t > 38 else GREEN)
                                  for t in scatter_t
                              ], line=dict(color=WHITE, width=1)),
                              textfont=dict(color=DIM, size=10))
        fig_abuse.update_layout(**DARK_LAYOUT, height=340,
                                title="🌡️ Thermal Abuse Monitor (Temp vs Current Draw)",
                                xaxis=dict(title="Temperature Sensor 1 (°C)"),
                                yaxis=dict(title="|Current| (A)"))
        st.plotly_chart(fig_abuse, use_container_width=True)

    # ── TAB 5: Fault Monitor ───────────────────────────────────────────────────
    with tab5:
        st.markdown(f"<p style='color:{DIM};font-size:11px;text-transform:uppercase;letter-spacing:1px'>Live Fault Grid — Any Active Alerts?</p>", unsafe_allow_html=True)

        fault_data = {lbl: [] for lbl in ALERT_LABELS}
        for r in rows:
            for col, lbl in zip(ALERT_COLS, ALERT_LABELS):
                fault_data[lbl].append(int(r.get(col, 0)) if pd.notna(r.get(col, np.nan)) else 0)

        fig_faults = go.Figure(go.Heatmap(
            z=[[fault_data[lbl][i] for lbl in ALERT_LABELS] for i in range(len(rows))],
            x=ALERT_LABELS,
            y=vids,
            colorscale=[[0, "#0a2e0a"], [0.01, "#0a2e0a"], [0.01, RED], [1, RED]],
            showscale=False,
            text=[["🟢" if fault_data[lbl][i] == 0 else "🔴" for lbl in ALERT_LABELS] for i in range(len(rows))],
            texttemplate="%{text}",
        ))
        fig_faults.update_layout(**DARK_LAYOUT, height=360,
                                 title="Fault Monitor — Green = Clear | Red = Alert Active")
        st.plotly_chart(fig_faults, use_container_width=True)

        # Fault count summary
        total_faults = sum(sum(fault_data[lbl]) for lbl in ALERT_LABELS)
        if total_faults == 0:
            st.success("✅ No active alerts across the fleet at this timestep.")
        else:
            st.error(f"⚠️ {total_faults} active fault(s) detected!")


# ─────────────────────────────────────────────────────────────────────────────
#  VEHICLE DEEP DIVE VIEW
# ─────────────────────────────────────────────────────────────────────────────
def VehicleDeepDive(vehicle_id):
    df = fleet.get(vehicle_id, pd.DataFrame())
    if df.empty:
        st.error(f"No data for {vehicle_id}")
        return

    step = st.session_state.step
    idx  = min(step, len(df) - 1)
    r    = df.iloc[idx]

    ts_str = pd.Timestamp(r["time"]).strftime("%b %d, %Y  %H:%M")
    soc    = r["soc"]
    soh    = r["soh"]
    cur    = r["current"]
    volt   = r["battery_voltage"]
    t1     = r.get("cell_temperature_01", np.nan)

    st.markdown(f"""
    <div style='display:flex;align-items:center;gap:16px;margin-bottom:16px'>
      <h1 style='font-family:Space Grotesk;font-size:22px;font-weight:700;color:{WHITE};margin:0'>
        🚗 {vehicle_id}
      </h1>
      <span style='background:{CARD2};border:1px solid #1f2937;border-radius:8px;
             padding:4px 12px;font-size:12px;color:{DIM}'>
        Step {step+1}/{len(df)} &nbsp;·&nbsp; {ts_str}
      </span>
    </div>
    """, unsafe_allow_html=True)

    # KPIs
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("State of Charge", f"{soc:.1f}%",
              delta=f"{soc - df.iloc[max(0,idx-1)]['soc']:.1f}%" if idx > 0 else None,
              delta_color="normal")
    k2.metric("State of Health", f"{soh:.1f}%")
    k3.metric("Pack Voltage", f"{volt:.2f} V")
    k4.metric("Current", f"{cur:.2f} A",
              delta="Charging" if cur < -1 else ("Discharging" if cur > 1 else "Idle"),
              delta_color="normal" if cur < -1 else ("inverse" if cur > 1 else "off"))
    k5.metric("Charge Cycles", f"{int(r['charge_cycle'])}")

    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Timeline", "🔬 Cell Analysis", "🌡️ Thermal", "🚨 Faults"
    ])

    window = df.iloc[max(0, idx - 200): idx + 1]

    # Tab 1 — Timeline
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            fig_soc = go.Figure(go.Scatter(
                x=window["time"], y=window["soc"],
                mode="lines", line=dict(color=GREEN, width=2),
                fill="tozeroy", fillcolor="rgba(0,255,159,0.06)"
            ))
            fig_soc.add_scatter(x=[r["time"]], y=[soc],
                                mode="markers", marker=dict(color=WHITE, size=8, symbol="circle"))
            fig_soc.update_layout(**DARK_LAYOUT, height=280, title="SOC Timeline (%)",
                                  yaxis=dict(range=[0,105]))
            st.plotly_chart(fig_soc, use_container_width=True)

        with c2:
            clrs_cur = [GREEN if c < 0 else (CYAN if c > 1 else DIM) for c in window["current"]]
            fig_cur = go.Figure(go.Bar(
                x=window["time"], y=window["current"],
                marker_color=clrs_cur,
            ))
            fig_cur.add_hline(y=0, line=dict(color=DIM, width=1))
            fig_cur.update_layout(**DARK_LAYOUT, height=280,
                                  title="Current Flow (A)  [Green=Charging, Cyan=Discharging]")
            st.plotly_chart(fig_cur, use_container_width=True)

        # Power timeline
        fig_pwr = go.Figure(go.Scatter(
            x=window["time"], y=window["power"] / 1000,
            mode="lines", line=dict(color=PURPLE, width=1.5),
        ))
        fig_pwr.add_hline(y=0, line=dict(color=DIM, width=1))
        fig_pwr.update_layout(**DARK_LAYOUT, height=220, title="Power Draw (kW)")
        st.plotly_chart(fig_pwr, use_container_width=True)

    # Tab 2 — Cell Analysis
    with tab2:
        cell_vals = [r.get(c, np.nan) for c in CELL_COLS]
        cell_vals_clean = [v for v in cell_vals if not np.isnan(v)]
        if cell_vals_clean:
            avg_cv = np.mean(cell_vals_clean)
            bar_clr = [
                GREEN if abs(v - avg_cv) < 0.025 else
                (GOLD if abs(v - avg_cv) < 0.050 else RED)
                for v in cell_vals
            ]
            fig_cells = go.Figure(go.Bar(
                x=[f"C{i+1}" for i in range(16)],
                y=cell_vals,
                marker_color=bar_clr,
                text=[f"{v:.3f}" for v in cell_vals],
                textposition="auto",
            ))
            fig_cells.add_hline(y=avg_cv, line=dict(color=WHITE, dash="dash", width=1),
                                annotation_text=f"Avg {avg_cv:.3f}V")
            fig_cells.update_layout(**DARK_LAYOUT, height=320,
                                    title=f"Cell Voltages — {vehicle_id}  (Green=Balanced | Red=Deviation)")
            st.plotly_chart(fig_cells, use_container_width=True)

        # Cell voltage evolution heatmap over window
        heat = []
        for _, row_w in window.iterrows():
            heat.append([row_w.get(c, np.nan) for c in CELL_COLS])
        fig_cev = go.Figure(go.Heatmap(
            z=heat,
            x=[f"C{i}" for i in range(1,17)],
            colorscale=[[0,"#ef4444"],[0.4,"#f59e0b"],[1.0,"#00ff9f"]],
            colorbar=dict(title="V", tickfont=dict(color=DIM)),
        ))
        fig_cev.update_layout(**DARK_LAYOUT, height=280,
                              title="Cell Voltage Evolution (Recent 200 Steps)",
                              xaxis_title="Cell", yaxis_title="Time Step")
        st.plotly_chart(fig_cev, use_container_width=True)

    # Tab 3 — Thermal
    with tab3:
        gcols = st.columns(3)
        sensor_names = ["Primary (Cell Zone)", "Secondary (Pack)", "Third (Ends)"]
        for i, tc in enumerate(TEMP_COLS):
            with gcols[i]:
                t = r.get(tc, np.nan)
                tc_color = color_temp(t)
                fig_g = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=t if not np.isnan(t) else 0,
                    gauge={
                        "axis": {"range": [0, 65], "tickcolor": DIM},
                        "bar": {"color": tc_color},
                        "bgcolor": CARD,
                        "steps": [
                            {"range": [0, 38], "color": "#102010", "name": "Normal"},
                            {"range": [38, 45], "color": "#201510", "name": "Monitor"},
                            {"range": [45, 65], "color": "#2a1010", "name": "Critical"},
                        ],
                        "threshold": {"line": {"color": RED, "width": 3}, "thickness": 0.75, "value": 45},
                    },
                    title={"text": f"SENSOR {i+1} — {sensor_names[i]}<br><span style='font-size:9px;color:{DIM}'>🟢 &lt;38°C Normal &nbsp; 🟡 38-45°C Monitor &nbsp; 🔴 &gt;45°C Critical</span>",
                           "font": {"color": DIM, "size": 11}},
                    number={"suffix": "°C", "font": {"color": WHITE}},
                ))
                fig_g.update_layout(**DARK_LAYOUT, height=250)
                st.plotly_chart(fig_g, use_container_width=True)

        # Temp trend with named lines
        fig_temp_trend = go.Figure()
        temp_names  = ["Sensor 1 — Cell Zone", "Sensor 2 — Pack Body", "Sensor 3 — End Plate"]
        temp_colors = [GREEN, GOLD, CYAN]
        for i, tc in enumerate(TEMP_COLS):
            if tc in window.columns:
                series = window[tc].replace(np.nan, None)
                fig_temp_trend.add_scatter(
                    x=window["time"], y=series,
                    mode="lines", name=temp_names[i],
                    line=dict(width=2, color=temp_colors[i])
                )
        fig_temp_trend.add_hline(y=45, line=dict(color=RED,  dash="dash", width=1.5),
                                 annotation_text="🔴 Critical 45°C",
                                 annotation_position="top left",
                                 annotation_font=dict(color=RED, size=10))
        fig_temp_trend.add_hline(y=38, line=dict(color=GOLD, dash="dot",  width=1.5),
                                 annotation_text="🟡 Monitor 38°C",
                                 annotation_position="bottom right",
                                 annotation_font=dict(color=GOLD, size=10))
        fig_temp_trend.update_layout(**DARK_LAYOUT, height=300,
                                     title="Temperature Trend (°C) — Named Sensors",
                                     legend=dict(font=dict(color=DIM, size=11)))
        st.plotly_chart(fig_temp_trend, use_container_width=True)

    # Tab 4 — Faults
    with tab4:
        fault_statuses = []
        for col, lbl in zip(ALERT_COLS, ALERT_LABELS):
            val = int(r.get(col, 0)) if pd.notna(r.get(col, np.nan)) else 0
            fault_statuses.append((lbl, val))

        cols_f = st.columns(4)
        for i, (lbl, val) in enumerate(fault_statuses):
            col = cols_f[i % 4]
            ic  = "🔴" if val else "🟢"
            col.markdown(f"""
            <div class='kpi-card' style='text-align:center;margin-bottom:8px;border:1px solid {"#ef4444" if val else "#1f2937"}'>
              <p style='font-size:22px;margin:0'>{ic}</p>
              <p style='color:{WHITE};font-size:11px;margin:4px 0 0'>{lbl}</p>
            </div>
            """, unsafe_allow_html=True)

        all_clear = all(v == 0 for _, v in fault_statuses)
        if all_clear:
            st.success("✅ All systems nominal — No active faults")
        else:
            active = [lbl for lbl, v in fault_statuses if v]
            st.error(f"⚠️ Active faults: {', '.join(active)}")


# ─────────────────────────────────────────────────────────────────────────────
#  GPS FLEET MAP  (separate page)
# ─────────────────────────────────────────────────────────────────────────────
def GpsMapView():
    st.markdown(f"""
    <div style='margin-bottom:16px'>
      <h1 style='font-family:Space Grotesk;font-size:22px;font-weight:700;color:{WHITE};margin:0'>
        🗺️ Fleet GPS Tracks
      </h1>
      <p style='color:{DIM};font-size:12px;margin:4px 0 0'>Historical positions for all 12 vehicles</p>
    </div>
    """, unsafe_allow_html=True)

    gps_sample = st.slider("GPS track density (lower = more points)", 1, 10, 1, 1)
    gps_df = load_all_gps(gps_sample)

    if gps_df.empty:
        st.warning("No GPS data found."); return

    # Filter out (0,0) invalid coords
    gps_df = gps_df[(gps_df["latitude"].abs() > 0.1) & (gps_df["longitude"].abs() > 0.1)]

    COLORS = [GREEN, CYAN, GOLD, RED, PURPLE, "#ff6b6b",
              "#4ecdc4", "#45b7d1", "#96ceb4", "#ffeaa7", "#dda0dd", "#98d8c8"]

    tab_all, tab_one = st.tabs(["📍 All Vehicles", "🔍 Single Vehicle Track"])

    with tab_all:
        # Full fleet on one map
        fig_map = go.Figure()
        for i, vid in enumerate(VEHICLES):
            vdf = gps_df[gps_df["vehicle_id"] == vid]
            if vdf.empty: continue
            color = COLORS[i % len(COLORS)]
            # Track line
            fig_map.add_scattermapbox(
                lat=vdf["latitude"], lon=vdf["longitude"],
                mode="lines",
                line=dict(width=1.5, color=color),
                name=vid, showlegend=True,
                hoverinfo="skip",
            )
            # Start / Latest markers
            fig_map.add_scattermapbox(
                lat=[vdf["latitude"].iloc[0], vdf["latitude"].iloc[-1]],
                lon=[vdf["longitude"].iloc[0], vdf["longitude"].iloc[-1]],
                mode="markers",
                marker=dict(size=[8, 12], color=color),
                name=vid, showlegend=False,
                text=[f"{vid} — Start", f"{vid} — Latest"],
                hovertemplate="%{text}<extra></extra>",
            )

        center_lat = gps_df["latitude"].mean()
        center_lon = gps_df["longitude"].mean()
        fig_map.update_layout(
            mapbox=dict(style="open-street-map",
                        center=dict(lat=center_lat, lon=center_lon), zoom=8),
            paper_bgcolor=CARD, height=550,
            margin=dict(l=0, r=0, t=0, b=0),
            legend=dict(font=dict(color=DIM, size=10), bgcolor=CARD2,
                        bordercolor="#1f2937", borderwidth=1),
        )
        st.plotly_chart(fig_map, use_container_width=True)

        # Stats
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Vehicles Tracked", len(gps_df["vehicle_id"].unique()))
        c2.metric("Total GPS Points", f"{len(gps_df):,}")
        c3.metric("Avg Speed (all)", f"{gps_df['speed'].mean():.1f} km/h")
        c4.metric("Date Range",
                  f"{gps_df['time'].min().strftime('%b %Y')} – {gps_df['time'].max().strftime('%b %Y')}")

    with tab_one:
        vid = sel_vehicle
        vdf = gps_df[gps_df["vehicle_id"] == vid].copy()
        if vdf.empty:
            st.info(f"No GPS data for {vid}"); return

        c_map, c_stats = st.columns([3, 1])
        with c_map:
            fig_v = go.Figure()
            fig_v.add_scattermapbox(
                lat=vdf["latitude"], lon=vdf["longitude"],
                mode="lines+markers",
                marker=dict(size=4, color=vdf["speed"],
                            colorscale=[[0, DIM],[0.5, GOLD],[1.0, GREEN]],
                            showscale=True,
                            colorbar=dict(title="Speed km/h", tickfont=dict(color=DIM))),
                line=dict(width=2, color=CYAN),
                customdata=np.stack([vdf["speed"], vdf["time"].astype(str)], axis=-1),
                hovertemplate="%{customdata[1]}<br>Speed: %{customdata[0]:.1f} km/h<extra></extra>",
            )
            fig_v.update_layout(
                mapbox=dict(style="open-street-map",
                            center=dict(lat=vdf["latitude"].mean(), lon=vdf["longitude"].mean()),
                            zoom=10),
                paper_bgcolor=CARD, height=500,
                margin=dict(l=0, r=0, t=0, b=0),
            )
            st.plotly_chart(fig_v, use_container_width=True)

        with c_stats:
            st.markdown(f"<p style='color:{DIM};font-size:11px;text-transform:uppercase;letter-spacing:1px'>Vehicle Stats</p>", unsafe_allow_html=True)
            st.metric("GPS Points", f"{len(vdf):,}")
            st.metric("Max Speed", f"{vdf['speed'].max():.1f} km/h")
            st.metric("Avg Speed", f"{vdf['speed'].mean():.1f} km/h")
            active = len(vdf[vdf["speed"] > 2])
            st.metric("Active Points", f"{active:,}")
            st.metric("From", vdf["time"].min().strftime("%b %d, %Y"))
            st.metric("To",   vdf["time"].max().strftime("%b %d, %Y"))

            # Speed distribution
            fig_spd = go.Figure(go.Histogram(
                x=vdf["speed"], nbinsx=30,
                marker_color=CYAN, opacity=0.8,
            ))
            fig_spd.update_layout(**DARK_LAYOUT, height=200,
                                  title="Speed Distribution",
                                  xaxis_title="km/h", yaxis_title="Count")
            st.plotly_chart(fig_spd, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
#  RENDER
# ─────────────────────────────────────────────────────────────────────────────
if view == "🏢 Fleet Manager":
    FleetManagerView()
elif view == "🗺️ GPS Fleet Map":
    GpsMapView()
else:
    VehicleDeepDive(sel_vehicle)

# ─────────────────────────────────────────────────────────────────────────────
#  AUTO-PLAY ENGINE
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.playing:
    base_sleep = 1.0 / max(st.session_state.spd, 0.1)
    time.sleep(max(0.05, base_sleep - 0.3))
    if st.session_state.step < N - 1:
        st.session_state.step += 1
    else:
        st.session_state.playing = False
    st.rerun()
