# trend-sources

Conectores de datos para el sistema de análisis de tendencias de moda.

## Dependencias

```bash
pip install requests pandas feedparser
```

Probado con Python 3.9.

## 1. `wiki_pageviews.py` — interés en Wikipedia

```bash
python3 wiki_pageviews.py
```

Antes de usarlo en otro contexto, edita la constante `USER_AGENT` al inicio
del archivo — Wikimedia exige un User-Agent descriptivo con un medio de
contacto real; sin eso la API responde 403.

Funciones principales:

- `get_pageviews(articulo, proyecto, inicio, fin)` → `DataFrame` con
  `fecha` y `vistas` para un artículo. Si el artículo no existe (404), lo
  reporta por consola y devuelve un DataFrame vacío (no lanza excepción).
- `comparar(lista_de_articulos, proyectos, inicio, fin)` → tabla larga con
  todos los artículos/proyectos y el `pct_cambio_ultimo_mes` (último mes vs.
  promedio de los meses previos).
- `resumen_comparativo(tabla)` → una fila por artículo/proyecto con total
  de vistas y % de cambio.

**Resultado de la prueba** (últimos 12 meses, `es.wikipedia` y
`en.wikipedia`, agente `user` — sin bots):

- En `en.wikipedia` los 5 términos existen y tienen datos:
  `Balenciaga` es el de mayor volumen (~371k vistas/año), seguido de
  `Fast_fashion` y `Streetwear`. Todos muestran caída en el mes en curso,
  pero es un mes parcial (el script corre a mitad de mes), no una señal real
  de tendencia — para lecturas de "último mes completo" hay que excluir el
  mes en curso.
- En `es.wikipedia`, `Streetwear`, `Y2K_fashion` y `Vintage_clothing` **no
  existen como artículos** (404) — el script lo reporta y sigue sin
  interrumpirse. Solo `Balenciaga` y `Fast_fashion` tienen artículo en
  español.

## 2. `test_feeds.py` — diagnóstico de feeds RSS

```bash
python3 test_feeds.py
```

Para cada feed imprime: status HTTP, `Content-Encoding` y si la
descompresión funcionó, `Content-Type`, si parsea como RSS/Atom válido
(vía `feedparser`), número de entradas y fecha de la más reciente. Al
final imprime un resumen VIABLE/DESCARTADO por feed.

### Resultado de la prueba (corrida directa, sin proxy)

| Feed | Estado | Notas |
|---|---|---|
| vogue.com/feed/rss | ✅ Viable | 200, gzip, `application/xml`, 30 entradas |
| hypebeast.com/feed | ✅ Viable | 200, gzip, `text/xml`, 20 entradas |
| highsnobiety.com/feed | ✅ Viable | 200, sin compresión, `application/octet-stream` (Content-Type mal declarado pero el cuerpo es RSS válido igual), 14 entradas |
| dazeddigital.com/rss | ✅ Viable | 200, gzip, `application/atom+xml`, 15 entradas |
| businessoffashion.com/feed | ✅ Viable | 200, gzip, `application/xml`, 100 entradas |
| wwd.com/feed | ✅ Viable | 200, gzip, `application/rss+xml`, 10 entradas |

**Los 6 feeds quedaron viables.** Ninguno se descarta.

### Diagnóstico específico de Vogue (pediste esto explícitamente)

El script hace la petición a `vogue.com/feed/rss` dos veces desde esta
máquina: una con un User-Agent de bot identificado
(`TrendSourcesBot/1.0 (contacto: ...)`) y otra con un User-Agent de
navegador de escritorio. **En ambos casos el resultado fue 200 OK, con RSS
válido y 30 entradas.** No hubo ningún 403 en ninguna de las dos pruebas.

`robots.txt` de Vogue permite explícitamente el feed: la línea
`Allow: /*rss?` cubre la ruta, y además el propio `robots.txt` lista
`https://www.vogue.com/feed/rss` como uno de sus sitemaps — es decir, Vogue
quiere que ese feed sea accedido por agentes automatizados.

**Conclusión: el 403 que viste antes no es un bloqueo de Vogue por
User-Agent, Cloudflare o el contenido del feed en sí — el feed es
accesible sin restricciones desde esta red/IP con las dos variantes de
User-Agent probadas.** Lo más probable es que el 403 fuera del proxy que
usaste (IP del proxy bloqueada/en lista negra de Cloudflare, o el proxy
inyectando headers que Vogue rechaza) — no del origen. Si vuelves a
correr esto desde el mismo proxy y quieres confirmarlo del todo, compara
el `cf-ray` / cuerpo de la respuesta 403 de ese momento; si menciona
Cloudflare, es casi seguro que es la reputación de la IP del proxy, no un
filtro de User-Agent. **Vogue es una fuente viable** para este proyecto
mientras se acceda con una IP/red no bloqueada.

## 3. `rss_trend_scanner.py` — candidatos nuevos para el tracker (sin diccionario de moda)

```bash
python3 rss_trend_scanner.py
```

