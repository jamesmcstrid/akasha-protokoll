# Akasha Meet

Transkribera möten på din egen Mac. Spela in direkt i webbläsaren, eller ladda upp en ljudfil.
Du får texten uppdelad per talare: **Talare 1**, **Talare 2** och så vidare, och du kan byta till riktiga namn.

- **Allt stannar på datorn.** Tal till text och talaruppdelning görs lokalt. Inget skickas till
  någon molntjänst.
- **Svensk taligenkänning** med [KB-Whisper](https://huggingface.co/KBLab/kb-whisper-medium) från
  Kungliga biblioteket.
- **Inspelningen tappas inte.** Ljudet sparas på disken var femte sekund under mötet.

## Använda

1. Öppna **http://127.0.0.1:8611** i Safari eller Chrome. Spara gärna sidan som bokmärke.
2. Välj hur många som pratar. Skriv gärna in namn och facktermer som förekommer, så stavas de rätt.
3. Tryck **Spela in**. När mötet är slut trycker du **Stoppa och transkribera**.
   Du kan också trycka **Ladda upp ljudfil…** och välja en fil, t.ex. från Röstmemon.
4. Vänta medan texten tas fram. Förloppet syns i listan. Det tar en stund för långa möten
   (se "Hur lång tid tar det?").
5. Skriv in vad talarna heter och tryck **Spara namn**. Kopiera texten eller ladda ner den som
   `.md` eller `.txt`. Klicka på en tid för att lyssna på just det stället.

**Tips:**

- Be alltid om lov innan du spelar in någon.
- Ställ datorn mellan er. Mikrofonen behöver höra alla ungefär lika bra.
- Låt fliken vara öppen och datorn vaken. Om locket stängs slutar inspelningen.
- Om fliken stängs eller datorn startas om ligger inspelningen kvar i listan som "Spelar in".
  Tryck **Avsluta och transkribera**, så transkriberas det som hann sparas.
- Kontrollera texten mot ljudet innan du använder den. Taligenkänning gör fel, särskilt på namn,
  siffror och när flera pratar samtidigt.

### Hur lång tid tar det?

Testat på en Linux-dator med 4 processorkärnor: 57 sekunder samtal tog cirka 26 sekunder, varav
4 sekunder talaruppdelning. Ett möte på en timme tar alltså i storleksordningen en halvtimme på en
sådan dator. Hur snabbt det går på en Mac är **inte uppmätt än**. Apple Silicon är troligen snabbare,
och whisper.cpp-motorn (se nedan) kan använda grafikprocessorn.

## Installera

Kräver: en Mac (helst Apple Silicon), [Homebrew](https://brew.sh) och cirka 4 GB ledigt utrymme.
Öppna Terminal och kör:

```bash
brew install python@3.12 git
git clone https://github.com/jamesmcstrid/Akasha-Meet.git ~/akasha-meet
cd ~/akasha-meet
bash mac/installera.sh
```

Installationen skapar en Python-miljö och laddar ner modellerna (cirka 1,6 GB, bara första gången).
Den lägger också in tjänsten så att den startar när du loggar in, och öppnar webbsidan. Första gången
du spelar in frågar webbläsaren om lov att använda mikrofonen.

Kontrollera att allt fungerar (tar några minuter):

```bash
bash halsokoll/prov.sh
```

Alla rader ska börja med `OK` och sista raden ska vara `PROV: OK`. Provet transkriberar
testljuden i `testljud/` och raderar sin provinspelning efteråt.

**Uppdatera:** `cd ~/akasha-meet && git pull && bash mac/installera.sh`

**Avinstallera:** `bash mac/avinstallera.sh`. Tjänsten stoppas, men inspelningar och modeller ligger
kvar tills du tar bort dem själv.

## Var hamnar inspelningarna?

I mappen `~/AkashaMeet` i din hemkatalog. Bara ditt konto kommer åt mappen. För varje inspelning
finns ljudet, en `.md` med texten och en `.json` med uppgifterna. **Radera** i listan tar bort alla
tre.

Mappen ligger medvetet inte i Dokument eller på Skrivbordet, eftersom de ofta synkas till iCloud.
Vill du ha den någon annanstans anger du `DATAKATALOG` i `.env`.

## Integritet och säkerhet

- Tjänsten lyssnar bara på `127.0.0.1`. Ingen annan dator i nätverket kommer åt den.
- Efter installationen kopplar den inte upp sig mot internet. Modellerna hämtas en gång från
  Hugging Face, med låsta versioner och kontrollerade kontrollsummor (sha256).
- Andra webbsidor du har öppna kan inte styra tjänsten. Den svarar bara på `localhost`, och allt som
  ändrar något kräver en särskild header som en främmande sida inte får skicka.
- Ingen språkmodell skriver om eller sammanfattar texten. Det whisper hör är det som står.

## Snabbare med whisper.cpp (valfritt)

Standardmotorn (faster-whisper) körs på processorn. whisper.cpp kan använda grafikprocessorn (Metal)
på Apple Silicon:

```bash
brew install whisper-cpp
bash mac/hamta-modeller.sh ggml
```

Ändra sedan `#MOTOR=faster` till `MOTOR=whispercpp` i `.env` och kör `bash mac/installera.sh` igen.
Båda motorerna klarar provet, men om Metal faktiskt används och hur mycket snabbare det blir är
**inte provat på en Mac än**.

## Inställningar

Allt har standardvärden. Vill du ändra något gör du det i `.env`, som skapas vid installationen.
Starta sedan om tjänsten med `launchctl kickstart -k gui/$(id -u)/local.akasha-meet`.

| Inställning | Standard | Vad |
|---|---|---|
| `MOTOR` | `faster` | `faster` (processorn) eller `whispercpp` (Metal) |
| `ORDLISTA` | tom | Ord som alltid ska stavas rätt, t.ex. företagets namn |
| `DATAKATALOG` | `~/AkashaMeet` | Var inspelningar och texter sparas |
| `PORT` | `8611` | Webbsidans port |
| `TALARE_TROSKEL` | `0.8` | Bara för "Vet inte – gissa". Högre värde ger färre talare |
| `MAX_MB` | `1024` | Största fil som går att ladda upp |

## Felsökning

| Problem | Gör så här |
|---|---|
| `Bootstrap failed: 5` vid installation | Uppdatera (`git pull`) och kör `bash mac/installera.sh` igen. Hjälper inte det: Systeminställningar → Allmänt → Inloggningsobjekt, tillåt `bash` i bakgrunden |
| Sidan öppnas inte | `launchctl kickstart -k gui/$(id -u)/local.akasha-meet`. Läs loggen `~/AkashaMeet/akasha-meet.log` |
| "Inte redo" uppe till höger | Håll muspekaren över texten för att se orsaken. Oftast saknas modellerna: `bash mac/hamta-modeller.sh` |
| "Fick inte tillgång till mikrofonen" | Tillåt mikrofonen för sidan i webbläsarens inställningar, och för webbläsaren i Systeminställningar → Integritet och säkerhet → Mikrofon |
| Fel antal talare | Ange antalet i stället för "Vet inte", och tryck **Gör om** i listan |
| Inspelningen fastnade på "Spelar in" | Tryck **Avsluta och transkribera** i listan |

## Hur det fungerar

```
Webbläsaren (http://127.0.0.1:8611)
  ├─ spelar in med MediaRecorder och skickar ljudet i delar om 5 s ──┐
  └─ eller laddar upp en fil ─────────────────────────────────────────┤
                                                                      ▼
app/app.py (Flask, bara 127.0.0.1) ── sparar i ~/AkashaMeet ── köar ett jobb
  └─ bakgrundstråd, ett jobb åt gången:
       1. avkodar ljudet (PyAV)
       2. KB-Whisper medium: text med tidsstämpel per ord        app/motor.py
       3. sherpa-onnx: vem pratar när                            app/talare.py
          (pyannote segmentation-3.0 + NeMo TitaNet small)
       4. varje ord får den talare som pratade då → repliker
       5. sparar .json och .md                                   app/lagring.py, app/export.py
```

| Mapp | Innehåll |
|---|---|
| `app/` | Tjänsten (`app.py`), motorerna, talaruppdelning, lagring, export, webbsidan i `static/` |
| `mac/` | `installera.sh`, `hamta-modeller.sh`, `kor.sh`, `avinstallera.sh`, launchd-mallen |
| `halsokoll/` | `prov.sh`: provet efter installation |
| `tester/` | Enhetstester. De behöver inga modeller |
| `testljud/` | Två testljud ur FLEURS, se `testljud/KALLOR.md` |

Köra enhetstesterna: `venv/bin/python -m unittest discover -s tester`

## Vad som är testat

Provat 2026-11-17 i en Linux-miljö utan grafikprocessor, med samma Python- och biblioteksversioner:

- **Enhetstester:** 30 st, gröna. De täcker talaruppdelning, lagring av inspelningar i delar,
  export, skydd mot andra webbsidor och alla API-flöden.
- **`installera.sh` från början:** med en ersättare för launchd. Modellnedladdningen med
  sha256-kontroll gick igenom.
- **`halsokoll/prov.sh`:** grön med båda motorerna. Två talare blev rätt både med känt antal och
  med "Vet inte".
- **Webbsidan i Chromium**, med en ljudfil som låtsasmikrofon:
  - inspelning, stopp, talaruppdelning, namn, kopiera, nedladdning, uppladdning och radering;
  - en inspelning där fliken stängdes mitt i, som sedan avslutades och transkriberades från listan.

**Inte provat än:**

- på en riktig Mac (launchd, Metal);
- inspelning i **Safari**, som spelar in i ett annat format än Chrome;
- riktiga möten med personer som avbryter varandra.

Om inspelningen krånglar i Safari: använd Chrome.

## Källor och licenser

| Del | Licens |
|---|---|
| [KB-Whisper medium](https://huggingface.co/KBLab/kb-whisper-medium) (KBLab, Kungliga biblioteket) | Apache-2.0 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | MIT |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 |
| pyannote segmentation-3.0 (CNRS), via sherpa-onnx | MIT |
| NeMo TitaNet small (NVIDIA), via sherpa-onnx | CC-BY-4.0 |
| Testljud: [Google FLEURS](https://huggingface.co/datasets/google/fleurs) | CC-BY-4.0 |
