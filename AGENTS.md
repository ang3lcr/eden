# Agent Instructions for Eden PDF Processor

## Project Overview
Eden is a desktop PDF processing application built with Tkinter for Windows. It processes scanned PDFs through a pipeline: blank page detection → orientation correction → page reordering → per-page cropping → export.

## Getting Started
- Setup: Follow [README.md](README.md) for installation and running.
- Run: `python main.py` (requires virtual environment with dependencies from requirements.txt)
- Note: On Windows, pdf2image requires Poppler in PATH.

## Architecture
- **core/**: Domain logic (loading, detection, export)
- **ui/**: Tkinter screens and navigation
- **utils/**: Image and threading utilities
- **main.py**: Controller orchestrating the pipeline

Use AppState for centralized state management. Screens are factories accepting state and navigation callbacks.

## Conventions
- Type hints with `from __future__ import annotations`
- Spanish UI text for domain terminology
- Frozen dataclasses for immutable configs
- Private methods prefixed with `_`
- Callbacks for loose coupling
- Demo data support in screens

## Common Pitfalls
- Ensure thread safety with PyMuPDF; use threading.local()
- Always close PDF documents to prevent memory leaks
- Handle PDF rotation matrices correctly for cropping
- Validate PDFs have pages before export
- Poppler must be installed on Windows for pdf2image

## Development
- No tests yet; consider adding pytest for core modules
- Use mypy for type checking, black for formatting
- Implement NotImplementedError stubs in utils/ and UI helpers