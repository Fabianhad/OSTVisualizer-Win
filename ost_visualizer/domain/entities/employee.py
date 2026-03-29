from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PayClass:
    uid: str
    name: str


@dataclass
class Employee:
    uid: str
    employee_no: str = ""
    first_name: str = ""
    last_name: str = ""
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    home_phone: str = ""
    mobile_phone: str = ""
    email: str = ""
    pay_class_uid: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or f"Employee {self.uid}"
