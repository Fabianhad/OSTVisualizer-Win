import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
import pyodbc

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
_DEFAULT_LAYERS = [
    ("Default", True, True, 2),
    ("Annotation", True, True, 1),
    ("Image", True, True, 0),
    ("Comments", True, True, 3),
]
_FK_INDEXES = [
    ("AffectDPCTypGroupViews", "BidUID"),
    ("BidALines", "BidPageUID"),
    ("BidALines", "BidTakeoffFromUID"),
    ("BidALines", "BidTakeoffToUID"),
    ("BidALines", "BidUID"),
    ("BidAnnoInk", "BidPageUID"),
    ("BidAnnoInk", "BidUID"),
    ("BidAnnotationClouds", "BidLayerUID"),
    ("BidAnnotationClouds", "BidPageUID"),
    ("BidAnnotationClouds", "BidUID"),
    ("BidAnnotationOvals", "BidLayerUID"),
    ("BidAnnotationOvals", "BidPageUID"),
    ("BidAnnotationOvals", "BidUID"),
    ("BidAnnotationPolygons", "BidLayerUID"),
    ("BidAnnotationPolygons", "BidPageUID"),
    ("BidAnnotationPolygons", "BidUID"),
    ("BidAnnotationRects", "BidLayerUID"),
    ("BidAnnotationRects", "BidPageUID"),
    ("BidAnnotationRects", "BidUID"),
    ("BidAreaTranslations", "BidPageUID"),
    ("BidAreas", "BidUID"),
    ("BidAreas", "GUID"),
    ("BidAreas", "ParentUID"),
    ("BidArrows", "BidPageUID"),
    ("BidArrows", "BidTakeoffFromUID"),
    ("BidArrows", "BidTakeoffToUID"),
    ("BidArrows", "BidUID"),
    ("BidCallOuts", "BidLayerUID"),
    ("BidCallOuts", "BidPageUID"),
    ("BidCallOuts", "BidUID"),
    ("BidComments", "BidLayerUID"),
    ("BidComments", "BidPageUID"),
    ("BidComments", "BidUID"),
    ("BidComments", "ParentCommentUID"),
    ("BidConditionFolders", "BidUID"),
    ("BidConditionFolders", "ParentUID"),
    ("BidConditions", "BidConditionFolderUID"),
    ("BidConditions", "BidLayerUID"),
    ("BidConditions", "BidUID"),
    ("BidConditions", "CdnTypeUID"),
    ("BidDPCSubscribers", "BidEmployeeUID"),
    ("BidDPCSubscribers", "BidUID"),
    ("BidDimensions", "BidPageUID"),
    ("BidDimensions", "BidTakeoffFromUID"),
    ("BidDimensions", "BidTakeoffToUID"),
    ("BidDimensions", "BidUID"),
    ("BidEmployees", "BidUID"),
    ("BidEmployees", "EmployeeUID"),
    ("BidEmployees", "GUID"),
    ("BidEmployees", "PayClassUID"),
    ("BidHighlights", "BidLayerUID"),
    ("BidHighlights", "BidPageUID"),
    ("BidHighlights", "BidUID"),
    ("BidHotLinks", "BidLayerUID"),
    ("BidHotLinks", "BidPageUID"),
    ("BidHotLinks", "BidPageViewUID"),
    ("BidHotLinks", "BidUID"),
    ("BidLaborActivity", "BidConditionUID"),
    ("BidLaborActivity", "BidLaborCostCodeUID"),
    ("BidLaborActivity", "BidUID"),
    ("BidLaborCostCodeTotals", "BidPageUID"),
    ("BidLaborCostCodeTotals", "BidUID"),
    ("BidLaborCostCodes", "BidUID"),
    ("BidLaborCostCodes", "CostCodeUID"),
    ("BidLaborCostCodes", "GUID"),
    ("BidLayers", "BidUID"),
    ("BidLayers", "IsTemplate"),
    ("BidLegends", "BidPageUID"),
    ("BidLegends", "BidUID"),
    ("BidNamedViews", "BidPageUID"),
    ("BidNamedViews", "BidUID"),
    ("BidNotes", "BidUID"),
    ("BidNotes", "GUID"),
    ("BidPageFolders", "BidUID"),
    ("BidPageFolders", "GUID"),
    ("BidPageFolders", "ParentUID"),
    ("BidPageSettings", "BidAreaUID"),
    ("BidPageSettings", "BidPageUID"),
    ("BidPageSettings", "BidTypAreaUID"),
    ("BidPages", "BidPageFolderUID"),
    ("BidPages", "BidUID"),
    ("BidPages", "GUID"),
    ("BidPercents", "BidLaborActivityUID"),
    ("BidPercents", "BidLaborCostCodeUID"),
    ("BidPercents", "BidPageUID"),
    ("BidPercents", "BidTakeoffUID"),
    ("BidPercents", "BidTimeCardStateUID"),
    ("BidPercents", "GUID"),
    ("BidPlanRooms", "BidUID"),
    ("BidProjects", "Name"),
    ("BidSettings", "BidPageSelectedUID"),
    ("BidTakeoffTotals", "BidPageUID"),
    ("BidTakeoffTotals", "BidUID"),
    ("BidTakeoffs", "BidAreaUID"),
    ("BidTakeoffs", "BidConditionUID"),
    ("BidTakeoffs", "BidPageUID"),
    ("BidTakeoffs", "BidTypAreaUID"),
    ("BidTakeoffs", "BidUID"),
    ("BidTakeoffs", "BidZoneUID"),
    ("BidTakeoffs", "GUID"),
    ("BidTakeoffs", "No"),
    ("BidTakeoffs", "ParentUID"),
    ("BidTexts", "BidLayerUID"),
    ("BidTexts", "BidPageUID"),
    ("BidTexts", "BidUID"),
    ("BidTimeCardStates", "BidUID"),
    ("BidTimeCardStates", "GUID"),
    ("BidTimeCards", "BidAreaUID"),
    ("BidTimeCards", "BidEmployeeUID"),
    ("BidTimeCards", "BidLaborCostCodeUID"),
    ("BidTimeCards", "BidTimeCardStateUID"),
    ("BidTimeCards", "BidTypicalAreaUID"),
    ("BidTimeCards", "GUID"),
    ("BidTransactionsHistory", "BidUID"),
    ("BidTypAreaCounts", "BidAreaUID"),
    ("BidTypAreaCounts", "BidTypAreaUID"),
    ("BidTypAreas", "BidUID"),
    ("BidTypGroupViews", "BidPageUID"),
    ("BidTypGroupViews", "BidUID"),
    ("BidTypicalGroupTotals", "BidPageUID"),
    ("BidTypicalGroupTotals", "BidUID"),
    ("BidZones", "BidLayerUID"),
    ("BidZones", "BidUID"),
    ("Bids", "BidProjectUID"),
    ("Bids", "BidType"),
    ("Bids", "ParentBidUID"),
    ("CdnTypes", "Name"),
    ("ConditionSetStyles", "ConditionSetUID"),
    ("ConditionSetStyles", "ConditionStyleUID"),
    ("ConditionSets", "EmployeeUID"),
    ("DPCCalcFilter", "BidUID"),
    ("Employees", "AccessLevelUID"),
    ("Employees", "LoginName"),
    ("Employees", "PayClassUID"),
    ("STSTransactionHistory", "ChangeType"),
    ("STSTransactionHistory", "ObjectUID"),
    ("UserMasterConditions", "Name"),
]
_FK_RELATIONSHIPS = [
    ("Employees", "AccessLevelUID", "AccessLevels", "UID"),
    ("BidPageSettings", "BidAreaUID", "BidAreas", "UID"),
    ("BidTakeoffs", "BidAreaUID", "BidAreas", "UID"),
    ("BidTimeCards", "BidAreaUID", "BidAreas", "UID"),
    ("BidTypAreaCounts", "BidAreaUID", "BidAreas", "UID"),
    ("BidConditions", "BidConditionFolderUID", "BidConditionFolders", "UID"),
    ("BidLaborActivity", "BidConditionUID", "BidConditions", "UID"),
    ("BidTakeoffs", "BidConditionUID", "BidConditions", "UID"),
    ("ConditionSetStyles", "ConditionStyleUID", "BidConditions", "UID"),
    ("BidTimeCards", "BidEmployeeUID", "BidEmployees", "UID"),
    ("BidLaborActivity", "BidLaborCostCodeUID", "BidLaborCostCodes", "UID"),
    ("BidPercents", "BidLaborCostCodeUID", "BidLaborCostCodes", "UID"),
    ("BidTimeCards", "BidLaborCostCodeUID", "BidLaborCostCodes", "UID"),
    ("BidCallOuts", "BidLayerUID", "BidLayers", "UID"),
    ("BidConditions", "BidLayerUID", "BidLayers", "UID"),
    ("BidHighlights", "BidLayerUID", "BidLayers", "UID"),
    ("BidHotLinks", "BidLayerUID", "BidLayers", "UID"),
    ("BidTexts", "BidLayerUID", "BidLayers", "UID"),
    ("BidZones", "BidLayerUID", "BidLayers", "UID"),
    ("BidHotLinks", "BidPageViewUID", "BidNamedViews", "UID"),
    ("BidPages", "BidPageFolderUID", "BidPageFolders", "UID"),
    ("BidALines", "BidPageUID", "BidPages", "UID"),
    ("BidAnnoInk", "BidPageUID", "BidPages", "UID"),
    ("BidArrows", "BidPageUID", "BidPages", "UID"),
    ("BidCallOuts", "BidPageUID", "BidPages", "UID"),
    ("BidDimensions", "BidPageUID", "BidPages", "UID"),
    ("BidHighlights", "BidPageUID", "BidPages", "UID"),
    ("BidHotLinks", "BidPageUID", "BidPages", "UID"),
    ("BidLegends", "BidPageUID", "BidPages", "UID"),
    ("BidNamedViews", "BidPageUID", "BidPages", "UID"),
    ("BidPageSettings", "BidPageUID", "BidPages", "UID"),
    ("BidSettings", "BidPageSelectedUID", "BidPages", "UID"),
    ("BidTakeoffTotals", "BidPageUID", "BidPages", "UID"),
    ("BidTakeoffs", "BidPageUID", "BidPages", "UID"),
    ("BidTexts", "BidPageUID", "BidPages", "UID"),
    ("BidTypicalGroupTotals", "BidPageUID", "BidPages", "UID"),
    ("Bids", "BidProjectUID", "BidProjects", "UID"),
    ("BidALines", "BidTakeoffFromUID", "BidTakeoffs", "UID"),
    ("BidArrows", "BidTakeoffFromUID", "BidTakeoffs", "UID"),
    ("BidDimensions", "BidTakeoffFromUID", "BidTakeoffs", "UID"),
    ("BidPercents", "BidTakeoffUID", "BidTakeoffs", "UID"),
    ("BidPercents", "BidTimeCardStateUID", "BidTimeCardStates", "UID"),
    ("BidTimeCards", "BidTimeCardStateUID", "BidTimeCardStates", "UID"),
    ("BidPageSettings", "BidTypAreaUID", "BidTypAreas", "UID"),
    ("BidTakeoffs", "BidTypAreaUID", "BidTypAreas", "UID"),
    ("BidTimeCards", "BidTypicalAreaUID", "BidTypAreas", "UID"),
    ("BidTypAreaCounts", "BidTypAreaUID", "BidTypAreas", "UID"),
    ("BidTakeoffs", "BidZoneUID", "BidZones", "UID"),
    ("BidALines", "BidUID", "Bids", "UID"),
    ("BidAreas", "BidUID", "Bids", "UID"),
    ("BidArrows", "BidUID", "Bids", "UID"),
    ("BidCallOuts", "BidUID", "Bids", "UID"),
    ("BidConditionFolders", "BidUID", "Bids", "UID"),
    ("BidConditions", "BidUID", "Bids", "UID"),
    ("BidDPCSubscribers", "BidUID", "Bids", "UID"),
    ("BidDimensions", "BidUID", "Bids", "UID"),
    ("BidEmployees", "BidUID", "Bids", "UID"),
    ("BidHighlights", "BidUID", "Bids", "UID"),
    ("BidHotLinks", "BidUID", "Bids", "UID"),
    ("BidLaborActivity", "BidUID", "Bids", "UID"),
    ("BidLaborCostCodes", "BidUID", "Bids", "UID"),
    ("BidLayers", "BidUID", "Bids", "UID"),
    ("BidLegends", "BidUID", "Bids", "UID"),
    ("BidNamedViews", "BidUID", "Bids", "UID"),
    ("BidNotes", "BidUID", "Bids", "UID"),
    ("BidPageFolders", "BidUID", "Bids", "UID"),
    ("BidPages", "BidUID", "Bids", "UID"),
    ("BidPlanRooms", "BidUID", "Bids", "UID"),
    ("BidTakeoffTotals", "BidUID", "Bids", "UID"),
    ("BidTexts", "BidUID", "Bids", "UID"),
    ("BidTimeCardStates", "BidUID", "Bids", "UID"),
    ("BidTransactionsHistory", "BidUID", "Bids", "UID"),
    ("BidTypAreas", "BidUID", "Bids", "UID"),
    ("BidTypicalGroupTotals", "BidUID", "Bids", "UID"),
    ("BidZones", "BidUID", "Bids", "UID"),
    ("BidConditions", "CdnTypeUID", "CdnTypes", "UID"),
    ("ConditionSetStyles", "ConditionSetUID", "ConditionSets", "UID"),
    ("BidLaborCostCodes", "CostCodeUID", "CostCodes", "UID"),
    ("BidDPCSubscribers", "BidEmployeeUID", "Employees", "UID"),
    ("BidEmployees", "EmployeeUID", "Employees", "UID"),
    ("ConditionSets", "EmployeeUID", "Employees", "UID"),
    ("BidEmployees", "PayClassUID", "PayClasses", "UID"),
    ("Employees", "PayClassUID", "PayClasses", "UID"),
]


