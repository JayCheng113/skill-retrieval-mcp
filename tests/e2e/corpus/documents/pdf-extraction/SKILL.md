---
name: pdf-extraction
description: Pull text, tables and metadata out of PDF documents, including scanned pages that need OCR.
category: documents
tags: [pdf, ocr, parsing, tables]
---

# Extracting content from PDFs

A PDF has no notion of a paragraph, only glyphs at coordinates, so extraction
quality depends entirely on how the file was produced.

Digitally generated PDFs carry a real text layer. Read it directly and reconstruct
reading order from the glyph positions; do not assume the stored order is correct,
because multi-column layouts frequently interleave.

Scanned PDFs are images. Rasterise each page at 300 DPI and run OCR. Below 200 DPI
character accuracy falls off sharply, and above 400 DPI you pay time for nothing.

Tables need their own pass. Ruled tables can be recovered from the drawn lines;
tables held together only by whitespace need column positions inferred from the
horizontal distribution of glyph starts.
