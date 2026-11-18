# Reporte del harness de estrés

## Resumen por escenario

| Escenario | Filas | P50 latencia (ms) | P95 latencia (ms) | Coste acumulado medio por ejecución (USD) | Hit rate caché exacta | Recall medio fact-tracker |
|---|---:|---:|---:|---:|---:|---:|
| growing | 60 | 12264 | 29348 | 0.303865 | 0.00 | 0.83 |
| pivot | 60 | 2556 | 6215 | 0.094912 | 0.00 | 0.63 |
| contradiction | 60 | 6336 | 31595 | 0.238555 | 0.00 | 0.00 |
| attachment | 15 | 6234 | 7493 | 0.012057 | 0.00 | 0.17 |

## Latencia frente a tokens de entrada

| N (turno) | Tokens entrada P50 | Latencia P50 (ms) | Latencia P95 (ms) |
|---:|---:|---:|---:|
| 1 | 407 | 4000 | 6899 |
| 3 | 1370 | 4057 | 5317 |
| 6 | 3503 | 5859 | 7429 |
| 10 | 5823 | 7742 | 12919 |
| 20 | 11992 | 25497 | 40555 |

## Coste acumulado frente al turno

| N (turno) | Coste acumulado medio (USD) |
|---:|---:|
| 1 | 0.002392 |
| 3 | 0.009826 |
| 6 | 0.028191 |
| 10 | 0.065955 |
| 20 | 0.212444 |

## Recall de hechos frente a N

| N (turno) | growing | pivot | contradiction |
|---:|---:|---:|---:|
| 1 | — | — | — |
| 3 | 0.83 | 0.50 | 0.00 |
| 6 | 0.83 | 0.67 | 0.00 |
| 10 | 0.83 | 0.67 | 0.00 |
| 20 | 0.83 | 0.67 | 0.00 |

## Adjuntos por tamaño

| Adjunto (KiB) | Latencia P50 (ms) | Coste medio (USD) | Recall marcadores medio |
|---:|---:|---:|---:|
| 0 | 2224 | 0.001203 | — |
| 5 | 6343 | 0.004382 | 0.00 |
| 20 | 6762 | 0.008808 | 0.00 |
| 50 | 5326 | 0.015834 | 0.50 |
| 100 | 6234 | 0.030058 | 0.17 |

## Lectura

_Pendiente: redactar tras la ejecución en vivo, con los números de este reporte._
