import unittest
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyFolderInfo,
    HierarchyPageInfo,
)
from ost_visualizer.domain.entities.project_factory import build_bid


class PageFolderOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.info = HierarchyBidInfo(
            uid="8",
            name="Bid",
            folders={
                "10": HierarchyFolderInfo(
                    name="Parent",
                    pages=[HierarchyPageInfo(uid="4", name="Parent")],
                    subfolders={
                        "11": HierarchyFolderInfo(
                            name="Nested",
                            pages=[
                                HierarchyPageInfo(uid="1", name="Nested second"),
                                HierarchyPageInfo(uid="2", name="Nested first"),
                            ],
                        )
                    },
                )
            },
            pages_without_folder=[HierarchyPageInfo(uid="3", name="Root")],
        )

    def test_build_bid_sets_direct_and_nested_folder_ownership(self):
        bid = build_bid(self.info)
        self.assertEqual(bid.folders["10"].pages[0].folder_uid, "10")
        self.assertEqual(bid.folders["10"].subfolders["11"].pages[0].folder_uid, "11")
        self.assertIsNone(bid.pages_without_folder[0].folder_uid)
        self.assertEqual((bid.uid, bid.name), ("8", "Bid"))
        self.assertEqual(
            [page.uid for page in bid.folders["10"].subfolders["11"].pages], ["1", "2"]
        )
        self.assertEqual(bid.pages_without_folder[0].uid, "3")


class ProjectFactoryHierarchyTests(unittest.TestCase):
    def hierarchy(self):
        from ost_visualizer.domain.entities.hierarchy_data import (
            HierarchyData,
            HierarchyFileEntry,
            HierarchyProjectInfo,
        )

        first = HierarchyFileEntry(
            file_path="C:/jobs/a.mdb",
            display_name="A",
            bid_projects={
                "p1": HierarchyProjectInfo(
                    name="Named",
                    description="Desc",
                    bids=[HierarchyBidInfo(uid="b1", name="One")],
                ),
                "p2": HierarchyProjectInfo(name="", bids=[]),
            },
            orphan_bids=[HierarchyBidInfo(uid="o1", name="Orphan one")],
        )
        second = HierarchyFileEntry(
            file_path="C:/jobs/b.mdb",
            display_name="B",
            bid_projects={
                "p3": HierarchyProjectInfo(
                    name="Third", bids=[HierarchyBidInfo(uid="b3", name="Three")]
                )
            },
            orphan_bids=[HierarchyBidInfo(uid="o2", name="Orphan two")],
        )
        return HierarchyData(loaded_files=[first, second])

    def test_empty_or_missing_hierarchy_builds_nothing(self):
        from ost_visualizer.domain.entities.hierarchy_data import HierarchyData
        from ost_visualizer.domain.entities.project_factory import (
            build_loaded_files,
            build_projects,
        )

        for hierarchy in (None, HierarchyData(), HierarchyData(loaded_files=[])):
            with self.subTest(hierarchy=hierarchy):
                self.assertEqual(build_projects(hierarchy), [])
                self.assertEqual(build_loaded_files(hierarchy), [])

    def test_build_projects_keeps_file_order_names_paths_and_adds_one_unassigned_group(self):
        from ost_visualizer.domain.entities.project_factory import build_projects

        projects = build_projects(self.hierarchy())
        self.assertEqual(
            [(p.uid, p.name, p.description, p.file_path) for p in projects],
            [
                ("p1", "Named", "Desc", "C:/jobs/a.mdb"),
                ("p2", "Project p2", "", "C:/jobs/a.mdb"),
                ("p3", "Third", "", "C:/jobs/b.mdb"),
                ("UNASSIGNED", "Unassigned Bids", "Bids without a project", ""),
            ],
        )
        self.assertEqual([b.uid for b in projects[0].bids], ["b1"])
        self.assertEqual(projects[1].bids, [])
        self.assertEqual([b.uid for b in projects[2].bids], ["b3"])
        self.assertEqual([b.uid for b in projects[3].bids], ["o1", "o2"])

    def test_build_projects_without_orphans_has_no_unassigned_group(self):
        from ost_visualizer.domain.entities.project_factory import build_projects

        hierarchy = self.hierarchy()
        for entry in hierarchy.loaded_files:
            entry.orphan_bids = []
        self.assertEqual(
            [p.uid for p in build_projects(hierarchy)], ["p1", "p2", "p3"]
        )

    def test_build_loaded_files_keeps_each_files_projects_and_orphans_separate(self):
        from ost_visualizer.domain.entities.project_factory import build_loaded_files

        loaded = build_loaded_files(self.hierarchy())
        self.assertEqual(
            [(f.file_path, f.display_name) for f in loaded],
            [("C:/jobs/a.mdb", "A"), ("C:/jobs/b.mdb", "B")],
        )
        self.assertEqual(
            [(p.uid, p.name, p.description) for p in loaded[0].projects],
            [("p1", "Named", "Desc"), ("p2", "Project p2", "")],
        )
        self.assertEqual([b.uid for b in loaded[0].projects[0].bids], ["b1"])
        self.assertEqual([b.uid for b in loaded[0].orphan_bids], ["o1"])
        self.assertEqual([p.uid for p in loaded[1].projects], ["p3"])
        self.assertEqual([b.uid for b in loaded[1].orphan_bids], ["o2"])

    def test_built_bid_containers_are_not_shared_with_the_hierarchy_data(self):
        # Mutating the built (domain) bid's folder/page containers must not change
        # the hierarchy snapshot it was built from (a shared list/dict would).
        from ost_visualizer.domain.entities.project_factory import build_projects

        hierarchy = self.hierarchy()
        info = hierarchy.loaded_files[0].bid_projects["p1"].bids[0]
        info.pages_without_folder = [HierarchyPageInfo(uid="r1", name="Root")]
        info.folders = {
            "f1": HierarchyFolderInfo(
                name="Folder",
                pages=[HierarchyPageInfo(uid="fp1", name="In folder")],
                subfolders={
                    "f2": HierarchyFolderInfo(
                        name="Sub", pages=[HierarchyPageInfo(uid="sp1", name="Nested")]
                    )
                },
            )
        }
        built = build_projects(hierarchy)[0].bids[0]
        built.pages_without_folder.clear()
        built.folders["f1"].pages.clear()
        built.folders["f1"].subfolders.clear()
        built.folders.clear()
        self.assertEqual([p.uid for p in info.pages_without_folder], ["r1"])
        self.assertEqual([p.uid for p in info.folders["f1"].pages], ["fp1"])
        self.assertEqual(list(info.folders["f1"].subfolders), ["f2"])
        self.assertEqual(
            [p.uid for p in info.folders["f1"].subfolders["f2"].pages], ["sp1"]
        )


