"""
Conector de datos: Wikimedia Pageviews API
--------------------------------------------
Mide interés a lo largo del tiempo sobre términos de moda a partir de las
vistas mensuales de artículos de Wikipedia (es/en).

Docs: https://wikimedia.org/api/rest_v1/#/Pageviews%20data
"""

from __future__ import annotations

import time
import urllib.parse
from datetime import datetime, timedelta

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# CONFIGURACIÓN — edita esto antes de usar el script
# ---------------------------------------------------------------------------
# Wikimedia exige un User-Agent descriptivo con un medio de contacto real.
# Sin esto, la API responde 403 Forbidden.
USER_AGENT = "TrendSourcesBot/1.0 (contacto: josedanielcuelloacademico@gmail.com)"

BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
ACCESS = "all-access"
AGENT = "user"  # excluye bots/crawlers, solo tráfico humano
RATE_LIMIT_SECONDS = 0.5  # pausa entre llamadas para no saturar la API

LANGLINKS_URL = "https://en.wikipedia.org/w/api.php"

HEADERS = {"User-Agent": USER_AGENT}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _fecha_api(fecha: str) -> str:
    """Normaliza una fecha a formato YYYYMMDD00 que exige la API."""
    fecha = fecha.strip()
    if len(fecha) == 8:  # YYYYMMDD
        return fecha + "00"
    if len(fecha) == 10 and fecha.endswith("00"):
        return fecha
    raise ValueError(f"Formato de fecha no reconocido: {fecha!r} (usa YYYYMMDD)")


def ultimos_n_meses(n: int = 12) -> tuple[str, str]:
    """Devuelve (inicio, fin) en formato YYYYMMDD00 cubriendo los últimos n meses."""
    hoy = datetime.utcnow()
    fin = hoy.strftime("%Y%m%d00")
    inicio_dt = hoy - timedelta(days=30 * n)
    inicio = inicio_dt.strftime("%Y%m0100")
    return inicio, fin


# ---------------------------------------------------------------------------
# Resolución de títulos entre idiomas (langlinks)
# ---------------------------------------------------------------------------
def resolver_titulo(articulo_en: str, idioma_destino: str = "es") -> str | None:
    """
    Traduce el título de un artículo desde en.wikipedia al título equivalente
    en otro idioma, usando la API de langlinks de MediaWiki.

    Devuelve el título en `idioma_destino` (con espacios, no guiones bajos),
    o None si no existe un artículo equivalente en ese idioma (o si el
    artículo en inglés tampoco existe).
    """
    articulo_en = articulo_en.strip().replace("_", " ")
    params = {
        "action": "query",
        "titles": articulo_en,
        "prop": "langlinks",
        "lllang": idioma_destino,
        "format": "json",
    }

    try:
        resp = requests.get(LANGLINKS_URL, params=params, headers=HEADERS, timeout=15)
    except requests.RequestException as e:
        print(f"[ERROR] resolver_titulo('{articulo_en}' -> {idioma_destino}): fallo de red — {e}")
        return None

    if not resp.ok:
        print(
            f"[ERROR {resp.status_code}] resolver_titulo('{articulo_en}' -> {idioma_destino}): "
            f"{resp.text[:200]}"
        )
        return None

    paginas = resp.json().get("query", {}).get("pages", {})
    if not paginas:
        return None

    pagina = next(iter(paginas.values()))
    if "missing" in pagina:
        # El artículo tampoco existe en en.wikipedia.
        return None

    langlinks = pagina.get("langlinks")
    if not langlinks:
        return None

    return langlinks[0].get("*")


# ---------------------------------------------------------------------------
# Función principal de consulta
# ---------------------------------------------------------------------------
def get_pageviews(
    articulo: str,
    proyecto: str = "en.wikipedia",
    inicio: str = "2024010100",
    fin: str = "2024123100",
    granularidad: str = "monthly",
) -> pd.DataFrame:
    """
    Consulta la API de Pageviews de Wikimedia para un artículo.

    Devuelve un DataFrame con columnas: fecha, articulo, proyecto, vistas.
    Si el artículo no existe (404) o hay otro error, devuelve un DataFrame
    vacío y reporta el problema por consola en vez de lanzar excepción.
    """
    inicio = _fecha_api(inicio)
    fin = _fecha_api(fin)

    # El título va URL-encoded y con guiones bajos en vez de espacios.
    articulo_normalizado = articulo.strip().replace(" ", "_")
    articulo_encoded = urllib.parse.quote(articulo_normalizado, safe="_")

    url = (
        f"{BASE_URL}/{proyecto}/{ACCESS}/{AGENT}/"
        f"{articulo_encoded}/{granularidad}/{inicio}/{fin}"
    )

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
    except requests.RequestException as e:
        print(f"[ERROR] {articulo} ({proyecto}): fallo de red — {e}")
        return pd.DataFrame(columns=["fecha", "articulo", "proyecto", "vistas"])

    if resp.status_code == 404:
        print(f"[NO ENCONTRADO] '{articulo}' no existe en {proyecto} (404).")
        return pd.DataFrame(columns=["fecha", "articulo", "proyecto", "vistas"])

    if resp.status_code == 403:
        print(
            f"[ERROR 403] '{articulo}' ({proyecto}): acceso denegado. "
            "Revisa que USER_AGENT esté configurado con un contacto válido."
        )
        return pd.DataFrame(columns=["fecha", "articulo", "proyecto", "vistas"])

    if not resp.ok:
        print(f"[ERROR {resp.status_code}] '{articulo}' ({proyecto}): {resp.text[:200]}")
        return pd.DataFrame(columns=["fecha", "articulo", "proyecto", "vistas"])

    data = resp.json().get("items", [])
    if not data:
        print(f"[SIN DATOS] '{articulo}' ({proyecto}): la API no devolvió items.")
        return pd.DataFrame(columns=["fecha", "articulo", "proyecto", "vistas"])

    df = pd.DataFrame(
        {
            "fecha": [pd.to_datetime(item["timestamp"][:8], format="%Y%m%d") for item in data],
            "articulo": articulo_normalizado,
            "proyecto": proyecto,
            "vistas": [item["views"] for item in data],
        }
    )
    return df


