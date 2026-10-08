import importlib.util
import unittest
from tests.paths import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "check_architecture_for_tests", REPO_ROOT / "tools" / "check_architecture.py"
)
check_architecture = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_architecture)


class NativeDestinationTests(unittest.TestCase):
    def setUp(self):
        self.text = check_architecture.CMAKE_LISTS.read_text(encoding="utf-8")

    def test_every_built_module_installs_and_copies_to_its_canonical_folder(self):
        modules = set(check_architecture._NB_MODULE_RE.findall(self.text))
        self.assertEqual(modules, set(check_architecture.PYD_ALLOWED_DIRS))
        self.assertEqual(len(modules), 13)
        installs = dict(
            (target, check_architecture._DESTINATION_RE.findall(body))
            for target, body in check_architecture._INSTALL_RE.findall(self.text)
        )
        self.assertEqual(installs["ost_pdf"], ["presentation/visualization/pdf"] * 2)
        self.assertEqual(
            installs["ost_snap"],
            ["presentation/components/plan_view/components"] * 2,
        )
        copies = {
            target: destination
            for destination, target in check_architecture._COPY_RE.findall(self.text)
        }
        self.assertEqual(copies["ost_pdf"], "presentation/visualization/pdf")
        self.assertEqual(
            copies["ost_snap"], "presentation/components/plan_view/components"
        )
        self.assertEqual(check_architecture.cmake_destination_problems(self.text), [])

    def test_wrong_install_or_copy_destinations_are_reported(self):
        wrong_install = self.text.replace(
            "LIBRARY DESTINATION ost_visualizer/presentation/components/plan_view/components\n"
            "    RUNTIME DESTINATION ost_visualizer/presentation/components/plan_view/components\n)\n"
            "\nadd_custom_command(TARGET ost_snap",
            "LIBRARY DESTINATION ost_visualizer/presentation/components\n"
            "    RUNTIME DESTINATION ost_visualizer/presentation/components/plan_view/components\n)\n"
            "\nadd_custom_command(TARGET ost_snap",
            1,
        )
        self.assertNotEqual(wrong_install, self.text)
        self.assertEqual(
            check_architecture.cmake_destination_problems(wrong_install),
            [
                "ost_snap installs to presentation/components, expected "
                "presentation/components/plan_view/components"
            ],
        )
        wrong_copy = self.text.replace(
            "${OST_ROOT}/ost_visualizer/presentation/visualization/pdf/$<TARGET_FILE_NAME:ost_pdf>",
            "${OST_ROOT}/ost_visualizer/presentation/visualization/$<TARGET_FILE_NAME:ost_pdf>",
        )
        self.assertEqual(
            check_architecture.cmake_destination_problems(wrong_copy),
            [
                "ost_pdf is copied to presentation/visualization, expected "
                "presentation/visualization/pdf"
            ],
        )

    def test_unlisted_and_unbuilt_modules_are_reported(self):
        extra = self.text + "\nnanobind_add_module(ost_linework src/x.cpp)\n"
        self.assertEqual(
            check_architecture.cmake_destination_problems(extra),
            ["native module ost_linework has no PYD_ALLOWED_DIRS destination"],
        )
        missing = self.text.replace(
            "nanobind_add_module(ost_snap", "add_library(ost_snap"
        )
        self.assertIn(
            "PYD_ALLOWED_DIRS lists ost_snap but CMake does not build it",
            check_architecture.cmake_destination_problems(missing),
        )


if __name__ == "__main__":
    unittest.main()
