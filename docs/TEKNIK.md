# Akasha Protokoll: teknik och tester

Hur Akasha Protokoll fungerar inuti, hur talaruppdelningen gick till och vad som är testat.
Användning och installation står i [README](../README.md).

## Hur det fungerar

```
Webbläsaren (http://127.0.0.1:8611, eller den port som PORT anger)
  ├─ spelar in med MediaRecorder och skickar ljudet i delar om 5 s ──┐
  │    digitalt möte: mikrofonen i vänster kanal, mötesfliken i höger │
  └─ eller laddar upp en fil ─────────────────────────────────────────┤
                                                                      ▼
app/app.py (Flask, bara 127.0.0.1) ── sparar i ~/AkashaProtokoll ── köar ett jobb
  └─ bakgrundstråd, ett jobb åt gången:
       1. avkodar ljudet (PyAV)
       2. KB-Whisper medium: text med tidsstämpel per ord        app/motor.py
       3. vem pratar när:                                        app/talare.py
          röstavtryck (NeMo TitaNet small via sherpa-onnx) i fönster om 1,5 s
          längs talet, uppdelade i lika många grupper som antalet talare
       4. varje ord får gruppen som fönstren runt ordet liknar mest
       5. talaren byter inte mitt i en mening (korta avvikelser rättas) → repliker
       6. sparar .json och .md                                   app/lagring.py, app/export.py
```

| Mapp | Innehåll |
|---|---|
| `app/` | Tjänsten (`app.py`), motorerna (`motor.py`), modellerna och hämtningen (`modeller.py`), talaruppdelningen (`talare.py`), det som skiljer mellan operativsystemen (`plattform.py`), starten som är gemensam för alla system (`start.py`), Dock-ikonen och menyn på Mac (`mac_app.py`), ikonen vid klockan och menyn på Windows (`windows_app.py`), avkodning med PyAV (`ljud.py`), lagring, export och webbsidan i `static/` |
| `paketering/` | PyInstaller-spec, kontrollskript och byggskript för programmet. `prova-linux.sh` bygger samma Python-delar på Linux och kör kontrollen. |
| `mac/` | `installera.sh`, `hamta-modeller.sh`, `kor.sh`, `avinstallera.sh` och launchd-mallen. Skripten som hämtar modeller anropar `app/modeller.py` |
| `halsokoll/` | `prov.sh`: provet efter installation. `sammanfatta.sh` och `talardiagnos.sh`: hur en transkribering gick, utan att visa texten (se nedan) |
| `tester/` | Enhetstester. De behöver inga modeller. Här finns också `falsk_hf.py` (en låtsaskälla som spelar Hugging Face), `falsk_onnx_asr.py` (låtsas-`onnx_asr` för Pianissimo), `forsta_start.py` (startar sidan som vid första start, med låtsaskällan) och `test_riktig_hamtning.py` (hämtar röstmodellen på riktigt, bara för hand) |
| `.github/workflows/` | Testerna i GitHub Actions och byggflödena för Mac- och Windows-programmet |
| `testljud/` | Tre testljud ur FLEURS, se [KALLOR.md](../testljud/KALLOR.md) |
| `docs/` | Den här filen och bilderna till README |

Köra enhetstesterna:

```bash
venv/bin/python -m unittest discover -s tester
```

## Webbsidan och API:t

Webbsidan är en enda sida utan ramverk: `app/static/index.html`, `app.js` och `stil.css`. Den
pratar med tjänsten via JSON. Allt som ändrar något är `POST` och kräver headern `X-Akasha-Protokoll: 1`.

| Anrop | Vad |
|---|---|
| `POST /api/inspelningar` | Ny inspelning: filändelse, rubrik, antal talare, ord och källa. Svarar med id |
| `POST /api/inspelningar/<id>/del?nr=N` | En del av ljudet, var femte sekund under inspelningen |
| `POST /api/inspelningar/<id>/klar` | Inspelningen är slut. Tar emot `talare`, `ord` och `titel`, som läses vid stopp så att de kan ändras under mötet. En tom `titel` behåller rubriken från starten. Utan `talare` gäller inställningarna från starten ("Avsluta och transkribera") |
| `POST /api/inspelningar/fil` | Uppladdad fil (multipart) |
| `POST /api/inspelningar/<id>/transkribera` | "Transkribera igen" (och "Försök igen"): `talare` och `ord` från dialogen. Källan behålls alltid, eftersom kanalerna i filen inte ändras |
| `GET /api/inspelningar`, `GET /api/inspelningar/<id>` | Listan, och en inspelning med text. Båda har `rattad` (talarna har rättats för hand). Maskinens version, `segment_original`, skickas inte: den finns bara i inspelningens `.json` |
| `GET /api/modeller` | Vilka modeller som saknas (med storlek, källa och licens), hur mycket som redan är hämtat, ledigt utrymme, och hur hämtningen går. `hinder` är satt när något saknas som en hämtning inte kan rätta |
| `POST /api/modeller/hamta` | Startar hämtningen av det som saknas, i en bakgrundstråd. Kroppen läses inte. En hämtning som redan pågår startas inte om. `POST /api/modeller/avbryt` stoppar den; det som hämtats ligger kvar |
| `POST …/titel`, `…/namn`, `…/talare`, `…/talare/angra`, `…/radera` | Byt rubrik, spara talarnamn, rätta talare, ångra alla rättningar, radera |
| `GET …/text.md`, `…/text.txt`, `…/ljud` | Nedladdningar. `?ladda_ner=1` på ljudet ger en fil att spara |
| `POST /transcribe` | För skript och hälsokollen: multipart `audio`, valfritt `speakers`. Svarar med texten direkt. Ett anrop åt gången: pågår redan ett svarar tjänsten 429 |

**Ljudet på disken.** Varje del läggs till i ljudfilen, och `.json` får `delar` och `byte` (ljudfilens längd efter delen). Sparas inte uppgifterna kortas ljudfilen tillbaka, och är filen längre än `byte` vid nästa del (programmet stannade mellan stegen) kortas den först. En del som webbläsaren skickar igen hamnar alltså aldrig två gånger i ljudet. En uppladdad fil skrivs först till `<id><ändelse>.delvis` och syns i listan först när den är hel. Det som en avbruten uppladdning lämnar (`.delvis` och en tom reservation) tas bort när programmet startar. Listan läser bara om en inspelnings `.json` när filen har ändrats.

När tjänsten inte svarar visar sidan "Akasha Protokoll svarar inte…" där felet hör hemma, etiketten blir "Tjänsten svarar inte", och sidan frågar var femte sekund tills tjänsten svarar igen.

Medan ett jobb pågår har inspelningen fältet `framsteg`: `fas` (`koar`, `transkriberar` eller
`talare`), `andel` (0–1) och `sekunder`, hur länge den här fasen har pågått. Sidan räknar ut
ungefär hur lång tid som är kvar av transkriberingen ur `andel` och `sekunder`, och visar
ingenting förrän minst 5 % är klart och 15 s har gått. Framsteget finns bara i minnet.

Sidan i korthet:

- **Ny transkribering:** antal talare, svårstavade ord och rubrik läses när man trycker Stoppa.
  Källan (mikrofon eller digitalt) gäller bara inspelning, och "Digitalt" är avstängt i
  webbläsare som inte kan dela flikljud (allt utom Chrome och andra Chromium-webbläsare). Under inspelningen visar en
  nivåmätare ljudet, och en varning visas om nivån har legat under −80 dBFS i tio sekunder.
  Flikens titel visar ● och tiden.
- **En sak i taget:** högra ytan visar formuläret eller den öppna inspelningen, aldrig båda, med knappen "Ny transkribering" för att komma tillbaka till formuläret. Det som pågår i formuläret (inspelning, kön för ljud som väntar, uppladdning) döljs aldrig, inte ens när modellkortet står ensamt vid första start (då ligger kortet över formuläret): öppnar man då en inspelning står den under formuläret. All visning och döljning sker i `visaYta()` i `app.js`.
- **Ljud som väntar:** Under inspelningen behåller sidan alla delar i minnet (cirka 27 MB per timme med mikrofonen och 40 MB digitalt, uppmätt med låtsasmikrofon) och skickar dem i ordning. Svarar inte tjänsten försöker sidan igen utan slut, och efter Stoppa startar transkriberingen när allt har kommit fram. Vid ett serverfel slutar sidan skicka och erbjuder "Spara ljudet som fil". Inspelningen släpps först när allt är sparat eller filen är sparad, och då släpps också ljudet ur minnet. Stannar inspelningen av sig själv (mikrofonen kopplas bort, ett fel i webbläsaren) skickas och transkriberas det som hann spelas in, som efter Stoppa, och sidan säger varför. Försvinner bara mikrofonen under ett digitalt möte fortsätter inspelningen med mötesljudet. Ett dubbelklick på Spela in startar en inspelning.
- **Listan:** byggs om varannan sekund medan något transkriberas eller fliken själv spelar in. En annan
  inspelning som står som "Spelar in" (oftast övergiven: fliken stängdes mitt i) ger var tionde sekund.
  Medan fliken är dold frågar sidan inte efter listan, och hämtar den direkt när fliken syns igen. Ljudet
  under en inspelning skickas ändå. Ett svar för en inspelning som man redan har lämnat visas inte.
  "Transkribera igen" öppnar en dialog
  som fylls i från inspelningens egna inställningar, inte från formuläret högst upp.
- **Visningen** i tre steg: 1 Vem är vem? (namnen sparas när fältet lämnas eller med Enter;
  "Lyssna" spelar upp till 10 s av talarens längsta säkra replik), 2 Kontrollera mot ljudet
  (förklaring av markeringarna, en rad med ljudspelaren som följer med vid bläddring, och texten)
  och 3 Använd texten. Ett klick på ett osäkert ord spelar från 2 s före ordets uppskattade tid.
- **Kvitton och fel** från listan och visningen visas i en ruta nederst i fönstret. Kvitton
  försvinner efter 6 s, fel ligger kvar tills man stänger dem.
