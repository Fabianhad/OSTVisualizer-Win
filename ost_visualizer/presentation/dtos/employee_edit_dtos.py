from __future__ import annotations
from dataclasses import dataclass
from ...domain.entities.employee import Employee, PayClass


@dataclass
class PayClassRecord:
    uid: str
    name: str
    is_new: bool = False

    @classmethod
    def from_pay_class(cls, pc: PayClass) -> "PayClassRecord":
        return cls(uid=pc.uid, name=pc.name)

    def to_pay_class(self) -> PayClass:
        return PayClass(uid=self.uid, name=self.name)


@dataclass
class EmployeeRecord:
    uid: str
    is_new: bool = False
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
        return f"{self.first_name} {self.last_name}".strip() or str(self.uid)

    @classmethod
    def from_employee(cls, emp: Employee) -> "EmployeeRecord":
        return cls(
            uid=emp.uid,
            employee_no=emp.employee_no,
            first_name=emp.first_name,
            last_name=emp.last_name,
            address1=emp.address1,
            address2=emp.address2,
            city=emp.city,
            state=emp.state,
            zip=emp.zip,
            home_phone=emp.home_phone,
            mobile_phone=emp.mobile_phone,
            email=emp.email,
            pay_class_uid=emp.pay_class_uid,
        )

    def to_employee(self) -> Employee:
        return Employee(
            uid=self.uid,
            employee_no=self.employee_no,
            first_name=self.first_name,
            last_name=self.last_name,
            address1=self.address1,
            address2=self.address2,
            city=self.city,
            state=self.state,
            zip=self.zip,
            home_phone=self.home_phone,
            mobile_phone=self.mobile_phone,
            email=self.email,
            pay_class_uid=self.pay_class_uid,
        )
