"""
Escáner de tendencias sobre los feeds RSS ya validados (ver test_feeds.py).

A diferencia de la primera versión, este script NO busca contra un
diccionario fijo de vocabulario de moda que alguien tuvo que anticipar.
En vez de eso, mina las palabras y frases (1-2 palabras) que más se
repiten en los títulos+resúmenes reales de los feeds, y en cuántas
fuentes distintas aparece cada una — eso es lo único que decide qué sube
en el reporte, no si coincide con una lista prearmada.

Por qué el cambio: un diccionario fijo solo puede encontrar lo que ya
esperabas encontrar (sesgo de selección) — nunca iba a "descubrir" algo
genuinamente nuevo, solo confirmar lo que ya sabías buscar. Contar
recurrencia real no tiene ese techo.

Cómo se filtra el ruido, sin usar una lista de "qué es moda":
1. Stopwords gramaticales en inglés (the, and, with, ...) — es un filtro
   lingüístico, no de contenido/vocabulario, así que no reintroduce sesgo
   de tema.
2. Corte por frecuencia de documento: un término que aparece en una
   fracción muy alta de TODAS las entradas (ver `DF_MAX_FRACCION`) es
   boilerplate estructural de los feeds (ej. "release info" en casi todo
   titular de Hypebeast) — no distingue nada, así que se descarta
   automáticamente por estadística, no porque alguien decidió que "no es
   moda".

Este script NO escribe en Notion. Solo genera el reporte para que el humano
(o una sesión de Claude con acceso a Notion) decida qué filas crear —
ver criterios de rigor en el README (multi-mención, multi-fuente, contexto
que tenga sentido).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import feedparser
import requests

USER_AGENT = "TrendSourcesBot/1.0 (contacto: josedanielcuelloacademico@gmail.com)"
TIMEOUT = 15

# Cuántos de los N candidatos con más fuentes distintas mostrar en el reporte.
TOP_N = 30
# Un término que aparece en más de esta fracción de TODAS las entradas se
# descarta por ser boilerplate estructural del feed, no señal de contenido.
DF_MAX_FRACCION = 0.12
# Longitud mínima de un token para considerarlo (corta ruido de un solo
# carácter, números sueltos, etc. — no es un filtro de vocabulario).
LONGITUD_MIN_TOKEN = 3

# Mapeo feed -> (nombre para reporte, valor de "Fuente" en el schema de Notion)
FEEDS = {
    "https://www.vogue.com/feed/rss": ("Vogue", "Vogue Runway"),
    "https://hypebeast.com/feed": ("Hypebeast", "Otro"),
    "https://www.highsnobiety.com/feed/": ("Highsnobiety", "Highsnobiety"),
    "https://www.dazeddigital.com/rss": ("Dazed", "Otro"),
    "https://www.businessoffashion.com/feed/": ("Business of Fashion", "Business of Fashion"),
    "https://wwd.com/feed/": ("WWD", "WWD"),
}

# Stopwords gramaticales — filtro lingüístico, no de tema.
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should", "could", "may",
    "might", "must", "can", "this", "that", "these", "those", "i", "you", "he", "she", "it",
    "we", "they", "what", "which", "who", "whom", "to", "of", "in", "on", "at", "by", "for",
    "with", "about", "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "from", "up", "down", "out", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how", "all", "any", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "s", "t", "just", "don", "now", "its", "their", "his",
    "her", "our", "your", "my", "as", "if", "while", "amp",
}

EXISTING_TRENDS_FILE = Path(__file__).parent / "existing_trends.txt"

# Memoria entre corridas — esto es lo que permite detectar algo que "apenas
# empieza": una sola mención hoy es indistinguible de ruido, pero un término
# que reaparece en corridas sucesivas (aunque sea con pocas menciones cada
# vez) sí es una señal distinta, que ninguna corrida individual puede ver.
HISTORIAL_FILE = Path(__file__).parent / "rss_historial.json"

# Traducciones conocidas ES<->EN para el dedup contra existing_trends.txt
# (los títulos del tracker están en español, los feeds en inglés). Como ya
# no partimos de un diccionario fijo, esta lista se va llenando sola con
# el tiempo — cada vez que confirmemos que un término minado es lo mismo
# que algo ya trackeado, agregar la traducción aquí.
SINONIMOS_ES: dict[str, list[str]] = {
    "leather": ["cuero"],
    "ballet flats": ["calzado plano", "ballerinas", "bailarinas"],
    "mary janes": ["calzado plano", "mary janes"],
    "kitten heels": ["calzado plano", "kitten heel"],
    "oversized": ["sobretalla", "oversize"],
    "oversize": ["sobretalla", "oversize"],
    "denim": ["denim"],
    "streetwear": ["streetwear"],
    "vintage": ["vintage"],
    "upcycling": ["upcycling", "segunda mano"],
    "fast fashion": ["fast fashion", "moda pronta"],
    "fringe": ["flecos"],
    "tailoring": ["sastrería"],
    "polka dot": ["lunares", "polka dot"],
    "capri pants": ["capri"],
    "silk scarf": ["pañuelos de seda", "pañuelo de seda"],
    "chunky jewelry": ["joyería chunky"],
}

_TOKEN_RE = re.compile(r"[a-záéíóúñü]+(?:-[a-záéíóúñü]+)?", re.IGNORECASE)


def cargar_tendencias_existentes() -> list[str]:
    if not EXISTING_TRENDS_FILE.exists():
        return []
    return [
        line.strip().lower()
        for line in EXISTING_TRENDS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def cargar_historial() -> dict[str, dict]:
    if not HISTORIAL_FILE.exists():
        return {}
    return json.loads(HISTORIAL_FILE.read_text(encoding="utf-8"))


def guardar_historial(historial: dict[str, dict], hallazgos: dict[str, dict], hoy: str) -> None:
    for termino, data in hallazgos.items():
        registro = historial.setdefault(termino, {"primera_vez": hoy, "fechas_vistas": []})
        if hoy not in registro["fechas_vistas"]:
            registro["fechas_vistas"].append(hoy)
        registro["menciones_ultima_corrida"] = len(data["menciones"])
    HISTORIAL_FILE.write_text(json.dumps(historial, indent=2, ensure_ascii=False), encoding="utf-8")


def ya_trackeado(termino: str, existentes: list[str]) -> bool:
    t = termino.lower()
    candidatos = [t] + SINONIMOS_ES.get(t, [])
    return any(c in titulo for c in candidatos for titulo in existentes)


def obtener_entradas(url: str) -> list[dict]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as e:
        print(f"[ERROR] {url}: fallo de red — {e}")
        return []
    if not resp.ok:
        print(f"[ERROR {resp.status_code}] {url}")
        return []
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        print(f"[ERROR] {url}: no parsea como RSS/Atom válido.")
        return []
    return parsed.entries


def _tokenizar(texto: str) -> list[str]:
    tokens = _TOKEN_RE.findall(texto.lower())
    return [t for t in tokens if len(t) >= LONGITUD_MIN_TOKEN and t not in STOPWORDS]


def _ngramas(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def escanear() -> dict[str, dict]:
    """Mina 1-gramas y 2-gramas de todas las entradas, cuenta en cuántas
    entradas/fuentes distintas aparece cada uno, y filtra boilerplate por
    frecuencia de documento. Devuelve {termino: {menciones: [...], df: int}}."""
    existentes = cargar_tendencias_existentes()

    entradas_totales = []
    for url, (nombre_feed, fuente_notion) in FEEDS.items():
        entradas = obtener_entradas(url)
        print(f"{nombre_feed}: {len(entradas)} entradas revisadas")
        for entrada in entradas:
            entradas_totales.append((nombre_feed, fuente_notion, entrada))

    n_entradas = len(entradas_totales)
    if n_entradas == 0:
        return {}

    doc_frecuencia: Counter[str] = Counter()  # en cuántas ENTRADAS aparece (no cuántas veces)
    hallazgos: dict[str, dict] = defaultdict(lambda: {"menciones": []})

    for nombre_feed, fuente_notion, entrada in entradas_totales:
        titulo = entrada.get("title", "")
        resumen = entrada.get("summary", "")
        texto = f"{titulo} {resumen}"
        link = entrada.get("link")
        fecha = entrada.get("published", entrada.get("updated", "sin fecha"))

        tokens = _tokenizar(texto)
        terminos_en_esta_entrada = set(tokens) | set(_ngramas(tokens, 2))

        for termino in terminos_en_esta_entrada:
            doc_frecuencia[termino] += 1
            hallazgos[termino]["menciones"].append(
                {
                    "fuente_feed": nombre_feed,
                    "fuente_notion": fuente_notion,
                    "titulo": titulo,
                    "link": link,
                    "fecha": fecha,
                }
            )

    # Corte por frecuencia de documento — boilerplate estructural, no juicio de tema.
    umbral = max(2, int(n_entradas * DF_MAX_FRACCION))
    for termino in list(hallazgos.keys()):
        if doc_frecuencia[termino] > umbral or doc_frecuencia[termino] < 2:
            del hallazgos[termino]

    historial = cargar_historial()
    for termino in hallazgos:
        hallazgos[termino]["ya_trackeado"] = ya_trackeado(termino, existentes)
        hallazgos[termino]["fuentes_distintas"] = len({m["fuente_feed"] for m in hallazgos[termino]["menciones"]})
        registro_previo = historial.get(termino)
        # Corridas anteriores == fechas ya vistas en el historial, sin contar
        # la de hoy (que se guarda recién al final de esta corrida).
        hallazgos[termino]["corridas_anteriores"] = len(registro_previo["fechas_vistas"]) if registro_previo else 0
        hallazgos[termino]["primera_vez"] = registro_previo["primera_vez"] if registro_previo else None

    return hallazgos


def reportar(hallazgos: dict[str, dict]) -> None:
    nuevos = {k: v for k, v in hallazgos.items() if not v["ya_trackeado"]}
    cubiertos = {k: v for k, v in hallazgos.items() if v["ya_trackeado"]}

    def por_fuerza(item):
        return (item[1]["fuentes_distintas"], len(item[1]["menciones"]))

    # Emergentes: pocas fuentes/menciones HOY (no calificarían solas), pero
    # ya se vieron en al menos una corrida anterior — repetirse en el tiempo
    # es una señal que ninguna corrida individual puede detectar por sí sola.
    emergentes = {
        k: v for k, v in nuevos.items()
        if v["corridas_anteriores"] >= 1 and v["fuentes_distintas"] < 2
    }

    print("\n" + "=" * 70)
    print(f"EMERGENTES — reaparecen entre corridas, aunque hoy sean pocas menciones ({len(emergentes)})")
    print("=" * 70)
    if not emergentes:
        print("(ninguno todavía — hace falta más de una corrida en el historial para que esto diga algo)")
    for termino, data in sorted(emergentes.items(), key=lambda kv: kv[1]["corridas_anteriores"], reverse=True):
        print(f"\n· \"{termino}\" — visto en {data['corridas_anteriores']} corrida(s) previa(s), primera vez el {data['primera_vez']}, hoy {len(data['menciones'])} mención(es)")
        for m in data["menciones"][:2]:
            print(f"    - ({m['fuente_feed']}, {m['fecha']}) {m['titulo']}")
            if m["link"]:
                print(f"      {m['link']}")

    print("\n" + "=" * 70)
    print(f"CANDIDATOS NUEVOS — top {TOP_N} por Nº de fuentes distintas ({len(nuevos)} en total)")
    print("=" * 70)
    for termino, data in sorted(nuevos.items(), key=por_fuerza, reverse=True)[:TOP_N]:
        fuentes = sorted({m["fuente_feed"] for m in data["menciones"]})
        print(f"\n· \"{termino}\" — {len(data['menciones'])} mención(es) en {data['fuentes_distintas']} fuente(s): {', '.join(fuentes)}")
        for m in data["menciones"][:3]:
            print(f"    - ({m['fuente_feed']}, {m['fecha']}) {m['titulo']}")
            if m["link"]:
                print(f"      {m['link']}")

    print("\n" + "=" * 70)
    print(f"YA CUBIERTOS POR EL TRACKER ACTUAL ({len(cubiertos)})")
    print("=" * 70)
    for termino, data in sorted(cubiertos.items(), key=por_fuerza, reverse=True):
        fuentes = sorted({m["fuente_feed"] for m in data["menciones"]})
        print(f"· \"{termino}\" — {len(data['menciones'])} mención(es) en {data['fuentes_distintas']} fuente(s): {', '.join(fuentes)} (refuerza señal existente)")


if __name__ == "__main__":
    hallazgos = escanear()
    reportar(hallazgos)

    hoy = date.today().isoformat()
    historial = cargar_historial()
    guardar_historial(historial, hallazgos, hoy)
    print(f"\n[historial actualizado: {HISTORIAL_FILE.name}, {len(historial)} términos acumulados]")
