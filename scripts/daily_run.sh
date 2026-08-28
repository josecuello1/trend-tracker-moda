#!/bin/bash
# Corrida diaria local del RSS scanner + juicio de Claude + escritura de
# borradores en Notion. Pensado para correr via launchd (ver
# ~/Library/LaunchAgents/com.josecuello.trendtracker.rss.plist).
#
# Corre en la Mac del usuario (no en la nube) a propósito: los 6 dominios
# de moda (vogue.com, hypebeast.com, etc.) están bloqueados por política
# de red en el sandbox en la nube de Claude, pero funcionan sin problema
# desde una red doméstica/normal.
set -euo pipefail

PROJECT_DIR="$HOME/trend-tracker-moda"
SCRIPTS_DIR="$PROJECT_DIR/scripts"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"
LOG_FILE="$LOG_DIR/rss_run_${TIMESTAMP}.log"
SCAN_OUTPUT="/tmp/rss_scan_latest.txt"

# Asegura que claude/python3 se encuentren igual que en una sesión interactiva
# (launchd corre con un PATH minimo). claude está instalado vía nvm, no en
# una ruta estándar del sistema.
export PATH="$HOME/.nvm/versions/node/v24.16.0/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/bin:$PATH"

{
  echo "=== Corrida $TIMESTAMP ==="
  cd "$SCRIPTS_DIR"
  python3 rss_trend_scanner.py 2>&1 | tee "$SCAN_OUTPUT"
} >> "$LOG_FILE" 2>&1

PROMPT=$(cat <<PROMPT_EOF
Eres parte del proyecto Trend Tracker de moda/lifestyle del usuario (Notion
data source id 1ab95990-6345-448f-99c2-6e44639c8d53, 'Trend Tracker — Moda &
Street Style'). Corres localmente en su Mac, con acceso normal a internet
(esto NO es el sandbox en la nube que bloquea estos dominios).

El RSS scanner ya corrió. Su salida completa está en el archivo
$SCAN_OUTPUT — léelo con la herramienta Read.

1. De esa salida, mira la sección 'EMERGENTES' completa y la sección
   'CANDIDATOS NUEVOS' filtrada a los que tengan 2 o más fuentes distintas
   (fuentes_distintas >= 2) — descarta el resto, con 1 sola fuente es
   mayormente ruido de periodismo genérico, no señal de moda.

2. Antes de nada, consulta en Notion (notion-query-data-sources, SQL:
   SELECT "Tendencia / Elemento" FROM la data source de arriba) TODOS los
   títulos existentes, sin importar su Estado (Aprobado o Borrador) — para
   no proponer un duplicado, ni siquiera si está en borrador. Los títulos
   existentes están en español y los candidatos del scanner en inglés, usa
   criterio (no solo comparación literal) para decidir si es lo mismo.

3. Para cada candidato que sobreviva los filtros anteriores (máximo 8 por
   corrida, prioriza los de más fuentes distintas), usa WebFetch para leer
   el artículo completo detrás de al menos uno de sus ejemplos (no solo el
   título) y juzga con tu propio criterio: ¿es una señal específica y
   creíble de tendencia de moda o lifestyle, o ruido/mención incidental?
   Sé exigente — el estándar ya validado en este proyecto es cosas como
   'colaboración Junya Watanabe x The North Face, primera desde 2017' o
   'línea de bolsos de cuero plisado de Issey Miyake Fall 2026', no
   términos genéricos como 'sneaker' o 'luxury' sin nada específico detrás.

4. Para cada candidato que pase tu juicio, crea una página nueva en esa
   data source de Notion (notion-create-pages) con estas propiedades
   exactas:
   - "Tendencia / Elemento": nombre específico y descriptivo (no el keyword crudo)
   - "Fuente": Vogue→"Vogue Runway", "Business of Fashion"→"Business of Fashion", WWD→"WWD", Highsnobiety→"Highsnobiety", Hypebeast o Dazed→"Otro"
   - "Etapa": "Pasarela / Industria"
   - "Pilar": "Moda"
   - "Categoría": la(s) que apliquen de ["Color","Silueta","Textura","Prenda","Accesorio","Calzado"], a tu criterio
   - "Temporalidad": "Actual"
   - "Link / Referencia": la URL del artículo leído
   - "Recurrencia (1-5)": tu estimación honesta de fuerza de señal
   - "Estado": SIEMPRE "Borrador — revisar" — nunca "Aprobado"
   - "Notas del análisis": voz de analista, cita el dato real que leíste, menciona en cuántas fuentes apareció y por qué pasó el filtro. Nunca describas ni reproduzcas imágenes.

5. NUNCA edites, borres, ni cambies el Estado de ninguna fila existente —
   solo puedes CREAR filas nuevas en Borrador.

6. Termina con un resumen breve en texto plano: cuántos candidatos pasaron
   el filtro de fuentes, cuántas filas nuevas creaste en Borrador (con sus
   nombres), y si no creaste ninguna, dilo explícitamente y por qué.
PROMPT_EOF
)

{
  claude -p "$PROMPT" \
    --allowedTools "Read,WebFetch,mcp__claude_ai_Notion__notion-query-data-sources,mcp__claude_ai_Notion__notion-create-pages" \
    --permission-mode bypassPermissions
  echo "=== Fin corrida $TIMESTAMP ==="
} >> "$LOG_FILE" 2>&1