- **Typsnitt:** Anton och Instrument Sans följer med programmet som `.woff2`-filer i `app/static/typsnitt/`, tillsammans med licenserna (SIL OFL 1.1, `OFL-*.txt`). Sidan hämtar inget typsnitt från internet.

## Modellerna och hämtningen

Modellerna är för stora för att följa med i repot (1,6 GB med standardvalet), så de hämtas från
Hugging Face första gången. Det är den enda användningen av internet. Allt om dem står i
`app/modeller.py`, och bara där: repo, revision, filnamn, katalog, storlek och sha256 för varje
fil. Skripten i `mac/` har ingen egen kopia utan anropar `python app/modeller.py`, och webbsidan
använder samma modul genom API:t ovan.

- **"Finns" betyder rätt storlek.** Det kostar inget och kontrolleras vid varje anrop till
  `/health` och `/api/modeller`. sha256 räknas när en fil har hämtats, inte vid varje start
  (1,5 GB tar flera sekunder).
- **Halva filer** heter `<namn>.delvis` bredvid målet och har aldrig målets namn. När sha256
  stämmer döps filen om med `os.replace`, som är atomiskt på alla tre systemen. Stämmer den inte
  tas `.delvis` bort. En avbruten hämtning fortsätter med `Range: bytes=N-`. Svarar servern 200 i
  stället för 206 börjar filen om från början.
- **Omdirigeringar följs för hand**, högst fem, och bara till `huggingface.co`, `*.huggingface.co`
  och `*.hf.co`, över https. Varje adress kontrolleras innan den begärs. Startadressen byggs alltid
  av manifestet, och varje försök börjar om därifrån, eftersom adresserna till CDN:et är signerade
  och går ut.
- **Egna omförsök:** avbrott, tidsgräns och nätfel ger två nya försök (efter 2 och 5 s) innan
  felet visas. Ett försök som har hunnit hämta minst 1 MiB räknas inte, men en fil får högst
  20 försök.
- **Proxy och certifikat:** `requests` följer `HTTPS_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE` och
  `CURL_CA_BUNDLE`. Det läser inte `SSL_CERT_FILE`, så `ny_session()` använder den om ingen av de
  andra är satt. Är ingen av de tre satt använder `ny_session()` operativsystemets egna certifikat
  via `truststore` (`truststore.SSLContext`), så ett företagsnät med egen rot-CA i nyckelringen
  fungerar utan inställningar. Saknas `truststore` blir det som förut. `.env` läses av `mac/kor.sh`,
  så proxyn kan stå där, och i programmet står den i `installningar.env` (se nedan).
- **`HF_HUB_OFFLINE=1`** sätts överst i `motor.py`, så att faster-whisper aldrig hämtar något
  själv.
- **Motorn väljs om efter hämtningen.** `motor.mal_motor()` säger vilken motor modellerna ska
  hämtas för: på en Mac med `whisper-cli` är det whisper.cpp även när GGML-filen saknas.
  `motor.uppdatera()` räknar om den aktiva motorn efter en lyckad hämtning och vid anrop till
  `/health` och `/api/modeller`. Den väntar aldrig på transkriberingslåset, så tjänsten blir redo
  utan omstart, även om modellerna hämtades med skriptet i en terminal.
- **Vad som erbjuds:** taligenkänningen bara om den aktiva motorn inte är redo, och röstmodellen om
  den saknas. Den som redan kör faster-whisper på en Mac får alltså ingen uppmaning att hämta
  GGML-modellen. Sådant som en hämtning inte kan rätta, till exempel `whisper-cli` som saknas med
  `MOTOR=whispercpp` eller en okänd `MODELL`, visas som "Inte redo".
- **Testkällan:** `tester/falsk_hf.py` är en transport för `requests` som spelar Hugging Face:
  omdirigering till en CDN-värd, `Range`, avbrott mitt i en fil, fel innehåll, serverfel och
  nätfel. Testerna och `forsta_start.py` byter bara ut sessionen (`modeller.ny_session`), så all
  riktig kod körs oförändrad: adresserna, omdirigeringarna, kravet på https och sha256. Det finns
  ingen flagga, miljövariabel eller undantag för http i `app/`. Transporten stoppar alla andra
  värdar än de falska, så inget test når nätet.

## Programmet (Mac)

Programmet är ett vanligt Mac-program, `Akasha Protokoll.app`, för Apple Silicon (macOS 14 eller senare).
Det ersätter inte terminalinstallationen: båda finns kvar och använder samma kod i `app/`.
Flödet `.github/workflows/mac-app.yml` bygger programmet för hand på `macos-26`.

- **Hur det byggs.** PyInstaller 6.22.3 i katalogläge samlar Python, beroendena och deras inbyggda
  bibliotek till ett `.app`-paket. En spec-fil, `paketering/akasha-protokoll.spec`, bygger både Mac-programmet
  och provbygget på Linux (en vanlig katalog). `whisper-cli` byggs från källkod i GitHub Actions
  från en fast tagg av whisper.cpp, statiskt och med Metal, och läggs in i paketet så att den
  signeras med resten. Artefakten är en zip-fil som packas med `ditto`, för att behålla
  behörigheter och signatur. Bygget är ad hoc-signerat, inte signerat med ett Apple Developer ID. Flödet i
  Actions (`.github/workflows/mac-app.yml`) körs bara för hand.
- **Vad som följer med.** Flask, waitress, requests, sherpa-onnx, numpy, PyAV (`av`), `truststore`
  och `whisper-cli`, samt PyObjC för Dock-ikonen och menyn. faster-whisper, ctranslate2,
  tokenizers, huggingface_hub och onnxruntime följer inte med, eftersom programmet använder
  whisper.cpp. Därför avkodas ljudet med `app/ljud.py` (PyAV) i stället för med faster-whisper.
  Sätts `MOTOR=faster` i programmet visar sidan "Inte redo" med en förklaring.
- **Licenserna.** `paketering/samla_licenser.py` körs av spec-filen direkt efter PyInstallers analys och
  skriver katalogen `licenser/`: en fil per komponent med hela licenstexten och upphovsrättsraderna, och
  förteckningen `LICENSER.txt` (namn, version, licens, källa, fil). Python-paketen är de distributioner
  som äger någon av filerna som analysen tog med (källsökvägarna jämförs med paketens `RECORD`), så det som
  `excludes` utesluter kommer inte med, medan till exempel `setuptools` och `packaging` gör det (PyInstallers
  körtidskrok `pyi_rth_setuptools`). Texterna läses ur paketens dist-info; ett paket utan licensfil är fel,
  utom `sherpa-onnx-core` och `pyobjc-core`, som får texten från ett paket ur samma projekt med samma
  version. Bibliotek som ett hjul bär med sig (`numpy.libs`, `sherpa_onnx/lib`, `av.libs`) ska täckas av
  paketets licenstext, av FFmpeg, av Visual C++-runtimen eller av en text i `paketering/licenstexter/`
  (ONNX Runtime 1.28.2 i sherpa-onnx-core 2.0.1). Dessutom Python (`LICENSE.txt` ur den Python som
  bygger), whisper.cpp (`build/whisper/licens/`, som `bygg-whisper-cli.sh` kopierar ur källkoden och flödet
  cachar med `whisper-cli`), FFmpeg (`AKASHA_FFMPEG_LICENSER`, katalogen `ut/ffmpeg` från `bygg-ffmpeg.sh`)
  och typsnitten. Katalogen hamnar i `Contents/Resources/licenser/`, före signeringen. Saknas en text byggs
  programmet ändå, med `LICENSER.txt` markerad `OFULLSTÄNDIG`, och `kontrollera_licenser.py` (i
  `bygg-mac.sh` och först i `kontrollera.py`) stoppar: den kontrollerar förteckningen och filerna, och att
  varje Python-paket i programmet, både filerna på disk och modulerna i PYZ-arkivet, står i förteckningen.
- **FFmpeg (bara LGPL).** Flödena bygger FFmpeg 6.1.6 och PyAV 12.3.0 från källkod, som `prova-linux.sh`
  (`bygg-ffmpeg.sh`, `bygg-pyav.sh`; på Mac bara för arm64), cachar hjulet, licenstexterna och
  källkodsarkivet (nyckel: skripten, komponentlistan och verktygens versioner) och installerar det egna
  hjulet i byggets venv. PyAV-hjulet från PyPI, vars FFmpeg är GPL-bygget med x264, x265 och ett trettiotal
  andra bibliotek, installeras aldrig där; `app/requirements.txt` (`av==12.3.0`) gäller som förut för
  terminalinstallationen och testerna. `kontrollera_ffmpeg.py` körs mot hjulet och mot det byggda programmet
  (`bygg-mac.sh`), enhetstesterna körs med `AKASHA_FFMPEG_LGPL=1`, och `kontrollera.py` avkodar alla tolv
  testljud i `testljud/format/` i programmet. Källkodsarkivet laddas upp som artefakten `ffmpeg-6.1.6-kallkod`
  (med `bygg-ffmpeg.sh` och `ffmpeg-komponenter.txt`) och ska läggas i releasen, där förteckningen säger att
  det finns. Uppmätt i körning 44912059276 (2026-11-21): programmet är 90 MB (förut 128 MB), zip-filen
  32,9 MB (förut 49 MB) och 138 Mach-O-filer (förut 164); förteckningen har 29 komponenter.
- **Det som följer med Python.** Python 3.12.10 från python.org har med sig OpenSSL 3.0.16 (`libssl.3.dylib`,
  `libcrypto.3.dylib`), XZ Utils 5.2.3 (statiskt i `_lzma`), expat (`pyexpat`), libmpdec (`_decimal`) och
  HACL* (`_md5`, `_sha1`, `_sha2`, `_sha3`); libffi, zlib och bzip2 kommer från macOS (`bygg-mac.sh` steg 3b
  visar vad lib-dynload-modulerna länkar mot). Förteckningen har därför OpenSSL och XZ Utils som egna
  komponenter (versionen av OpenSSL ur `ssl.OPENSSL_VERSION`, av XZ ur CPythons byggskript, `XZ_I_PYTHON`), och
  `python.txt` har CPythons `Doc/license.rst` och HACL*-texten (`paketering/licenstexter/cpython-3.12`).
  `kontrollera_licenser.py` faller om något av det finns i programmet men inte i förteckningen.
