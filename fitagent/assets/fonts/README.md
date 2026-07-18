# Caption fonts

Captions are burned in with libass, which finds fonts via fontconfig. The
default caption font is **DejaVu Sans** (preinstalled on nearly every Linux
distro), so nothing is required here out of the box.

For the classic condensed motivation-caption look, drop an OFL-licensed
display font in this folder (files are gitignored) and point the pipeline at
it — recommended picks, both SIL Open Font License:

- **Oswald** — https://fonts.google.com/specimen/Oswald
- **Bebas Neue** — https://fonts.google.com/specimen/Bebas+Neue

Then set the font name in `media/captions.py`'s `CaptionStyle.font` (or a
future `captions.font` config key). ffmpeg is invoked with
`fontsdir=assets/fonts` so fonts placed here are found without a system
install.
