import time
import traceback
import logging
from threading import Thread

# Minimal file containing only the 11 sequential step functions requested.
# Each step sleeps `SLEEP_SECONDS`, prints a debug message, and starts the next
# step in a new thread. The 11th step launches `slack.poll_timer(poll_id)`.

# Basic logging so messages appear in stdout
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

SLEEP_SECONDS = 300

def step1(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step1 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step1 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step2, args=(poll_id,))
    t.daemon = True
    t.start()


def step2(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step2 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step2 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step3, args=(poll_id,))
    t.daemon = True
    t.start()


def step3(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step3 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step3 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step4, args=(poll_id,))
    t.daemon = True
    t.start()


def step4(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step4 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step4 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step5, args=(poll_id,))
    t.daemon = True
    t.start()


def step5(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step5 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step5 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step6, args=(poll_id,))
    t.daemon = True
    t.start()


def step6(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step6 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step6 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step7, args=(poll_id,))
    t.daemon = True
    t.start()


def step7(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step7 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step7 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step8, args=(poll_id,))
    t.daemon = True
    t.start()


def step8(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step8 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step8 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step9, args=(poll_id,))
    t.daemon = True
    t.start()


def step9(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step9 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step9 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step10, args=(poll_id,))
    t.daemon = True
    t.start()


def step10(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step10 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step10 finished sleep {SLEEP_SECONDS}s")
    t = Thread(target=step11, args=(poll_id,))
    t.daemon = True
    t.start()


def step11(poll_id):
    time.sleep(SLEEP_SECONDS)
    logger.info("[poll=%s] step11 finished sleep %ds", poll_id, SLEEP_SECONDS)
    print(f"[poll={poll_id}] step11 finished sleep {SLEEP_SECONDS}s")
    # Collegamento al 12esimo: funzione `poll_timer` in slack.py
    try:
        from . import slack as slack_module
        t = Thread(target=slack_module.poll_timer, args=(poll_id,))
        t.daemon = True
        logger.info("[poll=%s] launching slack.poll_timer (12th)", poll_id)
        print(f"[poll={poll_id}] launching slack.poll_timer (12th)")
        t.start()
    except Exception:
        traceback.print_exc()