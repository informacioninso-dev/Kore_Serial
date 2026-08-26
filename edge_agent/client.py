"""Cliente HTTP contra la API de Conectividad.

Solo stdlib: este codigo corre en un PC de planta donde instalar paquetes es
un tramite, no un comando.
"""

import json
import urllib.error
import urllib.request


class TransportError(Exception):
    """La red fallo. El agente debe guardar y reintentar, no morir."""


class AuthError(Exception):
    """El token no sirve. Reintentar no lo va a arreglar."""


class KoreLineClient:
    def __init__(self, base_url, token, *, host_header="", timeout=15):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.host_header = host_header
        self.timeout = timeout

    def _request(self, method, path, body=None):
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"X-Edge-Token": self.token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.host_header:
            headers["Host"] = self.host_header

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "ignore")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise AuthError(
                    "El servidor rechazo el token del gateway. Revisa la configuracion "
                    "o regenera el token en Conectividad > Gateways."
                )
            detail = error.read().decode("utf-8", "ignore")[:300]
            raise TransportError(f"HTTP {error.code}: {detail}")
        except urllib.error.URLError as error:
            raise TransportError(f"Sin conexion con {self.base_url}: {error.reason}")
        except json.JSONDecodeError as error:
            raise TransportError(f"El servidor respondio algo que no es JSON: {error}")

    # --- operaciones ---

    def heartbeat(self, *, agent_version, buffered_count, queue_depth=0, latency_ms=None, detail=""):
        return self._request(
            "POST",
            "/api/edge/v1/heartbeat/",
            {
                "agent_version": agent_version,
                "buffered_count": buffered_count,
                "queue_depth": queue_depth,
                "latency_ms": latency_ms,
                "detail": detail,
            },
        )

    def devices(self):
        return self._request("GET", "/api/edge/v1/devices/")

    def send_signals(self, signals):
        return self._request("POST", "/api/edge/v1/signals/", {"signals": signals})

    def pull_commands(self):
        return self._request("GET", "/api/edge/v1/commands/")

    def ack_command(self, command_id, succeeded, response=None, detail=""):
        return self._request(
            "POST",
            "/api/edge/v1/commands/ack/",
            {
                "command_id": command_id,
                "succeeded": succeeded,
                "response": response or {},
                "detail": detail,
            },
        )