**Versión 2 (2026-08-28)** — la primera versión comparaba contra un
diccionario fijo de ~70 términos de moda que yo anticipé a mano; eso es
sesgo de selección (solo encuentra lo que ya esperabas encontrar). Ahora
el script mina 1 y 2-gramas (palabras y pares de palabras) de los
títulos+resúmenes reales de los 6 feeds, cuenta cuántas veces se repite
cada uno y en cuántas fuentes distintas aparece — eso es lo único que
decide qué sale en el reporte, no si coincide con una lista prearmada.

**Qué filtra y qué no** (decisión explícita del usuario, 2026-08-28: cero
lista de vocabulario, ni de moda ni de inglés general — revisión 100%
manual):
- Sí filtra stopwords gramaticales en inglés (`the`, `and`, `for`, `with`...)
  — es limpieza lingüística mínima, no juicio de tema; sin esto el reporte
  sería puro ruido de conectores.
- Sí filtra por frecuencia de documento (`DF_MAX_FRACCION`): un término que
  aparece en más del 12% de TODAS las entradas se descarta por ser
  boilerplate estructural del feed (ej. si algo apareciera en la mitad de
  los titulares de un medio, es la plantilla del medio, no una tendencia).
- NO filtra por tema/vocabulario de ninguna forma — así que el reporte va
  a traer mucho ruido genérico de periodismo en inglés ("best", "exclusive",
  "first", "need", "shop") mezclado con señal real de moda. Es a propósito:
  revisar y descartar eso a mano es el costo de no tener ningún sesgo de
  selección.

**No escribe en Notion.** El dedup usa `SINONIMOS_ES` (dict al inicio del
archivo) para reconocer cuando un término minado en inglés ya está
trackeado con otro nombre en español (ej. "leather" ↔ "cuero") — sin esto,
el scanner marcaría como "candidato nuevo" señal que ya está en el
tracker, solo porque el idioma no coincide. Cada vez que confirmes que un
término minado es lo mismo que algo ya trackeado, agrega la traducción
aquí — la lista se va llenando sola con el tiempo, a diferencia del viejo
diccionario que había que anticipar de una.

**Resultado de la prueba v1** (2026-08-26, con el diccionario fijo — ya
reemplazado): de 189 entradas, los candidatos más creíbles fueron cargo
pants, pearls/lace y velvet.

**Resultado de la prueba v2** (2026-08-28, sin diccionario): 182 entradas,
1317 candidatos "nuevos" en crudo (ver por qué tantos arriba). Tras
revisión manual del top 30 por Nº de fuentes: nada calificó como fila
nueva — lo único con contenido real de moda (`sneaker`, `shoe`, `luxury`,
`retail`) es demasiado genérico para ser una tendencia puntual, y el resto
es vocabulario de titular sin relación con moda. `leather` sí apareció,
pero correctamente clasificado como "ya cubierto" (gracias a
`SINONIMOS_ES`) en vez de como hallazgo nuevo.

## 4. `pinterest_trends.py` — moda y lifestyle en tiempo real (Pinterest Trends API)

```bash
python3 pinterest_trends.py
```

Cliente del API oficial de Pinterest Trends (`GET /v5/trends/keywords/{region}/top/{trend_type}`).
Por keyword trae % de crecimiento semana/mes/año y una serie de 52 semanas
normalizada 0-100. Filtra por región (`CO`, `MX+AR+CO+CL`, etc.) e interés —
incluye categorías de **moda** (`womens_fashion`, `mens_fashion`,
`childrens_fashion`, `beauty`) y de **lifestyle** (`home_decor`, `travel`,
`food_and_drinks`, `wedding`, `event_planning`), así que este mismo
conector reemplaza la cita manual de "Google Trends" que había en el
tracker Y llena el hueco de datos de lifestyle que no existía antes.

**Requiere credenciales** en `scripts/.env` (no incluido en el repo,
`.gitignore` ya lo cubre):
```
PINTEREST_CLIENT_ID=...
PINTEREST_CLIENT_SECRET=...
PINTEREST_ACCESS_TOKEN=...
PINTEREST_REFRESH_TOKEN=...
```
El script refresca el `access_token` automáticamente cuando expira (dura
~30 días) usando el `refresh_token` (dura ~1 año) — si el refresh_token
también expira, hay que rehacer el flujo OAuth completo desde
developers.pinterest.com (app ya registrada bajo la cuenta de Pinterest
del usuario, scope `ads:read,user_accounts:read`).

Funciones principales:
- `get_trending_keywords(region, trend_type, interests, limit)` → DataFrame.
- `comparar_intereses(intereses, region, trend_type, limit_por_interes)` →
  corre varios intereses y concatena resultados con columna `interes`.

## Notas generales

- Los tres scripts hacen manejo de errores por elemento: un artículo o
  feed que falla no detiene el resto de la corrida.
- `wiki_pageviews.py` incluye una pausa (`RATE_LIMIT_SECONDS = 0.5`) entre
  llamadas a la API de Wikimedia.
- Ningún script intenta evadir bloqueos (no usa proxies, no rota
  User-Agent para camuflarse, no falsea geolocalización). El experimento
  de dos User-Agent en Vogue es solo diagnóstico.
