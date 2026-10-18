"""Integration tests against a fake controller on localhost (synthetic data only)."""

import asyncio
from unittest.mock import PropertyMock, patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eopt_home.const import DOMAIN, STORAGE_KEY, STORAGE_VERSION
from custom_components.eopt_home.sensio_lib.hub import Hub
from custom_components.eopt_home.sensio_lib.socket_manager import SocketManager

FUNCS = {"functions": [
    {"address": 101, "subType": "light_on",    "name": "B_R_LysA_ON",    "displayName": "Lys A", "zoneId": "z-stue", "subGroupId": 10},
    {"address": 102, "subType": "light_off",   "name": "B_R_LysA_OFF",   "displayName": "Lys A", "zoneId": "z-stue", "subGroupId": 10},
    {"address": 103, "subType": "light_state", "name": "M_R_LysA_State", "displayName": "Lys A", "zoneId": "z-stue", "subGroupId": 10},
    {"address": 301, "subType": "LightOnRoom", "name": "B_LightStue_ON",  "displayName": "On",  "zoneId": "z-stue", "subGroupId": 0},
    {"address": 302, "subType": "LightOffRoom","name": "B_LightStue_OFF", "displayName": "Off", "zoneId": "z-stue", "subGroupId": 0},
    {"address": 401, "subType": "LigthSc1Room","name": "B_LightStue_Sc1", "displayName": "Sc1", "zoneId": "z-stue", "subGroupId": 0},
    {"address": 1001, "subType": "Thermostat", "name": "TH_Stue001", "displayName": "Stue Thermostat", "zoneId": "z-stue", "subGroupId": 0},
    {"address": 1002, "subType": "HeatRelay",  "name": "R_VKStue001", "displayName": "Stue Temperature Relay", "zoneId": "z-stue", "subGroupId": 0},
    {"address": 3001, "subType": "MeterReader", "name": "M_MeterCur", "displayName": "Meter value", "zoneId": "z-house", "subGroupId": 0},
    {"address": 3002, "subType": "MeterSum", "name": "M_MeterSum", "displayName": "Meter Sum", "zoneId": "z-house", "subGroupId": 0},
]}

# The fake controller is a real TCP server on localhost.
pytestmark = [pytest.mark.enable_socket, pytest.mark.allow_hosts(["127.0.0.1"])]

LYS_A = "light.eopt_home_test_lys_a"
ROOM = "light.eopt_home_test_stue_all_lights"


class FakeController:
    def __init__(self):
        self.writers, self.received, self.connections = [], [], 0

    async def start(self):
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _client(self, reader, writer):
        self.connections += 1
        self.writers.append(writer)
        writer.write(b'\x01<connect sn="00-000" fw="fake"/>\r\n\x02\x00')
        while data := await reader.read(1024):
            self.received.append(data)

    async def push(self, text):
        for w in self.writers:
            if not w.is_closing():
                w.write(b"\x01" + text.encode() + b"\x02\x00")
                await w.drain()

    async def stop(self):
        for w in self.writers:
            w.close()
        self.server.close()
        await self.server.wait_closed()


async def settle(hass, cond, timeout=3.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < end, "condition not met"
        await asyncio.sleep(0.02)
        await hass.async_block_till_done()


@pytest.fixture
async def controller():
    c = FakeController()
    await c.start()
    yield c
    await c.stop()


@pytest.fixture
async def setup(hass, controller):
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, unique_id="test",
        data={"hub_ip": "127.0.0.1", "username": "u", "password": "p", "project_id": "x",
              "project_name": "Test", "use_ha_pilot": False},
    )
    entry.add_to_hass(hass)
    await Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_test").async_save(FUNCS)

    def make_hub(ip):
        return Hub(ip, socket_manager=SocketManager(ip, controller.port, backoff_initial=0.05, backoff_max=0.2,
                                                    command_wait_timeout=0.3),
                   availability_grace=0.4)

    with patch("custom_components.eopt_home.Hub", side_effect=make_hub):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_state_from_rsn(hass, controller, setup):
    assert hass.states.get(LYS_A).state == STATE_UNKNOWN
    assert hass.states.get(LYS_A).attributes.get("assumed_state") is None
    await controller.push("RSN 103 M_R_LysA_State 23 1 0 1.00")          # wall switch on
    await settle(hass, lambda: hass.states.get(LYS_A).state == STATE_ON)
    assert hass.states.get(ROOM).state == STATE_ON
    await controller.push("RSN 103 M_R_LysA_State 23 1 0 0.00")
    await settle(hass, lambda: hass.states.get(LYS_A).state == STATE_OFF)
    assert hass.states.get(ROOM).state == STATE_OFF


