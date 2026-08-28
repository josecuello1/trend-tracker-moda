# Trend Tracker — Moda, Data & Lifestyle (@josecuello__)

Jose Daniel Cuello Corrales está rebrandeando su Instagram (@josecuello__)
alrededor de tres pilares: moda, lifestyle, y datos (para promocionar su
empresa, Vector Data Studio). Este directorio es el sistema de tracking de
tendencias que sostiene ese contenido, llevado desde Claude Code (no desde
Claude chat).

## Piezas

1. **Notion — base de datos "Trend Tracker — Moda & Street Style"**
   - Data source id: `1ab95990-6345-448f-99c2-6e44639c8d53`
   - Cada fila: tendencia/elemento, fuente, etapa (pasarela/calle/retail-búsqueda),
     categoría (color/silueta/textura/prenda/accesorio/calzado), ciudad, región,
     temporalidad (actual/pronóstico), recurrencia 1-5, link, notas de análisis.
   - Regla de oro del campo "Notas del análisis": solo datos derivados
     (colores, siluetas, texturas, conteos) — **nunca** la imagen ni el
     crédito de terceros.

2. **Dashboard público (Artifact)**
   - URL: https://claude.ai/code/artifact/d69346d8-3b1b-4f17-98c8-028e38e23b5a
   - Fuente local versionada en `dashboard/dashboard.html`. Al republicar:
     - Si copias el contenido desde una acción `read` del Artifact, esa
       copia trae inyectado un wrapper `frame-runtime` de la plataforma
       (todo antes de `<title>Radar de Tendencias</title>` y el
       `</body></html>` final) — hay que quitarlo antes de publicar, el
       archivo real solo empieza en `<title>...`.
     - El tool de Artifact tiene un bug conocido: republicar puede quedar
       en loop "hadn't viewed" → "identical content already refused" aunque
       el contenido sí cambió y ya se hizo el Read completo pedido. Si pasa,
       no asumas que es un conflicto real de contenido — pide confirmación
       explícita al usuario para usar `force:true`.

3. **Scripts en `scripts/`**
   - `wiki_pageviews.py` — cliente de la Wikimedia Pageviews API. Incluye
     `resolver_titulo()` (API de langlinks) para resolver el título correcto
     de un artículo en otro idioma antes de asumir que "no existe".
   - `test_feeds.py` — diagnóstico de los 6 feeds RSS de moda (Vogue,
     Hypebeast, Highsnobiety, Dazed, Business of Fashion, WWD).
   - `rss_trend_scanner.py` — escanea esos 6 feeds contra un diccionario de
     keywords de moda (editable al inicio del archivo), separa candidatos
     nuevos de los ya cubiertos por `existing_trends.txt` (snapshot de
     títulos ya en Notion). No escribe en Notion — solo genera reporte para
     revisión humana. Tiene falsos positivos por lo poco que trae el RSS en
     título/resumen; siempre revisar el artículo fuente antes de subir un
     candidato al tracker.
   - `README.md` — cómo correr los tres y sus dependencias
     (`requests`, `pandas`, `feedparser`).

## Qué fuentes están validadas y cuáles no

| Fuente | Estado | Notas |
|---|---|---|
| RSS (Vogue, Hypebeast, Highsnobiety, Dazed, BoF, WWD) | ✅ Viables | Los 6 dan 200 OK y parseo válido desde esta máquina. Un 403 anterior a Vogue fue por la IP/proxy de otra sesión, no un bloqueo de Vogue — confirmado con robots.txt (permite el feed explícitamente) y con/sin User-Agent de navegador. |
| Wikimedia Pageviews API | ✅ Funciona | Sin API key. Requiere User-Agent descriptivo. Mide "atención/tráfico", no intención de búsqueda ni de compra. Datos desde julio 2015. |
| Wikipedia langlinks API | ✅ Funciona | Para resolver el título equivalente entre idiomas antes de medir pageviews — evita subestimar por título distinto o desambiguación errónea (ej. "Balenciaga" en ES es el diseñador, no la marca — el título correcto es "Balenciaga (empresa)"). |
| Google Trends | ❌ Bloqueado en el sandbox de Claude / sin API libre | `pytrends` archivado (abril 2025) y bloqueado por proxy en el sandbox. La API oficial está en alpha con waitlist. |
| Blog oficial de Google (blog.google) | ✅ Usable como fuente editorial | No es una API, pero publica cifras de búsqueda reales de vez en cuando. |
| Pinterest Trends / API | ❌ Sin API pública viable | Descartado. |

## Reglas que hay que seguir siempre

- **Nunca** scrapear ni almacenar en bulk fotos con derechos de autor
  (Vogue, Instagram, etc.), aunque el uso final sea no comercial. Solo
  datos derivados y agregados.
- El dashboard público **nunca** muestra ni republica imágenes de terceros.
- Si un sitio devuelve 403 o está bloqueado por robots.txt: diagnosticar
  por qué (proxy vs. bloqueo real del sitio), **nunca** intentar evadirlo.
- Preferir siempre fuente oficial/API/RSS antes que scraping.

## Pendiente

- Automatizar un refresco recurrente (idealmente mensual) del tracker y el
  dashboard — todavía no montado. Es lo único que queda del roadmap
  original; todo lo demás (dashboard actualizado, números planos en.wikipedia,
  scanner de RSS) ya está hecho.
