from pycalima import Calima as CalimaProtocol

from .base_device import BaseDevice


class Calima(CalimaProtocol, BaseDevice):
    def __init__(self, hass, mac, pin):
        BaseDevice.__init__(self, hass, mac, pin)
        CalimaProtocol.__init__(self, self._readUUID, self._writeUUID)
