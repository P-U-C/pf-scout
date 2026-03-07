"""Rubric validation and loading for pf-scout.

This module provides functions to validate and load rubric YAML files.
A rubric defines dimensions, weights, and tier thresholds for scoring.
"""

from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Required rubric fields
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL = ["name", "dimensions"]
REQUIRED_DIMENSION_FIELDS = ["key"]
OPTIONAL_DIMENSION_FIELDS = ["label", "weight", "guide", "keywords", "description"]
OPTIONAL_TOP_LEVEL = ["version", "description", "tiers"]


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------

class RubricValidationError(Exception):
    """Raised when rubric validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Rubric validation failed: {'; '.join(errors)}")


def validate_rubric(path: str | Path) -> list[str]:
    """Validate a rubric YAML file.

    Checks for required fields, valid structure, and valid types.

    Args:
        path: Path to the rubric YAML file.

    Returns:
        List of validation errors (empty if valid).
    """
    errors = []
    path = Path(path)

    # Check file exists
    if not path.exists():
        return [f"Rubric file not found: {path}"]

    if not path.is_file():
        return [f"Path is not a file: {path}"]

    # Parse YAML
    try:
        with open(path) as f:
            rubric = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [f"Invalid YAML: {e}"]

    if not isinstance(rubric, dict):
        return ["Rubric must be a YAML mapping (dictionary)"]

    # Check required top-level fields
    for field in REQUIRED_TOP_LEVEL:
        if field not in rubric:
            errors.append(f"Missing required field: {field}")

    # Validate name
    if "name" in rubric:
        if not isinstance(rubric["name"], str):
            errors.append("'name' must be a string")
        elif not rubric["name"].strip():
            errors.append("'name' cannot be empty")

    # Validate version if present
    if "version" in rubric:
        v = rubric["version"]
        if not isinstance(v, (str, int, float)):
            errors.append("'version' must be a string or number")

    # Validate dimensions
    if "dimensions" in rubric:
        dims = rubric["dimensions"]
        if not isinstance(dims, list):
            errors.append("'dimensions' must be a list")
        elif len(dims) == 0:
            errors.append("'dimensions' cannot be empty")
        else:
            seen_keys = set()
            for i, dim in enumerate(dims):
                dim_errors = _validate_dimension(dim, i, seen_keys)
                errors.extend(dim_errors)

    # Validate tiers if present
    if "tiers" in rubric:
        tiers = rubric["tiers"]
        if not isinstance(tiers, list):
            errors.append("'tiers' must be a list")
        else:
            for i, tier in enumerate(tiers):
                tier_errors = _validate_tier(tier, i)
                errors.extend(tier_errors)

    return errors


def _validate_dimension(dim: Any, index: int, seen_keys: set) -> list[str]:
    """Validate a single dimension entry.

    Args:
        dim: The dimension dict to validate.
        index: Index in the dimensions list (for error messages).
        seen_keys: Set of already-seen dimension keys.

    Returns:
        List of validation errors.
    """
    errors = []
    prefix = f"dimensions[{index}]"

    if not isinstance(dim, dict):
        return [f"{prefix}: must be a mapping"]

    # Check required dimension fields
    for field in REQUIRED_DIMENSION_FIELDS:
        if field not in dim:
            errors.append(f"{prefix}: missing required field '{field}'")

    # Validate key
    if "key" in dim:
        key = dim["key"]
        if not isinstance(key, str):
            errors.append(f"{prefix}: 'key' must be a string")
        elif not key.strip():
            errors.append(f"{prefix}: 'key' cannot be empty")
        elif key in seen_keys:
            errors.append(f"{prefix}: duplicate key '{key}'")
        else:
            seen_keys.add(key)

    # Validate weight
    if "weight" in dim:
        weight = dim["weight"]
        if not isinstance(weight, (int, float)):
            errors.append(f"{prefix}: 'weight' must be a number")
        elif weight <= 0:
            errors.append(f"{prefix}: 'weight' must be positive")

    # Validate label
    if "label" in dim and not isinstance(dim["label"], str):
        errors.append(f"{prefix}: 'label' must be a string")

    # Validate keywords
    if "keywords" in dim:
        kw = dim["keywords"]
        if not isinstance(kw, list):
            errors.append(f"{prefix}: 'keywords' must be a list")
        elif not all(isinstance(k, str) for k in kw):
            errors.append(f"{prefix}: all keywords must be strings")

    return errors


def _validate_tier(tier: Any, index: int) -> list[str]:
    """Validate a single tier entry.

    Args:
        tier: The tier dict to validate.
        index: Index in the tiers list (for error messages).

    Returns:
        List of validation errors.
    """
    errors = []
    prefix = f"tiers[{index}]"

    if not isinstance(tier, dict):
        return [f"{prefix}: must be a mapping"]

    # Check required tier fields
    if "name" not in tier:
        errors.append(f"{prefix}: missing required field 'name'")
    elif not isinstance(tier["name"], str):
        errors.append(f"{prefix}: 'name' must be a string")

    # Require either min_pct or min_score
    has_threshold = "min_pct" in tier or "min_score" in tier
    if not has_threshold:
        errors.append(f"{prefix}: missing 'min_pct' or 'min_score'")

    if "min_pct" in tier:
        if not isinstance(tier["min_pct"], (int, float)):
            errors.append(f"{prefix}: 'min_pct' must be a number")
        elif not (0 <= tier["min_pct"] <= 1):
            errors.append(f"{prefix}: 'min_pct' must be between 0 and 1")

    if "min_score" in tier:
        if not isinstance(tier["min_score"], (int, float)):
            errors.append(f"{prefix}: 'min_score' must be a number")
        elif tier["min_score"] < 0:
            errors.append(f"{prefix}: 'min_score' must be non-negative")

    return errors


# ---------------------------------------------------------------------------
# Loading functions
# ---------------------------------------------------------------------------

def load_rubric(path: str | Path) -> dict:
    """Load and validate a rubric YAML file.

    Args:
        path: Path to the rubric YAML file.

    Returns:
        Parsed rubric dictionary with normalized structure.

    Raises:
        RubricValidationError: If validation fails.
        FileNotFoundError: If file doesn't exist.
    """
    path = Path(path)

    # Validate first
    errors = validate_rubric(path)
    if errors:
        raise RubricValidationError(errors)

    # Load and normalize
    with open(path) as f:
        rubric = yaml.safe_load(f)

    # Normalize dimensions
    normalized_dims = []
    for dim in rubric.get("dimensions", []):
        normalized_dims.append({
            "key": dim["key"],
            "label": dim.get("label", dim["key"]),
            "weight": dim.get("weight", 1),
            "description": dim.get("guide", dim.get("description", "")),
            "keywords": dim.get("keywords"),
        })

    # Normalize tiers (use defaults if not provided)
    tiers = rubric.get("tiers")
    if not tiers:
        tiers = [
            {"name": "🔴 Top Tier", "min_pct": 0.80, "description": "Strong prospect"},
            {"name": "🟡 Mid Tier", "min_pct": 0.60, "description": "Promising"},
            {"name": "⚪ Speculative", "min_pct": 0.0, "description": "Early signal"},
        ]

    return {
        "name": rubric.get("name", path.stem),
        "version": str(rubric.get("version", "1.0")),
        "description": rubric.get("description", ""),
        "dimensions": normalized_dims,
        "tiers": tiers,
    }


def get_rubric_name(path: str | Path) -> str:
    """Get the name from a rubric file without full validation.

    Args:
        path: Path to the rubric YAML file.

    Returns:
        Rubric name or filename stem if name not found.
    """
    path = Path(path)
    try:
        with open(path) as f:
            rubric = yaml.safe_load(f)
        return rubric.get("name", path.stem)
    except Exception:
        return path.stem
