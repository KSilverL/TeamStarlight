# Bundled background-music library

This folder is the local, royalty-free music library that `BundledMusicLibrary`
(`core/services/media_assets.py`) picks from. It's the default real music provider —
no API key, no per-render cost, works offline — replacing the enterprise-gated Soundraw.

The storyboard agent chooses a `musicMood` / `musicGenre` / `musicEnergy` on
`StoryboardSpec.audio`; at render time the library returns the track that best matches
those tags. **Ships empty** — until you add at least one tagged track, music renders
silent (in mock mode) or falls back to Soundraw (if a key is set).

## How to add tracks

1. **Get royalty-free tracks** cleared for commercial use. Good sources:
   - [Pixabay Music](https://pixabay.com/music/) (Pixabay license, no attribution)
   - [Uppbeat](https://uppbeat.io/) (free tier, attribution rules vary)
   - [Free Music Archive](https://freemusicarchive.org/) (check each track's CC license)
   - [YouTube Audio Library](https://studio.youtube.com/) (download, check attribution flag)
   - Incompetech / Kevin MacLeod (CC-BY — allowed, but **requires attribution**)

   **Verify each track's license yourself** and keep attribution where required. Prefer
   tracks **≥ 40 seconds** (the render clips to the video length; a short track leaves a
   silent tail).

2. **Drop the audio files in this folder** (`.mp3`, e.g. `uplifting-corporate-01.mp3`).

3. **Tag them in `manifest.json`** — one entry per track:

   ```json
   {
     "tracks": [
       { "file": "uplifting-corporate-01.mp3", "mood": "uplifting", "genre": "corporate", "energy": "medium" },
       { "file": "calm-ambient-01.mp3",        "mood": "calm",      "genre": "ambient",   "energy": "low" },
       { "file": "energetic-electronic-01.mp3","mood": "energetic", "genre": "electronic","energy": "high" }
     ]
   }
   ```

   `file` is relative to this folder. Use the exact tag vocabularies below (matching
   `core/video_schema.py`); a track scores highest on a `mood` match, then `genre`,
   then `energy`, and the best-matching track is chosen (ties broken at random for
   variety). A track that matches nothing is still preferable to silence, so any
   populated library always returns *some* music.

   | Tag | Allowed values |
   |---|---|
   | `mood` | `inspiring`, `uplifting`, `energetic`, `calm`, `dramatic`, `playful` |
   | `genre` | `corporate`, `cinematic`, `electronic`, `acoustic`, `hiphop`, `ambient` |
   | `energy` | `low`, `medium`, `high` |

   Aim for at least one track per common mood; a dozen well-tagged tracks give plenty
   of variety.

## Activating it

Set `USE_MOCK_MUSIC_GENERATION=false` (this one service; the rest can stay mocked).
Once `manifest.json` has ≥ 1 track, `factory.get_music_generation()` uses this library
automatically — no Soundraw key needed. Point `MUSIC_LIBRARY_DIR` elsewhere if you keep
the tracks outside the repo.

## A note on git

`manifest.json` and this README are tracked. The audio files can be large — decide per
project whether to commit them or keep them out of git (and distribute another way). If
you keep them out, add a `.gitignore` here for `*.mp3` but keep `manifest.json`.
