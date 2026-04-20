# PDF Scanner Processor (Tkinter)

Proyecto base (arquitectura modular) para una app de escritorio en Python orientada a PDFs escaneados:

- Detección/eliminación de hojas en blanco
- Detección/corrección de orientación
- Reordenamiento visual con miniaturas
- Editor de recorte por página
- Exportación a un nuevo PDF

## Requisitos

- Python 3.10+ recomendado
- Windows (probado para tu entorno)

Instalación:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

> Nota: `pdf2image` en Windows suele requerir Poppler instalado y agregado al PATH. Se resolverá en la fase de implementación.

## Ejecutar

```bash
python main.py
```

## Estructura

- `main.py`: entrypoint
- `ui/`: pantallas Tkinter
- `core/`: procesamiento PDF/imagen (stubs por ahora)
- `utils/`: utilidades (stubs por ahora)

## Estado actual

Este commit/estado **solo crea el esqueleto**: clases, funciones y pantallas están declaradas pero la lógica está marcada con `NotImplementedError`.

