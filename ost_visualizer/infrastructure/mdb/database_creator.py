import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import pyodbc
import win32com.client
from .reference_schema_metadata import (
    EXPLICIT_INDEXES,
    FIELD_DEFAULTS,
    REFERENCE_RELATIONSHIPS,
    UID_REQUIRED_TABLES,
)
from .schema_contract import DEFAULT_LAYER_ROWS
from ..database.schema_model import (
    DatabaseSchemaModel,
    schema_model_from_access_ddl,
)

_TABLE_DDL = [
    """CREATE TABLE [AccessLevels] (
        [UID] COUNTER PRIMARY KEY,
        [Description] VARCHAR(50),
        [Privileges] INTEGER
    )""",
    """CREATE TABLE [AffectDPCTypGroupViews] (
        [UID] COUNTER PRIMARY KEY,
        [BidTypGroupViewUID] INTEGER,
        [BidUID] INTEGER
    )""",
    """CREATE TABLE [BidALines] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidTakeoffFromUID] INTEGER,
        [BidTakeoffToUID] INTEGER,
        [Position] IMAGE,
        [Color] INTEGER,
        [Width] INTEGER
    )""",
    """CREATE TABLE [BidAnnoInk] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [Color] INTEGER,
        [Position] IMAGE,
        [Width] INTEGER
    )""",
    """CREATE TABLE [BidAnnotationClouds] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidLayerUID] INTEGER,
        [Color] INTEGER,
        [Position] IMAGE,
        [Width] INTEGER
    )""",
    """CREATE TABLE [BidAnnotationOvals] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidLayerUID] INTEGER,
        [Color] INTEGER,
        [Position] IMAGE,
        [Width] INTEGER
    )""",
    """CREATE TABLE [BidAnnotationPolygons] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidLayerUID] INTEGER,
        [Color] INTEGER,
        [Position] IMAGE,
        [Width] INTEGER
    )""",
    """CREATE TABLE [BidAnnotationRects] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidLayerUID] INTEGER,
        [Color] INTEGER,
        [Position] IMAGE,
        [Width] INTEGER
    )""",
    """CREATE TABLE [BidAreaTranslations] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [MasterAreaUID] INTEGER,
        [TranslateAreaUID] INTEGER
    )""",
    """CREATE TABLE [BidAreas] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [ParentUID] INTEGER,
        [Name] VARCHAR(50),
        [Sequence] INTEGER,
        [WasSent] YESNO,
        [GUID] VARCHAR(64)
    )""",
    """CREATE TABLE [BidArrows] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidTakeoffFromUID] INTEGER,
        [BidTakeoffToUID] INTEGER,
        [Position] IMAGE,
        [Color] INTEGER,
        [Width] INTEGER
    )""",
    """CREATE TABLE [BidCallOuts] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidLayerUID] INTEGER,
        [Name] IMAGE,
        [FontName] VARCHAR(50),
        [FontColor] INTEGER,
        [FontSize] SMALLINT,
        [FontBold] YESNO,
        [FontItalic] YESNO,
        [FontUnderline] YESNO,
        [TextAlign] INTEGER,
        [Position] VARCHAR(200),
        [Color] INTEGER,
        [Width] INTEGER
    )""",
    """CREATE TABLE [BidComments] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [ParentCommentUID] INTEGER,
        [BidLayerUID] INTEGER,
        [Color] INTEGER,
        [UserName] VARCHAR(250),
        [Comment] IMAGE,
        [Position] VARCHAR(200),
        [CommentModified] DATETIME
    )""",
    """CREATE TABLE [BidConditionFolders] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [ParentUID] INTEGER,
        [Name] VARCHAR(50),
        [Description] IMAGE,
        [ExpandState] YESNO
    )""",
    """CREATE TABLE [BidConditionUser] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [UserUID] INTEGER,
        [ConditionUID] INTEGER,
        [GUID] VARCHAR(50),
        [VALUE] VARCHAR(50),
        [Sequence] INTEGER,
        [StyleUID] INTEGER
    )""",
    """CREATE TABLE [BidConditions] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidConditionFolderUID] INTEGER,
        [BidLayerUID] INTEGER,
        [CdnTypeUID] INTEGER,
        [GUID] VARCHAR(40),
        [IsTemplate] YESNO,
        [ExternalID] INTEGER,
        [RefNo] INTEGER,
        [Name] VARCHAR(255),
        [Notes] IMAGE,
        [Type] SMALLINT,
        [Shape] INTEGER,
        [Pattern] INTEGER,
        [ColorLine] INTEGER,
        [ColorFill] INTEGER,
        [Width] DOUBLE,
        [Height] DOUBLE,
        [Spacing] DOUBLE,
        [Thickness] DOUBLE,
        [Rise] DOUBLE,
        [Run] DOUBLE,
        [Depth] DOUBLE,
        [UOM1] INTEGER,
        [UOM2] INTEGER,
        [UOM3] INTEGER,
        [RoundUp] DOUBLE,
        [Backout] YESNO,
        [DropRun] YESNO,
        [DropValue] DOUBLE,
        [Grid] YESNO,
        [GridSize1] DOUBLE,
        [GridSize2] DOUBLE,
        [Gap] DOUBLE,
        [Connect] YESNO,
        [ConnectTolerance] DOUBLE,
        [Trim] YESNO,
        [Curve] YESNO,
        [SnapToGrid] YESNO,
        [SnapToLinear] INTEGER,
        [SnapToLinearTolerance] DOUBLE,
        [ManualLength] YESNO,
        [MatAmount] DOUBLE,
        [LabAmount] DOUBLE,
        [SubAmount] DOUBLE,
        [DirectQuantity1] DOUBLE,
        [DirectQuantity2] DOUBLE,
        [DirectQuantity3] DOUBLE,
        [FontName] VARCHAR(75),
        [FontSize] SMALLINT,
        [FontBold] YESNO,
        [FontItalic] YESNO,
        [DisplayDimension] YESNO,
        [RoundQuantity] YESNO,
        [Quantity1] INTEGER,
        [Quantity2] INTEGER,
        [Quantity3] INTEGER,
        [ExcelCell1] VARCHAR(50),
        [ExcelCell2] VARCHAR(50),
        [ExcelCell3] VARCHAR(50),
        [IsCurvedSegment] YESNO,
        [OpenExternalID] INTEGER,
        [DisplayGridWhileDrawing] YESNO,
        [TypGroupUID] INTEGER,
        [ShowTakeoff] YESNO,
        [BFperLF] DOUBLE,
        [DisplaySize] INTEGER,
        [DisplayName] YESNO
    )""",
    """CREATE TABLE [BidDPCSubscribers] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidEmployeeUID] INTEGER
    )""",
    """CREATE TABLE [BidDimensions] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidTakeoffFromUID] INTEGER,
        [BidTakeoffToUID] INTEGER,
        [Position] IMAGE,
        [FontName] VARCHAR(50),
        [FontColor] INTEGER,
        [FontSize] SMALLINT,
        [FontBold] YESNO,
        [FontItalic] YESNO,
        [FontUnderline] YESNO
    )""",
    """CREATE TABLE [BidEmployees] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [EmployeeUID] INTEGER,
        [PayClassUID] INTEGER,
        [DateAdded] DATETIME,
        [IsActive] YESNO,
        [Notes] VARCHAR(50),
        [GUID] VARCHAR(64)
    )""",
    """CREATE TABLE [BidHighlights] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidLayerUID] INTEGER,
        [Color] INTEGER,
        [Position] IMAGE
    )""",
    """CREATE TABLE [BidHotLinks] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidPageViewUID] INTEGER,
        [BidLayerUID] INTEGER,
        [Color] INTEGER,
        [Position] IMAGE
    )""",
    """CREATE TABLE [BidLaborActivity] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidConditionUID] INTEGER,
        [BidLaborCostCodeUID] INTEGER,
        [Quantity] DOUBLE,
        [Hours] DOUBLE,
        [Sequence] INTEGER,
        [IsActive] YESNO,
        [UsesConditionQuantity] YESNO,
        [RuleType] VARCHAR(32),
        [RuleValue] INTEGER,
        [UseQtyIndex] INTEGER
    )""",
    """CREATE TABLE [BidLaborCostCodeTotals] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidAreaUID] INTEGER,
        [BidLaborCostCodeUID] INTEGER,
        [Date] DATETIME,
        [InstalledQty] DOUBLE,
        [CompletedHrs] DOUBLE
    )""",
    """CREATE TABLE [BidLaborCostCodes] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [Type] INTEGER,
        [CostCodeUID] INTEGER,
        [UOM] INTEGER,
        [IsActive] YESNO,
        [GUID] VARCHAR(64),
        [Notes] IMAGE
    )""",
    """CREATE TABLE [BidLayers] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [IsTemplate] YESNO,
        [Name] VARCHAR(50),
        [Show] YESNO,
        [IsLocked] YESNO,
        [Sequence] INTEGER
    )""",
    """CREATE TABLE [BidLegends] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [Position] IMAGE,
        [Rotation] DOUBLE,
        [FontName] VARCHAR(50),
        [FontColor] INTEGER,
        [FontSize] SMALLINT,
        [FontBold] YESNO,
        [FontItalic] YESNO,
        [FontUnderline] YESNO,
        [IsShowTotals] YESNO,
        [MoveToCorner] YESNO
    )""",
    """CREATE TABLE [BidMarkedPages] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [MarkTakeoffComplete] INTEGER
    )""",
    """CREATE TABLE [BidNamedViews] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [Name] VARCHAR(50),
        [Position] IMAGE,
        [Color] INTEGER,
        [Origin] INTEGER
    )""",
    """CREATE TABLE [BidNotes] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [DateCreated] DATETIME,
        [Notes] IMAGE,
        [GUID] VARCHAR(64)
    )""",
    """CREATE TABLE [BidPageFolders] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [ParentUID] INTEGER,
        [Name] VARCHAR(50),
        [Description] IMAGE,
        [WasSent] YESNO,
        [GUID] VARCHAR(64),
        [ExpandState] SMALLINT
    )""",
    """CREATE TABLE [BidPageSettings] (
        [UID] COUNTER PRIMARY KEY,
        [BidPageUID] INTEGER,
        [BidAreaUID] INTEGER,
        [BidTypAreaUID] INTEGER,
        [BidAreaSelected] INTEGER
    )""",
    """CREATE TABLE [BidPages] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageFolderUID] INTEGER,
        [Name] VARCHAR(255),
        [ImagePath] VARCHAR(255),
        [OverlayImagePath] VARCHAR(255),
        [RasterDrawMethod] INTEGER,
        [Show] INTEGER,
        [ScaleStyle] INTEGER,
        [IsCustomScale] YESNO,
        [ScaleFactor1] DOUBLE,
        [ScaleFactor2] DOUBLE,
        [Scale] DOUBLE,
        [Width] DOUBLE,
        [Height] DOUBLE,
        [ZoomFac] DOUBLE,
        [CurrentX] DOUBLE,
        [CurrentY] DOUBLE,
        [FlipX] YESNO,
        [FlipY] YESNO,
        [Rotation] DOUBLE,
        [DeskewRotation] DOUBLE,
        [OverlayOffsetX] DOUBLE,
        [OverlayOffsetY] DOUBLE,
        [OverlayRotation] DOUBLE,
        [MultiPageCount] INTEGER,
        [Index1] INTEGER,
        [Sequence] DOUBLE,
        [Invert] YESNO,
        [Bitonal] YESNO,
        [DigitizerNX1] INTEGER,
        [DigitizerNY1] INTEGER,
        [DigitizerNX2] INTEGER,
        [DigitizerNY2] INTEGER,
        [DigitizerWidth] DOUBLE,
        [DigitizerHeight] DOUBLE,
        [DigitizerResX] INTEGER,
        [DigitizerResY] INTEGER,
        [WasSent] YESNO,
        [MasterPageUID] INTEGER,
        [TypicalPageRepeats] INTEGER,
        [GUID] VARCHAR(64),
        [OverlayRect] VARCHAR(128),
        [OverlayResized] VARCHAR(255),
        [DeskewRotationOverlay] DOUBLE,
        [ZoomFlag] YESNO,
        [SheetNo] VARCHAR(50),
        [OCRState] INTEGER,
        [OCRUID] INTEGER,
        [ALState] INTEGER
    )""",
    """CREATE TABLE [BidPercents] (
        [UID] COUNTER PRIMARY KEY,
        [BidTimeCardStateUID] INTEGER,
        [BidLaborCostCodeUID] INTEGER,
        [BidLaborActivityUID] INTEGER,
        [BidTakeoffUID] INTEGER,
        [Percent] DOUBLE,
        [BidPageUID] INTEGER,
        [GUID] VARCHAR(64)
    )""",
    """CREATE TABLE [BidPlanRooms] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [ProjectID] VARCHAR(75),
        [DocumentsURL] VARCHAR(255),
        [Documents] IMAGE
    )""",
    """CREATE TABLE [BidProjects] (
        [UID] COUNTER PRIMARY KEY,
        [Name] VARCHAR(50),
        [Description] IMAGE
    )""",
    """CREATE TABLE [BidSettings] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageSelectedUID] INTEGER,
        [STSGUID] VARCHAR(40),
        [STSServerName] VARCHAR(50),
        [STSClientName] VARCHAR(50)
    )""",
    """CREATE TABLE [BidTakeoffTotals] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidZoneUID] INTEGER,
        [BidAreaUID] INTEGER,
        [BidTypAreaUID] INTEGER,
        [BidConditionUID] INTEGER,
        [Quantity1] DOUBLE,
        [Quantity2] DOUBLE,
        [Quantity3] DOUBLE,
        [SumQuantity1] DOUBLE,
        [SumQuantity2] DOUBLE,
        [SumQuantity3] DOUBLE
    )""",
    """CREATE TABLE [BidTakeoffs] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidConditionUID] INTEGER,
        [BidZoneUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidAreaUID] INTEGER,
        [BidTypAreaUID] INTEGER,
        [ParentUID] INTEGER,
        [No] INTEGER,
        [Quantity] DOUBLE,
        [Count] DOUBLE,
        [Rotation] DOUBLE,
        [Position] IMAGE,
        [GridOffsetX] DOUBLE,
        [GridOffsetY] DOUBLE,
        [GridRotation] DOUBLE,
        [IsNegativeQuantity] YESNO,
        [FontName] VARCHAR(50),
        [FontColor] INTEGER,
        [FontSize] SMALLINT,
        [FontBold] YESNO,
        [FontItalic] YESNO,
        [FontUnderline] YESNO,
        [TypGroupTakeoffUID] INTEGER,
        [TypPageTakeoffUID] INTEGER,
        [TakeoffModified] YESNO,
        [TypGroupUID] INTEGER,
        [TypGroupMarkerUID] INTEGER,
        [FlipX] YESNO,
        [FlipY] YESNO,
        [GUID] VARCHAR(64),
        [NameFontName] VARCHAR(50),
        [NameFontColor] INTEGER,
        [NameFontSize] SMALLINT,
        [NameFontBold] YESNO,
        [NameFontItalic] YESNO,
        [NameFontUnderline] YESNO,
        [Curve] INTEGER
    )""",
    """CREATE TABLE [BidTimeCardStates] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [Date] DATETIME,
        [State] SMALLINT,
        [Type] SMALLINT,
        [Percent] DOUBLE,
        [ProjectedOver] DOUBLE,
        [IsValid] YESNO,
        [GUID] VARCHAR(64)
    )""",
    """CREATE TABLE [BidTimeCards] (
        [UID] COUNTER PRIMARY KEY,
        [BidTimeCardStateUID] INTEGER,
        [BidEmployeeUID] INTEGER,
        [BidAreaUID] INTEGER,
        [BidTypicalAreaUID] INTEGER,
        [BidLaborCostCodeUID] INTEGER,
        [Hours1] DOUBLE,
        [Hours2] DOUBLE,
        [Hours3] DOUBLE,
        [Hours4] DOUBLE,
        [GUID] VARCHAR(64)
    )""",
    """CREATE TABLE [BidTexts] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidLayerUID] INTEGER,
        [Name] IMAGE,
        [FontName] VARCHAR(50),
        [FontColor] INTEGER,
        [FontSize] SMALLINT,
        [FontBold] YESNO,
        [FontItalic] YESNO,
        [FontUnderline] YESNO,
        [TextAlign] INTEGER,
        [Position] VARCHAR(200)
    )""",
    """CREATE TABLE [BidTransactionsHistory] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [TransactionID] INTEGER,
        [SendDate] DATETIME,
        [ReceiveDate] DATETIME,
        [LoginNameFrom] VARCHAR(50),
        [LoginNameTo] VARCHAR(50),
        [Description] VARCHAR(100),
        [EarnedHrs] INTEGER,
        [UsedHrs] INTEGER,
        [Type] VARCHAR(50),
        [File] VARCHAR(255)
    )""",
    """CREATE TABLE [BidTypAreas] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [Name] VARCHAR(50),
        [Sequence] INTEGER,
        [WasSent] YESNO
    )""",
    """CREATE TABLE [BidTypAreaCounts] (
        [UID] COUNTER PRIMARY KEY,
        [BidAreaUID] INTEGER,
        [BidTypAreaUID] INTEGER,
        [Count] INTEGER,
        [WasSent] YESNO
    )""",
    """CREATE TABLE [BidTypGroupViews] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidConditionUID] INTEGER,
        [BidPageUID] INTEGER,
        [Position] IMAGE
    )""",
    """CREATE TABLE [BidTypicalGroupTotals] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [BidZoneUID] INTEGER,
        [BidAreaUID] INTEGER,
        [BidTypGroupUID] INTEGER,
        [BidConditionUID] INTEGER,
        [Quantity1] DOUBLE,
        [Quantity2] DOUBLE,
        [Quantity3] DOUBLE
    )""",
    """CREATE TABLE [BidZones] (
        [UID] COUNTER PRIMARY KEY,
        [BidUID] INTEGER,
        [BidLayerUID] INTEGER,
        [ExternalID] INTEGER,
        [Name] VARCHAR(75),
        [Notes] IMAGE,
        [Pattern] INTEGER,
        [ColorLine] INTEGER,
        [ColorFill] INTEGER,
        [Spacing] DOUBLE,
        [IsNegativeValues] YESNO,
        [Sequence] INTEGER,
        [GUID] VARCHAR(40)
    )""",
    """CREATE TABLE [Bids] (
        [UID] COUNTER PRIMARY KEY,
        [BidProjectUID] INTEGER,
        [ParentBidUID] INTEGER,
        [OrigBidProjectUID] INTEGER,
        [OrigParentBidUID] INTEGER,
        [JobStatusUID] INTEGER,
        [EstimatorUID] INTEGER,
        [PrManagerUID] INTEGER,
        [JobSiteManagerUID] INTEGER,
        [SourceBidUID] VARCHAR(40),
        [ExternalID] INTEGER,
        [QuickBidDB] VARCHAR(255),
        [BidNo] INTEGER,
        [BidType] INTEGER,
        [JobID] VARCHAR(50),
        [JobName] VARCHAR(75),
        [ImageFolder] VARCHAR(255),
        [Notes] IMAGE,
        [IsAccepted] YESNO,
        [RecalcNeeded] YESNO,
        [CreateDateTime] DATETIME,
        [ModDateTime] DATETIME,
        [PriceUsing] INTEGER,
        [PriceUsingDatabase] VARCHAR(255),
        [PriceUsingWorksheet] VARCHAR(255),
        [TakeoffIncrements] DOUBLE,
        [HoursPerDay] SMALLINT,
        [MeasureBase] SMALLINT,
        [WeekStartDay] SMALLINT,
        [QuantitiesInLegend] YESNO,
        [JobSendRec] YESNO,
        [ScaleStyle] INTEGER,
        [IsCustomScale] YESNO,
        [ScaleFactor1] DOUBLE,
        [ScaleFactor2] DOUBLE,
        [PageScale] DOUBLE,
        [PageWidth] DOUBLE,
        [PageHeight] DOUBLE,
        [LastReceiveDateTime] DATETIME,
        [LastSendDateTime] DATETIME,
        [DeliverEntireBid] YESNO,
        [EstimatedDays] DOUBLE,
        [Percent] DOUBLE,
        [ProjectOver] DOUBLE,
        [DPCMode] YESNO,
        [IsDPCUpdated] YESNO,
        [IgnoreBidAreas] YESNO,
        [SendImageFiles] YESNO,
        [HasSTSClash] YESNO,
        [SRPending] YESNO,
        [IsUnlocked] YESNO,
        [FullBidSent] YESNO,
        [TypicalType] INTEGER,
        [GUID] VARCHAR(64),
        [BidDate] DATETIME,
        [CopyFromBidNO] INTEGER,
        [CopyTimeStamp] DATETIME,
        [CoverSheetSelItemType] SMALLINT,
        [CoverSheetSelItemUID] INTEGER,
        [LegendFlags] INTEGER,
        [IsCalculatedForSlope] YESNO,
        [IsCalculatedForLaborCostCodeTotals] YESNO
    )""",
    """CREATE TABLE [Boost] (
        [UID] COUNTER PRIMARY KEY,
        [TransactionID] VARCHAR(40),
        [BidUID] INTEGER,
        [BidPageUID] INTEGER,
        [State] INTEGER,
        [UploadURL] IMAGE,
        [CallbackURL] IMAGE,
        [ImagePath] VARCHAR(255)
    )""",
    """CREATE TABLE [CdnTypes] (
        [UID] COUNTER PRIMARY KEY,
        [Name] VARCHAR(50),
        [ExpandState] SMALLINT
    )""",
    """CREATE TABLE [ConditionSetStyles] (
        [UID] COUNTER PRIMARY KEY,
        [ConditionSetUID] INTEGER,
        [ConditionStyleUID] INTEGER,
        [Sequence] INTEGER
    )""",
    """CREATE TABLE [ConditionSets] (
        [UID] COUNTER PRIMARY KEY,
        [EmployeeUID] INTEGER,
        [Name] VARCHAR(50)
    )""",
    """CREATE TABLE [CostCodes] (
        [UID] COUNTER PRIMARY KEY,
        [Type] SMALLINT,
        [Name] VARCHAR(50),
        [Description] VARCHAR(75),
        [Sequence] INTEGER,
        [RuleType] VARCHAR(32),
        [RuleValue] INTEGER
    )""",
    """CREATE TABLE [DPCCalcFilter] (
        [UID] COUNTER PRIMARY KEY,
        [BidPageUID] INTEGER,
        [BidUID] INTEGER
    )""",
    """CREATE TABLE [Employees] (
        [UID] COUNTER PRIMARY KEY,
        [PayClassUID] INTEGER,
        [AccessLevelUID] INTEGER,
        [EmployeeNo] VARCHAR(50),
        [FirstName] VARCHAR(50),
        [LastName] VARCHAR(50),
        [EnableLogin] YESNO,
        [LoginName] VARCHAR(50),
        [Password] INTEGER,
        [Address1] VARCHAR(50),
        [Address2] VARCHAR(50),
        [City] VARCHAR(50),
        [State] VARCHAR(50),
        [Zip] VARCHAR(50),
        [HomePhone] VARCHAR(50),
        [MobilePhone] VARCHAR(50),
        [EMail] VARCHAR(50)
    )""",
    """CREATE TABLE [JobStatuses] (
        [UID] COUNTER PRIMARY KEY,
        [Locked] YESNO,
        [Name] VARCHAR(50),
        [Sequence] INTEGER
    )""",
    """CREATE TABLE [Locking] (
        [UID] COUNTER PRIMARY KEY,
        [Essence] VARCHAR(40) NOT NULL,
        [Owner] VARCHAR(39) NOT NULL,
        [Data] IMAGE
    )""",
    """CREATE TABLE [OCRProps] (
        [UID] COUNTER PRIMARY KEY,
        [NumberRegion] VARCHAR(100),
        [NameRegion] VARCHAR(100),
        [NameTemplate] VARCHAR(200)
    )""",
    """CREATE TABLE [PayClasses] (
        [UID] COUNTER PRIMARY KEY,
        [Name] VARCHAR(50)
    )""",
    """CREATE TABLE [STSTransactionHistory] (
        [UID] COUNTER PRIMARY KEY,
        [ObjectUID] INTEGER,
        [BidUID] INTEGER,
        [TableName] VARCHAR(50),
        [ChangeType] INTEGER,
        [ExtraInfo] VARCHAR(255),
        [ExtraInfo2] VARCHAR(255)
    )""",
    """CREATE TABLE [SchemaRegistry] (
        [UID] COUNTER PRIMARY KEY,
        [Version] INTEGER,
        [Product] INTEGER
    )""",
    """CREATE TABLE [Settings] (
        [UID] COUNTER PRIMARY KEY,
        [Name] VARCHAR(75),
        [Created] DATETIME,
        [NextBidNo] INTEGER,
        [LoginRequired] YESNO,
        [MeasureBase] SMALLINT,
        [PriceUsing] INTEGER,
        [QuantitiesInLegend] YESNO,
        [HoursPerDay] INTEGER,
        [StartWeekOn] INTEGER,
        [GridCountMethod] INTEGER,
        [TakeoffIncrements] DOUBLE,
        [ScaleStyle] INTEGER,
        [IsCustomScale] YESNO,
        [ScaleFactor1] DOUBLE,
        [ScaleFactor2] DOUBLE,
        [PageScale] DOUBLE,
        [PageWidth] DOUBLE,
        [PageHeight] DOUBLE,
        [LabelHours1] VARCHAR(25),
        [LabelHours2] VARCHAR(25),
        [LabelHours3] VARCHAR(25),
        [LabelHours4] VARCHAR(25),
        [IgnoreBidAreas] YESNO,
        [SendImageFiles] YESNO,
        [STSClientID] VARCHAR(50),
        [STSClientPassword] INTEGER,
        [BackupNo] INTEGER,
        [BackupPeriod] INTEGER,
        [CompressPeriod] INTEGER,
        [LegendFlags] INTEGER,
        [StyleLibrarySelItemType] SMALLINT,
        [StyleLibrarySelItemUID] INTEGER,
        [SLUExpandState] SMALLINT
    )""",
    """CREATE TABLE [Transactions] (
        [UID] COUNTER PRIMARY KEY,
        [ID] VARCHAR(39) NOT NULL,
        [ParentID] VARCHAR(39) NOT NULL,
        [State] INTEGER,
        [Type] INTEGER,
        [Owner] VARCHAR(39) NOT NULL,
        [Data] IMAGE
    )""",
    """CREATE TABLE [UserMasterConditions] (
        [UID] COUNTER PRIMARY KEY,
        [Name] VARCHAR(50)
    )""",
]
_SCHEMA_VERSIONS = [
    86,
    87,
    88,
    89,
    90,
    91,
    94,
    95,
    96,
    97,
    98,
    99,
    100,
    101,
    102,
    103,
    104,
    105,
    106,
    107,
    108,
    109,
    110,
    111,
    112,
    113,
]


