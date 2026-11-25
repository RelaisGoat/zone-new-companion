# Changelog

All notable changes to zone-new-companion will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Non publié] — branche debug-connexions

### Interface
- Nouvelle interface en français : barre de navigation (Connexion, Chaînes, Films, Séries, Journal), thème sombre maison
- Page Connexion séparée des listes : coller un lien **ou** saisie manuelle, connexions récentes, fiche compte (statut, expiration, connexions actives/max avec alerte si la ligne est pleine, bouton Rafraîchir)
- Listes en grand avec logos des chaînes (récupérés depuis l'API, mis en cache), vue liste ou grille, recherche dans les catégories et dans les chaînes

### Connexion par lien
- Accepte get.php, player_api.php, xmltv.php, liens de chaîne (/live/…, /login/mdp/id), playlists .m3u et portails Stalker ; le serveur, l'identifiant et le mot de passe sont extraits automatiquement (les doubles slashs sont corrigés)

### Diagnostic de lecture
- VLC est lancé avec son propre journal, lu en direct : codes HTTP réellement reçus (401, 456, 302…), redirections, première image
- Explication en clair de chaque code et état de la ligne (connexions actives/max) avant le lancement
- Relance automatique de VLC si le serveur refuse (nombre réglable dans le Journal)
- Onglet Journal : filtre, recherche, copie, accès au dossier des logs

## [1.2.2] - 2026-05-09

### Fixed
- **GitHub Actions Workflow**: Fixed release automation
  - Added proper permissions for release creation
  - Replaced deprecated actions with modern alternatives
  - Workflow now builds all platforms in parallel
  - Fixed 'Resource not accessible by integration' error

### Changed
- **Version bump**: Incremented to v1.2.2 to trigger new release workflow

## [1.2.1] - 2026-05-09

### Fixed
- **OptimizedSession Integration**: Fixed all services to properly use OptimizedSession
  - Fixed xtream_service.py to use `self._session.get()` instead of `self._session.session.get()`
  - Fixed m3u_service.py to use `self._session.get()` instead of `self._session.session.get()`
  - Fixed stream_verifier.py to use `self._session.get()` instead of `self._session.session.get()`
  - All services now benefit from protocol rotation and SSL fallback logic

### Changed
- **Build System**: Replaced manual build scripts with GitHub Actions workflow
  - Removed build-win.py and build-unix.py
  - Created comprehensive BUILD.md with build instructions for all platforms
  - Created .github/workflows/build-release.yml for automated cross-platform builds
  - Automated builds for Windows (.exe), Linux (.AppImage), and macOS (.dmg)

### Removed
- **Distribution Packages**: Removed Chocolatey and Snap packaging
  - Removed DISTRIBUTION.md
  - Removed chocolatey/ folder (keeping for reference but not maintained)
  - Users should now build from source or use GitHub Releases

### Documentation
- Updated README.md to remove package manager installation instructions
- Added comprehensive build instructions in BUILD.md
- Updated SECURITY.md with correct email (kidpoleon@proton.me)
- Developer name updated to "Kidpoleon" consistently across files

## [1.2.0] - 2026-05-09

### Fixed
- **Stalker Stream URL**: Fixed missing stream ID parameter causing playback failures
  - Changed from `stream=&extension=ts` to `stream=1924348&extension=ts`
  - Reordered resolution strategies to prioritize cmd field from metadata
  - Added validation to ensure stream= parameter is not empty before accepting URL

### Added
- **Chocolatey Package**: Created full Chocolatey distribution package for Windows
  - Added nuspec manifest with VLC dependency
  - Created PowerShell install/uninstall scripts
  - Included LICENSE.txt and VERIFICATION.txt for embedded binary
- **Snap Package**: Created Snap distribution package for Linux
  - Added snapcraft.yaml with proper desktop integration
  - Created desktop entry for application menu
  - Configured strict confinement with necessary plugs
- **Enhanced VLC Detection**: Added more VLC path locations across all platforms
  - Windows: Microsoft Store VLC paths
  - macOS: Homebrew paths for both Apple Silicon and Intel
  - Linux: Additional system and user-local paths

### Changed
- **Credits**: Added acknowledgments to referenced projects
  - [IPTV-MAC-STALKER-PLAYER-BY-MY-1](https://github.com/peterpt/IPTV-CHECK) by peterpt
  - [stalkerhek](https://github.com/CrazeeGhost/stalkerhek/) by CrazeeGhost

### Documentation
- Added comprehensive DISTRIBUTION.md guide for package maintainers
- Documented Chocolatey and Snap publishing procedures

## [1.1.4] - 2026-05-08

### Added
- **Advanced M3U8 Verification**: Resolved issue where playable M3U8 streams showed as red/unverified
- **Enhanced HLS Detection**: Improved M3U8 playlist validation with comprehensive marker detection
- **OCR Integration**: Integrated OCR functionality for stream validation when FFprobe fails
- **Multi-Stage FFprobe**: Implemented 3-stage FFprobe analysis for M3U8 streams with fallback strategies
- **Adaptive Stream Support**: Better handling of adaptive bitrate streams and live content
- **Permissive Validation**: More lenient M3U8 validation that recognizes valid stream structures
- **OCR Frame Analysis**: Automatic frame capture and text analysis for content validation
- **Comprehensive Logging**: Detailed debug logging for verification troubleshooting

### Fixed
- M3U8 verification false negatives
- Stream verification accuracy issues
- SSL session usage across all services

### Improved
- Stream verification reliability
- M3U8 playlist parsing
- Error handling and logging

## [1.1.3] - 2026-05-08

### Added
- **M3U URL Compatibility**: Fixed issues reading problematic M3U URLs including short URLs and redirects
- **Optimized Session Integration**: M3U service now uses optimized SSL sessions for better compatibility
- **Enhanced Redirect Handling**: Better support for short URLs (s.id, bit.ly, tinyurl.com) with proper user agents
- **Alphabetical Sorting**: All categories and items now sort alphabetically across all services (M3U, Xtream, Stalker)
- **Improved UI/UX**: Enhanced visual feedback with alternating row colors and better tooltips
- **Table Sorting**: Enabled table sorting and improved visual styling with modern dark theme
- **Better Error Handling**: More robust M3U parsing with enhanced logging and error recovery
- **User Experience**: Improved tooltips, visual indicators, and overall application polish

### Fixed
- M3U service connection issues
- Sorting inconsistencies across services
- UI visual feedback problems

## [1.1.2] - 2026-05-08

### Added
- **Fixed False Negatives**: Resolved issue where playable channels showed as red/unverified
- **Optimized Session Usage**: Stream verifier now uses optimized SSL sessions for better compatibility
- **Enhanced Progress Reporting**: Terminal now shows detailed verification progress for each channel
- **Improved Fallback Logic**: Added secondary reachability checks with longer timeouts
- **Better Error Handling**: More permissive verification logic reduces false positives
- **Detailed Logging**: Individual channel status updates with progress percentages
- **Optimized FFprobe**: Improved stream analysis with better timeout handling
- **Permissive Verification**: Streams marked as OK if reachable even if A/V probe fails

### Fixed
- Verification false negatives
- SSL connection issues in verification
- Progress reporting problems

## [1.1.1] - 2026-05-08

### Added
- **OCR Service Integration**: Complete OCR service based on IPTV-CHECK project for video stream validation
- **FFmpeg Frame Extraction**: Automatic frame capture from video streams for content analysis
- **Tesseract OCR Engine**: Multi-language text recognition with error detection patterns
- **Advanced DNS Resolution**: Multiple DNS server fallback (Google, Cloudflare, OpenDNS, Quad9)
- **Enhanced Connectivity Testing**: Multiple endpoint testing for better server compatibility
- **Connection Diagnostics**: Comprehensive connection testing with detailed diagnostics
- **Complete Logs Removal**: Fully removed logs functionality from title bar and application
- **Performance Optimization**: Improved connection success rates through advanced strategies

### Fixed
- Logs functionality removal
- DNS resolution issues
- Connection reliability problems

## [1.1.0] - 2026-05-08

### Added
- **Multi-Profile SSL Handling**: 4 SSL configuration profiles (default, legacy, permissive, modern) for maximum compatibility
- **SSL Fallback Strategy**: Automatic fallback through different SSL configurations when connection fails
- **HTTP/HTTPS Protocol Rotation**: Automatic protocol switching with caching for optimal connection method
- **Comprehensive Cipher Support**: Support for legacy and modern cipher suites including `ALL:@SECLEVEL=0`
- **Connection Method Caching**: Remembers successful protocols per domain for faster subsequent connections
- **Enhanced Error Recovery**: Better SSL error handling with multiple retry strategies
- **Server-Specific Optimization**: Adaptive SSL configuration based on server response patterns

### Fixed
- SSL connection issues
- Protocol switching problems
- Connection timeout issues

## [1.0.9] - 2026-05-08

### Added
- **Network Optimizations**: 50x speed improvement in connection handling
- **DNS Resolution**: Enhanced DNS resolution with multiple servers
- **Connection Pooling**: Improved connection reuse and management
- **Timeout Optimization**: Better timeout handling for different server types

### Fixed
- Connection speed issues
- DNS resolution failures
- Connection pooling problems

## [1.0.8] - 2026-05-08

### Added
- **Initial Release**: Base functionality for Xtream and Stalker portal support
- **Unified UI**: Single interface for multiple IPTV portal types
- **Modular Architecture**: Clean separation of concerns
- **Cross-Platform Support**: Windows, Linux, and macOS compatibility
- **VLC Integration**: Automatic VLC detection and launch
- **Configuration Management**: Persistent settings and history
- **Async Operations**: Non-blocking UI with background workers

---

## [Unreleased]

### Planned
- Enhanced EPG support
- Custom themes and UI customization
- Advanced filtering and search
- Stream recording capabilities
- Mobile app companion
- Plugin system for extensibility

---

**Note:** For detailed information about each version, please refer to the release notes on GitHub.