async def test_turn_on_sends_command(hass, controller, setup):
    await hass.services.async_call("light", "turn_on", {"entity_id": LYS_A}, blocking=True)
    await settle(hass, lambda: b"new_state 101 0" in b"".join(controller.received))
    assert b"".join(controller.received) == b"\x01new_state 101 0\x02"


async def test_short_reconnect_keeps_entities_available(hass, controller, setup):
    hub = hass.data[DOMAIN][setup.entry_id]
    seen = []
    hass.bus.async_listen("state_changed", lambda e: seen.append(e.data["new_state"].state)
                          if e.data["entity_id"] == LYS_A else None)
    for w in controller.writers:
        w.close()                                   # controller closes the idle connection
    await settle(hass, lambda: controller.connections == 2 and hub._socket_manager.connected)
    await asyncio.sleep(0.5)                        # past the grace period
    await hass.async_block_till_done()
    assert STATE_UNAVAILABLE not in seen and hass.states.get(LYS_A).state != STATE_UNAVAILABLE
    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.eopt_home_test_stue_scene_1"}, blocking=True)
    await settle(hass, lambda: b"new_state 401 0" in b"".join(controller.received))


async def test_nothing_sent_while_unavailable(hass, controller, setup):
    hub = hass.data[DOMAIN][setup.entry_id]
    await controller.stop()
    await settle(hass, lambda: hass.states.get(LYS_A).state == STATE_UNAVAILABLE)   # after the grace period
    await hass.services.async_call("light", "turn_on", {"entity_id": LYS_A}, blocking=True)
    assert controller.received == []          # HA skips unavailable entities


async def test_clean_error_if_connection_drops_mid_call(hass, controller, setup):
    hub = hass.data[DOMAIN][setup.entry_id]
    await controller.stop()
    await settle(hass, lambda: not hub.connected)
    # Entity still looked available when the call started, but the socket is gone.
    with patch.object(Hub, "available", new_callable=PropertyMock, return_value=True):
        with pytest.raises(HomeAssistantError, match="Could not turn on"):
            await hass.services.async_call("light", "turn_on", {"entity_id": LYS_A}, blocking=True)


async def test_drop_connection_service_reconnects_and_sends_nothing(hass, controller, setup):
    hub = hass.data[DOMAIN][setup.entry_id]
    await hass.services.async_call(DOMAIN, "drop_connection", {}, blocking=True)
    await settle(hass, lambda: controller.connections == 2 and hub.connected)
    assert controller.received == []
    await controller.push("RSN 103 M_R_LysA_State 23 1 0 1.00")
    await settle(hass, lambda: hass.states.get(LYS_A).state == STATE_ON)



def _eid(hass, unique_id):
    from homeassistant.helpers import entity_registry as er
    return er.async_get(hass).async_get_entity_id(
        unique_id.split("|")[0], DOMAIN, unique_id.split("|")[1])


async def test_heating_sensors_read_only(hass, controller, setup):
    temp = _eid(hass, "sensor|eopt_home_z-stue_climate_temperature")
    setp = _eid(hass, "sensor|eopt_home_z-stue_climate_setpoint")
    demand = _eid(hass, "binary_sensor|eopt_home_z-stue_climate_heat_demand")
    relay = _eid(hass, "binary_sensor|eopt_home_z-stue_climate_relay")
    power = _eid(hass, "sensor|eopt_home_test_meter_power")
    energy = _eid(hass, "sensor|eopt_home_test_meter_energy")
    assert all((temp, setp, demand, relay, power, energy))
    assert hass.states.get(temp).state == STATE_UNKNOWN

    await controller.push("RSN 1001 TH_Stue001 7 1 1 22.0 21.4 -0.3")
    await controller.push("RSN 1002 R_VKStue001 8 1 1 0")
    await controller.push("RSN 3001 M_MeterCur 23 1 0 1500.00")
    await controller.push("RSN 3002 M_MeterSum 23 1 0 36000000.00")
    await settle(hass, lambda: hass.states.get(energy).state == "10.0")

    t = hass.states.get(temp)
    assert (t.state, t.attributes["unit_of_measurement"], t.attributes["device_class"]) == ("21.4", "°C", "temperature")
    assert hass.states.get(setp).state == "22.0"
    assert hass.states.get(demand).state == STATE_ON and hass.states.get(relay).state == STATE_ON
    p = hass.states.get(power)
    assert (p.state, p.attributes["unit_of_measurement"]) == ("1500.0", "W")
    e = hass.states.get(energy)
    assert (e.attributes["unit_of_measurement"], e.attributes["state_class"]) == ("kWh", "total_increasing")
    assert controller.received == []        # read-only: nothing sent to the controller
