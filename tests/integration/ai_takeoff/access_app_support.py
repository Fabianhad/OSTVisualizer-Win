import logging
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.database_descriptor import DatabaseDescriptor
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.services.uom_service import CALC_AREA, UOM_SQUARE_FEET
from ost_visualizer.infrastructure.logging.logger_factory import LoggerFactory
import tests.helpers.mdb.schema_support as access

CHILD_ENV = "OSTV_AI_TAKEOFF_ACCESS_CHILD"
DUMP_TABLES = (
    "Bids",
    "BidPages",
    "BidConditionFolders",
    "BidConditions",
    "BidTakeoffs",
)


def run_in_access_child(testcase) -> bool:
    if not access._access_available():
        testcase.skipTest("Access ODBC/ADOX unavailable")
    if os.environ.get(CHILD_ENV) == "1":
        return False
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-m", "unittest", testcase.id()],
        capture_output=True,
        text=True,
        timeout=600,
        env=dict(os.environ, **{CHILD_ENV: "1", "QT_QPA_PLATFORM": "offscreen"}),
    )
    testcase.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    return True


def seed_access_bid(path: Path, pages, image_path: str = ""):
    if not access.DatabaseCreator().create_database(Path(path), "AiTakeoff"):
        raise AssertionError("Access database creation failed")
    connections = access.MdbConnectionManager()
    try:
        writer = access.MdbWriter(connections)
        bid_uid = writer.create_bid(
            str(path),
            None,
            {
                "job_name": "AI takeoff",
                "pages": [
                    dict(
                        name=name,
                        width=width,
                        height=height,
                        scale_factor1=sf1,
                        scale_factor2=sf2,
                        image_path=image_path,
                        index=1,
                    )
                    for name, width, height, sf1, sf2 in pages
                ],
            },
        )
        page_uids = sorted(
            access.MdbReader(connections).get_bid_data(str(path), bid_uid)[3]
        )
        existing = writer.insert_condition(
            str(path),
            bid_uid,
            CreateConditionSpec(
                name="Existing slab",
                condition_type=Condition.TYPE_AREA,
                thickness=6.0,
                calc_type1=CALC_AREA,
                uom1=UOM_SQUARE_FEET,
            ),
        )
        return str(bid_uid), [str(uid) for uid in page_uids], str(existing)
    finally:
        connections.close()


def dump_tables(path: Path) -> dict:
    connection = access._connect_mdb(Path(path))
    try:
        cursor = connection.cursor()
        dump = {}
        for table in DUMP_TABLES:
            cursor.execute(f"SELECT * FROM [{table}] ORDER BY [UID]")
            columns = [column[0] for column in cursor.description]
            dump[table] = [dict(zip(columns, tuple(row))) for row in cursor.fetchall()]
        return dump
    finally:
        connection.close()


@contextmanager
def configured_app(home: Path, db_path: Path, bid_uid: str):
    controller = None
    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, "home", return_value=home))
        stack.enter_context(patch.object(LoggerFactory, "configure"))
        stack.enter_context(
            patch.object(
                LoggerFactory,
                "get_logger",
                return_value=logging.getLogger("test.ai_takeoff.access"),
            )
        )
        from ost_visualizer.config.di_config import configure_application

        try:
            container = configure_application(log_dir=home / "logs")
            controller = container.get("app_controller")
            controller._database_descriptor_registry.register(
                DatabaseDescriptor.for_access(str(db_path))
            )
            container.get("file_loading_service").load_file(str(db_path))
            bid_ref = BidRef(str(db_path), str(bid_uid))
            container.get("load_bid_use_case").execute(bid_ref)
            yield container, bid_ref
        finally:
            if controller is not None:
                controller.cleanup()


def temporary_home():
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