- **Start och avslut.** `mac_app.py` är det tunna Mac-skalet: ikon i Dock, programmenyn och
  Dock-menyn. Allt annat ligger i `start.py`, som går att köra och testa på Linux: loggning, kontroll
  av inställningsfilen, om porten är ledig, tjänsten i en bakgrundstråd, att öppna webbläsaren och att
  stänga ned. Vid start frågar `start.lage()` om porten är ledig, upptagen av en annan Akasha Protokoll
  eller upptagen av något annat. En annan Akasha Protokoll gör att programmet bara öppnar sidan och
  avslutas, och något annat ger ett felmeddelande. Dubbelklick på ett program som redan är igång
  hanteras av macOS, som skickar "öppna igen" till det som körs. Vid ⌘Q frågar programmet först om
  det pågår en inspelning, en transkribering eller en hämtning (`start.pagar()`), och stänger sedan
  servern och `whisper-cli`. En transkribering som avbryts på det sättet blir `avbruten` och kan
  göras om med "Försök igen".
- **Den gamla installationen.** Finns launchd-tjänsten `local.akasha-meet` frågar programmet om det
  ska ta över. Svarar man ja stängs tjänsten av med `launchctl disable` och `launchctl bootout`, så
  att den inte startar vid nästa inloggning, och programmet väntar tills porten är ledig. Två
  tjänster får aldrig dela datakatalog, eftersom `lagring.aterstall_avbrutna()` vid start annars
  skulle märka den andras pågående jobb som avbrutna. `mac/installera.sh` stannar åt andra hållet
  med en förklaring om programmet är igång på porten och launchd-tjänsten inte finns.
- **Var saker ligger.** Inspelningar: `~/AkashaProtokoll`, som i terminalinstallationen. Modeller:
  `~/Library/Application Support/Akasha Protokoll/modeller`. Inställningar:
  `~/Library/Application Support/Akasha Protokoll/installningar.env`, med samma `NAMN=värde` som `.env`.
  Den läses bara när programmet är paketerat, och en miljövariabel som redan är satt vinner.
  Programmet stannar aldrig på grund av filen: det som inte går att läsa ersätts med
  standardvärdet, och rutan vid start, loggen och (utan fönster) stderr säger till. Problemtexterna
  innehåller bara radnummer och inställningens namn, aldrig något ur filen. Loggen ligger i
  `~/Library/Logs/Akasha Protokoll/akasha-protokoll.log` (roterande, 2 MB, tre filer). Har någon modeller i
  repots `modeller/` från terminalinstallationen hårdlänkas de in i programmets katalog vid start,
  så att inget hämtas igen och terminalinstallationen fungerar som förut. Går länken inte (annan
  volym) erbjuder sidan hämtning som vid första start.
- **Flytten från det gamla namnet.** Programmet hette förut Akasha Meet och hade `~/AkashaMeet` och
  `~/Library/Application Support/Akasha Meet` (på Linux `~/.local/share/akasha-meet`, på Windows
  `%LOCALAPPDATA%\Akasha Meet`). `plattform.programkatalog()` och `plattform.standard_datakatalog()`
  ger den nya mappen om den finns eller om den gamla inte finns, annars den gamla, så att sidan aldrig
  visar en tom lista eller erbjuder en ny hämtning även om flytten inte har gjorts. Flytten är
  `plattform.flytta_till_nya_namn()`: bara `os.rename`, bara när den gamla finns som katalog och den
  nya inte finns. Finns båda rörs ingenting (och det loggas), ett `OSError` loggas och lämnar den gamla
  på plats, och inspelningsmappen flyttas inte om `DATAKATALOG` är satt i miljön eller i
  inställningsfilen. Den görs i `Tjanst.starta()`, alltså bara när beslutet är att starta (inte när
  en annan Akasha redan kör eller porten är upptagen), före `import app`, och efteråt räknar
  `installningar.uppdatera_platser()` om standardplatserna. Ligger loggen i en katalog som flyttades
  (Linux, Windows) byter loggern till den nya sökvägen. Terminalinstallationen (`app.py` utan
  `start.py`) flyttar inget men följer samma upplösning; `mac/installera.sh` gör flytten med `mv`
  innan tjänsten startas om. Loggkatalogen och loggfilen byter namn utan flytt.
  `kontrollera.py` lägger de gamla mapparna före start och kontrollerar att de ligger under de nya
  namnen efteråt.
- **Det enda som skiljer.** Om koden körs som programmet avgörs av `sys.frozen`, PyInstallers eget
  märke, och bara i `app/plattform.py`. Det finns ingen testflagga eller testmiljövariabel i `app/`.
- **Kontrollen i Actions.** Det byggda programmet ska startas med en tom hemkatalog (`HOME`). En
  gles fil med GGML-modellens storlek läggs i `~/akasha-meet/modeller`, så att flytten av gamla
  modeller och motorvalet provas utan att 1,5 GB hämtas. Röstmodellen (40 MB) hämtas på riktigt
  genom programmets eget API. Ett testljud laddas upp, avkodningen ska lyckas och jobbet ska
  misslyckas med ett fel från den medföljande `whisper-cli` (den gles filen är ingen modell). Sist
  skickas SIGTERM och porten ska vara ledig. Dessutom ska den medföljande `whisper-cli`
  transkribera ett testljud med en liten riktig modell. Samma kontrollskript
  (`paketering/kontrollera.py`) körs mot provbygget på Linux. Kontrollen visar att programmet
  startar, att standardplatserna, flytten av modeller och av de gamla mapparna, motorvalet, sherpa-onnx, PyAV, requests och
  certifikaten fungerar i det frysta programmet, att hämtningen från Hugging Face fungerar, och att
  loggen och avslutet fungerar. Den visar inte att Metal används, att Gatekeeper släpper igenom
  programmet efter godkännandet i Systeminställningar, eller att en riktig KB-Whisper-modell
  transkriberar. Det kräver en riktig Mac.
- **Uppmätt i första körningen (2026-11-20).** Maskinen var macOS 26.7.2, Apple M1 (Virtual) med
  3 kärnor, Xcode 26.6 och Python 3.12.10. whisper.cpp v1.9.5 är commiten
  `d1be6fde11ac6e0407606b4e42fe72d34add8037`; `whisper-cli` byggdes statiskt, med Metal
  inbäddat och OpenMP av, länkar bara mot systembibliotek (åtta) och är 8,0 MB. Kompilatorns mål
  hade NEON, dotprod och fp16. Programmet är 128 MB och zip-filen 49 MB; störst är av (51 MB) och
  sherpa-onnx (33 MB). Alla 164 Mach-O-filer är arm64 med lägsta macOS 11.0 eller 14.0. Programmet
  är ad hoc-signerat och `codesign --verify --deep --strict` godkänner det; `spctl` avvisar det,
  vilket är väntat utan Developer ID. Jobbet tog 5 min 6 s.
- **Vad kontrollen visade.** Programmet startade och svarade efter 3 s med tom hemkatalog. Motorn
  blev whisper.cpp med det medföljande `whisper-cli`, en gammal modellfil hårdlänkades in,
  röstmodellen hämtades från Hugging Face och kontrollerades (6,4 s), och ljudet avkodades.
  `whisper-cli` startades från paketet, loggfilen hamnade i `~/Library/Logs/Akasha Meet`, och
  avslut med SIGTERM lämnade porten ledig. Det medföljande `whisper-cli` transkriberade ett
  testljud med en liten modell, med ordtider från DTW (42 ord). Metal fanns på Actions-maskinen
  (en paravirtuell GPU) och kompilerade sina bibliotek första gången (23 s); på en riktig MacBook
  Air tog den första transkriberingen av 12 s ljud 8,0 s och den andra 2,6 s (se Vad som är testat).
- **Uppmätt i andra körningen (2026-11-20).** Enhetstesterna på macOS gav 261 tester, OK, fyra
  överhoppade, och inga `Bad file descriptor` vid avslut (det som syntes i första körningen är
  rättat). Ett enda test tog 36 s: det första som skapar en testserver med `http.server`, vars
  `server_bind()` slår upp maskinens namn. Tolkningen, som inte är bevisad, är att namnuppslaget är
  långsamt på Actions-maskinen; testservern slår därför inte längre upp något namn, och programmet
  berörs inte (det använder waitress). `whisper-cli` byggdes igen från samma commit `d1be6fde…`.
  Metal-biblioteken kompilerades på 18,9 s första gången (23 s i första körningen), och den lilla
  transkriberingen tog 8 s. DTW-förvalen `medium` och `large.v3` godtas av v1.9.5: ett påhittat
  förval ger `error: unknown DTW preset` innan modellen laddas, medan `medium` och `large.v3`
  laddar modellen och sedan misslyckas som väntat, eftersom ordtidshuvudena inte passar den lilla
  provmodellen. Programkontrollen: `/health` svarade efter 2,8 s, röstmodellen hämtades på 8,7 s,
  zip-filen är 49 MB, 164 Mach-O-filer och signaturen är ad hoc.

## Programmet (Windows)

