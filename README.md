# <img src="app/static/elefant.svg" alt="" width="44" align="top"> Akasha Protokoll

Transkribera möten lokalt på din egen dator. Spela in i webbläsaren eller ladda upp en ljudfil, och få
texten uppdelad per talare med riktiga namn.

- **Allt stannar på datorn.** Internet används bara en gång, för att hämta modellerna.
- **Svensk taligenkänning** med [KB-Whisper](https://huggingface.co/KBLab/kb-whisper-medium) från
  Kungliga biblioteket.
- **Möten i rummet och digitalt**, med datorns mikrofon eller Google Meet och Slack i Chrome.
- **Inspelningen tappas inte.** Ljudet sparas på disken var femte sekund.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/bilder/akasha-protokoll-mork.png">
  <img src="docs/bilder/akasha-protokoll-ljus.png" alt="Akasha Protokoll i webbläsaren. Överst ett grönt fält med rubriken Mötet blir text. Inget lämnar datorn. och en elefant. Till vänster knappen Ny transkribering och listan med inspelningar, där en transkriberas just nu. Till höger ett transkriberat möte i tre steg: 1 Vem är vem? med namnen Anna och Jonas, 2 Kontrollera mot ljudet med en förklaring av markeringarna, ljudspelaren och replikerna, där en replik är markerad som osäker talare och två ord är understrukna som osäkra, och 3 Använd texten med knappar för att kopiera och ladda ner." width="760">
</picture>

<sub>Exemplet är påhittat.</sub>

## Installera

Ladda ned från [den senaste releasen](https://github.com/jamesmcstrid/akasha-protokoll/releases/latest),
under **Assets**. Du behöver inget GitHub-konto. Programmen är ännu inte signerade, så datorn varnar
första gången. Vid första start erbjuder sidan att hämta modellerna (cirka 1,6 GB, en gång).

### Mac (Apple Silicon, macOS 14 eller senare)

1. Ladda ned **Akasha-Protokoll-mac-arm64.zip**, öppna den och dra **Akasha Protokoll** till **Program**.
2. Dubbelklicka på programmet. macOS säger att det inte kunde verifieras: tryck **Klar** (inte Flytta
   till papperskorgen).
3. Gå till Systeminställningar → **Integritet och säkerhet**, och tryck **Öppna ändå** vid raden om
   Akasha Protokoll under **Säkerhet**. Bekräfta med **Öppna ändå** och Touch ID eller lösenord.
   Det behövs bara första gången. Apple beskriver stegen i
   [Öppna en Mac-app från en okänd utvecklare](https://support.apple.com/sv-se/guide/mac-help/mh40616/mac).

Saknas raden, eller säger macOS att programmet är skadat, kör en gång i Terminal och öppna igen:
`xattr -dr com.apple.quarantine "/Applications/Akasha Protokoll.app"`

Programmet har en prick under ikonen i Dock när det är igång. Klicka på ikonen för att öppna sidan,
och avsluta med **⌘Q**.

### Windows (x64, provat på Windows 11)

1. Ladda ned **Akasha-Protokoll-installation.exe** och dubbelklicka på den.
2. Windows (SmartScreen) varnar för ett okänt program. Tryck på länken för mer information och sedan
   på knappen för att köra ändå.
3. Följ guiden. Programmet installeras bara för ditt konto, utan administratörsrätt, och hamnar i
   Start-menyn.

Programmet syns som en ikon vid klockan (kanske bakom pilen **^**). Vänsterklicka för att öppna sidan,
högerklicka och välj **Avsluta Akasha Protokoll** för att avsluta. Pågår något frågar programmet först.

- **Uppdatera:** kör den nya installationsfilen. Avsluta programmet först om guiden ber om det.
- **Avinstallera:** Inställningar → Appar → Akasha Protokoll. Inspelningar, modeller och inställningar
  ligger kvar.
- **Utan installation:** ladda ned **Akasha-Protokoll-windows-x64.zip**, välj **Extrahera alla…** och
  starta **Akasha Protokoll.exe** i den uppackade mappen.

### Kontrollera nedladdningen

`SHA256SUMS.txt` i releasen har en kontrollsumma för varje fil. Jämför med
`Get-FileHash "$HOME\Downloads\Akasha-Protokoll-installation.exe"` i PowerShell, eller
`shasum -a 256 ~/Downloads/Akasha-Protokoll-mac-arm64.zip` i Terminal. Summan visar att filen är hel,
men ersätter ingen signering.

### Från Terminal (Mac)

Kräver [Homebrew](https://brew.sh) och cirka 4 GB ledigt.

```bash
brew install python@3.12 git
git clone https://github.com/jamesmcstrid/akasha-protokoll.git ~/akasha-meet
cd ~/akasha-meet
bash mac/installera.sh
```

Mappen måste ligga direkt i hemkatalogen (inte i Hämtade filer, Dokument, Skrivbord eller iCloud
Drive), eftersom macOS inte låter bakgrundstjänster läsa där. Den heter `akasha-meet` efter
programmets gamla namn. Installationen hämtar modellerna, startar tjänsten vid inloggning och öppnar
**http://127.0.0.1:8611**.

- **Kontrollera:** `bash halsokoll/prov.sh`. Sista raden ska vara `PROV: OK`.
- **Uppdatera:** `cd ~/akasha-meet && git pull && bash mac/installera.sh`
- **Avinstallera:** `bash mac/avinstallera.sh`. Inspelningar och modeller ligger kvar.

## Använda

1. Välj **Hur spelas mötet in?** och **Hur många pratar?**. Skriv namn och facktermer under
   **Svårstavade ord**, så stavas de rätt.
2. Tryck **Spela in**, och **Stoppa och transkribera** när mötet är slut. Eller tryck
   **Ladda upp ljudfil…**, till exempel från Röstmemon.
3. **Vem är vem?** Skriv in vad talarna heter. **Lyssna** spelar ett prov på varje röst.
4. **Kontrollera mot ljudet.** Klicka på en tid för att lyssna där. Repliker med osäker talare har ett
   **?**, och **Nästa osäkra talare** hoppar mellan dem. Understrukna ord var programmet osäkert på.
   Fel kan finnas även där inget är markerat.
5. Fel talare? Klicka på namnet i repliken och välj rätt person, eller markera några ord och välj vem
   som sa dem. **Ångra alla rättningar** går tillbaka till originalet.
6. **Använd texten:** kopiera den, ladda ner som .txt eller .md, eller ladda ner ljudet.

**Transkribera igen** i listan kör om en inspelning, till exempel med ett annat antal talare.
Rubriken kan skrivas under mötet eller bytas efteråt.

### Med mikrofonen eller digitalt

- **Med mikrofonen:** för möten i samma rum, eller digitala möten via högtalare. Ställ datorn mellan er.
- **Digitalt i Chrome:** välj fliken med mötet och kryssa i **Dela även flikljud**. Fungerar med
  hörlurar och med Meet, Slack, Teams och Zoom i Chrome. Din röst blir alltid **Du**. Räkna med dig
  själv i "Hur många pratar?". Safari och Firefox kan inte dela flikljud, och möten i apparna har ingen
  flik att dela (se [#1](https://github.com/jamesmcstrid/akasha-protokoll/issues/1)).

### Bra att veta

- **Be alltid om lov innan du spelar in någon.** I ett digitalt möte syns det inte för de andra.
- Låt fliken vara öppen och datorn vaken. Om locket stängs slutar inspelningen.
- Svarar inte programmet en stund fortsätter inspelningen i fliken. Stäng inte fliken.
- Fastnar en inspelning på "Spelar in", tryck **Avsluta och transkribera** i listan.
- Kontrollera texten mot ljudet. Taligenkänning gör fel, särskilt på namn och siffror.

### Hur lång tid tar det?

| Dator | Tid per timme möte |
|---|---|
| MacBook Air, Apple Silicon (grafikprocessorn) | drygt 8 minuter |
| Dell, Intel Core 12:e gen, Windows (processorn) | 80–95 minuter, fortare med laddare och **Bästa prestanda** |

## Var hamnar inspelningarna?

I `~/AkashaProtokoll` (på Windows `C:\Users\<namn>\AkashaProtokoll`), med ljud, `.md` och `.json` för
varje inspelning. Mappen ligger medvetet utanför Dokument och Skrivbord, som ofta synkas till molnet.
**Radera** i listan tar bort alla tre filerna.

## Integritet och säkerhet

- Tjänsten lyssnar bara på `127.0.0.1`. Ingen annan dator i nätverket kommer åt den.
- Internet används bara för att hämta modellerna från Hugging Face, med låsta versioner och sha256-kontroll.
  Inga inspelningar, texter eller uppgifter om dig skickas.
- Andra webbsidor kan inte styra tjänsten. Allt som ändrar något kräver en header som en främmande
  sida inte får skicka.
- Ingen språkmodell skriver om texten. Det whisper hör är det som står.

## Inställningar

Allt har standardvärden. Ändra i filen `installningar.env`, en inställning per rad (till exempel
`MODELL=large`), och starta om programmet. Filen finns inte från början.

| Var | Fil |
|---|---|
| Mac-programmet | `~/Library/Application Support/Akasha Protokoll/installningar.env` (skapa med TextEdit, ren text) |
| Windows | `%LOCALAPPDATA%\Akasha Protokoll\installningar.env` (skapa med Anteckningar, välj **Alla filer** så att det inte blir `.txt`) |
| Från Terminal | `.env` i mappen, starta om med `launchctl kickstart -k gui/$(id -u)/local.akasha-meet` |

Har filen ett fel säger programmet till och använder standardvärdet.

| Inställning | Standard | Vad |
|---|---|---|
| `MODELL` | `medium` | `large` gör färre fel men tar längre tid och behöver 1,1 GB till. Sidan erbjuder att hämta den |
| `ORDLISTA` | tom | Ord som alltid ska stavas rätt, till exempel företagets namn |
| `DATAKATALOG` | `~/AkashaProtokoll` | Var inspelningar och texter sparas |
| `PORT` | `8611` | Webbsidans port |
| `TALARE_TROSKEL` | `0.6` | Röster som liknar varandra mer än så räknas som samma person (0–1) |
| `MAX_MB` | `1024` | Största fil som går att ladda upp |
| `MOTOR` | `auto` | whisper.cpp (Metal på Mac, processorn på Windows). `faster` väljer faster-whisper, bara från Terminal |
| `GRAFIK` | `av` | Windows: `pa` provar grafikkretsen (Vulkan). Var långsammare på Intels inbyggda grafik |
| `HTTPS_PROXY`, `REQUESTS_CA_BUNDLE` | tom | Proxy och certifikat för hämtning på ett företagsnät |

## Felsökning

Loggen ligger i `~/Library/Logs/Akasha Protokoll/akasha-protokoll.log` (Mac),
`%LOCALAPPDATA%\Akasha Protokoll\logg\akasha-protokoll.log` (Windows) eller
`~/AkashaProtokoll/akasha-protokoll.log` (Terminal). Den innehåller inga inspelningar eller texter.

| Problem | Gör så här |
|---|---|
| Sidan öppnas inte, eller "Akasha Protokoll svarar inte" | Starta programmet igen (Windows: titta först efter ikonen vid klockan). Från Terminal: `launchctl kickstart -k gui/$(id -u)/local.akasha-meet`. Det du spelat in ligger kvar |
| "Operation not permitted", eller installationen säger att mappen ligger fel | Flytta mappen till hemkatalogen, ta bort `venv` i den och kör `bash mac/installera.sh` igen |
| Windows: programmet startar inte från zip-filen | Packa upp hela filen med **Extrahera alla…**. Mappen `_internal` måste ligga bredvid `.exe`-filen |
| Windows blockerar programmet helt | Kan bero på Smart App Control eller en jobbdator. Fråga IT i stället för att gå runt reglerna |
| Virusskyddet flaggar filen | Händer ibland med sådana program, oftast felaktigt. Kontrollera summan mot `SHA256SUMS.txt` och säg till |
| Port 8611 är upptagen | Ange en annan, till exempel `PORT=8612` |
| "Modellerna behöver hämtas" eller hämtningen misslyckas | Tryck **Hämta nu** eller **Försök igen**. Det som redan hämtats ligger kvar. På ett företagsnät, se `HTTPS_PROXY` ovan |
| `Bootstrap failed: 5` vid installation | `git pull` och kör installationen igen. Annars: Systeminställningar → Allmänt → Inloggningsobjekt, tillåt `bash` |
| "Fick inte tillgång till mikrofonen" eller "Inget ljud hörs" | Tillåt mikrofonen i webbläsaren och i systemets integritetsinställningar, och kontrollera att rätt mikrofon är vald |
| Fel antal talare, eller ingen uppdelning | **Transkribera igen** med rätt antal, eller **Vet inte – gissa** |
| Mötesljudet saknas i ett digitalt möte | Kryssa i **Dela även flikljud** i Chrome och spela in igen |
| Transkriberingen misslyckades | Öppna inspelningen och tryck **Försök igen** |

Verktyg för att felsöka utan att dela texten (`halsokoll/`) beskrivs i [docs/TEKNIK.md](docs/TEKNIK.md).

## Teknik och utveckling

Hur det fungerar inuti, utvärderingen av talaruppdelningen och byggena står i
[docs/TEKNIK.md](docs/TEKNIK.md). Testerna körs med `venv/bin/python -m unittest discover -s tester`,
och `python app/start.py` startar tjänsten utan programmet.

## Källor och licenser

Akasha Protokoll är © 2026 Dennis Fredin under Apache-2.0, se [LICENSE](LICENSE) och [NOTICE](NOTICE).

| Del | Licens |
|---|---|
| [KB-Whisper](https://huggingface.co/KBLab/kb-whisper-medium) (KBLab), [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT |
| NeMo TitaNet small (NVIDIA), testljud från [Google FLEURS](https://huggingface.co/datasets/google/fleurs) | CC-BY-4.0 |
| [FFmpeg](https://ffmpeg.org), eget bygge ([paketering/bygg-ffmpeg.sh](paketering/bygg-ffmpeg.sh)) | LGPL-2.1-or-later. Källkoden finns i samma release som programmen |
| [pystray](https://github.com/moses-palmer/pystray) (Windows) | LGPL-3.0, som vanliga `.py`-filer så att den går att byta ut |
| Typsnitten Anton och Instrument Sans | SIL Open Font License 1.1 |
| Python, Flask, numpy, PyAV, Pillow, ONNX Runtime, Visual C++-runtime med flera | Var och en sin licens |

Programmen har den fullständiga licenstexten för varje del i mappen `licenser` (börja med
`LICENSER.txt`): på Mac under `Akasha Protokoll.app/Contents/Resources/` (Visa paketinnehåll), på
Windows bredvid `Akasha Protokoll.exe`.
