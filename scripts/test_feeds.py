"""
Diagnóstico de feeds RSS de medios de moda
--------------------------------------------
Para cada feed reporta: código HTTP, compresión, Content-Type, si parsea
como RSS/Atom válido, número de entradas, fecha de la más reciente, y si
falla, el error exacto y un diagnóstico de la causa probable.

No intenta evadir ningún bloqueo (no usa proxies, no rota IPs, no falsea
geolocalización). El único experimento deliberado es Vogue con/sin
User-Agent de navegador, para diferenciar "bloqueo por header" de
"bloqueo por Cloudflare/geolocalización/proxy".
"""

from __future__ import annotations

import feedparser
import requests

FEEDS = [
    "https://www.vogue.com/feed/rss",
    "https://hypebeast.com/feed",
    "https://www.highsnobiety.com/feed/",
    "https://www.dazeddigital.com/rss",
    "https://www.businessoffashion.com/feed/",
    "https://wwd.com/feed/",
]

TIMEOUT = 15

# User-Agent "de script" honesto (identifica el bot) vs. uno "de navegador"
# (usado únicamente para el diagnóstico de Vogue, no para camuflarse en el
# uso normal del resto de feeds).
UA_SCRIPT = "TrendSourcesBot/1.0 (contacto: josedanielcuelloacademico@gmail.com)"
UA_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _diagnosticar_error(status_code: int | None, texto: str, excepcion: Exception | None) -> str:
    """Da un diagnóstico legible de la causa probable del fallo."""
    if excepcion is not None:
        nombre = type(excepcion).__name__
        if "Timeout" in nombre:
            return "Timeout — el servidor no respondió a tiempo."
        if "SSL" in nombre:
            return "Error de certificado SSL/TLS."
        if "ConnectionError" in nombre:
            return "No se pudo establecer conexión (DNS, red, o servidor caído)."
        return f"Excepción de red: {nombre}: {excepcion}"

    if status_code == 403:
        pistas = []
        t = texto.lower()
        if "cloudflare" in t or "cf-ray" in t:
            pistas.append("respuesta trae huellas de Cloudflare (posible bloqueo por WAF/bot-protection)")
        if "captcha" in t:
            pistas.append("la respuesta menciona un CAPTCHA")
        if "access denied" in t or "forbidden" in t:
            pistas.append("mensaje explícito de acceso denegado")
        detalle = "; ".join(pistas) if pistas else "sin pistas claras en el cuerpo de la respuesta"
        return f"403 Forbidden — probable bloqueo por User-Agent, WAF o geolocalización ({detalle})."
    if status_code == 404:
        return "404 — la URL del feed no existe (puede haber cambiado de ruta)."
    if status_code == 429:
        return "429 — rate limiting, demasiadas solicitudes."
    if status_code and status_code >= 500:
        return f"{status_code} — error del servidor remoto."
    if status_code and status_code >= 400:
        return f"{status_code} — error del cliente."
    return "Código de estado inesperado."


def probar_feed(url: str, headers: dict[str, str]) -> dict:
    """Descarga y analiza un feed, devolviendo un dict con el diagnóstico."""
    resultado = {
        "url": url,
        "status_code": None,
        "content_encoding": None,
        "descomprimio_ok": None,
        "content_type": None,
        "parsea_valido": False,
        "num_entradas": 0,
        "fecha_mas_reciente": None,
        "error": None,
        "diagnostico": None,
    }

    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        resultado["error"] = f"{type(e).__name__}: {e}"
        resultado["diagnostico"] = _diagnosticar_error(None, "", e)
        return resultado

    resultado["status_code"] = resp.status_code
    resultado["content_encoding"] = resp.headers.get("Content-Encoding", "(ninguno)")
    resultado["content_type"] = resp.headers.get("Content-Type", "(desconocido)")

    # requests descomprime automáticamente gzip/deflate; si llegamos aquí sin
    # excepción y con contenido, la descompresión (si aplicaba) funcionó.
    try:
        _ = resp.content  # fuerza la lectura/descompresión del cuerpo
        resultado["descomprimio_ok"] = True
    except Exception as e:  # noqa: BLE001 — queremos capturar cualquier fallo de descompresión
        resultado["descomprimio_ok"] = False
        resultado["error"] = f"Fallo al descomprimir: {e}"

    if not resp.ok:
        resultado["diagnostico"] = _diagnosticar_error(resp.status_code, resp.text, None)
        return resultado

    parsed = feedparser.parse(resp.content)

    # feedparser marca bozo=1 cuando el XML no es válido / hubo error de parseo
    if parsed.bozo and not parsed.entries:
        resultado["error"] = f"Bozo error: {parsed.bozo_exception}"
        resultado["diagnostico"] = (
            "El contenido no parsea como RSS/Atom válido "
            f"(Content-Type devuelto: {resultado['content_type']})."
        )
        return resultado

    resultado["parsea_valido"] = True
    resultado["num_entradas"] = len(parsed.entries)
    if parsed.entries:
        primera = parsed.entries[0]
        resultado["fecha_mas_reciente"] = (
            primera.get("published") or primera.get("updated") or "(sin fecha)"
        )
    return resultado