class ProjectFactoryBidTests(unittest.TestCase):
    def test_missing_bid_info_builds_an_empty_placeholder_bid(self):
        bid = build_bid(None)
        self.assertEqual((bid.uid, bid.name), ("", ""))
        self.assertEqual(bid.folders, {})
        self.assertEqual(bid.pages_without_folder, [])

    def test_every_bid_field_is_copied(self):
        info = HierarchyBidInfo(
            uid="8",
            name="Bid",
            job_id="J-1",
            bid_no=7,
            bid_date="2026-01-02",
            notes="n",
            status="Won",
            status_uid="s1",
            estimator="Ann",
            page_count=3,
            condition_count=4,
            measure_base=2,
            takeoff_increments=0.5,
            orig_bid_project_uid="p9",
            copy_from_bid_no=6,
            copy_timestamp="ts",
        )
        bid = build_bid(info)
        for name in (
            "uid",
            "name",
            "job_id",
            "bid_no",
            "bid_date",
            "notes",
            "status",
            "status_uid",
            "estimator",
            "page_count",
            "condition_count",
            "measure_base",
            "takeoff_increments",
            "orig_bid_project_uid",
            "copy_from_bid_no",
            "copy_timestamp",
        ):
            with self.subTest(field=name):
                self.assertEqual(getattr(bid, name), getattr(info, name))

    def test_folder_metadata_and_page_fields_are_copied_with_defaults_for_blanks(self):
        info = HierarchyBidInfo(
            uid="8",
            name="Bid",
            folders={
                "10": HierarchyFolderInfo(
                    name="Parent",
                    description="Parent desc",
                    pages=[
                        HierarchyPageInfo(uid="4", name="P4", sheet_no="A-1", sequence=5)
                    ],
                )
            },
            pages_without_folder=[
                HierarchyPageInfo(uid="3", name="Root", sheet_no=None, sequence=None),
                HierarchyPageInfo(uid="2", name="Seq", sheet_no=12, sequence="7"),
            ],
        )
        bid = build_bid(info)
        folder = bid.folders["10"]
        self.assertEqual((folder.uid, folder.name, folder.description), ("10", "Parent", "Parent desc"))
        page = folder.pages[0]
        self.assertEqual(
            (page.uid, page.name, page.sheet_no, page.sequence, page.folder_uid),
            ("4", "P4", "A-1", 5, "10"),
        )
        blank, converted = bid.pages_without_folder
        self.assertEqual((blank.sheet_no, blank.sequence, blank.folder_uid), ("", 0, None))
        self.assertEqual((converted.sheet_no, converted.sequence), ("12", 7))
        self.assertIsInstance(converted.sequence, int)
        self.assertIsInstance(converted.sheet_no, str)
