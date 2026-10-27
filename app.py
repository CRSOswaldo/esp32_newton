"""
Ley de Newton del Enfriamiento - Backend
========================================
- Recibe datos del ESP32 por HTTP POST
- Calcula dT/dt
- Ajusta el modelo de Newton periódicamente
- Retransmite en tiempo real por WebSocket
- Permite descargar CSV de la sesión actual
- Permite cargar CSV históricos para graficar
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from collections import deque
from datetime import datetime
import numpy as np
from scipy.optimize import curve_fit
import csv
import io
import asyncio
import json
import os
from typing import List, Optional

# ============ CONFIGURACIÓN ============
MAX_PUNTOS = 2000
INTERVALO_AJUSTE = 60.0          # segundos entre ajustes del modelo
# =======================================

# Ruta base = carpeta donde está este archivo .py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI(title="Ley de Newton - Tiempo Real")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ---------- Estado en memoria ----------
class Estado:
    def __init__(self):
        self.tiempos = deque(maxlen=MAX_PUNTOS)
        self.temps_agua = deque(maxlen=MAX_PUNTOS)
        self.temps_ambiente = deque(maxlen=MAX_PUNTOS)
        self.derivadas = deque(maxlen=MAX_PUNTOS)
        self.ultimo_ajuste = 0.0
        self.parametros = None          # (T0, k)
        self.Ta_usada = None
        self.tiempo_inicio = None
        self.clientes: List[WebSocket] = []

estado = Estado()

# ---------- Modelo de Newton ----------
def modelo_newton(t, T0, k, Ta):
    return Ta + (T0 - Ta) * np.exp(-k * t)

def ajustar_modelo():
    if len(estado.tiempos) < 8:
        return None
    try:
        t_data = np.array(estado.tiempos)
        T_data = np.array(estado.temps_agua)
        Ta = float(np.mean(estado.temps_ambiente))

        def modelo_fijo(t, T0, k):
            return modelo_newton(t, T0, k, Ta)

        popt, _ = curve_fit(
            modelo_fijo,
            t_data,
            T_data,
            p0=[T_data[0], 0.01],
            bounds=([0, 1e-5], [150, 1.0]),
            maxfev=2000
        )
        estado.parametros = popt
        estado.Ta_usada = Ta
        estado.ultimo_ajuste = t_data[-1]
        return {
            "T0": round(float(popt[0]), 2),
            "k": round(float(popt[1]), 5),
            "Ta": round(Ta, 2)
        }
    except Exception as e:
        print(f"Error ajuste: {e}")
        return None

# ---------- WebSocket manager ----------
async def broadcast(mensaje: dict):
    muertos = []
    for ws in estado.clientes:
        try:
            await ws.send_json(mensaje)
        except Exception:
            muertos.append(ws)
    for ws in muertos:
        if ws in estado.clientes:
            estado.clientes.remove(ws)

# ---------- Modelos Pydantic ----------
class DatoESP32(BaseModel):
    t: float                # tiempo en segundos desde el inicio del ESP32
    agua: float             # temperatura del agua
    amb: float              # temperatura ambiente

# ---------- Rutas ----------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/data")
async def recibir_dato(dato: DatoESP32):
    """Endpoint que llama el ESP32 cada segundo"""
    t = dato.t
    agua = dato.agua
    amb = dato.amb

    # Primera muestra → guardar tiempo de inicio de sesión
    if estado.tiempo_inicio is None:
        estado.tiempo_inicio = datetime.now()

    # Calcular dT/dt
    if len(estado.temps_agua) >= 1:
        dt = t - estado.tiempos[-1]
        dT = agua - estado.temps_agua[-1]
        dTdt = dT / dt if dt > 0 else 0.0
    else:
        dTdt = 0.0

    estado.tiempos.append(t)
    estado.temps_agua.append(agua)
    estado.temps_ambiente.append(amb)
    estado.derivadas.append(dTdt)

    # Ajuste periódico
    modelo_info = None
    if t - estado.ultimo_ajuste >= INTERVALO_AJUSTE:
        modelo_info = ajustar_modelo()

    # Payload para los clientes web
    payload = {
        "tipo": "dato",
        "t": round(t, 1),
        "agua": round(agua, 2),
        "amb": round(amb, 2),
        "dTdt": round(dTdt, 4),
        "modelo": modelo_info
    }

    # Si hay modelo actual, también enviar la curva teórica
    if estado.parametros is not None and estado.Ta_usada is not None:
        t0, k = estado.parametros
        t_max = max(estado.tiempos) + 30
        t_teorico = np.linspace(0, t_max, 150)
        T_teorico = modelo_newton(t_teorico, t0, k, estado.Ta_usada)
        payload["curva"] = {
            "t": [round(float(x), 1) for x in t_teorico],
            "T": [round(float(x), 2) for x in T_teorico]
        }

    await broadcast(payload)
    return {"status": "ok"}

@app.get("/api/estado")
async def obtener_estado():
    """Devuelve todo el historial actual (útil al conectar un cliente nuevo)"""
    modelo = None
    if estado.parametros is not None:
        modelo = {
            "T0": round(float(estado.parametros[0]), 2),
            "k": round(float(estado.parametros[1]), 5),
            "Ta": round(estado.Ta_usada, 2)
        }
    return {
        "tiempos": list(estado.tiempos),
        "agua": list(estado.temps_agua),
        "amb": list(estado.temps_ambiente),
        "dTdt": list(estado.derivadas),
        "modelo": modelo
    }

@app.get("/api/download")
async def descargar_csv():
    """Descarga el CSV de la sesión actual"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Tiempo_seg", "Temp_Agua_C", "Temp_Ambiente_C", "dT_dt"])
    for t, a, amb, d in zip(estado.tiempos, estado.temps_agua,
                            estado.temps_ambiente, estado.derivadas):
        writer.writerow([f"{t:.1f}", f"{a:.2f}", f"{amb:.2f}", f"{d:.4f}"])

    output.seek(0)
    nombre = f"newton_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nombre}"}
    )

