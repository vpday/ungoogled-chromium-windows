# Windows Optimization and Enhancement Patches Specification

## 1. Windows Native Optimizations and Feature Overrides (`patches/ungoogled-chromium/windows/`)

### 1.1 `windows-common-optimizations.patch` (Target-Agnostic Toolchain & Linker Tuning)
*Applies to: `x64`, `x86`, `arm64`*
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
*Applies to: `x64`, `x86`, `arm64`*
- Client AI & On-Device ML: Disables the Desktop AI assistant (Glic), Private AI, DevTools AI code features, and history passage embeddings.
- Speculative Networking & Preloading: Disables bookmark and NTP Prerender2, Navigation Predictor, Top Chrome WebUI preloading, and speculative ServiceWorker warm-up.
- Process De-bloating: Disables persistent spare renderer processes for the default search engine.
- Telemetry & Metrics: Disables Structured Metrics, Critical User Journeys, and Notification Telemetry.
- Security & UI Settings: Enables strict origin isolation and network service sandboxing; enables one-click tab audio muting and modern WebUI refresh.

### 1.4 `windows-adaptive-search-context-menu.patch` (Adaptive Multi-Engine Context Menu Search)
*Applies to: `x64`, `x86`, `arm64`*
- Multi-Engine Context Menu Search: Reads configured search engines from browser settings when text is selected on a webpage, showing multiple "Search with <Engine>" options in the right-click menu.
- Adaptive Menu Layout: Displays up to 4 search engines directly in the context menu, automatically folding additional engines into a "More search engines" submenu to keep the menu compact.

## 2. Curated Brave Patches (`patches/brave/`)

### 2.1 Resource De-bloating & AI Pruning
- `disable-web-platform-ai.patch`: Disables Web Platform AI APIs (`LanguageModel`, `PromptAPI`, and `WebPlatformAI` in `runtime_enabled_features.json5`), preventing web pages from downloading or running on-device AI models.
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
- `tab-restore-live-tabs.patch`: Guards tab restoration with `base::WeakPtr` to avoid use-after-free (UAF) crashes when closing and restoring tabs quickly.

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
- `copy-url-tab-context-menu.patch`: Adds a "Copy URL" option to the tab context menu.
- `mute-tab-context-menu.patch`: Adds a mute/unmute option to the tab context menu.
- `open-new-tabs-next-to-active-tab-option.patch`: Adds a flag to open new tabs directly next to the active tab rather than at the end of the tab strip.
- `enable-fluent-scrollbar.patch`: Enables Windows 11 Fluent minimal scrollbars across views.
- `disable-user-education-nags.patch`: Suppresses feature tutorial popups, prompts, and promo bubbles.
- `disable-outdated-build-detector.patch`: Disables the yellow "Chrome is out of date" warning banner.
- `disable-pdf-infobar.patch`: Removes the infobar shown when viewing PDFs.
- `disable-fedcm-bubble.patch`: Disables FedCM third-party account selection prompt bubbles.
- `add-more-zoom-presets.patch`: Adds more zoom percentage steps in `page_zoom.cc`.
- `center-window-on-launch.patch`: Centers the browser window on the screen on its first launch.
- `hide-page-actions-flag.patch`: Adds a flag to hide page action icons in the location bar.
- `hide-pip-live-caption-button.patch` & `disable-live-caption-completely.patch`: Hides the Live Caption toggle in Picture-in-Picture windows and removes the Live Caption background service and model downloader.
- `disable-non-standard-auth-features.patch`: Disables non-standard web authentication features (including `kFedCmDelegation`).
- `simplify-context-menu.patch`: Trims secondary options from the default context menu.

## 4. Curated Cromite Patches (`patches/cromite/`)

### 4.1 Anti-Fingerprinting & Hardware Masking
- `AudioBuffer-AnalyserNode-fp-mitigations.patch`: Adds subtle pseudo-random noise to WebAudio buffers and `AnalyserNode` outputs, preventing audio hardware and DAC fingerprinting.
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
- `Disable-text-fragments-by-default.patch`: Disables URL text fragments (Scroll-to-Text) by default.

### 4.4 Windows Ecosystem & Compatibility Support
- `Override-the-MV2-deprecation.patch`: Overrides Manifest V2 (MV2) deprecation in `manifest_v2_handler.cc`, allowing classic extensions (such as uBlock Origin MV2) to run normally.
- `WIN-disable-annotate-downloads.patch`: Stops writing the Windows `Zone.Identifier` (Mark-of-the-Web) stream to downloaded files in `download_file_impl.cc`.
- `WIN-Add-some-prefs-to-secure-preferences.patch`: Adds extensions and critical settings to Windows Secure Preferences with HMAC validation to protect against external tampering.
- `WIN-Disable-first-run.patch`: Disables the initial first-run setup screen on Windows.
- `WIN-Disable-search-for-image.patch`: Removes the "Search image with Google" option from context menus.
- `WIN-Fix-log-to-file.patch`: Fixes path handling and encoding when logging to files on Windows.
- `Enable-menu-on-reload-button.patch`: Adds a context menu to the reload button with Normal Reload, Hard Reload, and Empty Cache and Hard Reload.
