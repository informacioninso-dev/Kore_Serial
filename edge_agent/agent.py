"""Bucle del agente de planta.

Lee equipos, guarda en disco y recien despues intenta enviar. Ese orden es lo
que hace que un corte de red no pierda produccion: primero se persiste, luego
se transmite.
"""

import logging
import signal
import time
import uuid
from datetime import datetime, timezone as dt_timezone

from . import drivers
from .buffer import SignalBuffer
from .client import AuthError, KoreLineClient, TransportError


AGENT_VERSION = "1.0.0"

logger = logging.getLogger("edge_agent")


def _now_iso():
    return datetime.now(dt_timezone.utc).isoformat()


class EdgeAgent:
    def __init__(self, config):
        self.config = config
        self.client = KoreLineClient(
            config["base_url"],
            config["token"],
            host_header=config.get("host_header", ""),
            timeout=config["timeout_seconds"],
        )
        self.buffer = SignalBuffer(config["buffer_path"])
        self.drivers = {}
        self.running = True
        self.online = False
        self._restart_requested = False

        self._last_heartbeat = 0.0
        self._last_send = 0.0
        self._last_commands = 0.0
        self._last_read = {}

    # ------------------------------------------------------------------

    def start(self):
        self._install_signal_handlers()
        self._build_drivers()
        logger.info(
            "Agente %s iniciado contra %s con %s dispositivos (buffer: %s pendientes)",
            AGENT_VERSION,
            self.config["base_url"],
            len(self.drivers),
            self.buffer.count(),
        )
        try:
            self._loop()
        finally:
            self.shutdown()
        return self._restart_requested

    def _install_signal_handlers(self):
        def stop(signum, frame):  # noqa: ARG001
            logger.info("Senal recibida, cerrando ordenadamente")
            self.running = False

        signal.signal(signal.SIGINT, stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, stop)

    def _build_drivers(self):
        for device in self.config["devices"]:
            try:
                self.drivers[device["code"]] = drivers.build(device)
            except RuntimeError as error:
                # Un equipo mal configurado no puede dejar muda a toda la linea.
                logger.error("%s", error)

    def _loop(self):
        while self.running:
            now = time.monotonic()
            self._read_devices(now)

            if now - self._last_send >= self.config["send_seconds"]:
                self._flush(now)
            if now - self._last_heartbeat >= self.config["heartbeat_seconds"]:
                self._heartbeat(now)
            if now - self._last_commands >= self.config["command_seconds"]:
                self._commands(now)

            time.sleep(0.5)

    # ------------------------------------------------------------------

    def _read_devices(self, now):
        for device in self.config["devices"]:
            code = device["code"]
            driver = self.drivers.get(code)
            if driver is None:
                continue
            interval = device["interval_seconds"]
            if now - self._last_read.get(code, 0) < interval:
                continue
            self._last_read[code] = now

            try:
                readings = driver.read()
            except Exception as error:  # noqa: BLE001 - un equipo caido no frena a los demas
                logger.warning("Fallo leyendo %s: %s", code, error)
                continue

            for reading in readings:
                self._store(device, reading)

    def _store(self, device, reading):
        external_id = f"{device['code']}-{uuid.uuid4().hex[:16]}"
        payload = {
            "external_id": external_id,
            "device_code": device["code"],
            "signal_key": device["signal_key"],
            "raw_value": str(reading.value),
            "unit_serial_number": reading.unit_serial_number,
            "operator_username": reading.operator_username,
            "captured_at": _now_iso(),
            "payload": reading.extra,
        }
        self.buffer.add(external_id, payload, time.time())

    def _flush(self, now):
        self._last_send = now
        batch = self.buffer.take(self.config["batch_size"])
        if not batch:
            return

        pending_before = self.buffer.count()
        signals = []
        for external_id, payload in batch:
            body = dict(payload)
            # Si quedaron pendientes de una caida, el servidor debe saberlo.
            body["from_buffer"] = pending_before > len(batch) or not self.online
            signals.append(body)

        try:
            result = self.client.send_signals(signals)
        except AuthError as error:
            logger.error("%s", error)
            self.online = False
            return
        except TransportError as error:
            self.online = False
            self.buffer.mark_attempt([item[0] for item in batch])
            logger.warning("Sin enviar (%s pendientes): %s", pending_before, error)
            return

        self.online = True
        accepted = [item["external_id"] for item in result.get("accepted", [])]
        duplicated = [item["external_id"] for item in result.get("duplicated", [])]
        failed = result.get("failed", [])

        # Las duplicadas tambien salen del buffer: el servidor ya las tiene.
        self.buffer.drop(accepted + duplicated)

        for item in failed:
            logger.error("Senal rechazada %s: %s", item.get("external_id"), item.get("detail"))
        # Una senal que el servidor rechaza por configuracion no se reintenta
        # eternamente: se saca del buffer y queda el registro en el log.
        self.buffer.drop([item.get("external_id") for item in failed if item.get("external_id")])

        if accepted or duplicated:
            logger.info(
                "Enviadas %s (%s duplicadas), quedan %s en buffer",
                len(accepted),
                len(duplicated),
                self.buffer.count(),
            )

    def _heartbeat(self, now):
        self._last_heartbeat = now
        started = time.monotonic()
        try:
            result = self.client.heartbeat(
                agent_version=AGENT_VERSION,
                buffered_count=self.buffer.count(),
                latency_ms=None,
                detail="" if self.online else "Reconectando tras corte de red.",
            )
        except AuthError as error:
            logger.error("%s", error)
            self.online = False
            return
        except TransportError as error:
            self.online = False
            logger.warning("Latido sin llegar: %s", error)
            return

        latency = int((time.monotonic() - started) * 1000)
        self.online = True
        pending = result.get("pending_commands", 0)
        logger.debug("Latido ok (%s ms), comandos pendientes: %s", latency, pending)

    def _commands(self, now):
        self._last_commands = now
        try:
            result = self.client.pull_commands()
        except AuthError as error:
            logger.error("%s", error)
            return
        except TransportError as error:
            logger.debug("Sin poder consultar comandos: %s", error)
            return

        for command in result.get("commands", []):
            self._run_command(command)

    def _run_command(self, command):
        kind = command.get("command_type")
        command_id = command.get("id")
        logger.info("Comando recibido: %s (%s)", kind, command_id)

        succeeded, response, detail = True, {}, ""
        try:
            if kind == "PING":
                response = {"pong": True, "agent_version": AGENT_VERSION}
            elif kind == "FLUSH_BUFFER":
                pending = self.buffer.count()
                self._flush(time.monotonic())
                response = {"before": pending, "after": self.buffer.count()}
            elif kind == "RELOAD_CONFIG":
                self._reload_devices()
                response = {"devices": len(self.drivers)}
            elif kind == "RESTART_AGENT":
                self._restart_requested = True
                self.running = False
                response = {"restarting": True}
            elif kind == "PRINT_LABEL":
                # Sin impresora asignada el agente no inventa un exito.
                succeeded = False
                detail = "Este agente no tiene impresora configurada."
            else:
                succeeded = False
                detail = f"Comando no soportado por el agente: {kind}"
        except Exception as error:  # noqa: BLE001
            succeeded = False
            detail = str(error)

        try:
            self.client.ack_command(command_id, succeeded, response=response, detail=detail)
        except (AuthError, TransportError) as error:
            logger.warning("No se pudo confirmar el comando %s: %s", command_id, error)

    def _reload_devices(self):
        """Vuelve a pedir la configuracion de dispositivos al servidor."""
        try:
            remote = self.client.devices()
        except (AuthError, TransportError) as error:
            raise RuntimeError(f"No se pudo recargar la configuracion: {error}")

        remote_codes = {item["code"] for item in remote.get("devices", [])}
        local_codes = {device["code"] for device in self.config["devices"]}
        missing = sorted(local_codes - remote_codes)
        if missing:
            logger.warning(
                "Estos dispositivos locales ya no existen en el servidor: %s", ", ".join(missing)
            )
        extra = sorted(remote_codes - local_codes)
        if extra:
            logger.warning(
                "El servidor tiene dispositivos que este agente no lee: %s", ", ".join(extra)
            )

    def shutdown(self):
        for driver in self.drivers.values():
            try:
                driver.close()
            except Exception:  # noqa: BLE001
                pass
        pending = self.buffer.count()
        self.buffer.close()
        logger.info("Agente detenido. Quedan %s lecturas en el buffer.", pending)
