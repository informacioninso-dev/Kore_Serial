"""Configuracion del agente.

Un archivo JSON plano, editable por quien instala en planta sin saber Python.
"""

import json
import os


DEFAULTS = {
    "base_url": "http://localhost:8000",
    "token": "",
    "host_header": "",
    "gateway_code": "",
    "heartbeat_seconds": 30,
    "send_seconds": 5,
    "command_seconds": 15,
    "batch_size": 50,
    "buffer_path": "edge_agent_buffer.sqlite3",
    "timeout_seconds": 15,
    "devices": [],
}


class ConfigError(Exception):
    pass


def load(path):
    if not os.path.exists(path):
        raise ConfigError(
            f"No existe el archivo de configuracion: {path}\n"
            "Copia edge_agent/agent.example.json y ajusta token y dispositivos."
        )
    with open(path, "r", encoding="utf-8") as handle:
        try:
            raw = json.load(handle)
        except json.JSONDecodeError as error:
            raise ConfigError(f"El archivo de configuracion no es JSON valido: {error}")

    config = dict(DEFAULTS)
    config.update(raw)

    if not config["token"]:
        raise ConfigError(
            "Falta el token del gateway. Se obtiene en Conectividad > Gateways > "
            "el gateway > Token del collector."
        )
    if not config["devices"]:
        raise ConfigError(
            "No hay dispositivos configurados. Sin dispositivos el agente no tiene que leer."
        )
    for device in config["devices"]:
        if "code" not in device:
            raise ConfigError("Cada dispositivo necesita su 'code' tal como esta en Kore Line.")
        device.setdefault("driver", "simulator")
        device.setdefault("signal_key", "lectura")
        device.setdefault("interval_seconds", 30)
        device.setdefault("options", {})

    config["base_url"] = config["base_url"].rstrip("/")
    return config
