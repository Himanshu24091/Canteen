import logging
import sys
import time
import io
from datetime import datetime

# Force UTF-8 output on Windows so Unicode chars render correctly
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ─── ANSI Color Codes ─────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"

RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
CYAN    = "\033[36m"
WHITE   = "\033[37m"

BRED    = "\033[91m"
BGREEN  = "\033[92m"
BYELLOW = "\033[93m"
BBLUE   = "\033[94m"
BMAGENTA= "\033[95m"
BCYAN   = "\033[96m"
BWHITE  = "\033[97m"

BG_RED  = "\033[41m"
BG_GREEN= "\033[42m"


def setup_logging():
    """Suppress werkzeug default request logs (we print our own)."""
    # Enable ANSI color support on Windows 10+
    if sys.platform == "win32":
        import os
        os.system("color")          # activates VT100/ANSI in conhost
        os.system("")               # no-op, but triggers ENABLE_VIRTUAL_TERMINAL

    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    logging.getLogger('werkzeug').setLevel(logging.ERROR)


def get_timestamp():
    return datetime.now().strftime("%H:%M:%S")


def log_startup(host, port):
    line = "=" * 60
    dash = "-" * 60
    print(f"\n{BOLD}{BCYAN}{line}{RESET}", flush=True)
    print(f"  {BOLD}SmartCanteen{RESET}  {DIM}Flask Dev Server{RESET}", flush=True)
    print(f"{BOLD}{BCYAN}{line}{RESET}", flush=True)
    print(f"  {BGREEN}>> Running on{RESET}  {BOLD}http://{host}:{port}{RESET}", flush=True)
    print(f"  {BYELLOW}** Admin     {RESET}  admin@canteen.com / admin123", flush=True)
    print(f"  {DIM}Press Ctrl+C to stop{RESET}", flush=True)
    print(f"{BOLD}{BCYAN}{dash}{RESET}\n", flush=True)


# ─── Method color ─────────────────────────────────────────────────
METHOD_COLORS = {
    "GET":    BBLUE,
    "POST":   BGREEN,
    "PUT":    BYELLOW,
    "DELETE": BRED,
    "PATCH":  BMAGENTA,
}


def status_color(code):
    if code < 300: return BGREEN
    if code < 400: return BCYAN
    if code < 500: return BYELLOW
    return BRED


def log_request(method, path, status, duration_ms, user=None):
    ts     = get_timestamp()
    mcol   = METHOD_COLORS.get(method, WHITE)
    scol   = status_color(status)
    user_s = f"{DIM}[{user}]{RESET} " if user else ""
    dur_s  = f"{DIM}{duration_ms:.0f}ms{RESET}"
    pad    = " " * max(0, 38 - len(path))
    sys.stdout.write(
        f"  {DIM}{ts}{RESET}  "
        f"{mcol}{BOLD}{method:<7}{RESET}"
        f"{WHITE}{path}{pad}{RESET}"
        f"{scol}{BOLD}{status}{RESET}  "
        f"{user_s}{dur_s}\n"
    )
    sys.stdout.flush()


def log_event(icon, label, detail="", color=BGREEN):
    ts = get_timestamp()
    detail_s = f"  {DIM}{detail}{RESET}" if detail else ""
    try:
        sys.stdout.write(f"  {DIM}{ts}{RESET}  {color}{BOLD}{icon} {label}{RESET}{detail_s}\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        # Fallback without icon
        sys.stdout.write(f"  {ts}  {label}  {detail}\n")
        sys.stdout.flush()


def log_separator():
    sys.stdout.write(f"  {DIM}{'-' * 56}{RESET}\n")
    sys.stdout.flush()
