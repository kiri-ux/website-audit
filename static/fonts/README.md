# Brand fonts — drop the files here

The PDF picks these up automatically on the next deploy. Nothing else to
configure; `engine/fonts.py` looks in this folder and falls back to Roboto,
then Helvetica, per family.

## Headlines — Agdasima

Free, from Google Fonts: https://fonts.google.com/specimen/Agdasima
Download the family, unzip, and put these two here with exactly these names:

    Agdasima-Regular.ttf
    Agdasima-Bold.ttf

## Body copy — GT Walsheim Pro

Licensed from Grilli Type. It cannot be downloaded automatically — copy the
files from wherever the licence lives and rename them to:

    GTWalsheimPro-Regular.ttf
    GTWalsheimPro-Bold.ttf
    GTWalsheimPro-Italic.ttf         (optional)
    GTWalsheimPro-BoldItalic.ttf     (optional)

`.otf` will not work — reportlab embeds TrueType only. If all you have is OTF,
convert it once with fontforge or an online converter and commit the TTF.

## Checking it worked

The worker prints one line per family at startup:

    [fonts] Agdasima registered for headlines
    [fonts] GT Walsheim Pro registered for body copy

No line for a family means the files were not found, and that family stays on
Roboto. Each registers independently, so one missing file does not cost you
both.

## Why the italics are optional

Reportlab synthesises nothing. A missing italic would silently drop asides back
to Helvetica in the middle of a sentence, so when the italic files are absent
the regular face is mapped to italic instead — a smaller wrong than a typeface
change inside one paragraph.
