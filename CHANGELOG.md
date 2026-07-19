# Changelog

This file records user-visible changes to Link. The project is currently in developer preview, so interfaces and local data schemas may still change between minor releases.

## [Unreleased]

## [0.2.1] - 2026-07-19

### Added

- LinkAgent menu-bar quick panel with device state, recent Codex sync, daily token usage, offline queue, and one-click sync.
- Daily Codex usage aggregation backed by a stable `usage` raw record.
- Repeatable private Alibaba Cloud ECS deployment and SSH tunnel scripts.
- Server-side proxy between Link Web and the independent crawler service.

### Changed

- Replaced the prototype build wrapper with a standard TanStack Start, Vite, React, Tailwind CSS, and Nitro Node production build.
- Moved the production container to Node.js 24 and a non-root runtime user.
- Updated the product and technical documents to describe the desktop companion and private-cloud boundary.

### Removed

- Removed Lovable-specific build configuration, runtime error hooks, and repository metadata.

## [0.2.0] - 2026-07-18

### Added

- Initial Link developer preview.
- Codex local-history intake through LinkAgent.
- Device pairing, heartbeat, incremental upload, offline batches, and source provenance browsing.
- Docker Compose stack for Link, PostgreSQL, and the independent web crawler.

[Unreleased]: https://github.com/Jo-Tsu/link/compare/v0.2.1-developer-preview...HEAD
[0.2.1]: https://github.com/Jo-Tsu/link/releases/tag/v0.2.1-developer-preview
[0.2.0]: https://github.com/Jo-Tsu/link/releases/tag/v0.2.0-developer-preview
