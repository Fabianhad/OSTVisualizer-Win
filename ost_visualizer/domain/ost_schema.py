from typing import List

BID_SECTIONS: List[str] = [
    "BidPlanRooms",
    "BidAreas",
    "BidTypAreas",
    "BidConditionFolders",
    "BidPageFolders",
    "BidSettings",
    "BidLayers",
    "BidTypAreaCounts",
    "BidConditions",
    "UserMasterConditions",
    "BidConditionUser",
    "BidZones",
    "BidTypGroupViews",
    "OCRProps",
]
PAGE_SECTIONS: List[str] = [
    "BidTakeoffs",
    "BidHighlights",
    "BidTexts",
    "BidDimensions",
    "BidArrows",
    "BidALines",
    "BidCallOuts",
    "BidAnnotationRects",
    "BidAnnotationOvals",
    "BidAnnotationPolygons",
    "BidAnnotationClouds",
    "BidAnnoInk",
    "BidLegends",
    "BidPageSettings",
    "BidAreaTranslations",
    "BidMarkedPages",
    "BidComments",
]
BID_TAIL_SECTIONS: List[str] = ["BidNamedViews", "BidHotLinks"]
GLOBAL_SECTIONS: List[str] = ["Employees", "AccessLevels", "CdnTypes", "JobStatuses"]
RAW_BID_TABLES: List[str] = BID_SECTIONS + ["BidPages"] + BID_TAIL_SECTIONS
RAW_GLOBAL_TABLES: List[str] = ["Employees", "AccessLevels", "CdnTypes", "JobStatuses"]


def singular(table_name: str) -> str:
    if table_name.endswith("s"):
        return table_name[:-1]
    return table_name
