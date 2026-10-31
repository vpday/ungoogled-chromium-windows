# Windows Optimizations & Curated Patches Reference

## 1. Windows Native Optimizations and Feature Overrides (`patches/ungoogled-chromium/windows/`)

### 1.1 `windows-common-optimizations.patch` (Target-Agnostic Toolchain & Linker Tuning)
- Compiler Optimization: Enables `-O3` globally for Clang and Rust in release builds.
- ThinLTO Code Generation: Runs ThinLTO backend optimization at Level 3 (`lldltocgo=3`).
- Fast Floating-Point Contraction: Enables `-ffp-contract=fast` across C/C++ and Rust to speed up WebGL, canvas, and math calculations.
- Libc++ Fast Hardening: Uses `_LIBCPP_HARDENING_MODE_FAST` to eliminate extensive runtime assertion overhead in release builds.
- Debug Symbol Hashing: Enables `/clang:-gcodeview-ghash` to accelerate PDB generation and link-time deduplication.
- Warning Suppression: Suppresses non-critical warnings (`-Wno-deprecated-attributes`, `-Wno-nonportable-include-path`).

### 1.2 `windows-x64-optimizations.patch` (Target-Specific x64 AVX2 / ISA Acceleration)
*Applies to: `x64` (dynamically injected at build time)*
- Discrete AVX2/ISA Flags: Sets an AVX2 baseline via discrete flags rather than a monolithic `-march=x86-64-v3`, preserving runtime dynamic dispatch modules (such as Skia's AVX-512 code paths).
- Gather/Scatter Avoidance: Disables gather and scatter instructions in C/C++ and Rust to prevent latency regressions on CPUs with slow microcode implementations.

### 1.3 `windows-additional-feature-overrides.patch` (Feature Overrides & Background De-bloating)
- Client AI & On-Device ML: Disables the Desktop AI assistant (Glic), Private AI, DevTools AI code features, and history passage embeddings.
- Speculative Networking & Preloading: Disables bookmark and NTP Prerender2, Navigation Predictor, Top Chrome WebUI preloading, and speculative ServiceWorker warm-up.
- Process De-bloating: Disables persistent spare renderer processes for the default search engine.
- Telemetry & Metrics: Disables Structured Metrics, Critical User Journeys, Notification Telemetry, cold-start OneDrive sync state probing (`kCloudSyncedFolderChecker`), and BrowserContext-bound digital credentials service instantiation.
- Performance & Memory Tuning: Locks background tab freezing under critical memory pressure (`kDisablePeriodicUnfreezeOnCriticalMemoryPressure`) and boosts closing tab priority (`kBoostClosingTabs`) for smoother tab strip animations.
- Security & UI Settings: Enables strict origin isolation and network service sandboxing; enables one-click tab audio muting and modern WebUI refresh.

### 1.4 `windows-multiple-search-engines-context-menu.patch` (Multi-Engine Context Menu Search)
- Multi-Engine Context Menu Search: Reads configured search engines from browser settings when text is selected on a webpage, showing multiple "Search with <Engine>" options in the right-click menu.
- Adaptive Menu Layout: Displays up to 4 search engines directly in the context menu, automatically folding additional engines into a "More search engines" submenu to keep the menu compact.
- Configuration (Disabled by default):
  - `chrome://flags`: Set `#enable-multiple-search-engines-context-menu` ("Show more search engines in context menu") to `Enabled` (or `Default` to disable).
  - Command Line: Add `--enable-multiple-search-engines-context-menu` to enable; omit to keep disabled.

### 1.5 `windows-disable-digital-credentials.patch` (W3C Digital Credentials Downgrade)
- Digital Identity Credentials: Sets `WebIdentityDigitalCredentials` and `WebIdentityDigitalCredentialsCreation` to experimental status in `runtime_enabled_features.json5`, preventing websites from triggering Google Optimization Guide low-friction whitelist requests.

### 1.6 `windows-disable-jumplist-history.patch` (Taskbar JumpList Privacy Protection)
- Taskbar History Leak Prevention: Disables writing "Most Visited" and "Recently Closed" URLs and favicon icons to the Windows JumpList in `jumplist.cc`, keeping Windows taskbar shortcuts stateless (e.g. New Window, Incognito Window) and preventing unencrypted OS-level browsing history leaks.

### 1.7 `windows-normalize-user-agent-platform-version.patch` (High-Entropy Windows Version Masking)
- Platform Version Normalization: Returns a fixed `"10.0.0"` in `GetWindowsPlatformVersion()` within `user_agent_utils.cc`, preventing Client Hints from leaking granular Windows OS contract/build versions.

### 1.8 `windows-disable-antivirus-metrics-provider.patch` (Antivirus WMI & Subprocess Pruning)
- Antivirus Telemetry Pruning: Removes `GoogleUpdateMetricsProviderWin` and `AntiVirusMetricsProvider` registration in `chrome_metrics_service_client.cc`, eliminating unnecessary WMI queries to `root\SecurityCenter2` and utility worker process launches on startup.

### 1.9 `windows-disable-pepc-elements.patch` (PEPC HTML Declarative Permission Elements Hardening)
- PEPC Element Deactivation: Disables `<camera>`, `<microphone>`, `<geolocation>`, and `<usermedia>` in-page permission elements (`CameraAndMicrophoneElements`, `GeolocationElement`, `UserMediaElement`, and `UserMediaElementLegacy` in `runtime_enabled_features.json5`), preventing clickjacking and anchor-based permission elevation while routing all hardware prompts through the trusted Omnibox origin bubble.

### 1.10 `windows-disable-ai-page-content-tracking.patch` (Render-Side Password and Subframe Tracking Cutoff)
- AI Page Content Tracking Deactivation: Disables `AIPageContentTrackedElementsPassword` and `AIPageContentTrackedElementsIframe` in `runtime_enabled_features.json5`, eliminating unnecessary per-frame heuristic password box coordinate tracking and compositor frame metadata serialization.

### 1.11 `windows-disable-webrtc-diagnostic-logging.patch` (WebRTC Diagnostic Logging Interface Deactivation)
- WebRTC Diagnostic Logging Blocking: Clears the default desktop status of `RTCDiagnosticLogging` in `runtime_enabled_features.json5`, removing `startDiagnosticLogging` and `stopDiagnosticLogging` extensions from `RTCPeerConnection` to eliminate client fingerprinting surfaces and unused Mojo IPC channels.

### 1.12 `windows-hide-navigator-webdriver.patch` (Navigator WebDriver Automation Detection Mitigation)
- WebDriver Property Suppression: Adds `kHideNavigatorWebDriver` feature in `features.h/cc`. When enabled, `Navigator::webdriver()` immediately returns `false` at the Blink entry point, neutralizing both static automation flags and CDP dynamic emulation overrides (`probe::ApplyAutomationOverride`).

### 1.13 `windows-spoof-webgpu-adapter-info.patch` (WebGPU Adapter Information & WebGL Linkage)
- WebGPU Adapter Spoofing: Extends `GPUAdapter::CreateAdapterInfoForAdapter()` in `gpu_adapter.cc` to synchronize with `kSpoofWebGLInfo`. Maps GPU vendor and microarchitecture tokens (e.g. `nvidia` -> `maxwell`/`ampere`, `intel` -> `gen-12lp`, `amd` -> `rdna-2`) to eliminate contradictions between WebGL and WebGPU hardware disclosures.

### 1.14 `windows-deterministic-canvas-noise.patch` (Deterministic Canvas Edge Noise & Readout Alignment)
- Deterministic Edge Anti-Aliasing Noise: Replaces Bromite's random pixel mutation with a deterministic FNV-1a hash applied only to edge gradient pixels. Skips transparent and 4-neighbor identical solid color blocks to defeat pure-color trap tests. Pre-noises `CanvasAsyncBlobCreator` to guarantee identical pixel hashes across `toDataURL()`, `toBlob()`, and `getImageData()`.

### 1.15 `windows-spoof-webgl-params.patch` (WebGL Extended Parameter Table & ReadPixels Edge Noise)
- WebGL Parameter Interception & Readback Noise: Intercepts over 80 GL parameter enums in `getParameter()` via a static lookup table (`kSpoofedGlIntParams`) when `kSpoofWebGLInfo` is enabled. In `ReadPixelsHelper`, applies deterministic edge noise while preserving solid color geometries.

### 1.16 `windows-timezone-sandbox.patch` (Independent Renderer Timezone Sandbox & IPC Whitelist)
- Per-Process Timezone Sandboxing: Registers `--timezone` in `content_switches.h/cc` and `render_process_host_impl.cc`'s renderer switch propagation whitelist. In `TimeZoneController::Init()`, sets the virtual host timezone and returns early to prevent asynchronous host OS clock updates from overwriting the sandboxed timezone, while preserving CDP `Emulation.setTimezoneOverride` capabilities.

### 1.17 `windows-permissions-consistency.patch` (Permissions and Notifications State Consistency)
- Undecided State Alignment: Synchronizes `Notification.permission` and `navigator.permissions.query({name: 'notifications'})` in undecided states (`ASK`) via `--notifications-permission`. Enforces strict `DENIED` status in cross-origin iframes to eliminate Headless discrepancy signals.

### 1.18 `windows-font-fallback-filter.patch` (System Font Fallback Blacklist Filtering)
- Font Enumeration Defense: Blocks blacklisted font queries in `FontCache::GetFontPlatformData()` via `--font-blacklist` and `--fonts-hidden`, while safeguarding standard CSS generic font families (`serif`, `sans-serif`, `monospace`, `system-ui`, etc.) to prevent layout collapse.

### 1.19 `windows-media-devices-limit.patch` (Narrowing-Only Media Device Enumeration Truncation)
- Media Device Count Truncation: Caps the number of enumerated audio/video devices via `--limit-media-devices` without fabricating non-existent devices, preserving Chromium's native salted `deviceId` hashing to ensure `getUserMedia()` compatibility.

### 1.20 `windows-speech-voices-narrow.patch` (Speech Synthesis Voice Truncation & Localized Aliases)
- Voice List Narrowing: Limits returned voices in `speechSynthesis.getVoices()` via `--limit-speech-voices` and `--speech-voices`, with built-in mapping for localized Windows Chinese voice names.

### 1.21 `windows-geolocation-override.patch` (Smooth Continuous Virtual Geolocation Provider)
- Continuous Natural Geolocation: Implements `VirtualLocationProvider` via `--geolocation=lat,lng` in `chrome_content_browser_client.cc`, supplying smooth continuous sensor micro-drifts (~10cm) with advancing timestamps to resolve CDP static timestamp freeze tells, while forwarding all anti-fingerprint CLI switches to renderer child processes.

## 2. Curated Brave Patches (`patches/brave/`)

### 2.1 Resource De-bloating & AI Pruning
- `disable-web-platform-ai.patch`: Disables Web Platform AI APIs (`AIPromptAPI`, `AIPromptAPIMultimodalInput`, `AIProofreaderAPI`, `AIRewriterAPI`, `AISummarizationAPI`, and `AIWriterAPI` in `runtime_enabled_features.json5`), preventing web pages from downloading or running on-device AI models.
- `disable-history-embeddings.patch`: Sets `kEnabledByDefaultForDesktopOnly` to `false` in `history_embeddings_utils.cc`, disabling passage embedding generation on browsing history.
- `consolidated-features-overrides.patch`: Disables bookmark and New Tab Page Prerender2 triggers, DevTools Console Insights, DevTools AI code features, WebUI Omnibox Popups, and tab hover card thumbnail previews.
- `kill-profile-reset-report-uploader.patch`: Empties `ResetReportUploader::DispatchReport` in `chrome/browser/profile_resetter/reset_report_uploader.cc` to stop telemetry uploads when resetting browser profiles.

### 2.2 System Security & Process Hardening
- `crashpad-prune-win-environment-block.patch`: Removes the PEB environment variable block from Crashpad minidumps on Windows so tokens and environment variables do not leak into crash reports.
- `fsa-restrict-to-opfs.patch`: Restricts the File System Access (FSA) API to the Origin Private File System (OPFS) sandbox in `file_system_access_handle_base.cc`, blocking websites from requesting access to arbitrary host directories.
- `defer-permission-prompts-to-load.patch`: Defers permission prompts in `permission_request_manager.cc` until the main page finishes loading, preventing clickjacking while the page is still rendering.

### 2.3 Tab Management & Desktop Ergonomics
- `tab-close-button-threshold.patch`: Lowers the close button width threshold in `chrome/browser/ui/views/tabs/tab.h` from 82px to 55px, preventing accidental tab closures when many tabs are open.
- `pip-allow-full-window-size.patch`: Removes the maximum size cap in `video_overlay_window_views.cc`, allowing Picture-in-Picture windows to be resized freely across the screen.
- `download-context-menu-actions.patch`: Adds "Copy Download Link" and "Show in folder" actions to the download bubble context menu.
- `suppress-undo-tab-close-toast.patch`: Suppresses the "Undo closed tab" snackbar notification in `browser_commands.cc`.
- `hide-cookie-controls-location-bar-icon.patch`: Hides the third-party cookie blocking icon from the omnibox.
- `disable-global-signin-promos.patch`: Disables the first-run account selection screen and desktop sign-in promotional banners.

## 3. Curated Helium Patches (`patches/helium/`)

### 3.1 Memory Conservation & Cold Startup Acceleration
- `memory-saving-by-default.patch`: Enables Chromium's Memory Saver by default in `prefs.cc` to discard idle background tabs automatically.
- `lazy-session-restore.patch`: Enables lazy session restore in `browser_tabrestore.h`; only the active tab loads on startup, while background tabs remain unloaded until clicked.
- `infinite-tab-freezing.patch`: Removes background tab freezing timeouts in `components/performance_manager/features.cc`, keeping idle tabs frozen indefinitely without periodic background wakeups.
- `hibernate-tab-context-menu.patch`: Adds a "Hibernate Tab" option to the tab context menu to discard individual tabs manually.

### 3.2 Display Energy Efficiency & Subpixel Rendering
- `add-low-power-framerate-flag.patch`: Adds a flag to cap rendering framerate, saving battery on high-refresh-rate (120Hz+) screens.
- `dont-antialias-rects.patch`: Disables non-antialiased rectangle draws in `ui/views/view.cc` under fractional scaling (125%, 150%, etc.), fixing visible seam lines and subpixel jitter.
- `disable-ink-ripple-effect.patch`: Removes the Material Design ink ripple animation in `platform_style.h` for faster, click-responsive UI feedback.

### 3.3 Privacy, Degoogling & Network Layer Hardening
- `split-clienthello.patch`: Randomly splits TLS ClientHello packets in BoringSSL, helping resist TLS fingerprinting and bypass SNI-based blocking.
- `spoof-chrome-ua-brand.patch`: Replaces Google Chrome brand tokens with generic identifiers in Client Hints (`user_agent_utils.cc`).
- `reduce-accept-language-headers.patch`: Trims the `Accept-Language` request header to a minimal format, reducing language-based fingerprinting.
- `disable-ad-topics-and-etc.patch`: Disables Privacy Sandbox tracking features, including the Topics API and Private Aggregation, in `network::features`.
- `disable-history-clusters.patch`: Disables History Clusters (Journeys) grouping and background analysis.
- `clean-omnibox-suggestions.patch`: Removes Google promotional action buttons ("pedals") from omnibox suggestions.
- `ridiculous-google-compat-exceptions.patch` & `degoogle-context-menu.patch`: Removes hardcoded Google sign-in exceptions and unhooks Google Search / Google Lens from context menus.

### 3.4 Ergonomics & Web Content Control
- `shift-right-click-context-menu.patch`: Forces the browser's native context menu to open on `Shift + Right-Click`, bypassing pages that block right-clicking.
- `force-paste-action.patch`: Forces paste actions to work in input fields that attempt to block clipboard pasting.
- `close-tabs-to-left.patch`: Adds a "Close tabs to the left" option to the tab context menu.
- `open-new-tabs-next-to-active-tab-option.patch`: Adds a flag to open new tabs directly next to the active tab rather than at the end of the tab strip.
- `disable-user-education-nags.patch`: Suppresses feature tutorial popups, prompts, and promo bubbles.
- `disable-outdated-build-detector.patch`: Disables the yellow "Chrome is out of date" warning banner.
- `disable-annoying-infobars.patch`: Removes the infobar shown when viewing PDFs and disables the startup foreground launch infobar.
- `disable-fedcm-bubble.patch`: Disables FedCM third-party account selection prompt bubbles.
- `add-more-zoom-presets.patch`: Adds more zoom percentage steps in `page_zoom.cc`.
- `center-window-on-launch.patch`: Centers the browser window on the screen on its first launch.
- `hide-page-actions-flag.patch`: Adds a flag to hide page action icons in the location bar.
- `hide-pip-live-caption-button.patch` & `disable-live-caption-completely.patch`: Hides the Live Caption toggle in Picture-in-Picture windows and removes the Live Caption background service and model downloader.
- `disable-non-standard-auth-features.patch`: Disables non-standard web authentication features (including `kFedCmDelegation`).

## 4. Curated Cromite Patches (`patches/cromite/`)

### 4.1 Anti-Fingerprinting & Hardware Masking
- `AudioBuffer-AnalyserNode-fp-mitigations.patch`: Adds deterministic FNV-1a hash perturbation (controlling delta < 2.55e-5) to WebAudio buffers and `AnalyserNode` outputs based on sample index, with strict 0Hz silence protection (`data == 0.0f`) to prevent audio hardware fingerprinting without non-deterministic hash drift across repeated offline renders.
- `High-Resolution-Timing-Mitigation.patch`: Clamps performance timer resolution with jitter in `time_clamper.cc`, protecting against timing-based side-channel attacks and execution profiling.
- `Fonts-fingerprinting-mitigation.patch`: Restricts local system font enumeration in Blink to limit font-based tracking.
- `Media-fingerprinting-mitigations.patch`: Restricts video decoder capability enumeration in WebCodecs (`isConfigSupported`) to prevent hardware codec fingerprinting.
- `Reduce-input-capability-fingerprinting-through-normalization.patch`: Normalizes reported mouse, pen, and touch capabilities in `pointer_device_win.cc`.
- `Disable-support-for-pointer-device-id.patch`: Disables stylus pen device ID reporting in `pen_id_handler.cc`.
- `Keyboard-protection-flag.patch`: Adds a flag to block `navigator.keyboard.getLayoutMap()` from enumerating physical keyboard layouts.
- `Remove-support-for-device-memory-and-cpu-recovery.patch`: Removes `navigator.deviceMemory` reporting and limits hardware concurrency probing.
- `Set-caret-blink-interval-to-default.patch`: Uses a fixed caret blink interval in `web_view_impl.cc` to prevent cursor timing fingerprinting.
- `Disable-Posture-API.patch`, `Disable-Device-Attributes-API.patch`, `Disable-Viewport-Segments.patch`: Disables foldable screen posture, device attribute, and viewport segment APIs.
- `Disable-idle-detection.patch`: Disables the Blink Idle Detection API.
- `Disable-visited-pseudo-class.patch`: Prevents CSS `:visited` styles from being queried for browsing history sniffing.
- `Disable-conversion-measurement-api.patch`: Disables the Attribution Reporting API.
- `Disable-css-preferred-text-scale.patch`, `Disable-prefers-reduced-transparency-media-query.patch`, `Disable-CSSDynamicRangeLimit.patch`: Disables non-essential CSS media queries used for browser fingerprinting.
- `Add-a-flag-to-disable-GamePad-API.patch`: Adds a flag to disable the Gamepad API.
- `Disable-Web-Bluetooth-by-default-in-desktop-platforms.patch`: Disables Web Bluetooth by default.
- `Partition-MediaDeviceId-by-default.patch`: Partitions media device IDs per origin to stop cross-site device correlation.
- `Override-Navigator-Language.patch`: Allows overriding `navigator.language` to mask the real system locale.

### 4.2 Resource Teardown & Isolation
- `Immediately-destroy-shared-workers-when-closing-the-page.patch`: Shuts down Shared Workers in `shared_worker_host.cc` as soon as the last connected page closes, freeing memory right away.
- `Keep-ComputePressure-disabled.patch`: Keeps the Compute Pressure API disabled so websites cannot poll CPU load states.
- `Keep-disabled-CpuPerformance.patch`: Disables the CPU performance benchmarking API.
- `Keep-disabled-FetchLaterAPI.patch`: Disables the `fetchLater()` API to stop pages from scheduling delayed network requests after being closed.
- `Lock-Profile-Cookie-Database.patch`: Acquires an exclusive lock on the SQLite cookie database in `profile_network_context_service.cc`, preventing other programs from reading active session cookies.
- `Remove-window-name-on-cross-origin-navigation.patch`: Clears `window.name` on cross-origin navigations to break cross-site tracking via window properties.
- `Clear-CORS-Preflight-Cache-on-clearing-data.patch`: Clears the CORS preflight cache whenever browsing data is deleted.
- `Disable-Service-and-Shared-workers-on-3P-iframe.patch`: Blocks Service Workers and Shared Workers inside third-party iframes.
- `Disable-Sticky-User-Activation-Across-Same-Origin-Navigation.patch`: Resets user gesture activation state when navigating between same-origin pages.

### 4.3 Network & Protocol Hardening
- `Reduce-HTTP-headers-in-DoH-requests-to-bare-minimum.patch`: Strips non-essential HTTP headers from DNS-over-HTTPS (DoH) queries.
- `Replace-DoH-probe-domain-with-RIPE-domain.patch`: Changes the default DoH connectivity probe domain from Google to neutral RIPE NCC servers.
- `Disable-requests-for-single-word-Omnibar-searches.patch`: Stops single-word omnibox queries from triggering local intranet DNS lookups.
- `Enable-Global-Privacy-Control.patch`: Sends `Sec-GPC: 1` on web requests and sets `navigator.globalPrivacyControl` to `true`.

### 4.4 Windows Ecosystem & Compatibility Support
- `Override-the-MV2-deprecation.patch`: Overrides Manifest V2 (MV2) deprecation in `manifest_v2_handler.cc`, allowing classic extensions (such as uBlock Origin MV2) to run normally.
- `WIN-disable-annotate-downloads.patch`: Stops writing the Windows `Zone.Identifier` (Mark-of-the-Web) stream to downloaded files in `download_file_impl.cc`.
- `WIN-Add-some-prefs-to-secure-preferences.patch`: Adds extensions and critical settings to Windows Secure Preferences with HMAC validation to protect against external tampering.
- `WIN-Disable-first-run.patch`: Disables the initial first-run setup screen on Windows.
- `WIN-Disable-search-for-image.patch`: Removes the "Search image with Google" option from context menus.
- `WIN-Fix-log-to-file.patch`: Fixes path handling and encoding when logging to files on Windows.
- `Enable-menu-on-reload-button.patch`: Adds a context menu to the reload button with Normal Reload, Hard Reload, and Empty Cache and Hard Reload.
