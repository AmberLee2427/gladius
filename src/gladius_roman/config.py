"""Validated, versioned run configuration. Relative paths belong to the YAML file."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from astropy.time import Time
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveInt = Annotated[int, Field(strict=True, gt=0)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class Options(BaseModel):
    """Reject misspelled keys instead of silently choosing defaults."""

    model_config = ConfigDict(extra="forbid", validate_default=True, frozen=True)


class Target(Options):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    ra: Annotated[float, Field(ge=0, lt=360, allow_inf_nan=False)] | None = None
    dec: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)] | None = None
    x: FiniteFloat | None = None
    y: FiniteFloat | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coordinate_pair(self):
        sky = self.ra is not None and self.dec is not None
        pix = self.x is not None and self.y is not None
        if (
            sky == pix
            or (sky and (self.x is not None or self.y is not None))
            or (pix and (self.ra is not None or self.dec is not None))
        ):
            raise ValueError(
                "Supply exactly one complete pair: ra/dec (ICRS degrees) or x/y (0-based)"
            )
        return self


class Inputs(Options):
    mode: Literal["directory", "mast"] = "directory"
    directory: Path | None = Path("images")
    pattern: str = "*_cal.asdf"
    recursive: bool = False
    mast_criteria: dict[str, Any] = Field(default_factory=dict)
    mast_radius_arcmin: Annotated[float, Field(gt=0, le=30, allow_inf_nan=False)] = 6.0
    product_suffix: str = "_cal"
    product_filename: str | None = None
    query_limit: PositiveInt = 50000

    @model_validator(mode="after")
    def source(self):
        if self.mode == "directory" and self.directory is None:
            raise ValueError("directory input requires inputs.directory")
        if self.mode == "mast" and any(t in self.mast_criteria for t in ("token", "password")):
            raise ValueError("Use MAST_API_TOKEN in the environment, not YAML credentials")
        reserved = {"limit", "offset", "select_cols", "count_only"} & self.mast_criteria.keys()
        if reserved:
            raise ValueError(f"MAST criteria cannot override managed query options: {sorted(reserved)}")
        return self


class Selection(Options):
    start: str | None = None
    end: str | None = None
    detectors: list[Annotated[int, Field(strict=True, ge=1, le=18)]] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)

    @field_validator("start", "end", mode="before")
    @classmethod
    def timestamps(cls, value):
        if isinstance(value, datetime) and value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        if value is not None:
            # Normalize ISO UTC inputs; do not guess another time scale.
            value = str(value).removesuffix("Z")
            Time(value, scale="utc")
        return value

    @field_validator("filters")
    @classmethod
    def uppercase(cls, values):
        return [v.upper() for v in values]

    @model_validator(mode="after")
    def interval(self):
        if self.start and self.end and Time(self.start) >= Time(self.end):
            raise ValueError("selection.end must follow start; interval is [start, end) in UTC")
        if len(set(self.detectors)) != len(self.detectors):
            raise ValueError("detectors contains duplicates")
        return self


class Extraction(Options):
    size: PositiveInt = 150
    edge: Literal["pad", "strict"] = "pad"
    no_overlap: Literal["pad", "skip", "error"] = "pad"


class Astrometry(Options):
    mode: Literal["use", "validate", "corrected"] = "validate"
    corrected_directory: Path | None = Path("gaia_wcs")
    corrected_pattern: str = "{stem}_gaiawcs.asdf"
    roundtrip_tolerance_pixels: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 0.001
    fits_tolerance_pixels: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 0.01

    @model_validator(mode="after")
    def correction(self):
        if self.mode == "corrected" and self.corrected_directory is None:
            raise ValueError("corrected mode requires corrected_directory")
        # Do not permit a filename pattern to escape the correction directory.
        try:
            name = self.corrected_pattern.format(stem="example", filename="example.asdf")
        except (KeyError, ValueError) as exc:
            raise ValueError("corrected_pattern supports only {stem} and {filename}") from exc
        if Path(name).name != name:
            raise ValueError("corrected_pattern must produce a basename")
        return self


class Quality(Options):
    autocorrelation_limit: Annotated[float, Field(gt=1, allow_inf_nan=False)] | None = None
    tile_size: Annotated[int, Field(strict=True, ge=16, le=512)] = 64
    radius: Annotated[int, Field(strict=True, ge=2)] = 15
    exclude_from_stacks: bool = True

    @model_validator(mode="after")
    def radius_inside_tile(self):
        if self.radius >= self.tile_size // 2:
            raise ValueError("quality.radius must be less than half tile_size")
        return self


class Stacks(Options):
    enabled: bool = False
    max_exposures: Annotated[int, Field(strict=True, ge=0)] = 100
    max_memory_mb: Annotated[int, Field(strict=True, ge=0)] = 512


class Storage(Options):
    output_directory: Path = Path("cutouts")
    retain_full_images: bool = False
    formats: list[Literal["asdf", "fits"]] = Field(default_factory=lambda: ["asdf", "fits"])

    @field_validator("formats")
    @classmethod
    def output_formats(cls, values):
        if not values or len(set(values)) != len(values):
            raise ValueError("formats must be a nonempty list without duplicates")
        return values


class Execution(Options):
    resume: bool = True
    continue_on_error: bool = False
    lock_timeout_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0


class RunConfig(Options):
    """All settings recorded with a run, including resolved defaults."""

    schema_version: Literal[1] = 1
    targets: list[Target] = Field(min_length=1)
    inputs: Inputs = Field(default_factory=Inputs)
    selection: Selection = Field(default_factory=Selection)
    extraction: Extraction = Field(default_factory=Extraction)
    astrometry: Astrometry = Field(default_factory=Astrometry)
    quality: Quality = Field(default_factory=Quality)
    stacks: Stacks = Field(default_factory=Stacks)
    storage: Storage = Field(default_factory=Storage)
    execution: Execution = Field(default_factory=Execution)

    @model_validator(mode="after")
    def unique_targets(self):
        if len({t.id for t in self.targets}) != len(self.targets):
            raise ValueError("target IDs must be unique")
        if self.inputs.mode == "mast" and not any(t.ra is not None for t in self.targets):
            bounds = set(self.inputs.mast_criteria) - {"productLevel", "instrument_name", "radius"}
            if not bounds:
                raise ValueError("Pixel-only MAST targets require mast_criteria, e.g. a program ID")
        return self

    def resolved(self, base: Path) -> RunConfig:
        data = self.model_dump(mode="json")
        for section, key in (
            ("inputs", "directory"),
            ("astrometry", "corrected_directory"),
            ("storage", "output_directory"),
        ):
            value = data[section][key]
            if value is not None:
                data[section][key] = str((base / Path(value).expanduser()).resolve())
        return RunConfig.model_validate(data)


class UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader which refuses duplicate mapping keys."""


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def parse_config(text: str, *, base: Path, targets=None) -> RunConfig:
    """Validate YAML text, optionally replacing its targets before validation."""
    data = yaml.load(text, Loader=UniqueKeyLoader)
    if not isinstance(data, dict):
        raise ValueError("The YAML root must be a mapping")
    if targets is not None:
        data["targets"] = targets
    return RunConfig.model_validate(data).resolved(base)


def load_config(path: str | Path, *, targets_path: str | Path | None = None) -> RunConfig:
    """Load YAML, validate all options, and resolve paths relative to its location."""
    path = Path(path).expanduser().resolve()
    targets = None
    if targets_path is not None:
        from .targets import read_targets_csv

        targets = read_targets_csv(targets_path)
    return parse_config(path.read_text(), base=path.parent, targets=targets)
