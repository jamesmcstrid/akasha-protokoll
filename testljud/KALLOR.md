# Testljud

Båda filerna är byggda av klipp ur **Google FLEURS**, svenska (`sv_se`), dev-delen.
FLEURS är licensierat [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
([datasetet på Hugging Face](https://huggingface.co/datasets/google/fleurs), revision `70bb2e84`).

| Fil | Innehåll | Facit |
|---|---|---|
| `en-talare.m4a` | Klipp 1546 (`8643204747919211256.wav`), kvinnlig talare, 26 s | Texten innehåller "dinosaurie" |
| `tva-talare.m4a` | Klipp 1604 (`17669446668889921801.wav`, man) och 1546 (kvinna). Varje klipp är delat i två delar vid tystaste stället nära mitten, ordning man–kvinna–man–kvinna, 0,5 s paus emellan, 57 s | Två talare. "Carter" och "Afghanistan" (mannen) hos samma talare, "struktur" och "Forskarna" (kvinnan) hos den andra |
| `digitalt-mote.webm` | Ett digitalt möte i stereo, som Akasha Protokoll spelar in det. Vänster kanal ("du", mikrofonen): klipp 1604 (man). Höger kanal (mötet): klipp 1546 (kvinna) och 1525 (`16794003699941737274.wav`, en annan man). Ordning du–kvinna–man–du–kvinna–man, 80 s, Opus 96 kbit/s | Du är Talare 1 ("Carter", "Afghanistan"). Kvinnan ("struktur", "Forskarna") och den andra mannen ("boulevarderna", "Turkiet") är två olika talare |

Eftersom varje röst är ett och samma klipp vet vi säkert hur många personer det är.
`en-talare.m4a` och `tva-talare.m4a` är omkodade till AAC, 64 kbit/s, mono, 16 kHz. `digitalt-mote.webm`
är Opus, 96 kbit/s, stereo, 48 kHz. Ingenting annat är ändrat.

## testljud/facit.json

Den förväntade texten per testfil, för `halsokoll/jamfor_motorer.py`. Texterna är FLEURS egna avskrifter
(kolumnen `raw_transcription` i
[`data/sv_se/dev.tsv`](https://huggingface.co/datasets/google/fleurs/blob/70bb2e84b976b7e960aa89f1c648e09c59f894dd/data/sv_se/dev.tsv),
revision `70bb2e84`) för klippen 1546, 1604 och 1525, ordrätt. I de delade filerna ligger
klippens delar i den ordning ljudet har (till exempel man del 1, kvinna del 1, man del 2, kvinna del 2).
Var varje klipp delades står inte i FLEURS: delningsordet hittades genom att para ihop klippets text med
vad Pianissimo hörde i varje del, så att summan av ordfel blev minst. Facit är alltså FLEURS text, men
delningsstället är uppskattat (på meningsgränsen i alla tre klippen).

## testljud/format/

Tolv filer om 5 s (672 kB), ett exempel av varje ljudformat som avkodningen ska klara (de testas i
`tester/test_ljud.py` med exakta längder, och skickas genom det paketerade programmet av `paketering/kontrollera.py`).
Källan är samma FLEURS-klipp som ovan (CC-BY-4.0): de fem första sekunderna av `en-talare.m4a` (mono, 16 kHz) och av
`digitalt-mote.webm` (stereo, 48 kHz, för `opus-stereo.webm`), omkodade till formaten nedan. Inget annat är ändrat.

`mp3.mp3`, `opus.ogg`, `opus.opus`, `vorbis.oga`, `flac.flac`, `pcm.wav`, `adpcm.wav` (IMA), `aac.aac` (ADTS), `aac.mov`,
`aac-safari.mp4` (fragmenterad mp4, som Safari spelar in), `alac.m4a`, `opus-stereo.webm`.

De är gjorda med PyAV (med GPL-kodare som libmp3lame, libopus och libvorbis; det spelar ingen roll, filerna är data):
ett litet skript klipper de fem sekunderna, omsamplar till 16 kHz mono respektive 48 kHz stereo med
`av.audio.resampler.AudioResampler` och kodar med en kodare per format (`libmp3lame` 32 kbit/s, `libopus` 24 kbit/s för
mono och 48 kbit/s för stereo, `libvorbis` 32 kbit/s, `flac`, `pcm_s16le`, `adpcm_ima_wav`, `aac` 32 kbit/s, `alac`). Filerna
är inte bit för bit reproducerbara (Ogg-strömmar får ett slumpat serienummer), men längderna är exakta.
