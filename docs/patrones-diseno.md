# Árbol de patrones de diseño

## Nivel macro — Arquitectura de agentes

- **Pipeline** — Flujo: perfil de gustos → descubrimiento geográfico → filtrado
  por reseñas → ranking personalizado → construcción del plan de viaje.
- **Strategy** — Distintas estrategias de recomendación según el tipo de
  usuario (mochilero, familia, gastronómico, aventura); el algoritmo de
  ranking se puede cambiar sin tocar el resto del sistema.
- **Observer** — El plan de viaje se recalcula si cambian las condiciones
  (un lugar cerró, mal clima, el usuario se desvió de la ruta).
- **ReAct** — El agente piensa → consulta APIs geográficas/reseñas → observa
  resultados → refina la recomendación.
- **Memoria** — Corto plazo: ubicación actual y contexto de la sesión activa
  (Redis). Largo plazo: perfil de gustos aprendido (histórico de like/dislike).

## Nivel micro — Patrones de software

### Creacionales
- **Builder** — construye el "perfil de gustos" combinando preferencias
  explícitas (encuesta inicial) + implícitas (historial de interacción).
- **Factory Method** — instancia el tipo de recomendador según categoría
  (comida, cultura, naturaleza, vida nocturna).

### Estructurales
- **Adapter** — normaliza fuentes heterogéneas (Google Places, TripAdvisor,
  OpenStreetMap) a un modelo único de "lugar".
- **Facade** — una sola interfaz para que el usuario pida "qué hago hoy" sin
  ver la orquestación interna.
- **Composite** — el plan de viaje es un árbol: día → bloques de tiempo →
  lugares; un bloque se trata igual que un lugar individual.
- **Decorator** — enriquece una recomendación base con capas opcionales
  (traducir reseñas, añadir accesibilidad, añadir precio estimado).

### Comportamiento
- **Strategy** — algoritmo de ranking configurable (ver macro).
- **Observer** — recalcula el plan ante cambios de contexto.
- **Chain of Responsibility** — filtros sucesivos: distancia máxima →
  presupuesto → horario de apertura → rating mínimo → coincidencia de gustos.
- **Command** — cada acción del usuario sobre el plan (agregar, quitar,
  reordenar una parada) es un objeto reversible (deshacer/rehacer).
- **Template Method** — estructura fija para "generar un día de plan", con
  pasos que cada subtipo de viaje (cultural, gastronómico) rellena distinto.

### Datos / Integración
- **Repository** — acceso uniforme a lugares, reseñas y perfiles de usuario.
- **Cache-Aside** — cachea resultados de APIs geográficas (evita costos y
  latencia repetidos).
- **CQRS ligero** — separa lecturas (explorar mapa) de escrituras (guardar
  plan, dar feedback).
