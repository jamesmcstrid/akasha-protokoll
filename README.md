# <img src="app/static/elefant.svg" alt="" width="44" align="top"> Akasha Meet

Transkribera möten på din egen Mac. Spela in direkt i webbläsaren, eller ladda upp en ljudfil.
Du får texten uppdelad per talare och kan byta "Talare 1" och "Talare 2" mot riktiga namn.

- **Allt stannar på datorn.** Tal till text och talaruppdelning görs lokalt. Inget skickas till
  någon molntjänst.
- **Svensk taligenkänning** med [KB-Whisper](https://huggingface.co/KBLab/kb-whisper-medium) från
  Kungliga biblioteket. På Mac med Apple Silicon används grafikprocessorn (Metal).
- **Möten i rummet och digitalt.** Med datorns mikrofon, eller Google Meet och Slack i Chrome.
- **Inspelningen tappas inte.** Ljudet sparas på disken var femte sekund under mötet.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/bilder/akasha-meet-mork.png">
  <img src="docs/bilder/akasha-meet-ljus.png" alt="Akasha Meet i webbläsaren: formuläret för en ny transkribering och ett transkriberat möte där replikerna är uppdelade mellan Anna och Jonas." width="760">
</picture>

<sub>Exemplet är påhittat.</sub>

## Använda

1. Öppna **http://127.0.0.1:8611** i Chrome (eller Safari). Spara gärna sidan som bokmärke.
2. Välj **hur mötet spelas in** och **hur många som pratar**. Skriv gärna in namn och facktermer
   som förekommer, så stavas de rätt.
3. Tryck **Spela in**. När mötet är slut trycker du **Stoppa och transkribera**. Du kan också
   trycka **Ladda upp ljudfil…** och välja en fil, till exempel från Röstmemon.
4. Vänta medan texten tas fram. Förloppet syns i listan.
5. Skriv in vad talarna heter och tryck **Spara namn**. Kopiera texten eller ladda ner den som
   `.md` eller `.txt`. Klicka på en tid för att lyssna på just det stället. **Ladda ner ljudet**
   finns bredvid ljudspelaren.
6. Har en replik fått fel talare? Klicka på namnet i repliken och välj rätt person. Är bara en del
   fel, markera de orden och välj vem som sa dem. Där kan du också säga att alla repliker från en
   talare egentligen är någon annans. **Ångra rättningarna** tar texten tillbaka till hur den var
   efter transkriberingen. **Gör om** tar bort rättningarna, så sidan frågar först.

Inspelningen heter "Möte" och datum om du inte skriver en rubrik. Rubriken går att byta efteråt
med **Byt rubrik**. Filnamnet på en uppladdad fil används aldrig, eftersom Röstmemon döper
inspelningar efter platsen (en gatuadress).

### Med mikrofonen

För möten i samma rum, eller digitala möten där du har högtalare på. Mikrofonen fångar alla som
hörs i rummet.

- Ställ datorn mellan er. Mikrofonen behöver höra alla ungefär lika bra.
- Är du med i ett digitalt möte via högtalare blir de andras röster något sämre än i det digitala
  läget nedan.

### Digitalt i Chrome (Google Meet, Slack)

När du trycker **Spela in** frågar Chrome vilken flik som ska delas: välj fliken med mötet och
kryssa i **Dela även flikljud**. Det fungerar med hörlurar, och med alla möten i en Chrome-flik:
Google Meet, en Slack-huddle i Slack i Chrome (`app.slack.com`), Teams eller Zoom i webbläsaren.

- Din mikrofon och mötet spelas in i varsin kanal. Det du säger blir därför alltid **Du**, och bara
  de andra behöver delas upp efter röst.
- Räkna med dig själv i "Hur många pratar?". Tre betyder du och två till.
- Det fungerar bara i Chrome och andra Chromium-webbläsare. Safari och Firefox kan inte dela
  ljudet från en flik.
- Möten i **apparna** (Slack-appen, Teams, Zoom) har ingen flik att dela. Öppna mötet i Chrome,
  eller använd högtalare och **Med mikrofonen**. En Mac-hjälpare som hämtar ljudet direkt från
  apparna finns som förslag i [#1](https://github.com/jamesmcstrid/Akasha-Meet/issues/1).

### Bra att veta

- **Be alltid om lov innan du spelar in någon.** I ett digitalt möte ser de andra inte att du
  spelar in, som de gör när Meet själv spelar in. Säg till.
- Låt fliken vara öppen och datorn vaken. Om locket stängs slutar inspelningen.
- Medan texten tas fram somnar datorn inte av sig själv. Stänger du locket pausas
  transkriberingen och fortsätter när du öppnar det igen.
- Om fliken stängs eller datorn startas om ligger inspelningen kvar i listan som "Spelar in".
  Tryck **Avsluta och transkribera**, så transkriberas det som hann sparas.
- Kontrollera texten mot ljudet innan du använder den. Taligenkänning gör fel, särskilt på namn,
  siffror och när flera pratar samtidigt.

### Hur lång tid tar det?

På en MacBook Air med Apple Silicon tog ett möte på 1 timme och 24 minuter 12 minuter att
transkribera och dela upp per talare, alltså drygt 8 minuter per timme möte. Förloppet syns i
listan.

## Installera

Kräver: en Mac (helst Apple Silicon), [Homebrew](https://brew.sh) och cirka 4 GB ledigt utrymme.
Repot är privat, så du behöver läsrätt till det och en SSH-nyckel kopplad till ditt GitHub-konto.
Öppna Terminal och kör:

```bash
brew install python@3.12 git
git clone git@github.com:jamesmcstrid/Akasha-Meet.git ~/akasha-meet
cd ~/akasha-meet
bash mac/installera.sh
```

Installationen skapar en Python-miljö och laddar ner modellerna (cirka 1,6 GB, bara första gången).
På Apple Silicon installerar den också `whisper-cpp` via Homebrew, så att grafikprocessorn används.
Den lägger in tjänsten så att den startar när du loggar in, och öppnar webbsidan. Första gången
du spelar in frågar webbläsaren om lov att använda mikrofonen.

Kontrollera att allt fungerar (tar några minuter):

```bash
bash halsokoll/prov.sh
```

Alla rader ska börja med `OK` och sista raden ska vara `PROV: OK`. Provet transkriberar
testljuden i `testljud/` och raderar sina provinspelningar efteråt.

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

## Inställningar

Allt har standardvärden. Vill du ändra något gör du det i `.env`, som skapas vid installationen.
Starta sedan om tjänsten med `launchctl kickstart -k gui/$(id -u)/local.akasha-meet`.

| Inställning | Standard | Vad |
|---|---|---|
| `MOTOR` | `auto` | `auto` väljer whisper.cpp med Metal på Apple Silicon och faster-whisper på processorn annars. Går att tvinga med `whispercpp` eller `faster` (kör då `bash mac/installera.sh` igen) |
| `MODELL` | `medium` | `large` gör färre fel men tar längre tid och behöver 1,1 GB till. Kör `bash mac/installera.sh` efter att du ändrat, så hämtas modellen |
| `ORDLISTA` | tom | Ord som alltid ska stavas rätt, till exempel företagets namn |
| `DATAKATALOG` | `~/AkashaMeet` | Var inspelningar och texter sparas |
| `PORT` | `8611` | Webbsidans port |
| `TALARE_TROSKEL` | `0.6` | Två röster som liknar varandra mer än så räknas som samma person (0–1) |
| `MAX_MB` | `1024` | Största fil som går att ladda upp |

## Felsökning

| Problem | Gör så här |
|---|---|
| Sidan öppnas inte | `launchctl kickstart -k gui/$(id -u)/local.akasha-meet`. Läs loggen `~/AkashaMeet/akasha-meet.log` |
| "Inte redo" uppe till höger | Håll muspekaren över texten för att se orsaken. Oftast saknas modellerna: `bash mac/installera.sh` |
| `Bootstrap failed: 5` vid installation | Uppdatera (`git pull`) och kör `bash mac/installera.sh` igen. Hjälper inte det: Systeminställningar → Allmänt → Inloggningsobjekt, tillåt `bash` i bakgrunden |
| "Fick inte tillgång till mikrofonen" | Tillåt mikrofonen för sidan i webbläsarens inställningar, och för webbläsaren i Systeminställningar → Integritet och säkerhet → Mikrofon |
| Texten är inte uppdelad per talare | Kontrollera att "Hur många pratar?" inte står på 1, och tryck **Gör om** i listan |
| Fel antal talare, eller "bara 1 röst gick att skilja åt" | Tryck **Gör om** med rätt antal. Ange inte fler än som pratar; är du osäker, välj **Vet inte – gissa**. Rösterna skiljs lättare åt om ni sitter på ungefär samma avstånd från datorn. Är ni många i rummet hjälper en konferensmikrofon mitt på bordet |
| Du vill visa någon hur det gick, utan att dela texten | `bash halsokoll/sammanfatta.sh` skriver ut tider, talare och tecken på fel, men inga ord ur mötet. `bash halsokoll/talardiagnos.sh` visar varför det blev så många talare, och `bash halsokoll/jamfor.sh <id A> <id B>` jämför två transkriberingar av samma möte. Se [docs/TEKNIK.md](docs/TEKNIK.md) |
| Mötesljudet saknas i ett digitalt möte | Kryssade du i **Dela även flikljud**? Det går bara i Chrome. Gör en ny inspelning |
| Inspelningen fastnade på "Spelar in" | Tryck **Avsluta och transkribera** i listan |

## Teknik och utveckling

Hur det fungerar inuti, hur talaruppdelningen utvärderades och vad som är testat står i
[docs/TEKNIK.md](docs/TEKNIK.md). Enhetstesterna körs med
`venv/bin/python -m unittest discover -s tester`.

## Källor och licenser

| Del | Licens |
|---|---|
| [KB-Whisper medium](https://huggingface.co/KBLab/kb-whisper-medium) (KBLab, Kungliga biblioteket) | Apache-2.0 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | MIT |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 |
| NeMo TitaNet small (NVIDIA), via sherpa-onnx | CC-BY-4.0 |
| Testljud: [Google FLEURS](https://huggingface.co/datasets/google/fleurs) | CC-BY-4.0 |