@app.post("/api/upload")
async def cargar_csv(file: UploadFile = File(...)):
    """Carga un CSV histórico y lo devuelve parseado para graficar"""
    contenido = await file.read()
    texto = contenido.decode("utf-8")
    reader = csv.DictReader(io.StringIO(texto))

    tiempos, agua, amb, dTdt = [], [], [], []
    for row in reader:
        # Soporta diferentes nombres de columnas
        t = float(row.get("Tiempo_seg") or row.get("Tiempo_min") or row.get("t") or list(row.values())[0])
        a = float(row.get("Temp_Agua_C") or row.get("agua") or list(row.values())[1])
        am = float(row.get("Temp_Ambiente_C") or row.get("amb") or list(row.values())[2])
        d = float(row.get("dT_dt") or row.get("dTdt") or (list(row.values())[3] if len(row) > 3 else 0))
        tiempos.append(t)
        agua.append(a)
        amb.append(am)
        dTdt.append(d)

    # Intentar ajustar modelo también sobre datos históricos
    modelo = None
    if len(tiempos) >= 8:
        try:
            t_data = np.array(tiempos)
            T_data = np.array(agua)
            Ta = float(np.mean(amb))
            def modelo_fijo(t, T0, k):
                return modelo_newton(t, T0, k, Ta)
            popt, _ = curve_fit(modelo_fijo, t_data, T_data,
                                p0=[T_data[0], 0.01],
                                bounds=([0, 1e-5], [150, 1.0]))
            modelo = {
                "T0": round(float(popt[0]), 2),
                "k": round(float(popt[1]), 5),
                "Ta": round(Ta, 2)
            }
            t_teorico = np.linspace(t_data[0], t_data[-1] + 30, 150)
            T_teorico = modelo_newton(t_teorico, popt[0], popt[1], Ta)
            curva = {
                "t": [round(float(x), 1) for x in t_teorico],
                "T": [round(float(x), 2) for x in T_teorico]
            }
        except Exception:
            curva = None
    else:
        curva = None

    return {
        "tiempos": tiempos,
        "agua": agua,
        "amb": amb,
        "dTdt": dTdt,
        "modelo": modelo,
        "curva": curva
    }

@app.post("/api/reset")
async def reset_sesion():
    """Reinicia los buffers de la sesión actual"""
    estado.tiempos.clear()
    estado.temps_agua.clear()
    estado.temps_ambiente.clear()
    estado.derivadas.clear()
    estado.ultimo_ajuste = 0.0
    estado.parametros = None
    estado.Ta_usada = None
    estado.tiempo_inicio = None
    await broadcast({"tipo": "reset"})
    return {"status": "ok"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    estado.clientes.append(websocket)
    print(f"Cliente conectado. Total: {len(estado.clientes)}")

    # Enviar estado actual al conectar
    try:
        await websocket.send_json({
            "tipo": "estado_inicial",
            "tiempos": list(estado.tiempos),
            "agua": list(estado.temps_agua),
            "amb": list(estado.temps_ambiente),
            "dTdt": list(estado.derivadas),
            "modelo": {
                "T0": round(float(estado.parametros[0]), 2),
                "k": round(float(estado.parametros[1]), 5),
                "Ta": round(estado.Ta_usada, 2)
            } if estado.parametros is not None else None
        })
    except Exception:
        pass

    try:
        while True:
            # Mantener la conexión viva (el cliente puede enviar pings)
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in estado.clientes:
            estado.clientes.remove(websocket)
        print(f"Cliente desconectado. Total: {len(estado.clientes)}")

# ---------- Arranque ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
