"""Como se lee cada tipo de equipo.

Un driver devuelve cero o mas lecturas por ciclo. Nunca bloquea el bucle: si
el equipo no tiene nada que decir, devuelve una lista vacia y el agente sigue.

El driver `simulator` existe para demostrar y para probar la instalacion antes
de que llegue el equipo real. No es un adorno: permite validar red, token y
reglas de normalizacion sin depender del proveedor del PLC.
"""

import os
import random
import socket
import time


class Reading:
    """Una lectura tomada del piso."""

    def __init__(self, value, *, unit_serial_number="", operator_username="", extra=None):
        self.value = value
        self.unit_serial_number = unit_serial_number
        self.operator_username = operator_username
        self.extra = extra or {}


class BaseDriver:
    def __init__(self, device):
        self.device = device
        self.code = device["code"]
        self.signal_key = device["signal_key"]
        self.options = device.get("options", {})

    def read(self):
        raise NotImplementedError

    def close(self):
        pass


class SimulatorDriver(BaseDriver):
    """Genera lecturas plausibles dentro (o fuera) del rango esperado."""

    def __init__(self, device):
        super().__init__(device)
        self.minimum = float(self.options.get("min", 80))
        self.maximum = float(self.options.get("max", 120))
        self.out_of_range_ratio = float(self.options.get("out_of_range_ratio", 0.0))
        self.unit_serial_number = self.options.get("unit_serial_number", "")
        self.operator_username = self.options.get("operator_username", "")

    def read(self):
        if random.random() < self.out_of_range_ratio:
            # Fuera de rango a proposito: sirve para ver el rechazo en pantalla.
            value = round(self.maximum + random.uniform(1, 20), 2)
        else:
            value = round(random.uniform(self.minimum, self.maximum), 2)
        return [
            Reading(
                value,
                unit_serial_number=self.unit_serial_number,
                operator_username=self.operator_username,
                extra={"simulated": True},
            )
        ]


class TcpDriver(BaseDriver):
    """Lee lineas de texto desde un socket TCP (PLC, banco de pruebas, balanza)."""

    def __init__(self, device):
        super().__init__(device)
        self.host = self.options.get("host", "127.0.0.1")
        self.port = int(self.options.get("port", 9000))
        self.read_timeout = float(self.options.get("read_timeout", 2))
        self._socket = None

    def _connect(self):
        if self._socket is not None:
            return self._socket
        self._socket = socket.create_connection((self.host, self.port), timeout=self.read_timeout)
        self._socket.settimeout(self.read_timeout)
        return self._socket

    def read(self):
        try:
            connection = self._connect()
            data = connection.recv(4096)
        except (socket.timeout, TimeoutError):
            return []
        except OSError:
            self.close()
            raise

        readings = []
        for line in data.decode("utf-8", "ignore").splitlines():
            line = line.strip()
            if line:
                readings.append(Reading(line))
        return readings

    def close(self):
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None


class SerialDriver(BaseDriver):
    """Lee de un puerto serial. Requiere pyserial, que es opcional."""

    def __init__(self, device):
        super().__init__(device)
        try:
            import serial  # noqa: PLC0415 - dependencia opcional del sitio
        except ImportError:
            raise RuntimeError(
                f"El dispositivo {self.code} usa el driver serial y falta pyserial. "
                "Instalalo con: pip install pyserial"
            )
        self._serial = serial.Serial(
            port=self.options.get("port", "COM3"),
            baudrate=int(self.options.get("baudrate", 9600)),
            timeout=float(self.options.get("read_timeout", 1)),
        )

    def read(self):
        line = self._serial.readline().decode("utf-8", "ignore").strip()
        return [Reading(line)] if line else []

    def close(self):
        try:
            self._serial.close()
        except Exception:  # noqa: BLE001
            pass


class FileDriver(BaseDriver):
    """Sigue un archivo que el equipo va escribiendo.

    Muchos equipos viejos no tienen API pero si dejan un log. Esto los integra
    sin tocarlos.
    """

    def __init__(self, device):
        super().__init__(device)
        self.path = self.options.get("path", "")
        self._position = 0
        if self.path and os.path.exists(self.path):
            self._position = os.path.getsize(self.path)

    def read(self):
        if not self.path or not os.path.exists(self.path):
            return []
        size = os.path.getsize(self.path)
        if size < self._position:
            # El archivo se roto: empezar de nuevo.
            self._position = 0
        if size == self._position:
            return []
        with open(self.path, "r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(self._position)
            chunk = handle.read()
            self._position = handle.tell()
        return [Reading(line.strip()) for line in chunk.splitlines() if line.strip()]


DRIVERS = {
    "simulator": SimulatorDriver,
    "tcp": TcpDriver,
    "serial": SerialDriver,
    "file": FileDriver,
}


def build(device):
    name = device.get("driver", "simulator")
    driver_class = DRIVERS.get(name)
    if driver_class is None:
        raise RuntimeError(
            f"Driver desconocido '{name}' en el dispositivo {device.get('code')}. "
            f"Disponibles: {', '.join(sorted(DRIVERS))}."
        )
    return driver_class(device)
