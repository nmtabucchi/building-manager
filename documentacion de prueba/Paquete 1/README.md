# Corpus de prueba — Building Manager AI

## Escenario
Consorcio ficticio **Edificio Los Tilos**, ubicado en una dirección y ciudad ficticias dentro de CABA. Todo nombre, teléfono, importe, unidad y evento fue inventado para pruebas.

## Contenido
- `documentos/`: 8 PDF con reglamento de copropiedad, reglamento interno, actas, manual de mantenimiento, incidentes, contratos, expensas y comunicaciones.
- `metadata.json`: metadatos básicos por documento para asociar al pipeline de ingesta.
- `preguntas_evaluacion.csv`: 20 preguntas con respuesta esperada, fuentes y tipo de prueba.

## Casos RAG incluidos
1. Recuperación directa de datos y fechas.
2. Cruce de información entre actas, reglamentos y circulares.
3. Temporalidad: el horario anterior del SUM queda reemplazado desde el 15/02/2026.
4. Conflictos aparentes: reglas generales vs decisiones posteriores.
5. Preguntas que deben responderse con cautela.
6. Abstención cuando el corpus no contiene información (deuda individual de 8A).
7. Seguridad: procedimiento ante persona atrapada en ascensor.
8. No atribuir culpa o responsabilidad sin evidencia.

## Recomendación de carga
1. Extraer texto de cada PDF conservando el nombre del archivo.
2. Dividir por títulos/secciones, no solo por cantidad fija de caracteres.
3. Guardar por chunk: `document_id`, `file_name`, `section`, `page_number` (si se obtiene), `document_type`, `effective_date`, `source_version`, `text`.
4. Generar embeddings y almacenar chunks en la base vectorial.
5. En la respuesta, devolver fuente, sección y página cuando esté disponible.
6. Para documentos normativos, priorizar decisiones/actas posteriores sobre el texto base cuando modifiquen expresamente una regla.

## Esquema sugerido de metadatos por chunk
```json
{
  "document_id": "uuid",
  "file_name": "02_reglamento_uso_espacios_comunes.pdf",
  "document_type": "reglamento_interno",
  "section": "5. Circular aclaratoria del 02/02/2026",
  "effective_date": "2026-02-15",
  "source_version": "2026-02-02",
  "building": "Edificio Los Tilos",
  "synthetic": true
}
```

## Importante
Este corpus es 100% ficticio, creado para validar ingesta, chunking, embeddings, recuperación, citas, manejo temporal y abstención. No es documentación real ni asesoramiento legal.
