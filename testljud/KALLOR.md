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
