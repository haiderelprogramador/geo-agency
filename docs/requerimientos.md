# Requerimientos y clientes potenciales

## Requerimientos funcionales

| # | Requerimiento |
|---|---|
| RF1 | El sistema debe construir un perfil de gustos del usuario a partir de preferencias explícitas y su comportamiento (lugares guardados, calificados, descartados) |
| RF2 | Debe detectar o recibir la ubicación del usuario y buscar lugares cercanos dentro de un radio configurable |
| RF3 | Debe recolectar y analizar reseñas de cada lugar candidato (sentimiento, temas recurrentes) |
| RF4 | Debe rankear los lugares candidatos combinando cercanía, calidad (reseñas) y afinidad con el perfil de gustos |
| RF5 | Debe generar un plan de viaje/itinerario (secuencia de lugares por bloque de tiempo/día) optimizando la ruta entre paradas |
| RF6 | El usuario debe poder editar el plan (agregar, quitar, reordenar paradas) y el sistema debe recalcular automáticamente |
| RF7 | El sistema debe recalcular el plan si cambian las condiciones (lugar cerrado, clima, el usuario se desvía de la ruta) |
| RF8 | Debe filtrar resultados por restricciones explícitas del usuario (presupuesto, horario, accesibilidad, tipo de comida) |
| RF9 | Debe explicar en lenguaje natural por qué recomienda cada lugar ("te gusta porque...") |
| RF10 | El usuario debe poder dar feedback (me gustó / no me gustó) que retroalimenta el perfil para futuras recomendaciones |
| RF11 | Debe soportar múltiples idiomas para el usuario final |

## Requerimientos no funcionales

| # | Requerimiento |
|---|---|
| RNF1 | Tiempo de respuesta de una recomendación o recálculo de ruta < 5 segundos |
| RNF2 | Precisión: la tasa de "me gustó" sobre recomendaciones aceptadas debe ser medible y mejorar con el tiempo |
| RNF3 | Privacidad: la ubicación y el historial de gustos del usuario deben protegerse (cifrado, consentimiento explícito, cumplimiento de habeas data) |
| RNF4 | Escalabilidad: soportar múltiples usuarios concurrentes sin degradar el tiempo de respuesta |
| RNF5 | Control de costo: minimizar llamadas repetidas a APIs de terceros (Google Places, LLM) mediante caché |
| RNF6 | Disponibilidad offline parcial: el plan ya generado debe poder consultarse sin conexión |
| RNF7 | Usabilidad: la interacción debe funcionar por lenguaje natural, sin requerir una interfaz compleja |
| RNF8 | Portabilidad geográfica: la arquitectura no debe depender de datos hardcodeados de una sola ciudad — debe poder extenderse a otras ciudades |
| RNF9 | Trazabilidad: registrar qué datos y qué razonamiento llevaron a cada recomendación |
| RNF10 | Cumplimiento de términos de uso de las APIs externas consultadas (Google Places, TripAdvisor, etc.) |

## Posibles clientes

- Turistas individuales o en grupo que visitan una ciudad y no la conocen bien (B2C directo, freemium/app)
- Agencias de viaje y operadores turísticos, como herramienta para armar itinerarios personalizados más rápido
- Hoteles y hostales, como valor agregado para sus huéspedes ("tu concierge digital")
- Aerolíneas o plataformas de reserva (Booking, Despegar, etc.) como feature integrable
- Oficinas de turismo municipales/departamentales, interesadas en dispersar turistas hacia zonas menos saturadas
- Aplicaciones de movilidad urbana que quieran añadir "qué hacer cerca de mí" a su producto existente
