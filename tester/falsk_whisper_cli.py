"""En falsk whisper-cli for testerna av kontrollskripten: samma flaggor och samma sorts utskrift som den riktiga, men
ingen modell laases. Startas som ett skript (via en liten startfil i testet).

  --help          anvandningstext med alla flaggor som app/motor.py anvander (stderr, slutkod 0)
  --dtw X         X ska vara ett kant forval, annars "error: unknown dtw preset" fore modelladdningen (slutkod 1)
  annars          laddningsrader, framsteg, och en JSON (-oj -of PREFIX) med ett segment per ord och t_dtw per token
Miljovariabler: FALSK_CLI_SAKNAR_FLAGGA=-nfa tar bort en flagga ur --help; FALSK_CLI_UTAN_DTW=1 ger JSON utan t_dtw;
FALSK_CLI_KOD=N avslutar med den koden efter laddningsraderna.
"""
import json
import os
import sys

HELP = """usage: whisper-cli [options] file0 file1 ...
  -m FNAME,  --model FNAME       [       ] model path
  -f FNAME,  --file FNAME        [       ] input audio file path
  -l LANG,   --language LANG     [en     ] spoken language
  -bs N,     --beam-size N       [5      ] beam size for beam search
  -np,       --no-prints         [false  ] do not print anything other than the results
  -pp,       --print-progress    [false  ] print progress
  -oj,       --output-json       [false  ] output result in a JSON file
  -ojf,      --output-json-full  [false  ] include more information in the JSON file
  -of FNAME, --output-file FNAME [       ] output file path (without file extension)
             --prompt PROMPT     [       ] initial prompt
  -t N,      --threads N         [4      ] number of threads to use during computation
  -ml N,     --max-len N         [0      ] maximum segment length in characters
  -sow,      --split-on-word     [false  ] split on word rather than on token
             --dtw MODEL         [       ] compute token-level timestamps
  -nfa,      --no-flash-attn     [false  ] disable flash attention
"""
DTW_KANDA = {"tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large.v1", "large.v2", "large.v3"}
ORD = ["Hej", "Åsa", "och", "välkomna", "till", "mötet", "i", "Göteborg."]


def main():
    args = sys.argv[1:]
    if len(args) == 1 and args[0].startswith("@"):  # svarsfil: en rad per argument, UTF-8, byte for byte
        with open(args[0][1:], "rb") as f:
            args = f.read().decode("utf-8").split("\n")[:-1]
    if "--help" in args or "-h" in args:
        sak = os.environ.get("FALSK_CLI_SAKNAR_FLAGGA")
        sys.stderr.write("".join(r + "\n" for r in HELP.splitlines() if not (sak and f" {sak}," in r + ",")))
        return 0
    if "--dtw" in args and args[args.index("--dtw") + 1] not in DTW_KANDA:
        sys.stderr.write(f"error: unknown dtw preset '{args[args.index('--dtw') + 1]}'\n")
        return 1
    modell = args[args.index("-m") + 1]
    if not os.path.isfile(modell):
        sys.stderr.write(f"error: failed to open '{modell}'\n")
        return 2
    sys.stderr.write(f"whisper_init_from_file_with_params_no_state: loading model from '{modell}'\n")
    sys.stderr.write("whisper_model_load: type = 1 (tiny)\n")
    sys.stderr.write("system_info: n_threads = 4 / 8 | WHISPER : CPU : SSE3 = 1 | AVX = 1 | AVX2 = 1 |\n")
    if os.environ.get("FALSK_CLI_KOD"):
        return int(os.environ["FALSK_CLI_KOD"])
    sys.stderr.write("whisper_print_progress_callback: progress =  50%\n")
    sys.stderr.write("whisper_print_progress_callback: progress = 100%\n")
    if "-oj" in args:
        med_dtw = "--dtw" in args and not os.environ.get("FALSK_CLI_UTAN_DTW")
        seg = []
        for i, o in enumerate(ORD):
            start = 1000 + 500 * i
            tok = {"text": " " + o, "p": 0.9}
            if med_dtw:
                tok["t_dtw"] = (start + 400) // 10
            seg.append({"text": " " + o, "offsets": {"from": start, "to": start + 500}, "tokens": [tok]})
        with open(args[args.index("-of") + 1] + ".json", "w", encoding="utf-8") as f:
            json.dump({"transcription": seg}, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
