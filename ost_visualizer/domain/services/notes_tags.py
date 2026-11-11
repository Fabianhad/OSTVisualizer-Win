from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple, Union

FEET_PER_METRE = 1.0 / 0.3048
LENGTH_UNITS_HINT = "feet (a plain number, or a number with ft or m)"
_UNIT_FEET = {"ft": 1.0, "m": FEET_PER_METRE}
_NUMBER = r"\d+(?:\.\d+)?|\.\d+"
_LENGTH_RE = re.compile(rf"^({_NUMBER})(ft|m)?$")
_WHOLE_NUMBER_RE = re.compile(r"^\d+$")
_PERCENT_RE = re.compile(rf"^({_NUMBER})%$")
_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")
_NAME_RE = re.compile(r"^\s*([A-Za-z_]\w*)(.*)$", re.DOTALL)
_KEY_RE = re.compile(r"^[A-Za-z_]\w*$")
_ASSIGN_SPACING_RE = re.compile(r"\s*=\s*")
_VALUE_ENDS_IN_NUMBER_RE = re.compile(rf"=(?:{_NUMBER})$")
_TOKEN_RE = re.compile(r'[^\s,="\']+="[^"]*"|[^\s,="\']+=\'[^\']*\'|[^\s,]+')
_UNCLOSED_RE = re.compile(r"\[\s*([A-Za-z_]\w*)[^\[\]]*(?=\[|$)")


def parse_length_ft(text: str, *, bare_is_feet: bool = True) -> Optional[float]:
    match = _LENGTH_RE.match(str(text).strip().lower())
    if match is None:
        return None
    unit = match.group(2)
    if unit is None and not bare_is_feet:
        return None
    return float(match.group(1)) * _UNIT_FEET.get(unit, 1.0)


@dataclass(frozen=True)
class TagFraction:
    value: float


@dataclass(frozen=True)
class TagLength:
    feet: float


TagValue = Union[int, TagFraction, TagLength]


@dataclass(frozen=True)
class SectionsOrLength:
    pitch_ft: float
    noun: str = "sections"
    reach_base_ft: Optional[float] = None

    def parse(self, text: str) -> Optional[TagValue]:
        if _WHOLE_NUMBER_RE.match(text):
            return int(text)
        length = parse_length_ft(text, bare_is_feet=False)
        if length is None:
            return None
        return int(round((length - (self.reach_base_ft or 0.0)) / self.pitch_ft))

    def magnitude(self, value: TagValue) -> float:
        return float(value)

    def note(self, text: str, value: TagValue) -> Optional[str]:
        if _WHOLE_NUMBER_RE.match(text):
            return None
        if self.reach_base_ft is not None:
            reach = self.reach_base_ft + value * self.pitch_ft
            return f"{value} {self.noun} ({reach:.1f} ft reach)"
        return f"{value} {self.noun} ({value * self.pitch_ft:.1f} ft)"

    @property
    def expects(self) -> str:
        return f"a whole number of {self.noun}, or a length with ft or m"


@dataclass(frozen=True)
class PercentOrLength:
    def parse(self, text: str) -> Optional[TagValue]:
        percent = _PERCENT_RE.match(text.strip())
        if percent is not None:
            return TagFraction(float(percent.group(1)) / 100.0)
        length = parse_length_ft(text)
        return None if length is None else TagLength(length)

    def magnitude(self, value: TagValue) -> Optional[float]:
        return None

    def note(self, text: str, value: TagValue) -> Optional[str]:
        return None

    @property
    def expects(self) -> str:
        return f"a percentage, or a distance in {LENGTH_UNITS_HINT}"


@dataclass(frozen=True)
class Length:
    def parse(self, text: str) -> Optional[TagValue]:
        length = parse_length_ft(text)
        return None if length is None else TagLength(length)

    def magnitude(self, value: TagValue) -> float:
        return value.feet

    def note(self, text: str, value: TagValue) -> Optional[str]:
        return None

    @property
    def expects(self) -> str:
        return f"a length in {LENGTH_UNITS_HINT}"


ValueKind = Union[SectionsOrLength, PercentOrLength, Length]


@dataclass(frozen=True)
class KeySpec:
    name: str
    kind: ValueKind
    default_text: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    range_text: str = ""


@dataclass(frozen=True)
class TagSchema:
    name: str
    keys: Tuple[KeySpec, ...]

    def key(self, name: str) -> Optional[KeySpec]:
        folded = name.casefold()
        return next((key for key in self.keys if key.name == folded), None)


@dataclass(frozen=True)
class TagWarning:
    code: str
    key: str
    message: str


@dataclass(frozen=True)
class ParsedTag:
    present: bool = False
    values: Mapping[str, TagValue] = field(default_factory=dict)
    warnings: Tuple[TagWarning, ...] = ()
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedNotes:
    tags: Mapping[str, ParsedTag]
    warnings: Tuple[TagWarning, ...] = ()

    def tag(self, name: str) -> ParsedTag:
        return self.tags.get(name, ParsedTag())


