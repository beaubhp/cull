use std::{fmt, str::FromStr};

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct TextRange {
    pub start: u32,
    pub end: u32,
}

impl TextRange {
    pub const fn new(start: u32, end: u32) -> Self {
        Self { start, end }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub struct PythonVersion {
    pub major: u8,
    pub minor: u8,
}

impl PythonVersion {
    pub const PY310: Self = Self {
        major: 3,
        minor: 10,
    };
    pub const PY311: Self = Self {
        major: 3,
        minor: 11,
    };
    pub const PY312: Self = Self {
        major: 3,
        minor: 12,
    };
    pub const PY313: Self = Self {
        major: 3,
        minor: 13,
    };
    pub const PY314: Self = Self {
        major: 3,
        minor: 14,
    };
    pub const PY315: Self = Self {
        major: 3,
        minor: 15,
    };

    pub const fn is_candidate_semantic_version(self) -> bool {
        self.major == 3 && self.minor >= 10 && self.minor <= 14
    }

    pub const fn is_forward_canary(self) -> bool {
        self.major == 3 && self.minor == 15
    }
}

impl Default for PythonVersion {
    fn default() -> Self {
        Self::PY314
    }
}

impl fmt::Display for PythonVersion {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}.{}", self.major, self.minor)
    }
}

impl FromStr for PythonVersion {
    type Err = PythonVersionParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let original = value.trim();
        let normalized = original.to_ascii_lowercase();
        let value = normalized
            .strip_prefix("python")
            .or_else(|| normalized.strip_prefix("py"))
            .unwrap_or(&normalized);
        let (major, minor) = if let Some((major, minor)) = value.split_once('.') {
            (major, minor)
        } else if value.len() >= 2 && value.bytes().all(|byte| byte.is_ascii_digit()) {
            value.split_at(1)
        } else {
            return Err(PythonVersionParseError(original.to_owned()));
        };
        let major = major
            .parse()
            .map_err(|_| PythonVersionParseError(original.to_owned()))?;
        let minor = minor
            .parse()
            .map_err(|_| PythonVersionParseError(original.to_owned()))?;
        Ok(Self { major, minor })
    }
}

#[derive(Debug, Error)]
#[error("invalid Python version `{0}`")]
pub struct PythonVersionParseError(String);

#[cfg(test)]
mod tests {
    use super::PythonVersion;

    #[test]
    fn parses_common_python_version_spellings() {
        for spelling in ["3.14", "py3.14", "python3.14", "py314", "python314"] {
            assert_eq!(
                spelling.parse::<PythonVersion>().unwrap(),
                PythonVersion::PY314
            );
        }
    }

    #[test]
    fn rejects_invalid_python_version_spellings() {
        assert!("py".parse::<PythonVersion>().is_err());
        assert!("three.fourteen".parse::<PythonVersion>().is_err());
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct DecodedSourceInfo {
    pub encoding: String,
    pub had_utf8_bom: bool,
}
