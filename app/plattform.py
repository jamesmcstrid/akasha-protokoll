"""Det som skiljer mellan operativsystemen, samlat pa ett stalle."""
import contextlib
import logging
import platform
import shutil
import subprocess

from installningar import WHISPERCPP_BIN

log = logging.getLogger("akasha-meet")


def system():
    return platform.system()


def whisper_cli():
    return shutil.which(WHISPERCPP_BIN)


@contextlib.contextmanager
def hall_vaken():
    """Pa Mac: lat inte datorn somna av sig sjalv medan ett jobb pagar (caffeinate -i).
    Ett stangt lock sover anda, och da pausas jobbet tills locket oppnas."""
    process = None
    if platform.system() == "Darwin" and shutil.which("caffeinate"):
        try:
            process = subprocess.Popen(["caffeinate", "-i"])
        except OSError as e:
            log.warning("kunde inte starta caffeinate: %s", e)
    try:
        yield
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