# ---------------------------------------------------------------------------
# Comparación de varios artículos
# ---------------------------------------------------------------------------
def comparar(
    lista_de_articulos: list[str],
    proyectos: list[str] | None = None,
    inicio: str | None = None,
    fin: str | None = None,
) -> pd.DataFrame:
    """
    Consulta varios artículos (opcionalmente en varios proyectos) y arma una
    tabla comparativa con el total de vistas por mes, más el % de cambio del
    último mes disponible contra el promedio de los meses previos.

    Los artículos se asumen con título en inglés. Para cualquier proyecto que
    no sea en.wikipedia, primero se resuelve el título equivalente vía
    `resolver_titulo` (langlinks) antes de consultar pageviews — así se
    distingue "el artículo se llama distinto en ese idioma" de "el artículo
    no existe en ese idioma".

    Devuelve un DataFrame con columnas:
    articulo, proyecto, fecha, vistas, pct_cambio_ultimo_mes
    """
    proyectos = proyectos or ["en.wikipedia"]
    if inicio is None or fin is None:
        inicio, fin = ultimos_n_meses(12)

    resultados = []
    for articulo in lista_de_articulos:
        for proyecto in proyectos:
            idioma = proyecto.split(".")[0]

            if idioma == "en":
                titulo_consulta = articulo
            else:
                titulo_consulta = resolver_titulo(articulo, idioma_destino=idioma)
                time.sleep(RATE_LIMIT_SECONDS)
                if titulo_consulta is None:
                    print(
                        f"[NO EXISTE] '{articulo}' no tiene artículo equivalente en "
                        f"{proyecto} (sin langlink a '{idioma}')."
                    )
                    continue
                if titulo_consulta.replace(" ", "_") != articulo.replace("_", " ").replace(" ", "_"):
                    print(f"[TÍTULO RESUELTO] '{articulo}' -> '{titulo_consulta}' en {proyecto}")

            df = get_pageviews(titulo_consulta, proyecto=proyecto, inicio=inicio, fin=fin)
            if not df.empty:
                # Guardamos el resultado bajo el nombre del término original en
                # inglés para poder comparar entre idiomas en la misma tabla.
                df["articulo"] = articulo.replace(" ", "_")
                resultados.append(df)
            time.sleep(RATE_LIMIT_SECONDS)  # rate limiting entre llamadas

    if not resultados:
        print("[AVISO] No se obtuvo ningún dato para la lista de artículos.")
        return pd.DataFrame(
            columns=["articulo", "proyecto", "fecha", "vistas", "pct_cambio_ultimo_mes"]
        )

    todo = pd.concat(resultados, ignore_index=True)
    todo = todo.sort_values(["articulo", "proyecto", "fecha"])

    filas = []
    for (articulo, proyecto), grupo in todo.groupby(["articulo", "proyecto"]):
        grupo = grupo.sort_values("fecha").reset_index(drop=True)
        if len(grupo) >= 2:
            ultimo = grupo.iloc[-1]["vistas"]
            previos = grupo.iloc[:-1]["vistas"]
            promedio_previo = previos.mean()
            pct_cambio = (
                ((ultimo - promedio_previo) / promedio_previo * 100)
                if promedio_previo > 0
                else float("nan")
            )
        else:
            pct_cambio = float("nan")
        grupo["pct_cambio_ultimo_mes"] = pct_cambio
        filas.append(grupo)

    return pd.concat(filas, ignore_index=True)


def resumen_comparativo(tabla: pd.DataFrame) -> pd.DataFrame:
    """Colapsa la tabla de comparar() a una fila por artículo/proyecto con el
    total de vistas del período y el % de cambio del último mes."""
    if tabla.empty:
        return tabla
    return (
        tabla.groupby(["articulo", "proyecto"])
        .agg(
            total_vistas=("vistas", "sum"),
            vistas_ultimo_mes=("vistas", "last"),
            pct_cambio_ultimo_mes=("pct_cambio_ultimo_mes", "first"),
        )
        .reset_index()
        .sort_values("total_vistas", ascending=False)
    )


# ---------------------------------------------------------------------------
# Prueba manual
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    terminos = [
        "Streetwear",
        "Fast_fashion",
        "Balenciaga",
        "Y2K_fashion",
        "Vintage_clothing",
    ]

    inicio, fin = ultimos_n_meses(12)
    print(f"Consultando pageviews de {inicio} a {fin} para: {', '.join(terminos)}\n")

    for proyecto in ["es.wikipedia", "en.wikipedia"]:
        print(f"\n=== Proyecto: {proyecto} ===")
        tabla = comparar(terminos, proyectos=[proyecto], inicio=inicio, fin=fin)
        resumen = resumen_comparativo(tabla)
        if resumen.empty:
            print("(sin datos)")
        else:
            with pd.option_context("display.float_format", "{:.1f}".format):
                print(resumen.to_string(index=False))
