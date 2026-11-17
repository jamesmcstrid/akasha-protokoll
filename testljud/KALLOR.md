# Testljud

Båda filerna är byggda av klipp ur **Google FLEURS**, svenska (`sv_se`), dev-delen.
FLEURS är licensierat [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
([datasetet på Hugging Face](https://huggingface.co/datasets/google/fleurs), revision `70bb2e84`).

| Fil | Innehåll | Facit |
|---|---|---|
| `en-talare.m4a` | Klipp 1546 (`8643204747919211256.wav`), kvinnlig talare, 26 s | Texten innehåller "dinosaurie" |
| `tva-talare.m4a` | Klipp 1604 (`17669446668889921801.wav`, man) och 1546 (kvinna). Varje klipp är delat i två delar vid tystaste stället nära mitten, ordning man–kvinna–man–kvinna, 0,5 s paus emellan, 57 s | Två talare. "Carter" och "Afghanistan" (mannen) hos samma talare, "struktur" och "Forskarna" (kvinnan) hos den andra |

Eftersom varje röst är ett och samma klipp vet vi säkert att det är exakt två personer.
Ljudet är omkodat till AAC, 64 kbit/s, mono, 16 kHz. Ingenting annat är ändrat.
