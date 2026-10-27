"""
Ley de Newton del Enfriamiento - Streamlit
==========================================
- Lee datos en tiempo real desde Supabase (escritos por el ESP32)
- Gráfica interactiva con Plotly
- Descarga CSV de la sesión
- Carga de CSV históricos
- Ajuste automático del modelo de Newton
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from scipy.optimize import curve_fit
from datetime import datetime
import time
import io
import os

# ============ CONFIGURACIÓN ============
# Estas variables se configuran en Streamlit Cloud → Settings → Secrets
# O localmente en .streamlit/secrets.toml
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")
TABLA = "temperaturas"
REFRESH_SEGUNDOS = 2          # cada cuántos segundos refrescar
INTERVALO_AJUSTE = 60         # segundos entre ajustes del modelo
# =======================================

st.set_page_config(
    page_title="Ley de Newton – Tiempo Real",
    page_icon="🌡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------- Modelo de Newton ----------
def modelo_newton(t, T0, k, Ta):
    return Ta + (T0 - Ta) * np.exp(-k * t)

def ajustar_modelo(df):
    """Ajusta T0 y k manteniendo Ta como promedio del ambiente"""
    if len(df) < 8:
        return None
    try:
        t = df["t"].values
        T = df["agua"].values
        Ta = float(df["amb"].mean())

        def f(t, T0, k):
            return modelo_newton(t, T0, k, Ta)

        popt, _ = curve_fit(
            f, t, T,
            p0=[T[0], 0.01],
            bounds=([0, 1e-5], [150, 1.0]),
            maxfev=3000
        )
        return {
            "T0": round(float(popt[0]), 2),
            "k": round(float(popt[1]), 5),
            "Ta": round(Ta, 2)
        }
    except Exception:
        return None

def generar_curva(modelo, t_max):
    if modelo is None:
        return None, None
    t = np.linspace(0, t_max + 30, 200)
    T = modelo_newton(t, modelo["T0"], modelo["k"], modelo["Ta"])
    return t, T

# ---------- Conexión Supabase ----------
@st.cache_resource
def get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def leer_datos_supabase(limit=2000):
    sb = get_supabase()
    if sb is None:
        return pd.DataFrame(columns=["t", "agua", "amb", "created_at"])
    try:
        res = sb.table(TABLA).select("t, agua, amb, created_at") \
                 .order("t", desc=False) \
                 .limit(limit) \
                 .execute()
        df = pd.DataFrame(res.data)
        if df.empty:
            return pd.DataFrame(columns=["t", "agua", "amb", "created_at"])
        df["t"] = pd.to_numeric(df["t"], errors="coerce")
        df["agua"] = pd.to_numeric(df["agua"], errors="coerce")
        df["amb"] = pd.to_numeric(df["amb"], errors="coerce")
        df = df.dropna(subset=["t", "agua", "amb"])
        return df
    except Exception as e:
        st.error(f"Error leyendo Supabase: {e}")
        return pd.DataFrame(columns=["t", "agua", "amb", "created_at"])

def calcular_dTdt(df):
    if len(df) < 2:
        df = df.copy()
        df["dTdt"] = 0.0
        return df
    df = df.copy()
    dt = df["t"].diff()
    dT = df["agua"].diff()
    df["dTdt"] = np.where(dt > 0, dT / dt, 0.0)
    df["dTdt"] = df["dTdt"].fillna(0.0)
    return df

# ---------- UI ----------
st.title("🌡️ Ley de Newton del Enfriamiento")
st.caption("Dos sensores DS18B20 · ESP32 · Datos en la nube · Visible desde cualquier red")

# Sidebar
with st.sidebar:
    st.header("Controles")
    modo = st.radio(
        "Modo de visualización",
        ["Tiempo real (Supabase)", "Cargar CSV histórico"],
        index=0
    )

    st.divider()
    auto_refresh = st.checkbox("Auto-refresco", value=True)
    if auto_refresh and modo.startswith("Tiempo real"):
        st.caption(f"Actualizando cada {REFRESH_SEGUNDOS} s")

    st.divider()
    st.subheader("Sesión actual")
    if st.button("🔄 Forzar actualización"):
        st.cache_data.clear()
        st.rerun()

# ---------- Modo Tiempo Real ----------
if modo.startswith("Tiempo real"):
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.warning(
            "⚠️ Faltan las credenciales de Supabase.\n\n"
            "Ve a **Streamlit Cloud → Settings → Secrets** y agrega:\n\n"
            "```toml\n"
            'SUPABASE_URL = "https://xxxxx.supabase.co"\n'
            'SUPABASE_KEY = "eyJhbGciOi..."\n'
            "```"
        )
        st.info("Mientras tanto puedes usar el modo **Cargar CSV histórico**.")
        df = pd.DataFrame()
    else:
        df = leer_datos_supabase()
        df = calcular_dTdt(df)

    if df.empty:
        st.info("Esperando datos del ESP32… Asegúrate de que el ESP32 esté enviando a Supabase.")
    else:
        # Valores actuales
        ultimo = df.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Tiempo", f"{ultimo['t']:.1f} s")
        c2.metric("Temp. Agua", f"{ultimo['agua']:.2f} °C")
        c3.metric("Temp. Ambiente", f"{ultimo['amb']:.2f} °C")
        c4.metric("dT/dt", f"{ultimo['dTdt']:.4f} °C/s")

        # Ajuste del modelo
        modelo = ajustar_modelo(df)
        if modelo:
            st.success(
                f"**Modelo de Newton** →  "
                f"T₀ = {modelo['T0']} °C   |   "
                f"Tₐ = {modelo['Ta']} °C   |   "
                f"k = {modelo['k']} s⁻¹"
            )
            st.latex(r"T(t) = T_a + (T_0 - T_a)\, e^{-k\, t}")

        # Gráfica
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Scatter(x=df["t"], y=df["agua"], name="Temp. Agua",
                       line=dict(color="#38bdf8", width=2.5)),
            secondary_y=False
        )
        fig.add_trace(
            go.Scatter(x=df["t"], y=df["amb"], name="Temp. Ambiente",
                       line=dict(color="#94a3b8", width=1.8)),
            secondary_y=False
        )
        if modelo:
            t_c, T_c = generar_curva(modelo, df["t"].max())
            fig.add_trace(
                go.Scatter(x=t_c, y=T_c, name="Modelo Newton",
                           line=dict(color="#f87171", width=2, dash="dash")),
                secondary_y=False
            )
        fig.add_trace(
            go.Scatter(x=df["t"], y=df["dTdt"], name="dT/dt",
                       line=dict(color="#4ade80", width=1.5)),
            secondary_y=True
        )
        fig.update_layout(
            height=520,
            margin=dict(t=30, b=40, l=50, r=50),
            legend=dict(orientation="h", y=1.12),
            hovermode="x unified",
            template="plotly_dark"
        )
        fig.update_xaxes(title_text="Tiempo (s)")
        fig.update_yaxes(title_text="Temperatura (°C)", secondary_y=False)
        fig.update_yaxes(title_text="dT/dt (°C/s)", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)

        # Descarga CSV
        csv_buf = io.StringIO()
        df_out = df[["t", "agua", "amb", "dTdt"]].copy()
        df_out.columns = ["Tiempo_seg", "Temp_Agua_C", "Temp_Ambiente_C", "dT_dt"]
        df_out.to_csv(csv_buf, index=False)
        st.download_button(
            label="⬇ Descargar CSV de la sesión",
            data=csv_buf.getvalue(),
            file_name=f"newton_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )

    # Auto-refresh
    if auto_refresh and not df.empty:
        time.sleep(REFRESH_SEGUNDOS)
        st.rerun()

# ---------- Modo Histórico ----------
else:
    st.subheader("📂 Cargar datos históricos")
    archivo = st.file_uploader("Selecciona un archivo CSV", type=["csv"])

    if archivo is not None:
        try:
            df = pd.read_csv(archivo)
            # Normalizar nombres de columnas
            colmap = {}
            for c in df.columns:
                cl = c.lower().strip()
                if "tiempo" in cl or cl == "t":
                    colmap[c] = "t"
                elif "agua" in cl:
                    colmap[c] = "agua"
                elif "amb" in cl:
                    colmap[c] = "amb"
                elif "dt" in cl or "deriv" in cl:
                    colmap[c] = "dTdt"
            df = df.rename(columns=colmap)

            if "dTdt" not in df.columns:
                df = calcular_dTdt(df)

            required = {"t", "agua", "amb"}
            if not required.issubset(df.columns):
                st.error(f"El CSV debe tener columnas de tiempo, temperatura de agua y ambiente. Encontradas: {list(df.columns)}")
            else:
                st.success(f"Cargados {len(df)} puntos")

                ultimo = df.iloc[-1]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Tiempo", f"{ultimo['t']:.1f} s")
                c2.metric("Temp. Agua", f"{ultimo['agua']:.2f} °C")
                c3.metric("Temp. Ambiente", f"{ultimo['amb']:.2f} °C")
                c4.metric("dT/dt", f"{ultimo.get('dTdt', 0):.4f} °C/s")

                modelo = ajustar_modelo(df)
                if modelo:
                    st.success(
                        f"**Modelo de Newton** →  "
                        f"T₀ = {modelo['T0']} °C   |   "
                        f"Tₐ = {modelo['Ta']} °C   |   "
                        f"k = {modelo['k']} s⁻¹"
                    )

                fig = make_subplots(specs=[[{"secondary_y": True}]])
                fig.add_trace(go.Scatter(x=df["t"], y=df["agua"], name="Temp. Agua",
                                         line=dict(color="#38bdf8", width=2.5)), secondary_y=False)
                fig.add_trace(go.Scatter(x=df["t"], y=df["amb"], name="Temp. Ambiente",
                                         line=dict(color="#94a3b8", width=1.8)), secondary_y=False)
                if modelo:
                    t_c, T_c = generar_curva(modelo, df["t"].max())
                    fig.add_trace(go.Scatter(x=t_c, y=T_c, name="Modelo Newton",
                                             line=dict(color="#f87171", width=2, dash="dash")), secondary_y=False)
                if "dTdt" in df.columns:
                    fig.add_trace(go.Scatter(x=df["t"], y=df["dTdt"], name="dT/dt",
                                             line=dict(color="#4ade80", width=1.5)), secondary_y=True)
                fig.update_layout(height=520, template="plotly_dark",
                                  legend=dict(orientation="h", y=1.12), hovermode="x unified")
                fig.update_xaxes(title_text="Tiempo (s)")
                fig.update_yaxes(title_text="Temperatura (°C)", secondary_y=False)
                fig.update_yaxes(title_text="dT/dt (°C/s)", secondary_y=True)
                st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            st.error(f"No se pudo leer el archivo: {e}")
    else:
        st.info("Sube un CSV con columnas: Tiempo_seg, Temp_Agua_C, Temp_Ambiente_C (y opcionalmente dT_dt)")
