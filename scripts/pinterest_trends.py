"""
Conector de datos: Pinterest Trends API (v5)
----------------------------------------------
Trae keywords en tendencia con % de crecimiento (semana/mes/año) y una
serie de tiempo de 52 semanas, filtrable por región e interés.

Requiere credenciales en `scripts/.env` (mismo directorio que este script):
    PINTEREST_CLIENT_ID=...
    PINTEREST_CLIENT_SECRET=...
    PINTEREST_ACCESS_TOKEN=...
    PINTEREST_REFRESH_TOKEN=...

Cómo se consiguieron esas credenciales (para cuando el refresh_token expire,
~1 año):
1. App registrada en developers.pinterest.com con scope `ads:read,user_accounts:read`.
2. Autorización manual vía navegador: /oauth/?client_id=...&redirect_uri=...
   &response_type=code&scope=ads:read,user_accounts:read
3. Intercambio del `code` por access_token/refresh_token en
   POST https://api.pinterest.com/v5/oauth/token (Basic Auth con client_id:client_secret).

Este script SÍ escribe/actualiza `.env` cuando refresca el access_token
(el refresh_token puede rotar). No lo subas a ningún repo — ya está en
.gitignore.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

ENV_PATH = Path(__file__).parent / ".env"
API_BASE = "https://api.pinterest.com/v5"
RATE_LIMIT_SECONDS = 1.0

# Regiones relevantes para @josecuello__ (ver TrendsSupportedRegion en la
# doc oficial para la lista completa).
REGION_COLOMBIA = "CO"
REGION_HISPANIC_LATAM = "MX+AR+CO+CL"

# Intereses de moda y de lifestyle soportados por el API — el mismo
# endpoint sirve para llenar el hueco de datos de lifestyle del tracker.
INTERESES_MODA = ["womens_fashion", "mens_fashion", "childrens_fashion", "beauty"]
INTERESES_LIFESTYLE = ["home_decor", "travel", "food_and_drinks", "wedding", "event_planning"]


def _leer_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        raise FileNotFoundError(f"No existe {ENV_PATH}. Corre el flujo de OAuth primero.")
    valores = {}
    for linea in ENV_PATH.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valores[clave.strip()] = valor.strip()
    return valores


def _escribir_env(valores: dict[str, str]) -> None:
    lineas = [f"{clave}={valor}" for clave, valor in valores.items()]
    ENV_PATH.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    ENV_PATH.chmod(0o600)


def _refrescar_token(env: dict[str, str]) -> dict[str, str]:
    """Usa el refresh_token para obtener un access_token nuevo y actualiza .env."""
    resp = requests.post(
        f"{API_BASE}/oauth/token",
        auth=(env["PINTEREST_CLIENT_ID"], env["PINTEREST_CLIENT_SECRET"]),
        data={"grant_type": "refresh_token", "refresh_token": env["PINTEREST_REFRESH_TOKEN"]},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    env["PINTEREST_ACCESS_TOKEN"] = data["access_token"]
    if "refresh_token" in data:
        env["PINTEREST_REFRESH_TOKEN"] = data["refresh_token"]
    _escribir_env(env)
    print("[INFO] Access token de Pinterest refrescado.")
    return env


def get_trending_keywords(
    region: str = REGION_COLOMBIA,
    trend_type: str = "monthly",
    interests: list[str] | None = None,
    limit: int = 25,
) -> pd.DataFrame:
    """
    Consulta GET /trends/keywords/{region}/top/{trend_type}.

    trend_type: "growing" | "monthly" | "yearly" | "seasonal"
    interests: lista de categorías (ver INTERESES_MODA / INTERESES_LIFESTYLE),
               o None para todas.

    Devuelve un DataFrame con: keyword, region, trend_type, pct_growth_wow,
    pct_growth_mom, pct_growth_yoy, y una columna `time_series` con la lista
    de (fecha, valor normalizado 0-100) de las últimas 52 semanas.

    Si el token expiró, refresca automáticamente y reintenta una vez.
    """
    env = _leer_env()
    params = {"limit": limit}
    if interests:
        params["interests"] = ",".join(interests)

    url = f"{API_BASE}/trends/keywords/{region}/top/{trend_type}"

    def _consultar(token: str) -> requests.Response:
        return requests.get(
            url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15
        )

    resp = _consultar(env["PINTEREST_ACCESS_TOKEN"])

    if resp.status_code == 401:
        env = _refrescar_token(env)
        resp = _consultar(env["PINTEREST_ACCESS_TOKEN"])

    if not resp.ok:
        print(f"[ERROR {resp.status_code}] region={region} trend_type={trend_type}: {resp.text[:300]}")
        return pd.DataFrame(
            columns=["keyword", "region", "trend_type", "pct_growth_wow", "pct_growth_mom", "pct_growth_yoy", "time_series"]
        )

    trends = resp.json().get("trends", [])
    if not trends:
        print(f"[SIN DATOS] region={region} trend_type={trend_type} interests={interests}")
        return pd.DataFrame(
            columns=["keyword", "region", "trend_type", "pct_growth_wow", "pct_growth_mom", "pct_growth_yoy", "time_series"]
        )

    filas = []
    for t in trends:
        filas.append(
            {
                "keyword": t.get("keyword"),
                "region": region,
                "trend_type": trend_type,
                "pct_growth_wow": t.get("pct_growth_wow"),
                "pct_growth_mom": t.get("pct_growth_mom"),
                "pct_growth_yoy": t.get("pct_growth_yoy"),
                "time_series": sorted((t.get("time_series") or {}).items()),
            }
        )
    return pd.DataFrame(filas)


def comparar_intereses(
    intereses: list[str],
    region: str = REGION_COLOMBIA,
    trend_type: str = "monthly",
    limit_por_interes: int = 10,
) -> pd.DataFrame:
    """Consulta varios intereses por separado y devuelve todo concatenado,
    con una columna `interes` para saber de dónde salió cada fila."""
    tablas = []
    for interes in intereses:
        df = get_trending_keywords(region=region, trend_type=trend_type, interests=[interes], limit=limit_por_interes)
        if not df.empty:
            df["interes"] = interes
            tablas.append(df)
        time.sleep(RATE_LIMIT_SECONDS)
    if not tablas:
        return pd.DataFrame()
    return pd.concat(tablas, ignore_index=True)


if __name__ == "__main__":
    print("=== Moda — Colombia, tendencias del mes ===")
    moda = comparar_intereses(INTERESES_MODA, region=REGION_COLOMBIA, trend_type="monthly", limit_por_interes=5)
    if not moda.empty:
        with pd.option_context("display.max_colwidth", 30):
            print(moda[["interes", "keyword", "pct_growth_wow", "pct_growth_mom", "pct_growth_yoy"]].to_string(index=False))

    print("\n=== Lifestyle — Colombia, tendencias del mes ===")
    lifestyle = comparar_intereses(INTERESES_LIFESTYLE, region=REGION_COLOMBIA, trend_type="monthly", limit_por_interes=5)
    if not lifestyle.empty:
        with pd.option_context("display.max_colwidth", 30):
            print(lifestyle[["interes", "keyword", "pct_growth_wow", "pct_growth_mom", "pct_growth_yoy"]].to_string(index=False))