Windows-programmet är en katalog, `Akasha Protokoll\`, med `Akasha Protokoll.exe` och `_internal\`, för
x64. Det använder samma kod i `app/` som Mac-programmet. Det finns som zip-fil, som packas upp och startas i
mappen, och som installationsfil (se **Installationsfilen** nedan). Flödet `.github/workflows/windows-app.yml` bygger det bara för
hand, på `windows-2025`. **Allt nedan är byggt och kontrollerat på den maskinen (byggmaskinen). Programmet
har inte körts på en vanlig Windows-dator.**

- **Hur det byggs.** Fyra skript, i den här ordningen. `bygg-whisper-cli-windows.sh` hämtar whisper.cpp
  v1.9.5 (commiten `d1be6fde11ac6e0407606b4e42fe72d34add8037`, låst i skriptet) och bygger det med
  whisper.cpp:s egna Windows-flaggor: `BUILD_SHARED_LIBS=ON`, `GGML_NATIVE=OFF`, `GGML_BACKEND_DL=ON`
  och `GGML_CPU_ALL_VARIANTS=ON`, utan SDL2, tester, server och curl. Det ger en `ggml-cpu-<variant>.dll`
  för varje processorgeneration, nio stycken (x64, sse42, sandybridge, haswell, skylakex, cannonlake,
  cascadelake, icelake, alderlake), och den bästa väljs när `whisper-cli` startar (på byggmaskinen
  laddades `ggml-cpu-cascadelake.dll`). Det kompilerade cachas med nyckeln version plus hash av skriptet.
  `samla-whisper-cli-windows.sh` kopierar in C-runtimen och kontrollerar beroendena efter varje bygge och
  varje cacheträff. `bygg-windows.sh` gör ikonen (`.ico`) och versionsresursen, kör PyInstaller i katalogläge med
  `akasha-protokoll.spec` (samma spec-fil som Mac och Linux, med `windows_app.py` som startfil och
  `console=False`, alltså ett fönsterprogram utan konsol), kontrollerar innehållet och beroendena, och packar
  zip-filen och en uppackad kopia. Artefakterna är `Akasha-Protokoll-windows-x64.zip`,
  `Akasha-Protokoll-installation.exe` och `SHA256SUMS.txt`, var och en uppladdad som den är
  (`archive: false`) och sparad i sju dagar. Det finns ett jobb `signera`, men det körs aldrig
  (`if: false`) och har bara ett platshållarsteg: programmet är inte signerat.
- **Vad som följer med.** Det som följer med Mac-programmet, utom PyObjC och Mac-versionen av
  `whisper-cli`, och i stället pystray och Pillow för ikonen. `whisper-cli.exe` ligger i
  `_internal\whisper\` med `whisper.dll`, `ggml.dll`, `ggml-base.dll`, de nio `ggml-cpu-*.dll` och
  C-runtimen (`MSVCP140.dll`, `VCOMP140.DLL`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`, version
  14.52.37029.0, ur Visual Studios Redist-katalog, eftersom hos användaren inte alltid finns Visual C++
  Redistributable). `parakeet.dll` och de andra programmen ur whisper.cpp-bygget följer inte med.
  faster-whisper, ctranslate2, tokenizers, huggingface_hub, onnxruntime och tkinter följer inte med
  (`bygg-windows.sh` kontrollerar det). pystray är LGPL-3.0, så dess kod ligger som vanliga `.py`-filer i
  programmet (`module_collection_mode`), inte inbakad i arkivet. `plattform.whisper_cli()` letar efter
  `_internal\whisper\whisper-cli.exe` i det paketerade programmet.
- **Licenserna.** Som på Mac (se där), men katalogen `licenser\` ligger bredvid `Akasha Protokoll.exe`, inte
  i `_internal`: spec-filen kopierar dit den efter `COLLECT`, så att den syns direkt i programkatalogen, i
  zip-filen och i installationen (Inno Setup tar med hela katalogen). Förteckningen har också
  Visual C++-runtimen, med de DLL-filer som finns i programmet och var Microsofts villkor står (ingen
  licenstext är kopierad), och GCC-runtimen om `bygg-ffmpeg.sh` lade dess texter i `ut/ffmpeg`.
  whisper.cpp:s licens ligger i `build/whisper/licens/` och cachas med det kompilerade. `bygg-windows.sh`
  (steg 4b) och `kontrollera.py` (zip-filen och installationen) kör `kontrollera_licenser.py`. Provat på
  utvecklingsdatorn (2026-11-21) med ett riktigt PyInstaller-bygge av spec-filen, med en låtsad whisper-cli:
  analysen gav 24 Python-paket och 30 komponenter (825 kB), PYZ-arkivet 885 moduler, och kontrollen hittade
  alla 23 paket i programmet i förteckningen. Förteckningen blev `OFULLSTÄNDIG` för PyAV-hjulets skull.
  Med det egna FFmpeg-bygget har förteckningen 33 komponenter, bland dem GCC- och mingw-w64-runtimen
  (libgcc, startkoden och winpthreads är statiskt inlänkade i FFmpeg-DLL:erna) och Vulkan-Headers och
  SPIRV-Headers från Khronos (inbyggda i `ggml-vulkan.dll`; texterna i `paketering/licenstexter/`, versionerna
  ur whisper.cpp:s `KALLA.txt`). Universal C Runtime (`ucrtbase.dll`, `api-ms-win-*.dll`), som PyInstaller
  annars tar med från en JDK i byggmaskinens PATH, utesluts i spec-filen: den finns i Windows 10 och 11.
  Python 3.12.10 för Windows har OpenSSL 3.0.16 och XZ Utils 5.2.5, som också är egna komponenter.
- **FFmpeg (bara LGPL).** Som på Mac, men FFmpeg byggs i MSYS2 UCRT64 (finns i `C:\msys64` på byggmaskinen;
  gcc, nasm och make ur pacman, inga åtgärder från tredje part) och PyAV med MSVC mot FFmpegs
  importbibliotek. I MSYS2-steget slås `MSYS_NO_PATHCONV` av (annars får gcc `/tmp/...`), och FFmpeg länkas
  med `-static` så att DLL-filerna inte behöver `libgcc_s_seh-1.dll` eller `libwinpthread-1.dll`.
  Paketen i MSYS2 (gcc, binutils, nasm, make m.fl.) är inte låsta: `pacman -Sy` tar de senaste, och versionerna
  står i stegets logg och i `KALLA.txt` (kompilatorn).
  `bygg-windows.sh` (steg 4c) kör `kontrollera_ffmpeg.py` mot programmet, även importerna. Uppmätt i körning
  44912056987 (2026-11-21): `av.libs` är 3,4 MB (förut 70,1 MB), programmet 158,3 MB (292 filer), zip-filen
  61,6 MB (förut 70,6 MB), installationsfilen 37,2 MB (förut 48,5 MB) och installationen 162,7 MB.
- **Start och avslut.** `windows_app.py` är det tunna skalet; texterna ligger i `start.py` (`WIN_*`,
  `STARTAR_REDAN_*` och de gemensamma). Rutorna är `MessageBoxW` via `ctypes`, med `MB_SETFOREGROUND` och
  `MB_TOPMOST`. Knapparnas text (*Ja*, *Nej*, *OK*) kommer från Windows och följer Windows språk, så
  varje fråga slutar med en ja/nej-fråga i stället för egna knappnamn som på Mac. Ordningen vid start:
  loggningen ställs in (`win: startar`); en mutex (`Local\AkashaProtokoll`, per inloggad användare) ser
  till att bara en kopia kör, och en andra kopia väntar högst 30 s på att den första svarar, öppnar sidan
  och avslutas med kod 0 (annars rutan `STARTAR_REDAN_*`); fel i inställningsfilen ger en ruta; `start.forbered()`
  avgör `starta`, `redan_igang` eller `upptagen` (`ta_over` kan inte hända, launchd finns inte).
  Ikonen visas direkt, med verktygstipset "Akasha Protokoll startar…", och tjänsten startar i en
  bakgrundstråd. När tjänsten svarar blir tipset "Akasha Protokoll är igång", sidan öppnas, och första
  gången (ingen `forsta-start-visad` i programkatalogen) visas en notis med `pystray.Icon.notify()`. Svarar
  tjänsten inte inom 30 s visas rutan `STARTADE_INTE_*` med frågan om loggen ska visas, och programmet
  avslutas. Menyn har två rader, "Öppna Akasha Protokoll i webbläsaren" (förval, alltså vänsterklick
  och dubbelklick på ikonen) och "Avsluta Akasha Protokoll". Vid avslut frågar programmet först om det
  pågår något (`start.pagar()`, rutan med *Nej* förvalt), och stänger sedan tjänsten och ikonen. Går ikonen
  inte att skapa loggas `win: ikonen kunde inte visas: …` och programmet fortsätter utan ikon.
  pystray och Pillow importeras först i `main()`, så att loggningen hinner ställas in före allt annat.
- **Barnprocessen och datorn.** `plattform.starta_barn()` startar `whisper-cli` utan konsolfönster
  (`CREATE_NO_WINDOW`) och lägger processen i ett jobbobjekt med `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, så att den
  dör när programmet dör, också med `TerminateProcess`, Aktivitetshanteraren eller utloggning (Windows
  avslutar annars inte barnprocesser). `hall_vaken()` anropar `SetThreadExecutionState`. pystray svarar inte på
  `WM_QUERYENDSESSION`, så vid utloggning avslutar Windows programmet utan att fråga; en transkribering som
  pågick blir `avbruten` vid nästa start (`lagring.aterstall_avbrutna()`) och kan göras om med "Försök igen",
  och en inspelning fortsätter i webbläsarfliken tills den stängs. Det senare är läst ur koden och inte provat
  (se Inte provat än).
- **Sökvägar med å, ä och ö.** `whisper-cli` på Windows läser argumenten i systemets teckentabell, medan
  modellens sökväg tolkas som UTF-8. Därför körs den med `MODELLKATALOG` som arbetskatalog och relativa
  sökvägar, och med alla argument i en svarsfil (`@args.txt`, UTF-8) så att prompten med å, ä och ö kommer
  fram oförvanskad (`motor.cli_kommando()`). Den tillfälliga katalogen ligger under `MODELLKATALOG`, inte i
  `%TEMP%`, och städas med `ignore_cleanup_errors=True`.