def imprimir_resultado(r: dict, etiqueta: str = "") -> None:
    titulo = f"{r['url']}" + (f"  [{etiqueta}]" if etiqueta else "")
    print(f"\n--- {titulo} ---")
    print(f"  HTTP status:        {r['status_code']}")
    print(f"  Content-Encoding:   {r['content_encoding']}")
    print(f"  Descompresión OK:   {r['descomprimio_ok']}")
    print(f"  Content-Type:       {r['content_type']}")
    print(f"  Parsea RSS/Atom:    {r['parsea_valido']}")
    print(f"  Nº entradas:        {r['num_entradas']}")
    print(f"  Entrada más reciente: {r['fecha_mas_reciente']}")
    if r["error"]:
        print(f"  ERROR:              {r['error']}")
    if r["diagnostico"]:
        print(f"  DIAGNÓSTICO:        {r['diagnostico']}")


def revisar_robots_txt(dominio_base: str) -> None:
    url = f"{dominio_base}/robots.txt"
    try:
        resp = requests.get(url, headers={"User-Agent": UA_SCRIPT}, timeout=TIMEOUT)
        print(f"\n--- robots.txt: {url} (HTTP {resp.status_code}) ---")
        if resp.ok:
            lineas = resp.text.splitlines()
            relevantes = [
                l
                for l in lineas
                if l.strip()
                and (
                    "feed" in l.lower()
                    or l.strip().lower().startswith(("user-agent", "disallow", "allow", "sitemap"))
                )
            ]
            for linea in relevantes[:40]:
                print(f"  {linea}")
        else:
            print("  No se pudo obtener robots.txt.")
    except requests.RequestException as e:
        print(f"\n--- robots.txt: {url} ---\n  ERROR: {e}")


if __name__ == "__main__":
    print("=" * 70)
    print("DIAGNÓSTICO GENERAL DE FEEDS (User-Agent identificado como bot)")
    print("=" * 70)

    resultados = {}
    for url in FEEDS:
        r = probar_feed(url, headers={"User-Agent": UA_SCRIPT})
        resultados[url] = r
        imprimir_resultado(r)

    print("\n" + "=" * 70)
    print("DIAGNÓSTICO ESPECÍFICO DE VOGUE (con y sin User-Agent de navegador)")
    print("=" * 70)

    vogue_url = "https://www.vogue.com/feed/rss"
    r_script_ua = probar_feed(vogue_url, headers={"User-Agent": UA_SCRIPT})
    imprimir_resultado(r_script_ua, etiqueta="UA de script/bot")

    r_browser_ua = probar_feed(vogue_url, headers={"User-Agent": UA_BROWSER})
    imprimir_resultado(r_browser_ua, etiqueta="UA de navegador")

    if r_script_ua["status_code"] == r_browser_ua["status_code"]:
        print(
            "\n>> Mismo resultado con ambos User-Agent "
            f"(status {r_script_ua['status_code']} en los dos) -> el bloqueo NO depende "
            "solo del User-Agent. Es más probable que sea Cloudflare/WAF o geolocalización "
            "a nivel de IP/red que un filtro simple de header."
        )
    else:
        print(
            f"\n>> Resultado distinto según User-Agent (script: {r_script_ua['status_code']}, "
            f"navegador: {r_browser_ua['status_code']}) -> el bloqueo SÍ depende del header "
            "User-Agent."
        )

    revisar_robots_txt("https://www.vogue.com")

    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    for url, r in resultados.items():
        estado = "VIABLE" if r["parsea_valido"] and r["num_entradas"] > 0 else "DESCARTADO"
        razon = r["diagnostico"] or "OK"
        print(f"  [{estado:10}] {url}  -> {razon}")
