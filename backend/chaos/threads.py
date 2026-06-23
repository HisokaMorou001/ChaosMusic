import time
import traceback
import logging
from threading import Thread

# Ensure at least a basic logging configuration so INFO messages reach stdout
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


def start_poll_timer_chain(poll_id, final_callable, steps=11, step_seconds=300):
    """Avvia una catena di `steps` thread; ciascuno dorme `step_seconds` e
    avvia il successivo. Il thread numero `steps` avvia `final_callable`
    (che di solito è `poll_timer` in `slack.py`) in un nuovo thread.

    Questo realizza 11 * 300s + last poll_timer(300s) = 3600s totali.
    """
    def worker(idx):
        try:
            logger.info("[poll=%s] thread %d/%d started, sleeping %ds", poll_id, idx, steps, step_seconds)
            print(f"[poll={poll_id}] thread {idx}/{steps} started, sleeping {step_seconds}s")
            time.sleep(step_seconds)
            if idx < steps:
                t = Thread(target=worker, args=(idx + 1,))
                t.daemon = True
                logger.info("[poll=%s] starting thread %d/%d", poll_id, idx + 1, steps)
                print(f"[poll={poll_id}] starting thread {idx+1}/{steps}")
                t.start()
            else:
                # Avvia il 12esimo thread (final_callable) che gestirà l'ultimo
                # sleep e la finalizzazione del sondaggio.
                t_final = Thread(target=final_callable, args=(poll_id,))
                t_final.daemon = True
                logger.info("[poll=%s] starting final poll_timer thread", poll_id)
                print(f"[poll={poll_id}] starting final poll_timer thread")
                t_final.start()
        except Exception:
            traceback.print_exc()

    # start first thread
    logger.info("[poll=%s] starting initial timer thread 1/%d", poll_id, steps)
    print(f"[poll={poll_id}] starting initial timer thread 1/{steps}")
    t0 = Thread(target=worker, args=(1,))
    t0.daemon = True
    t0.start()
    return