- **Var saker ligger.** Inspelningar: `C:\Users\<namn>\AkashaProtokoll` (`~/AkashaProtokoll`). Programkatalogen:
  `%LOCALAPPDATA%\Akasha Protokoll`, med `modeller\`, `installningar.env`, `forsta-start-visad` och
  `logg\akasha-protokoll.log` (roterande, 2 MB, tre filer). På Windows ligger alltså loggen i
  programkatalogen, till skillnad från Mac. Inställningsfilen läses som på Mac (UTF-8 med eller utan BOM,
  eller UTF-16 med BOM, som Anteckningar kan spara) och en miljövariabel som redan är satt vinner. Filtyperna
  för sidan sätts av programmet självt (`app.py`), inte av Windows register. Flytten från det gamla namnet körs
  också på Windows, men ingen Windows-installation har haft det gamla namnet, så det finns inget att
  flytta. En programkatalog med det gamla namnet (Akasha Meet) kan dock inte byta namn medan programmet
  kör, eftersom loggfilen ligger i den.
- **Kontrollerna i Actions.** Flödet kör, var och en så att alla körs även om en faller (steget Sammanfattning
  faller jobbet om något föll): enhetstesterna; kontrollen av `whisper-cli` (`kontrollera_whisper_cli_windows.py`);
  bygget med sina egna kontroller; `kontrollera.py` mot programmet uppackat ur zip-filen; och
  `kontrollera_windows.py` (sökvägar och talare). Kontrollen av `whisper-cli` ser att alla 14 flaggor som
  `motor.py` använder finns, och transkriberar testljudet (26 s) med den lilla testmodellen genom programmets
  egen kod (`motor.cli_kommando()` och `motor._whispercpp()`), med svarsfilen, med modellkatalogen under en
  mapp som heter `Åsa Ölund` och med prompten "Åsa Öberg, Göteborg". `kontrollera_pe.py` kontrollerar att alla
  exe-, dll- och pyd-filer är x64 och hittar sina importer. Programmet kontrolleras uppackat ur zip-filen i
  en mapp med å, ä, ö och mellanslag, med en hemkatalog som heter `Åsa Ölund`: `/health` svarar, typsnittet
  skickas som `font/woff2`, inspelningsmappen med det gamla namnet flyttas, sherpa-onnx går att importera,
  motorn är whisper.cpp, röstmodellen hämtas genom programmet, en uppladdning tas emot och ljudet avkodas
  och `whisper-cli` startas (jobbet faller som väntat, eftersom kontrollen inte har någon riktig
  taligenkänningsmodell), loggen har raderna `win: startar`, `win: beslut starta`, `win: ikonen visas` och
  `win: tjansten svarar, oppnar webblasaren`, en andra start avslutar sig själv med kod 0 (`win: kopia finns
  redan`) medan den första fortsätter svara, och efter `TerminateProcess` är porten ledig och ingen
  `whisper-cli.exe` kvar. `kontrollera_windows.py` laddar röstmodellen från
  `…\Åsa Ölund\AppData\Local\Akasha Protokoll\modeller\talare\…`, ger ett röstavtryck (192 tal) och delar upp
  testljudet med två talare. Enhetstesterna körs också på Windows vid varje push (487 tester); bland dem
  barnprocessen som dör vid `TerminateProcess`, en kopia åt gången, datorn som hålls vaken och svarsfilen med
  en modellkatalog under `Åsa Ölund`.
- **Installationsfilen.** `Akasha-Protokoll-installation.exe` byggs efter zip-kontrollen av
  `paketering/bygg_installation.py`, som letar upp `ISCC.exe` (Inno Setup 6) och kompilerar
  `paketering/akasha-protokoll.iss` ur `dist\Akasha Protokoll\`, med versionen `0.2.0.<byggnummer>`. Skriptet
  installerar per användare med `PrivilegesRequired=lowest`, alltså utan administratörsrätt och utan
  UAC-ruta, till `{localappdata}\Programs\Akasha Protokoll` (`DisableDirPage=yes`: ingen väljer en mapp
  med annat i; `/DIR=` på kommandoraden gäller ändå, och kontrollen använder det). Det är bara för x64
  (`ArchitecturesAllowed=x64compatible`, `MinVersion=10.0`), har ett fast `AppId`, utgivaren Dennis Fredin,
  licenssidan med `LICENSE`, en uppgift `desktopicon` (av från början) och genvägen i Start-menyn, och en
  rad under `[Run]` för att starta programmet efteråt (inte i tyst läge). `AppMutex=Local\AkashaProtokoll` är
  samma mutex som skalet skapar (`windows_app.MUTEX`): är programmet igång ber installationen och
  avinstallationen användaren avsluta det, och stänger det inte själva (`CloseApplications=no`, eftersom en
  inspelning kan pågå). Avinstallationen tar bort `_internal` (som PyInstaller kan ha lagt filer i
  efter installationen) men aldrig `{app}` med allt innehåll, så att andras filer klarar den, och rör aldrig
  inspelningarna eller `%LOCALAPPDATA%\Akasha Protokoll`; slutrutan säger det. Texterna är på svenska
  (`Swedish.isl`, en inofficiell översättning som följer med Inno Setup om den installationen har den; annars
  används den engelska språkfilen och texterna i `[Messages]` och `[Tasks]` är ändå svenska). Inget
  av detta har körts med mus och tangentbord.
- **Kontrollen av installationen.** `kontrollera_installation.py` körs bara i Actions
  (`GITHUB_ACTIONS=true`), eftersom den installerar och avinstallerar för den inloggade användaren med samma
  `AppId` som en riktig installation och skriver i de riktiga mapparna. Den gör en tyst installation
  (`/VERYSILENT`) till en katalog med å, ä, ö och mellanslag och kontrollerar filerna, genvägen i Start-menyn
  och posten i Windows applista (`DisplayName`, `DisplayVersion`, `Publisher`). Med programmet igång
  provar den mutexen: installationsfilen ska avbryta i tyst läge med kod 1 och inte stänga programmet.
  `kontrollera.py` körs mot det installerade programmet. Sist avinstallerar den tyst och kontrollerar att
  programmets filer, genvägen och posten är borta, medan en främmande fil som kontrollen lade i
  installationskatalogen, `AkashaProtokoll` i hemkatalogen och `%LOCALAPPDATA%\Akasha Protokoll\modeller`
  ligger kvar.
- **Kontrollsummor.** `kontrollsummor.py` skriver `SHA256SUMS.txt` i `sha256sum`-format (summan, två mellanslag
  och filnamnet) för zip-filen och installationsfilen, och skriver ut hela filen i jobbloggen. Filen laddas
  upp som en egen artefakt. Mac-flödet skriver ingen sådan fil. Summan visar att filen är orörd, inte vem
  som byggt den.
- **Vad kontrollen inte visar.** Att SmartScreen, Smart App Control eller Defender släpper igenom ett
  nedladdat, osignerat program. Att en riktig KB-Whisper-modell transkriberar på Windows, och hur lång tid
  det tar. Hur rutorna, menyn och notisen ser ut, om ikonen syns vid klockan (loggraden `win: ikonen visas`
  säger bara att anropet gick igenom på byggmaskinen), och att inget svart fönster blinkar förbi.
  Mikrofonen i webbläsaren på Windows, "Visa i Utforskaren", ett riktigt konto med å, ä eller ö i namnet,
  och utloggning medan programmet kör. Att installationsguiden fungerar med mus och tangentbord på en riktig
  dator, vad Windows säger om installationsfilen (SmartScreen m.m.), uppdatering från en äldre installation
  och avinstallation via Inställningar → Appar. Hämtningen av KB-Whisper (1,5 GB) har inte gjorts på Windows.
- **Uppmätt på byggmaskinen, installationsfilen (körningarna 4–6).** Inno Setup 6.7.1 fanns på
  byggmaskinen, med den svenska språkfilen, och guiden är på svenska. Kompileringen tog cirka 40 s.
  Installationsfilen blev 48 474 168 byte (körning 6), version 0.2.0.<byggnummer>, utgivare Dennis Fredin. Den
  tysta installationen till `…\Installerat Åäö\Akasha Protokoll` gav 290 filer, 185,2 MB, genvägen i
  Start-menyn och en post i applistan (`DisplayName=Akasha Protokoll`, `DisplayVersion=0.2.0.6`,
  `Publisher=Dennis Fredin`). `kontrollera.py` godtog det installerade programmet (`/health` efter
  1,7–2,5 s, ikonen, andra kopian, avslutet). Mutexprovet: med programmet igång avbröt installationsfilen i tyst
  läge med kod 1 och stängde inte programmet; guidens text i det läget, ur Inno Setups logg, var
  "Installationsprogrammet har upptäckt att Akasha Protokoll är igång. Avsluta det angivna programmet nu.
  Klicka sedan på OK för att gå vidare eller på Avbryt för att avsluta." Avinstallationen tog bort
  `Akasha Protokoll.exe`, `_internal`, genvägen och posten, och lämnade den främmande filen,
  `AkashaProtokoll` i hemkatalogen och `modeller`. Hela flödet med installationsfilen och cacheträff tog 3 min 45 s till
  3 min 48 s.
- **Uppmätt på byggmaskinen, programmet (körningarna 1–3 av flödet).** Maskinen var Windows Server 2025 (10.0.26100),
  Visual Studio 2026 (18.12) med MSVC 19.52.37029, CMake 4.5.0 och Python 3.12.10, med 2 kärnor och 8 GB
  minne. whisper.cpp byggdes på 5 min 22 s, och hela flödet tog 7 min 49 s och 9 min 16 s när whisper.cpp
  byggdes och 2 min 54 s ur cachen. Programmet är 180,7 MB uppackat (288 filer), zip-filen är 70 589 058 byte och
  `Akasha Protokoll.exe` är 8,1 MB. Störst är `av.libs` (70,1 MB, FFmpeg i PyAV), `sherpa_onnx` (23,3 MB),
  `numpy.libs` (21,2 MB), `whisper` (12,3 MB inklusive C-runtimen) och `PIL` (11,3 MB). Alla 201 exe-, dll- och
  pyd-filer är x64 och hittar alla sina 1 088 importer. `/health` svarade efter 3,1–3,5 s, röstmodellen hämtades
  genom programmet på 4,2–5,0 s, och transkriberingen av testljudet (26 s) med den lilla testmodellen tog
  4,1 s och gav 42 ord med ordtider från DTW. Siffrorna är från byggmaskinen och säger inget om hur snabbt KB-Whisper
  medium är på en vanlig dator.

## Tillägg

Programmet kan ladda tillägg: separat installerade paket som lägger till egna vägar, en egen del av sidan och
egna bakgrundsjobb. Utan tillägg gör `app/tillagg.py` ingenting och allt fungerar som förut. Den här filen är hela gränssnittet.

**Var de ligger.** Ett tillägg är en mapp med en fil `tillagg.py`, till exempel `akasha_x/tillagg.py`. Mappnamnet är tilläggets id
(gemener, siffror och `_`). Programmet letar i varje katalog i `TILLAGG` (i den ordningen) och sist i `tillagg/` i
programkatalogen, bredvid `installningar.env`. Hittas samma id på flera ställen gäller det första. Tilläggets mapp läggs sist i
`sys.path`, så att det kan importera sina egna filer.

**Vad `tillagg.py` ska ha:** `NAMN` (visas för användaren), `KRAVER_API` (heltal, måste vara lika med `tillagg.API_VERSION`, nu 1),
`registrera(api)` och, om man vill, `VERSION`. Tilläggen laddas en gång i `forbered()`, före servern, eftersom Flask inte tar emot nya vägar
efter den första begäran. Fel `KRAVER_API`, ett undantag vid import eller i `registrera`, eller ett ogiltigt mappnamn gör att tillägget
inte blir aktivt: orsaken loggas, och en kort text visas i `problem` på `GET /api/tillagg`. Programmet startar ändå. Vägar som ett
tillägg hann lägga till innan det föll svarar 404.

**`api`:**

| Medlem | Vad |
|---|---|
| `api.route(regel, **val)` | Som `app.route`, men regeln hamnar under `/api/tillagg/<id>/`. Det är enda stället ett tillägg lägger vägar. Samma skydd som programmets egna anrop gäller: Host, och `X-Akasha-Protokoll: 1` för allt utom GET |
| `api.statisk(katalog)` | Serverar filer ur `katalog` på `/tillagg/<id>/<fil>` (bara GET, filtyperna ur `FILTYPER`, inget utanför katalogen). Sidan laddar `tillagg.js` och `tillagg.css` därifrån |
| `api.koa(funktion)` | Kör `funktion()` i den enda bakgrundstråden, i kön bland transkriberingarna, så att ett tungt jobb pågår åt gången. Ett undantag loggas och stoppar inte tråden |
| `api.vid_inspelning(fn)` | `fn(meta)` returnerar ett dict eller `None`. Dictet läggs i `GET /api/inspelningar/<id>` under `tillagg[<id>]` |
| `api.vid_radera(fn)` | `fn(id)` anropas under `lagring._las` precis innan inspelningens filer tas bort, så att tillägget kan ta bort sina egna `<id>.*` |
| `api.hindrar(fn)` | `fn(meta)` returnerar en text eller `None`. Med en text svarar radera och "Transkribera igen" 409 med texten |
| `api.vid_start(fn)`, `api.vid_stopp(fn)` | Anropas efter programmets städning vid start, och tillsammans med `motor.stoppa()` när programmet stängs (för barnprocesser) |
| `api.app`, `api.id`, `api.lagring`, `api.export`, `api.modeller`, `api.plattform`, `api.log` | Att läsa, inte byta ut |

Ett undantag i en av funktionerna ovan loggas och hoppas över: det stoppar inte raderingen eller de andra tilläggen.
Ett `hindrar` som kastar hindrar alltså ingenting.

**Sidan.** `index.html` har en tom `<div id="tillagg-ytor">` sist i steg 3. Vid start hämtar `app.js` `GET /api/tillagg` och lägger en
`<script src="/tillagg/<id>/tillagg.js">` och en stilmall för varje aktivt tillägg (CSP:n är oförändrad, `default-src 'self'`). Skriptet
anropar `window.akashaTillagg.registrera(id, { visad(m, harText, byttId) {} })`. `visad` anropas i slutet av `visa()` för varje
visad inspelning (och en gång direkt om skriptet registrerar sig efter visningen), i try/catch. `akashaTillagg.api` är sidans
`api()`, som redan skickar rätt header, och `akashaTillagg.el` är `el()`. `/health` har fältet `tillagg` med de aktiva idn.

## Talaruppdelningen

Första versionen använde pyannote för att hitta talarbyten. I det första riktiga samtalet, två
personer inspelade med en MacBook Airs mikrofon, hittade den inga byten alls, och nästan allt hamnade
hos Talare 1. Nu används en annan metod som klarar samma inspelning:

1. whisper ger varje ord en tidsstämpel. Med whisper.cpp används DTW-justering för detta, eftersom
   de vanliga ordtiderna kunde hamna 0,6 s fel. DTW kräver att flash attention är av, så det slås
   bara på när talare ska delas upp. Det kostar cirka 20 % i tid.
2. Röstavtryck (NeMo TitaNet small) tas i glidande fönster om 1,5 sekunder där det pratas. Nästan
   tysta fönster hoppas över.
3. Avtrycken delas upp i lika många grupper som antalet talare. Är två grupper nästan lika
   (`TALARE_TROSKEL`) är det samma person. Då slås de ihop, och sidan säger till att färre röster
   gick att skilja åt i stället för att hitta på en talare. "Vet inte – gissa" provar 2, 3, 4 …
   grupper och stannar innan två grupper blir för lika, eller innan någon talare får mindre än
   1,5 s eget tal.

   Hur lika två grupper är beror på hur stora de är. Har båda minst 30 s tal jämförs de
   ursprungliga grupperna med varandra, och likheten blir snittet. Annars jämförs gruppernas
   samlade röster. Skälet: en sammanslagen grupps samlade röst hamnar mellan delarna och blir
   mer lik en tredje grupp än någon av delarna är. I ett riktigt möte med fem personer slogs en
   person med 17 minuters tal därför ihop med mötesledaren, trots att den liknade båda delarna
   av mötesledarens röst mindre än gränsen. För en kort grupp är det tvärtom bra: dess egen röst
   är osäker, och det är oftast en kort avvikelse hos någon som redan finns.
4. Varje ord får den grupp som fönstren närmast ordet liknar mest.
5. Talaren byter sällan mitt i en mening. Inom en mening (som slutar vid punkt, frågetecken,
   utropstecken eller en paus på 0,4 s) får korta avvikande sjok, högst 4 ord i rad, samma talare
   som resten av meningen, om en talare har mer än hälften av meningens ord. Egna meningar som
   "Ja, ja." och längre avvikelser rörs inte. Det behövs eftersom ordtiderna är ungefärliga:
   whisper.cpp:s ordtider låg i ett riktigt möte i snitt 0,17 s före faster-whispers och ibland en
   sekund fel. Svagheten: om whisper inte sätter något skiljetecken vid ett talarbyte kan ett kort
   svar som "Nej, precis." hamna hos den andra.

**Rättningar för hand** (`app/rattning.py`): på webbsidan kan en hel replik, några markerade ord
eller alla repliker från en talare få en annan talare. Repliker i följd med samma talare slås ihop.
Ordtiderna sparas inte, så när en replik delas uppskattas tiden utifrån andelen text före
delningen. Maskinens version sparas som `segment_original` i inspelningens `.json` vid första
rättningen, så att allt kan ångras. "Transkribera igen" ersätter båda, så dialogen varnar först.

**Osäkra ställen** markeras på webbsidan, som en hjälp att veta var man ska börja kontrollera:

- **Osäker talare** (`osaker_talare` på en replik): minst hälften av replikens ord är osäkra. Ett
  ord är osäkert om rösten liknar två grupper nästan lika mycket (`MARGINAL`, skillnad under
  0,03), om meningsregeln flyttade ordet, eller i digitala möten om kanalen inte avgjorde. I
  AMI-mötena hade ord med marginal under 0,05 fel talare i 44 % av fallen, mot 16 % i snitt och
  2,6 % när marginalen var stor. På replikernivå är signalen svagare: 12 % av replikerna
  markerades, och 31 % av dem var fel, mot 24 % av alla repliker. I det konstgjorda digitala mötet
  med täta "mm" markerades ungefär hälften av de felaktiga replikerna. Fel kan alltså finnas även
  där det inte är markerat.
- **Osäkra ord** (`osakra_ord`, index i texten): whispers sannolikhet för ordet är låg. whisper.cpp
  ger den per token, och ordet får den lägsta. På 40 FLEURS-meningar med facit var whisper.cpp:s
  ord under 0,5 fel i 20 % av fallen, mot 4–5 % för övriga. Det är ungefär 7 % av orden, ofta namn
  och ovanliga ord. faster-whispers sannolikheter skilde sämre, så där gäller 0,4: knappt 1 % av
  orden, och en tredjedel av dem var fel.

När en talare bestäms för hand försvinner markeringen för osäker talare. Knappen "… stämmer" gör
detsamma utan att byta talare.

**Digitala möten:** mikrofonen och mötesfliken ligger i varsin kanal. Ett ord hör till den kanal
som är starkast under ordet, om den är minst fyra gånger så stark; annars får ordet samma som
närmaste säkra ord. Det du säger blir alltid Talare 1 ("Du"). Bara de andra (höger kanal) delas upp
efter röst, enligt stegen ovan.

Först räckte dubbelt så stark. I ett riktigt digitalt möte (18 minuter, tre personer) blev då
en tredjedel av replikerna bara 1–3 ord: när någon i mötet skrattade eller sa "mm" medan du
pratade hamnade enstaka ord mitt i dina meningar hos de andra. Med fyra gånger så stark blev det
65 repliker i stället för 99, och 6 korta i stället för 32. Av de 39 ord som bytte talare var
ungefär 35 tydligt rätt utifrån innehållet. Med konstgjorda "mm" och skratt i testljudet, där
facit finns, gick andelen ord med rätt talare från 80–91 % till 89–98 % (medel över åtta
slumpvisa varianter), och rent ljud gav fortfarande 100 %.

Meningsregeln (punkt 5 ovan) gjorde mest skillnad med whisper.cpp, som din Mac använder. I samma
möte med whisper.cpp:s ordtider: 141 repliker med 50 korta blev 70 med 6, med tre talare. I ett
urval av de ändrade orden var ungefär 22 av 24 rätt. Med konstgjorda "mm" och skratt blev 97–99,6 %
av orden rätt talare. I rummet gav regeln samma resultat för testdialogerna (100 %) och något
bättre för AMI-mötena (75,3 → 76,0 %, 83,6 → 85,1 % och 89,0 → 90,8 %).

Först fick bara sjok på högst 3 ord meningens talare. Omkört på Macen gav det 86 repliker i stället
för 144, men tre sjok på 4 ord låg kvar hos fel person ("Att man lägger upp", "Så därför tycker
jag", "Då vet jag inte"). Med högst 4 ord hamnade de rätt, och AMI-mötena, testdialogerna och
testljudet med konstgjorda ljud blev lika bra eller något bättre.

Utvärderat på ordnivå, med båda motorerna:

- **Tre konstgjorda dialoger med facit:** 100 % rätt talare, både med angivet antal och med "Vet inte".
- **Två inspelningar med bara en röst:** delades inte upp, med 2 angivet blev det en varning.
- **Konstgjort digitalt möte** (`testljud/digitalt-mote.webm`: du i vänster kanal, en kvinna och en
  annan man i höger): du blev alltid Talare 1, och de två andra blev två olika talare, både med
  angivet antal och med "Vet inte".
- **Ett riktigt samtal:** fick 2 talare med båda sätten. Bytena hamnade mellan rätt ord
  ("…det visste jag inte" | "kan du säga…"), och det korta "vad sa du?" blev en egen replik.
  Ett "mhm" mitt i en lång replik hamnade hos fel person.

- **Ett riktigt möte med fem personer** (1 h 24 min, laptopens mikrofon): bara tre talare
  hittades. `halsokoll/talardiagnos.sh` visade att fyra röster gick att skilja åt, men att en
  person med 17 minuters tal hade slagits ihop med mötesledaren. Tidsmönstret bekräftade det: när
  den personen pratade mer pratade mötesledaren mindre. Därför ändrades sammanslagningen (punkt 3).
  Omkört med den nya sammanslagningen blev det fyra talare. Personen fick 20 % av taltiden, med
  samma tidsmönster som i diagnosen, och mötesledarens andel sjönk från 74 till 53 %. Den femte
  personen gick fortfarande inte att skilja ut.
- **Tre möten ur AMI-korpusen** (engelska, riktiga möten med 3–4 personer, en mikrofon mitt i
  rummet, 30–48 min): med rätt antal angivet blev 75, 83 och 89 % av orden rätt talare. Med en
  talare för mycket angiven blev antalet ändå rätt. "Vet inte" gav rätt antal i två av tre möten.
  Den gamla och den nya sammanslagningen gav samma resultat.
- **Fem inspelningar med en person ur AMI** (4–6 min, samma mikrofon): med 2 angivna och med
  "Vet inte" blev det alltid en talare. Med 3–5 angivna blev det ofta 2–3 talare, med båda
  sätten att slå ihop (den nya gav en gång fler: 2 i stället för 1, med 4 angivna). Ange alltså
  inte fler talare än som pratar, och välj hellre "Vet inte" om du är osäker.

I AMI-proven kommer ordtiderna från korpusens utskrifter, inte från whisper. AMI Meeting Corpus
(CC-BY-4.0) användes bara för utvärderingen och finns inte i repot.

Korta inpass på under en sekund är svårast, och personer som sitter långt från mikrofonen låter
mer lika varandra.

## Medium eller large

`MODELL=large` ger KB-Whisper large, KBLab:s största modell. För whisper.cpp används KBLab:s
kvantiserade version (q5_0, 1,1 GB). Enligt KBLab gör large cirka 15–25 % färre fel än medium.
Provat i Linux-miljön, med whisper.cpp på processorn och samma inställningar som när talare delas
upp:

- **40 meningar ur FLEURS** (svenska, uppläst, 715 ord): 6,4 % fel ord med medium och 5,5 % med
  large. Large var bättre i 9 meningar och sämre i 8, så provet är för litet för att säga mer än
  att large verkar något bättre.
- **Testljudet med två talare:** båda gav rätt talare, och båda tappade ett par ord, på olika
  ställen.
- **Tid:** för en minut ljud tog large ungefär lika lång tid som medium. För 40 korta klipp tog
  large 2,4 gånger så lång tid, men då laddas modellen om för varje klipp. Med Metal på Mac är det
  inte uppmätt än.

Det som avgör är ett riktigt möte: transkribera samma ljud med båda och jämför med
`halsokoll/jamfor.sh` (nedan).

## Pianissimo (valfri motor)

`MOTOR=pianissimo` kör Klangs svenska Parakeet-modell (`KlangAI/pianissimo-sv-onnx`, CC-BY-4.0, int8,
660 MB) i stället för KB-Whisper. Den är aldrig `auto`: onnx-asr, som kör modellen, ingår inte i
`app/requirements.txt` och inte i programmen för Mac och Windows (`motor.hinder()` säger det). I
terminalinstallationen installeras det med `pip install -r app/krav-pianissimo.txt`, och modellen hämtas på
sidan eller med `python app/modeller.py pianissimo`, som de andra modellerna (manifestet är `PAKET["pianissimo"]`).

- **Hastighet (uppmätt):** 6–8 gånger snabbare än KB-Whisper medium på en Windows-laptop (bara processorn) och
  ungefär 6 gånger snabbare än KB-Whisper med Metal på en MacBook Air (49 gånger realtid). På utvecklingsdatorn
  tar testljudet på 57 s drygt 3,5 s när modellen redan är laddad.
- **Bara processorn, alltid.** På Mac väljer onnxruntime annars CoreML, som bara klarar en del av grafen: den
  delades i 348 bitar (1648 av 4635 noder) som skickas fram och tillbaka, och det blev 6 gånger långsammare.
  `pianissimo.ladda()` anger därför `CPUExecutionProvider`.
- **Kvalitet:** i ett riktigt möte minst lika bra som KB-Whisper, bättre på engelska lånord och utan påhittade
  upprepningar. Men den hoppar över korta inpass som "Ja.".
- **Ordlista:** samma prompt som de andra motorerna får (`ORDLISTA` och svårstavade ord, kommaseparerade) förstärker
  orden. `app/pianissimo_boost.py` är en bearbetad kopia av Klangs kod i modellrepot (`phrase_boost.py` och
  `pianissimo_onnx.py`, samma revision som modellen, CC-BY-4.0), i sin tur en portning av NeMos frasförstärkning:
  fraserna blir ett träd över SentencePiece-token (`tokenizer.model`, med i manifestet), och varje token som modellen
  väljer får en bonus om den fortsätter en fras. Klangs kod körs alltså inte; kopian är kort nog att läsa rad för
  rad, och ändringarna står i dess huvud. Avkodningsslingan är onnx-asr 0.12.0:s med bonusen tillagd, därför är
  versionen fastlåst. Förstärkningen sätts in på modellen för en transkribering och tas bort efteråt (också vid fel),
  så en inspelnings ord följer aldrig med till nästa; en tom prompt kostar ingenting. Går något fel (t.ex. att
  `sentencepiece` saknas) loggas det utan orden och transkriberingen fortsätter utan ordlista. Uppmätt med
  `halsokoll/jamfor_motorer.sh --motor pianissimo --ord "Carter, Afghanistan, boulevarderna, Turkiet"`: "Carter"
  blev "karter" utan hjälp och rätt med, och ordfelen sjönk från 7,4 till 6,2 % (`tva-talare.m4a`) och från 7,6 till
  6,7 % (`digitalt-mote.webm`); `en-talare.m4a` har inga av orden och är oförändrad (2,8 %).
- **Så arbetar den (`app/pianissimo.py`):** ljudet delas vid tystaste stället i bitar om högst 30 s, och ordtiderna
  kommer från onnx-asr:s tid per token. Med ordtider (talaruppdelning) får orden samma form som whisper.cpp:s
  DTW-ord, och segmenten delas efter meningsslut; utan blir det ett segment per bit. Talaruppdelningen
  fungerar som med de andra motorerna: sherpa-onnx och onnxruntime från onnx-asr kördes i samma process på
  `tva-talare.m4a` med rätt två talare.
- **Minne och trådar:** modellen laddas vid första transkriberingen och ligger kvar i minnet (som
  faster-whisper). En egen lås gör att bara en tråd i taget använder den, utöver transkriberingslåset i `motor.py`.
- **Stopp:** `motor.stoppa()` sätter `_avslutas`, som kontrolleras före varje bit, så en timmes möte stannar inom
  en bit (högst 30 s ljud) och ger `Avbruten`.
- **Testerna** använder `tester/falsk_onnx_asr.py` (en falsk `onnx_asr` och `onnxruntime`) och kräver inte
  paketen. Bara `RiktigaPaketet` i `test_pianissimo.py` gör det, och hoppas annars över.

## Se hur det gick, utan att visa texten

Tre verktyg skriver bara ut siffror och tider, inga ord ur mötet och inga namn. Utskriften går
alltså att visa för någon annan.

```bash
bash halsokoll/sammanfatta.sh
```

Senaste färdiga inspelningen: tid per timme möte, antal repliker och andel tal per talare,
tystnader utan text (tappade stycken), ställen där whisper har fastnat i en slinga, och
fördelningen per talare i block om 5 eller 10 minuter. Ange ett id för en annan inspelning.

```bash
bash halsokoll/talardiagnos.sh
```

Räknar om röstavtrycken (runt en minut per timme möte) och visar grupperna innan något slås
ihop: hur lika de är, hur många talare det blir med olika `TALARE_TROSKEL`, och när varje grupp
pratar. Ändrar ingenting.

```bash
bash halsokoll/jamfor.sh <id A> <id B>
```

Jämför två transkriberingar av samma möte: samma ljud med olika modeller, eller samma möte
inspelat med två enheter (datorn och en telefon). Visar hur stor andel av orden som skiljer, totalt
och per tiominutersblock, om talarna stämmer överens och hur mycket inspelningarna är förskjutna i
tid. Skillnaderna med text sparas i `jamforelser/` i inspelningsmappen. Att två transkriberingar
stämmer överens betyder inte att de är rätt, eftersom samma modell gör samma fel på namn och
facktermer. Men där de skiljer sig har minst en av dem hört fel.

```bash
bash halsokoll/jamfor_motorer.sh
```

Jämför KB-Whisper (appens motor) med Klang Pianissimo, en svensk Parakeet-modell
(`KlangAI/pianissimo-sv-onnx`, CC-BY-4.0, int8, 660 MB), på de tre testljuden: tid, gånger realtid, antal
ord, ordfel mot facit (`testljud/facit.json`) och om ordtiderna räcker för talaruppdelningen
(`tva-talare.m4a`, samma facit som `halsokoll/prov.sh`). Pianissimo körs med onnx-asr, som inte ingår i
appen. Installera det en gång i appens venv (på Windows heter `bin` `Scripts`):

```bash
venv/bin/pip install -r app/krav-pianissimo.txt            # Windows: venv\Scripts\pip
bash mac/hamta-modeller.sh talare                          # röstmodellen, om den saknas
bash halsokoll/jamfor_motorer.sh                             # Windows: venv\Scripts\python halsokoll\jamfor_motorer.py
```

Första körningen hämtar Pianissimo till `pianissimo-sv-onnx/` i modellkatalogen, med samma hämtning som
appens modeller (fastlåst revision, bara Hugging Face, sha256). `--motor pianissimo` eller `--motor kbwhisper`
kör en av dem, `--fil` väljer testljud. KB-Whisper hoppas över om dess modell saknas. Långt ljud delas vid
tystaste stället i bitar om högst 30 s, så en timmes möte går att köra. Ingen ordlista (Klangs
ordförstärkning) används, och Klangs egen kod i modellrepot körs inte.

Tiderna gäller den här datorn och är inte jämförbara med Klangs siffror på andra processorer. Ordfelen mäts på
bara tre korta klipp och säger därför lite: avgörande är ett riktigt möte.

```bash
bash halsokoll/jamfor_motorer.sh --mote <id> [--ut pianissimo.txt]
```

Kör Pianissimo på ljudet i en inspelning och jämför med den sparade KB-Whisper-texten. Utskriften är bara
siffror (tid, gånger realtid, antal ord, andel ord som skiljer) och innehåller inga ord ur mötet. Ingenting skrivs i
datakatalogen. Vill du läsa Pianissimos text anger du `--ut` med en sökväg utanför datakatalogen. För att se var
texterna skiljer: transkribera mötet med båda motorerna i appen och kör `jamfor.sh`.

## Vad som är testat

**Senast, på Windows 11 (utvecklingsdatorn, 2026-11-21):** 661 enhetstester (35 av dem för licenserna), OK, 28 överhoppade (bland dem testet med symboliska länkar, som kräver utvecklarläge i Windows). Webbsidans ändringar samma dag (dubbelklick, inspelare som stannar, gamla svar, dold flik, tangentbord) är provade med en låtsas-DOM i Node, inte i en riktig webbläsare.

**I en Linux-miljö utan grafikprocessor** (samma Python- och biblioteksversioner):

- **Enhetstester:** 263 st (2 överhoppade), gröna, och ett till som bara körs för hand (se nedan). De täcker
  talaruppdelning (även digitala möten), lagring av inspelningar i delar, export, skydd mot andra
  webbsidor, alla API-flöden och modellhämtningen mot låtsaskällan.
- **Första start i Chromium**, med låtsaskällan i stället för Hugging Face: kortet med modellerna,
  hämtning, stopp och fortsättning, en sida som laddas om mitt i hämtningen, och alla felfall
  (avbrott, fel kontrollsumma, inget nät och full disk) med "Försök igen". Både i ljust och mörkt
  läge, utan fel i konsolen.
- **Riktig hämtning av röstmodellen** (40 MB) från Hugging Face: avbruten efter några MB och
  fortsatt med `Range`, med omdirigering till en CDN-värd och rätt sha256. Körs för hand med
  `AKASHA_RIKTIG_HAMTNING=1 venv/bin/python -m unittest discover -s tester -p test_riktig_hamtning.py`.
  Taligenkänningen (1,5 GB) har aldrig hämtats på riktigt i provet.
- **GitHub Actions:** enhetstesterna körs på ubuntu-latest, windows-latest och macos-latest vid varje push till main och i pull requests. macOS är med sedan 2026-11-21, när repot blev publikt och Actions gratis; före dess bara i Mac-app-flödet (251 tester, 4 överhoppade). faster-whisper installeras inte där (testerna behöver den inte).
- **Programmet:** provbygge på Linux med kontrollskriptet (start, standardplatser, flytt av gamla modeller, riktig hämtning av röstmodellen, avkodning, avslut).
- **`installera.sh` från början:** med en ersättare för launchd, även en ominstallation när
  tjänsten redan finns. Modellnedladdningen med sha256-kontroll gick igenom.
- **`halsokoll/prov.sh`:** grön med båda motorerna.
- **Webbsidan i Chromium**, med en ljudfil som låtsasmikrofon: inspelning, stopp, talaruppdelning,
  namn, rubrik, kopiera, nedladdning, uppladdning, radering och en inspelning där fliken stängdes
  mitt i, som sedan avslutades från listan.
- **Den omgjorda webbsidan i Chromium**, med påhittade inspelningar i alla lägen och en riktig
  transkribering: rubrik som skrivs under inspelningen, varningen om inget ljud (med en tyst
  ljudström), dialogen "Transkribera igen", förloppet med tid kvar, namn som sparas av sig själva,
  "Lyssna", klick på osäkra ord, rättning av talare med mus och tangentbord, kvittorutan och
  kontrasten i ljust och mörkt läge (uppmätt i webbläsaren). Inte provat: Safari, skärmläsare
  och tröskeln för varningen om inget ljud med en riktig mikrofon.
- **Digitalt möte i Chromium:** mikrofonen i vänster kanal och en delad ljudström i höger. Mannen i
  mikrofonen blev **Du** och kvinnan i "mötet" Talare 2. Chromes testläge kan inte dela en riktig
  flik med ljud, så själva flikdelningen ersattes av en ljudström via samma `getDisplayMedia`.

**På en MacBook Air med Apple Silicon:**

- `installera.sh` och `halsokoll/prov.sh` gick gröna med båda motorerna, och senare även med provet
  för digitala möten.
- `whisper-cli` använde Metal. Testljudet på 57 s tog 7,2 s med Metal och 18,3 s på processorn.
- Ett riktigt möte på 1 h 24 min (uppladdat) tog 12 minuter, varav 1,5 minuter talaruppdelning.
  Whisper fastnade inte och tappade inga stycken.
- Ett riktigt samtal inspelat i Chrome och ett röstmemo uppladdat i Safari delades upp i två talare.
- DTW kostade lite: för ett samtal på 48 s gick transkriberingen från 5,9 till 7,1 s.
- Programmet på en riktig Mac med Apple Silicon (prov 2026-11-20, bygget från Mac-körning 2):
  Gatekeeper (Klar, Öppna ändå under Integritet och säkerhet, Öppna ändå i nästa ruta, Touch ID
  eller lösenord); övertagande av en terminalinstallation (frågan kom, modellerna togs in utan
  hämtning, ikonen i Dock); installation från grunden (sidan erbjöd att hämta modellerna, hämtningen
  på 1,6 GB blev klar på omkring fem minuter, uppskattat och inte mätt, och en inspelning på 12 s
  transkriberades på 8,0 s första gången och 2,6 s andra gången, enligt programmets logg;
  skillnaden är troligen modellens inläsning och Metal-biblioteken vid första körningen).

**Inte provat än:**

- programmet på en riktig Mac: tider för en längre inspelning (inte mätta) och avslut mitt i en transkribering (Gatekeeper, övertagande, första start, hämtning, en kort transkribering och loggfilen är provade, se ovan);
- Windows-programmet på en riktig Windows-dator: guiden med mus och tangentbord, varningen från Windows för
  installationsfilen, uppdatering från en äldre installation, avinstallation via Inställningar, SmartScreen, Smart App Control och Defender med ett nedladdat
  program, en riktig transkribering med KB-Whisper och hur lång tid den tar, rutorna, menyn och notisen (och att
  inget svart fönster blinkar förbi), mikrofonen i webbläsaren, "Visa i Utforskaren", ett riktigt konto med å, ä
  eller ö i namnet och utloggning medan programmet kör (det som är provat står under Programmet (Windows));
- faster-whisper på Windows (CI installerar inte faster-whisper, och programmet har det inte med);
- hämtning på ett företagsnät med proxy;
- ett riktigt Google Meet-möte eller en Slack-huddle, där Chromes flikväljare och
  "Dela även flikljud" används på riktigt;
- inspelning med avbrott och räddningsfil i Safari och Edge (provat i Chromium);
- inspelning via webbsidan i Safari (Safari spelar in i ett annat format än Chrome);
- fler långa möten på svenska, och möten där flera pratar i mun på varandra (bara provat i
  AMI-mötena, på engelska).
