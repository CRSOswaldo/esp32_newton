# Ley de Newton – Streamlit + ESP32 (nube)

Aplicación web pública para visualizar el enfriamiento de un líquido en **tiempo real** desde cualquier red.

```
ESP32  ──WiFi──►  Supabase (nube)  ◄──lee──  Streamlit Cloud
                                              (GitHub)
```

No necesitas abrir puertos ni dejar tu PC encendida.

---

## 1. Crear la base de datos (Supabase) – 3 minutos

1. Entra en [https://supabase.com](https://supabase.com) y crea una cuenta (gratis).
2. **New project** → elige nombre y contraseña de base de datos.
3. Cuando esté listo, ve a **SQL Editor** → New query y pega esto:

```sql
create table temperaturas (
  id bigint generated always as identity primary key,
  t real not null,
  agua real not null,
  amb real not null,
  created_at timestamptz default now()
);

-- Permitir que cualquiera inserte y lea (solo para este experimento)
alter table temperaturas enable row level security;

create policy "Permitir insertar" on temperaturas
  for insert with check (true);

create policy "Permitir leer" on temperaturas
  for select using (true);
```

4. Ejecuta el SQL (Run).
5. Ve a **Settings → API** y copia:
   - **Project URL** (ejemplo: `https://abcdef.supabase.co`)
   - **anon public** key (empieza por `eyJ...`)

---

## 2. Configurar el ESP32

Abre `esp32_newton.ino` y cambia estas líneas:

```cpp
const char* WIFI_SSID     = "TU_WIFI";
const char* WIFI_PASSWORD = "TU_PASSWORD";

const char* SUPABASE_URL  = "https://XXXXXXXX.supabase.co";
const char* SUPABASE_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...";
```

Sube el sketch al ESP32.  
En el Monitor Serial deberías ver:

```
WiFi OK · IP: 192.168.x.x
Sensores encontrados: 2
12.0 s | Agua: 65.20 °C | Amb: 22.10 °C | OK
```

---

## 3. Subir la app a GitHub + Streamlit Cloud

### 3.1 Crear repositorio en GitHub
1. Crea un repositorio nuevo (puede ser público).
2. Sube estos archivos:
   - `app.py`
   - `requirements.txt`
   - `README.md` (opcional)

### 3.2 Desplegar en Streamlit Community Cloud
1. Entra en [https://share.streamlit.io](https://share.streamlit.io)
2. Conecta tu cuenta de GitHub.
3. **New app** → selecciona el repositorio y el archivo `app.py`.
4. Antes de desplegar, ve a **Advanced settings → Secrets** y pega:

```toml
SUPABASE_URL = "https://XXXXXXXX.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

5. Deploy.

Cuando termine tendrás una URL pública del tipo:
`https://tu-app.streamlit.app`

Cualquiera con internet puede abrirla y ver los datos en vivo.

---

## 4. Funciones de la web

| Función | Descripción |
|---------|-------------|
| **Tiempo real** | Lee de Supabase cada 2 segundos y actualiza la gráfica |
| **Descargar CSV** | Descarga todos los puntos de la sesión actual |
| **Cargar CSV histórico** | Sube un CSV anterior y ve el gráfico + ajuste de Newton |
| **Modelo de Newton** | Ajuste automático de \(T_0\), \(k\) y \(T_a\) |

---

## Cableado de los sensores

| Cable del DS18B20 | ESP32 |
|-------------------|-------|
| Rojo (VCC)        | 3.3V  |
| Negro (GND)       | GND   |
| Amarillo (DATA)   | GPIO4 |
| Resistencia 4.7 kΩ | entre DATA y 3.3V |

- Índice 0 → temperatura del **agua**
- Índice 1 → temperatura **ambiente**

---

## Formato del CSV

```csv
Tiempo_seg,Temp_Agua_C,Temp_Ambiente_C,dT_dt
0.0,65.20,22.10,0.0000
1.0,64.85,22.15,-0.3500
```

---

## Notas

- El plan gratuito de Supabase es más que suficiente para un experimento de laboratorio.
- Si quieres borrar los datos antiguos: en Supabase → Table Editor → temperatures → borra filas.
- Streamlit Cloud se duerme tras un rato de inactividad; la primera visita puede tardar ~20 s en despertar.
