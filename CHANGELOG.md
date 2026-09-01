# Changelog

## [0.4.27] - 2026.09.01
### Fixed
- Prevent Rust panic when converting timed-out `fetch_requests` results.
- Return a complete empty response object for incomplete error results.
### Added
- Add timeout regression and reproduction tests for `fetch_single` and `fetch_requests`.

## [0.4.26] - 2026.08.10
### Fixed
- Honour per-request `timeout` values below 3 seconds instead of silently clamping them to 3s (#12)
### Added
- Regression tests for timeout behaviour
- Project docs: LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY
- Performance benchmark scripts and related CI

## [0.4.25] - 2025.09.25
### Added
- Improve `pyproject` configuration
- Update README

## [0.4.21] - 2025.09.23
### Added
- Add Python type stub files

## [0.4.20] - 2025.09.22
### Added
- Add `trust_env` to `ProxyConfig` to control whether environment variables are used
### Fixed
- Fix Windows installation failures

## [0.3.85] - 2025.09.15
### Added
- Option to enable or disable SSL certificate verification

## [0.3.83] - 2025.09.11
### Added
- Support specifying the HTTP protocol version for requests
- Add `http_version` parameter with full control: AUTO / HTTP1_ONLY / HTTP2 / HTTP2_PRIOR_KNOWLEDGE
### Changed
- Split and reorganise code structure
### Fixed
- Support username and password in proxy settings

## [0.3.65] - 2025-09-05
### Added
- Add proxy configuration support
### Optimized
- `set_debug` now supports both logging and console output
### Changed
- Add Chinese README

## [0.3.2] - 2025-08-11
### Changed
- Expand support for more Python versions to improve compatibility across systems and environments

## [0.3.0] - 2025-08-08
### Optimized
- Add `ConcurrencyMode` parameter to `fetch_requests`

## [0.2.8] - 2025-08-08
### Added
- Add `fetch_single` method