def _tokens(arguments: str) -> Sequence[str]:
    tokens = []
    for token in _TOKEN_RE.findall(_ASSIGN_SPACING_RE.sub("=", arguments)):
        if (
            tokens
            and (token.lower() in _UNIT_FEET or token == "%")
            and _VALUE_ENDS_IN_NUMBER_RE.search(tokens[-1])
        ):
            tokens[-1] += token
        else:
            tokens.append(token)
    return tokens


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return "".join(value[1:-1].split())
    return value


def _parse_arguments(schema: TagSchema, arguments: str) -> ParsedTag:
    label = f"[{schema.name}]"
    values: Dict[str, TagValue] = {}
    warnings = []
    notes = []
    rejected = []
    for token in _tokens(arguments):
        raw_key, assigned, raw_value = token.partition("=")
        if not _KEY_RE.match(raw_key):
            warnings.append(
                TagWarning(
                    "unexpected_text",
                    "",
                    f'{label}: "{token}" is not a key=value argument and is ignored.',
                )
            )
            continue
        key = schema.key(raw_key)
        if key is None:
            known = ", ".join(spec.name for spec in schema.keys)
            warnings.append(
                TagWarning(
                    "unknown_key",
                    raw_key.casefold(),
                    f'{label}: unknown key "{raw_key}" is ignored (keys: {known}).',
                )
            )
            continue
        if key.name in values:
            warnings.append(
                TagWarning(
                    "duplicate_key",
                    key.name,
                    f"{label}: {key.name} is given more than once; "
                    "the first valid value is used.",
                )
            )
            continue
        raw_value = _unquote(raw_value.strip())
        value = key.kind.parse(raw_value)
        if not assigned or value is None:
            rejected.append(
                (
                    len(warnings),
                    "bad_value",
                    key,
                    f"{label}: {token} is not {key.kind.expects}",
                )
            )
            warnings.append(
                TagWarning(
                    "bad_value",
                    key.name,
                    f"{label}: {token} is not {key.kind.expects}; "
                    f"using {key.default_text}.",
                )
            )
            continue
        magnitude = key.kind.magnitude(value)
        if magnitude is not None and (
            (key.minimum is not None and magnitude < key.minimum)
            or (key.maximum is not None and magnitude > key.maximum)
        ):
            rejected.append(
                (
                    len(warnings),
                    "out_of_range",
                    key,
                    f"{label}: {token} is outside {key.range_text}",
                )
            )
            warnings.append(
                TagWarning(
                    "out_of_range",
                    key.name,
                    f"{label}: {token} is outside {key.range_text}; "
                    f"using {key.default_text}.",
                )
            )
            continue
        values[key.name] = value
        note = key.kind.note(raw_value, value)
        if note:
            notes.append(f"{label}: {token} \u2192 {note}.")
    for index, code, key, message in rejected:
        if key.name in values:
            warnings[index] = TagWarning(code, key.name, f"{message}; it is ignored.")
    return ParsedTag(True, values, tuple(warnings), tuple(notes))


def _looks_like_tag(arguments: str) -> bool:
    return any(
        "=" in token and _KEY_RE.match(token.partition("=")[0])
        for token in _tokens(arguments)
    )


def parse_notes_tags(notes: str, schemas: Sequence[TagSchema]) -> ParsedNotes:
    text = str(notes or "")
    by_name = {schema.name: schema for schema in schemas}
    tags: Dict[str, ParsedTag] = {}
    first_tag_at: Dict[str, int] = {}
    warnings = []
    for match in _BRACKET_RE.finditer(text):
        named = _NAME_RE.match(match.group(1))
        if named is None:
            continue
        name = named.group(1).casefold()
        schema = by_name.get(name)
        if schema is None:
            if _looks_like_tag(named.group(2)):
                known = ", ".join(f"[{known_name}]" for known_name in by_name)
                warnings.append(
                    TagWarning(
                        "unknown_object",
                        name,
                        f"[{named.group(1)} ...] is not a known tag (known: {known}).",
                    )
                )
            continue
        if name in tags:
            warnings.append(
                TagWarning(
                    "multiple_tags",
                    name,
                    f"More than one [{name}] tag; the first one is used.",
                )
            )
            continue
        tags[name] = _parse_arguments(schema, named.group(2))
        first_tag_at[name] = match.start()
    reported = set()
    for unclosed in _UNCLOSED_RE.finditer(text):
        name = unclosed.group(1).casefold()
        if name not in by_name or name in reported:
            continue
        if name not in tags or unclosed.start() < first_tag_at[name]:
            reported.add(name)
            warnings.append(
                TagWarning(
                    "unclosed_tag",
                    name,
                    f'[{name} is missing its closing "]" and is ignored.',
                )
            )
    return ParsedNotes(tags, tuple(warnings))
