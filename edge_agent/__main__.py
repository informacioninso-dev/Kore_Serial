"""Punto de entrada del agente.

    python -m edge_agent --config agent.json

Corre en el PC de planta. Solo necesita Python 3.9 o superior: nada de
dependencias externas, salvo pyserial si se usan lectores por puerto serial.
"""

import argparse
import logging
import sys
import time

from .agent import AGENT_VERSION, EdgeAgent
from .config import ConfigError, load


def build_parser():
    parser = argparse.ArgumentParser(
        prog="edge_agent",
        description="Agente de planta de Kore Line (Conectividad).",
    )
    parser.add_argument("--config", default="agent.json", help="Ruta del archivo de configuracion.")
    parser.add_argument("--verbose", action="store_true", help="Muestra el detalle de cada ciclo.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Valida configuracion y conexion con el servidor, y termina.",
    )
    parser.add_argument("--version", action="version", version=f"edge_agent {AGENT_VERSION}")
    return parser


def run_check(config):
    from .client import AuthError, KoreLineClient, TransportError

    client = KoreLineClient(
        config["base_url"],
        config["token"],
        host_header=config.get("host_header", ""),
        timeout=config["timeout_seconds"],
    )
    try:
        remote = client.devices()
    except AuthError as error:
        print(f"ERROR de autenticacion: {error}")
        return 2
    except TransportError as error:
        print(f"ERROR de red: {error}")
        return 3

    remote_codes = {item["code"] for item in remote.get("devices", [])}
    local_codes = {device["code"] for device in config["devices"]}

    print(f"Conexion correcta con {config['base_url']}")
    print(f"Gateway: {remote.get('gateway')}")
    print(f"Dispositivos en el servidor: {', '.join(sorted(remote_codes)) or 'ninguno'}")
    print(f"Dispositivos en este agente : {', '.join(sorted(local_codes))}")

    missing = sorted(local_codes - remote_codes)
    if missing:
        print(f"AVISO: no existen en el servidor y seran rechazados: {', '.join(missing)}")
        return 1
    extra = sorted(remote_codes - local_codes)
    if extra:
        print(f"AVISO: el servidor espera datos de: {', '.join(extra)}")
    print("Configuracion lista.")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = load(args.config)
    except ConfigError as error:
        print(f"ERROR: {error}")
        return 2

    if args.check:
        return run_check(config)

    while True:
        agent = EdgeAgent(config)
        restart = agent.start()
        if not restart:
            return 0
        logging.getLogger("edge_agent").info("Reinicio solicitado desde el MES")
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
