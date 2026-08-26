"""Tests del agente de planta.

El agente no depende de Django, pero se prueba aqui para que corra con el
resto de la suite: es codigo que va a quedar solo en un PC de planta y no
puede estar sin red de seguridad.
"""

import json
import os
import tempfile
import unittest

from edge_agent import drivers
from edge_agent.buffer import SignalBuffer
from edge_agent.config import ConfigError, load


class SignalBufferTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.buffer = SignalBuffer(os.path.join(self.folder.name, "buffer.sqlite3"))

    def tearDown(self):
        self.buffer.close()
        self.folder.cleanup()

    def test_readings_survive_and_keep_order(self):
        self.buffer.add("a", {"v": 1}, created_at=1.0)
        self.buffer.add("b", {"v": 2}, created_at=2.0)

        taken = self.buffer.take(10)
        self.assertEqual([item[0] for item in taken], ["a", "b"])
        self.assertEqual(taken[0][1], {"v": 1})

    def test_same_external_id_is_not_stored_twice(self):
        self.buffer.add("a", {"v": 1}, created_at=1.0)
        self.buffer.add("a", {"v": 99}, created_at=2.0)
        self.assertEqual(self.buffer.count(), 1)

    def test_take_does_not_remove(self):
        """Solo se borra con confirmacion del servidor, no al enviar."""
        self.buffer.add("a", {"v": 1}, created_at=1.0)
        self.buffer.take(10)
        self.assertEqual(self.buffer.count(), 1)

        self.buffer.drop(["a"])
        self.assertEqual(self.buffer.count(), 0)

    def test_buffer_persists_across_restarts(self):
        path = os.path.join(self.folder.name, "persist.sqlite3")
        first = SignalBuffer(path)
        first.add("a", {"v": 1}, created_at=1.0)
        first.close()

        second = SignalBuffer(path)
        self.assertEqual(second.count(), 1)
        second.close()

    def test_attempts_are_counted(self):
        self.buffer.add("a", {"v": 1}, created_at=1.0)
        self.buffer.mark_attempt(["a"])
        self.buffer.mark_attempt(["a"])
        rows = self.buffer._connection.execute("SELECT attempts FROM pending").fetchone()
        self.assertEqual(rows[0], 2)

    def test_missing_folder_gives_a_readable_error(self):
        with self.assertRaises(RuntimeError) as caught:
            SignalBuffer(os.path.join(self.folder.name, "no-existe", "b.sqlite3"))
        self.assertIn("No existe la carpeta", str(caught.exception))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.folder.cleanup()

    def write(self, data):
        path = os.path.join(self.folder.name, "agent.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return path

    def test_missing_file_is_explained(self):
        with self.assertRaises(ConfigError) as caught:
            load(os.path.join(self.folder.name, "no-existe.json"))
        self.assertIn("No existe el archivo", str(caught.exception))

    def test_missing_token_is_explained(self):
        path = self.write({"devices": [{"code": "D1"}]})
        with self.assertRaises(ConfigError) as caught:
            load(path)
        self.assertIn("token", str(caught.exception).lower())

    def test_missing_devices_is_explained(self):
        path = self.write({"token": "x"})
        with self.assertRaises(ConfigError) as caught:
            load(path)
        self.assertIn("dispositivos", str(caught.exception).lower())

    def test_device_without_code_is_refused(self):
        path = self.write({"token": "x", "devices": [{"driver": "simulator"}]})
        with self.assertRaises(ConfigError):
            load(path)

    def test_defaults_are_filled_in(self):
        path = self.write({"token": "x", "devices": [{"code": "D1"}]})
        config = load(path)
        self.assertEqual(config["devices"][0]["driver"], "simulator")
        self.assertEqual(config["heartbeat_seconds"], 30)
        self.assertFalse(config["base_url"].endswith("/"))

    def test_invalid_json_is_explained(self):
        path = os.path.join(self.folder.name, "roto.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{no es json")
        with self.assertRaises(ConfigError) as caught:
            load(path)
        self.assertIn("JSON", str(caught.exception))


class DriverTests(unittest.TestCase):
    def test_simulator_stays_inside_the_range(self):
        driver = drivers.build(
            {
                "code": "D1",
                "driver": "simulator",
                "signal_key": "torque",
                "options": {"min": 40, "max": 45, "out_of_range_ratio": 0},
            }
        )
        for _ in range(30):
            reading = driver.read()[0]
            self.assertGreaterEqual(reading.value, 40)
            self.assertLessEqual(reading.value, 45)

    def test_simulator_can_force_out_of_range(self):
        driver = drivers.build(
            {
                "code": "D1",
                "driver": "simulator",
                "signal_key": "torque",
                "options": {"min": 40, "max": 45, "out_of_range_ratio": 1},
            }
        )
        self.assertGreater(driver.read()[0].value, 45)

    def test_unknown_driver_is_refused_with_the_list(self):
        with self.assertRaises(RuntimeError) as caught:
            drivers.build({"code": "D1", "driver": "telepatia", "signal_key": "x"})
        self.assertIn("simulator", str(caught.exception))

    def test_file_driver_reads_only_new_lines(self):
        folder = tempfile.TemporaryDirectory()
        path = os.path.join(folder.name, "equipo.log")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("vieja\n")

        driver = drivers.build(
            {"code": "D1", "driver": "file", "signal_key": "x", "options": {"path": path}}
        )
        self.assertEqual(driver.read(), [])

        with open(path, "a", encoding="utf-8") as handle:
            handle.write("nueva\n")
        readings = driver.read()
        self.assertEqual([r.value for r in readings], ["nueva"])
        self.assertEqual(driver.read(), [])
        folder.cleanup()

    def test_file_driver_survives_rotation(self):
        folder = tempfile.TemporaryDirectory()
        path = os.path.join(folder.name, "equipo.log")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("linea larga original\n")

        driver = drivers.build(
            {"code": "D1", "driver": "file", "signal_key": "x", "options": {"path": path}}
        )
        driver.read()

        # El equipo rota el archivo y queda mas corto que la posicion guardada.
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("nueva\n")
        self.assertEqual([r.value for r in driver.read()], ["nueva"])
        folder.cleanup()
