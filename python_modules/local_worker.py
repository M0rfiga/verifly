"""Execute nesta máquina para atender às verificações solicitadas pelo painel."""

import argparse
import logging
import os
import threading
import time

logger = logging.getLogger("verifly.worker")


def process_check(reserve_id, token):
    from .comparator import COLLECTION, COMPARABLE_STATUS, STATUS_PENDING, build_comparison_update
    from .firebase_db import db
    from .verification_queue import finish_check, renew_lease

    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(30):
            try:
                if not renew_lease(reserve_id, token):
                    return
            except Exception:
                logger.exception("Não foi possível renovar a execução de %s", reserve_id)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    reserve = None
    try:
        snapshot = db.collection(COLLECTION).document(reserve_id).get()
        if snapshot.exists:
            reserve = snapshot.to_dict()
        update = None
        if reserve is not None and reserve.get("status", STATUS_PENDING) in COMPARABLE_STATUS:
            logger.info("Consultando a companhia para %s nesta máquina", reserve_id)
            update = build_comparison_update(reserve)
        published = finish_check(reserve_id, token, reserve, update)
        if published:
            logger.info("Verificação %s: %s", reserve_id, (update or {}).get("lastCheckError") or "finalizada")
    except Exception:
        # Erros de infraestrutura são retomados após a expiração da concessão.
        # Não gravar uma falha terminal quando o banco ficou indisponível.
        logger.exception("Falha ao processar %s; a fila permitirá nova tentativa", reserve_id)
    finally:
        stopped.set()
        thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Processa a fila atual e encerra")
    parser.add_argument("--poll-seconds", type=float, default=5, help="Intervalo entre consultas (padrão: 5)")
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds deve ser maior que zero")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # O navegador fica visível na máquina local; VERIFLY_HEADLESS=1 o oculta.
    os.environ.setdefault("VERIFLY_HEADLESS", "0")
    from .verification_queue import claim_next

    logger.info("Worker local ativo. Aguardando verificações do painel. Ctrl+C para encerrar.")
    try:
        while True:
            try:
                claim = claim_next()
                if claim:
                    process_check(*claim)
                    continue
                if args.once:
                    return
            except Exception:
                logger.exception("Não foi possível consultar a fila")
                if args.once:
                    raise
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        logger.info("Worker encerrado; trabalhos interrompidos serão retomados ao reiniciar.")


if __name__ == "__main__":
    main()
