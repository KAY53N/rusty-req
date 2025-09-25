# Changelog

## [0.4.24] - 2025.09.25
### Added
- 完善pyproject
- 更新README

## [0.4.21] - 2025.09.23
### Added
- 添加Python类型存根文件

## [0.4.20] - 2025.09.22
### Added
- ProxyConfig增加trust_env参数，指定是否忽略环境变量
### Fixed
- Windows安装不成功问题修复

## [0.3.85] - 2025.09.15
### Added
- 指定是否对SSL证书验证

## [0.3.83] - 2025.09.11
### Added
- 增加指定请求的http协议版本
- 新增http_version参数支持，提供完整的HTTP协议版本控制，包括AUTO/HTTP1_ONLY/HTTP2/HTTP2_PRIOR_KNOWLEDGE选项
### Changed
- 代码结构拆分
### Fixed
- 代理设置的用户名和密码支持

## [0.3.65] - 2025-09-05
### Added
- 增加代理设置
### Optimized
- set_debug 方法增加日志记录和控制台输出两种方式
### Changed
- 中文README

## [0.3.2] - 2025-08-11
### Changed
- 这个版本扩展了对更多 Python 版本的支持，确保不同系统和环境的兼容性。


## [0.3.0] - 2025-08-08
### Optimized
- fetch_requests方法增加ConcurrencyMode参数

## [0.2.8] - 2025-08-08
### Added
- 增加fetch_single方法