# body/manager.py

from body.base import BodyBase


class BipedBody(BodyBase):
    name = "biped"


class BodyManager:
    def __init__(self):
        self.body = BipedBody()

    def get_body(self):
        return self.body
