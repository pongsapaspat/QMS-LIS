from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.domain.exceptions import CatalogNotFoundError, DuplicateCatalogCodeError
from app.models.audit import AuditLog
from app.models.package import TestPackage
from app.models.test_catalog import LabTest
from app.schemas.package import PackageCreate


class PackageService:
    def __init__(self, session: Session):
        self.session = session

    def list(self, available_only: bool = False) -> list[TestPackage]:
        packages = list(
            self.session.scalars(
                select(TestPackage)
                .options(selectinload(TestPackage.tests))
                .order_by(TestPackage.code)
            )
        )
        return [p for p in packages if p.available] if available_only else packages

    def get(self, package_id: int) -> TestPackage:
        package = self.session.get(TestPackage, package_id)
        if package is None:
            raise CatalogNotFoundError("Package not found")
        return package

    def save(self, data: PackageCreate, actor: str, package_id: int | None = None) -> TestPackage:
        tests = list(self.session.scalars(select(LabTest).where(LabTest.id.in_(data.test_ids))))
        if len(tests) != len(data.test_ids):
            raise CatalogNotFoundError("One or more package tests were not found")
        if data.is_active and any(
            not (
                t.is_active
                and t.department.is_active
                and t.category.is_active
                and t.specimen_type.is_active
            )
            for t in tests
        ):
            raise CatalogNotFoundError("Active packages require active tests and configurations")
        package = self.get(package_id) if package_id else TestPackage()
        values = data.model_dump(exclude={"test_ids", "reason"})
        changed = [key for key, value in values.items() if getattr(package, key, None) != value]
        if {test.id for test in package.tests} != set(data.test_ids):
            changed.append("test_ids")
        for key, value in values.items():
            setattr(package, key, value)
        package.tests = tests
        try:
            self.session.add(package)
            self.session.flush()
            self.session.add(
                AuditLog(
                    event_type="PACKAGE_UPDATED" if package_id else "PACKAGE_CREATED",
                    entity_type="test_package",
                    entity_id=package.id,
                    changed_fields=changed,
                    reason=data.reason,
                    actor_reference=actor,
                )
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateCatalogCodeError("Package code already exists") from exc
        return package