def get_reference_schema_model() -> DatabaseSchemaModel:
    return schema_model_from_access_ddl(
        _TABLE_DDL,
        required_uid_tables=UID_REQUIRED_TABLES,
        field_defaults=FIELD_DEFAULTS,
        indexes=EXPLICIT_INDEXES,
        relationships=REFERENCE_RELATIONSHIPS,
    )


def get_reference_seed_data():
    return tuple(_SCHEMA_VERSIONS), tuple(DEFAULT_LAYER_ROWS)


_DEFAULT_LAYERS = DEFAULT_LAYER_ROWS


class DatabaseCreator:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def create_database(
        self,
        db_path: Path,
        name: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        db_path = Path(db_path)
        if db_path.exists():
            return False
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._report_progress(progress_callback, "database file")
            self._create_blank_mdb(db_path)
            self._create_schema(db_path, progress_callback=progress_callback)
            self._insert_seed_data(
                db_path,
                name,
                progress_callback=progress_callback,
            )
            self._report_progress(progress_callback, "finalizing")
            return True
        except Exception as exc:
            self._logger.exception("Failed to create database %s: %s", db_path, exc)
            if db_path.exists():
                try:
                    db_path.unlink()
                except OSError:
                    pass
            return False

    def _report_progress(
        self,
        progress_callback: Optional[Callable[[str], None]],
        description: str,
    ) -> None:
        if progress_callback is not None:
            progress_callback(description)

    def _create_blank_mdb(self, db_path: Path) -> None:
        vbs_script = (
            "dbPath = WScript.Arguments(0)\n"
            'Set cat = CreateObject("ADOX.Catalog")\n'
            'cat.Create "Provider=Microsoft.ACE.OLEDB.12.0;Data Source=" '
            '& Chr(34) & dbPath & Chr(34) & ";Jet OLEDB:Engine Type=5;"\n'
            "Set cat = Nothing\n"
        )
        vbs_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="ost_create_mdb_",
                suffix=".vbs",
                delete=False,
            ) as vbs_file:
                vbs_file.write(vbs_script)
                vbs_path = Path(vbs_file.name)
            result = subprocess.run(
                ["cscript", "//NoLogo", str(vbs_path), str(db_path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"VBScript failed (rc={result.returncode}): {result.stderr}"
                )
            if not db_path.exists():
                raise RuntimeError("VBScript completed but MDB file was not created")
        finally:
            if vbs_path is not None:
                try:
                    vbs_path.unlink(missing_ok=True)
                except OSError:
                    self._logger.exception(
                        "Failed to remove temporary MDB creation script %s",
                        vbs_path,
                    )

    def _create_schema(
        self,
        db_path: Path,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        conn_str = (
            "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};" f"DBQ={db_path};"
        )
        conn = pyodbc.connect(conn_str, autocommit=False)
        cursor = None
        operation_failed = False
        try:
            cursor = conn.cursor()
            self._report_progress(progress_callback, "schema tables")
            for ddl in _TABLE_DDL:
                cursor.execute(ddl)
            conn.commit()
        except Exception:
            operation_failed = True
            self._rollback_connection(conn, "schema creation")
            raise
        finally:
            self._close_odbc_resources(
                cursor,
                conn,
                "schema creation",
                suppress_errors=operation_failed,
            )
        self._apply_reference_schema_metadata(
            db_path,
            progress_callback=progress_callback,
        )

    def _apply_reference_schema_metadata(
        self,
        db_path: Path,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        engine = win32com.client.Dispatch("DAO.DBEngine.120")
        db = engine.OpenDatabase(str(db_path))
        operation_failed = False
        try:
            self._report_progress(progress_callback, "schema field metadata")
            for table_name in UID_REQUIRED_TABLES:
                db.TableDefs(table_name).Fields("UID").Required = True
            for (table_name, field_name), default_value in FIELD_DEFAULTS.items():
                db.TableDefs(table_name).Fields(field_name).DefaultValue = default_value
            self._report_progress(progress_callback, "schema indexes")
            for table_name, index_name, unique, columns in EXPLICIT_INDEXES:
                table_def = db.TableDefs(table_name)
                index = table_def.CreateIndex(index_name)
                index.Unique = bool(unique)
                for column in columns:
                    index.Fields.Append(index.CreateField(column))
                table_def.Indexes.Append(index)
            self._report_progress(progress_callback, "schema relationships")
            for (
                relation_name,
                child_table,
                child_column,
                parent_table,
                parent_column,
            ) in REFERENCE_RELATIONSHIPS:
                relation = db.CreateRelation(
                    relation_name,
                    parent_table,
                    child_table,
                    0,
                )
                relation_field = relation.CreateField(parent_column)
                relation_field.ForeignName = child_column
                relation.Fields.Append(relation_field)
                db.Relations.Append(relation)
        except Exception:
            operation_failed = True
            raise
        finally:
            self._close_dao_database(db, suppress_errors=operation_failed)

    def _insert_seed_data(
        self,
        db_path: Path,
        name: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        conn_str = (
            "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};" f"DBQ={db_path};"
        )
        conn = pyodbc.connect(conn_str, autocommit=False)
        cursor = None
        operation_failed = False
        try:
            cursor = conn.cursor()
            self._report_progress(progress_callback, "default data")
            now = datetime.now()
            cursor.execute(
                "INSERT INTO [Settings] ([Name], [Created], [NextBidNo], "
                "[LoginRequired], [MeasureBase], [PriceUsing], "
                "[QuantitiesInLegend], [HoursPerDay], [StartWeekOn], "
                "[GridCountMethod], [TakeoffIncrements], [ScaleStyle], "
                "[IsCustomScale], [ScaleFactor1], [ScaleFactor2], "
                "[PageScale], [PageWidth], [PageHeight], "
                "[LabelHours1], [LabelHours2], [LabelHours3], [LabelHours4], "
                "[IgnoreBidAreas], [SendImageFiles], "
                "[BackupNo], [BackupPeriod], [CompressPeriod]) "
                "VALUES (?, ?, 1, 0, 0, 0, -1, 8, 0, 0, 1.0, 1, 0, "
                "0.125, 12.0, 1.0, 42.0, 30.0, "
                "'Regular', 'Overtime', 'Time + 1/2', 'Double', "
                "0, 0, 2, 2, 2)",
                name,
                now,
            )
            cursor.execute(
                "INSERT INTO [BidProjects] ([Name]) VALUES (?)",
                "Deleted Bids",
            )
            for layer_name, show, locked, seq in _DEFAULT_LAYERS:
                cursor.execute(
                    "INSERT INTO [BidLayers] "
                    "([IsTemplate], [Name], [Show], [IsLocked], [Sequence]) "
                    "VALUES (-1, ?, ?, ?, ?)",
                    layer_name,
                    -1 if show else 0,
                    -1 if locked else 0,
                    seq,
                )
            for version in _SCHEMA_VERSIONS:
                cursor.execute(
                    "INSERT INTO [SchemaRegistry] ([Version], [Product]) "
                    "VALUES (?, 2)",
                    version,
                )
            conn.commit()
        except Exception:
            operation_failed = True
            self._rollback_connection(conn, "seed-data insertion")
            raise
        finally:
            self._close_odbc_resources(
                cursor,
                conn,
                "seed-data insertion",
                suppress_errors=operation_failed,
            )

    def _rollback_connection(self, connection, operation: str) -> None:
        try:
            connection.rollback()
        except Exception:
            self._logger.exception("Failed to roll back MDB %s", operation)

    def _close_odbc_resources(
        self,
        cursor,
        connection,
        operation: str,
        *,
        suppress_errors: bool,
    ) -> None:
        first_error = None
        for resource_name, resource in (
            ("cursor", cursor),
            ("connection", connection),
        ):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception as exc:
                self._logger.exception(
                    "Failed to close MDB %s after %s",
                    resource_name,
                    operation,
                )
                if first_error is None:
                    first_error = exc
        if first_error is not None and not suppress_errors:
            raise first_error

    def _close_dao_database(self, database, *, suppress_errors: bool) -> None:
        try:
            database.Close()
        except Exception:
            self._logger.exception("Failed to close MDB DAO database")
            if not suppress_errors:
                raise