class DatabaseCreator:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def create_database(self, db_path: Path, name: str) -> bool:
        db_path = Path(db_path)
        if db_path.exists():
            self._logger.error("Database already exists: %s", db_path)
            return False
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._create_blank_mdb(db_path)
            self._create_schema(db_path)
            self._insert_seed_data(db_path, name)
            return True
        except Exception as exc:
            self._logger.exception("Failed to create database %s: %s", db_path, exc)
            if db_path.exists():
                try:
                    db_path.unlink()
                except OSError:
                    pass
            return False

    def _create_blank_mdb(self, db_path: Path) -> None:
        vbs_script = (
            'Set cat = CreateObject("ADOX.Catalog")\n'
            f'cat.Create "Provider=Microsoft.ACE.OLEDB.12.0;'
            f'Data Source={db_path};Jet OLEDB:Engine Type=5;"\n'
            "Set cat = Nothing\n"
        )
        vbs_path = Path(tempfile.gettempdir()) / "ost_create_mdb.vbs"
        try:
            vbs_path.write_text(vbs_script, encoding="utf-8")
            result = subprocess.run(
                ["cscript", "//NoLogo", str(vbs_path)],
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
            if vbs_path.exists():
                vbs_path.unlink()

    def _create_schema(self, db_path: Path) -> None:
        conn_str = (
            "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};" f"DBQ={db_path};"
        )
        conn = pyodbc.connect(conn_str, autocommit=False)
        try:
            cursor = conn.cursor()
            for ddl in _TABLE_DDL:
                cursor.execute(ddl)
            for table, column in _FK_INDEXES:
                cursor.execute(
                    f"CREATE INDEX [{table}_{column}] " f"ON [{table}] ([{column}])"
                )
            cursor.execute("CREATE UNIQUE INDEX [UI_Locking2] ON [Locking] ([Essence])")
            cursor.execute(
                "CREATE UNIQUE INDEX [UI_Locking] " "ON [Locking] ([Essence], [Owner])"
            )
            for child, child_col, parent, parent_col in _FK_RELATIONSHIPS:
                cursor.execute(
                    f"ALTER TABLE [{child}] "
                    f"ADD CONSTRAINT [FK_{child}_{child_col}] "
                    f"FOREIGN KEY ([{child_col}]) "
                    f"REFERENCES [{parent}] ([{parent_col}])"
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _insert_seed_data(self, db_path: Path, name: str) -> None:
        conn_str = (
            "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};" f"DBQ={db_path};"
        )
        conn = pyodbc.connect(conn_str, autocommit=False)
        try:
            cursor = conn.cursor()
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
            conn.rollback()
            raise
        finally:
            conn.close()
