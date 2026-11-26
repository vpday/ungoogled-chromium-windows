# Windows Optimizations & Curated Patches Reference

## 1. Windows Native Optimizations and Feature Overrides (`patches/ungoogled-chromium/windows/`)

- `windows-common-optimizations.patch`: Enables Clang -O3 and ThinLTO optimization, fast floating-point contractions, and removes release-build assertion overhead to improve rendering and execution speed across all architectures.
- `windows-x64-optimizations.patch`: Enables AVX2 and FMA hardware acceleration on x64 builds while avoiding microarchitectural slow-instruction bottlenecks for smooth high-load performance.
- `windows-additional-feature-overrides.patch`: Disables desktop AI assistants (Glic), on-device AI, speculative preloading, and telemetry while tuning background tab freezing and closing tab responsiveness.
- `windows-multiple-search-engines-context-menu.patch`: Adds multi-engine search options to the right-click menu when selecting text. Enable via `chrome://flags#enable-multiple-search-engines-context-menu` or `--enable-multiple-search-engines-context-menu`.
- `windows-disable-digital-credentials.patch`: Blocks websites from silently invoking Digital Identity Credentials API requests.
- `windows-disable-jumplist-history.patch`: Prevents writing frequently visited sites and recently closed tabs to the Windows taskbar JumpList to avoid unencrypted OS-level browsing history leaks.
- `windows-normalize-user-agent-platform-version.patch`: Masks the Windows OS build version to a static 10.0.0 in Client Hints to prevent exact operating system version probing.
- `windows-disable-antivirus-metrics-provider.patch`: Removes startup WMI queries for third-party antivirus states and eliminates unnecessary background utility processes.
- `windows-disable-pepc-elements.patch`: Disables in-page declarative permission and app installation elements to prevent clickjacking and deceptive permission prompts.
- `windows-disable-ai-page-content-tracking.patch`: Disables heuristic scanning of password fields, SVGs, and layout trees for on-device AI content extraction.
- `windows-disable-webrtc-diagnostic-logging.patch`: Disables WebRTC diagnostic logging and removes related debugging interfaces to eliminate fingerprinting surfaces.
- `windows-hide-navigator-webdriver.patch`: Hides the `navigator.webdriver` flag to prevent legitimate browsing sessions from being misidentified as automated bots.
- `windows-spoof-webgpu-adapter-info.patch`: Normalizes WebGPU adapter information and aligns it with WebGL disclosures to avoid hardware contradictions.
- `windows-deterministic-canvas-noise.patch`: Applies deterministic edge micro-noise to Canvas rendering, defeating canvas fingerprinting while preserving solid color geometries.
- `windows-spoof-webgl-params.patch`: Normalizes over 80 WebGL parameters and applies readback protection to weaken hardware fingerprinting.
- `windows-timezone-sandbox.patch`: Supports setting an isolated browser timezone via `--timezone` that resists system clock updates.
- `windows-permissions-consistency.patch`: Aligns browser-internal permission states with JavaScript queries when custom permission policies are specified.
- `windows-font-fallback-filter.patch`: Restricts local system font enumeration via `--font-blacklist` to mitigate font-based tracking.
- `windows-media-devices-limit.patch`: Limits the number of enumerated audio and video devices via `--limit-media-devices` to prevent hardware enumeration fingerprinting.
- `windows-speech-voices-narrow.patch`: Limits the number of returned speech synthesis voices via `--limit-speech-voices` and normalizes localized Windows voice names.
- `windows-geolocation-override.patch`: Provides smooth, natural simulated GPS movement via `--geolocation=lat,lng` to defeat static spoofing detection.
- `windows-clipboard-off-the-record.patch`: Isolates text and links copied in incognito mode from the Windows 10/11 clipboard history (`Win + V`) and cloud clipboard synchronization.
- `windows-block-tsf-recall-learning.patch`: Signals Windows Text Services Framework to block Windows 11 Copilot+ Recall OCR screen capture and cloud IME dictionary harvesting.
- `windows-keep-window-open-on-last-tab.patch`: Automatically opens a new blank tab when closing the last tab, preventing accidental browser window termination.
- `windows-disable-reading-mode.patch`: Completely disables broken Reading Mode (Read Anything) entry points, address bar chips, background optimization guide polling, and WebUI routes.
- `windows-force-context-menu-on-shift-right-click.patch`: Forces the native context menu on Shift + Right-Click even when overridden by web scripts, preserving text selection and search context actions while safeguarding interactive Canvas and WebGL elements.
- `windows-utility-process-start-hidden.patch`: Launches unsandboxed Windows utility processes with `start_hidden = true` to prevent transient console window flashing when running with `--no-sandbox`.

## 2. Curated Brave Patches (`patches/brave/`)

### 2.1 Resource De-bloating & AI Pruning
- `disable-web-platform-ai.patch`: Disables web platform AI APIs to prevent websites from downloading or executing on-device language models.
- `consolidated-features-overrides.patch`: Disables bookmark and NTP pre-rendering, DevTools AI code features, and tab hover card thumbnail previews to conserve background resources.
- `kill-profile-reset-report-uploader.patch`: Stops sending diagnostic telemetry reports to Google when resetting browser profiles.
- `chrome-browser-media-webrtc-webrtc_event_log_uploader.cc.patch` & `chrome-browser-media-webrtc-webrtc_log_uploader.cc.patch`: Blocks WebRTC event and diagnostic log uploads to Google servers and cleans up local dump files.
- `third_party-blink-renderer-platform-runtime_enabled_features.json5.patch`: Disables JS Self-Profiling (`ProfilerAPI`), extension script tracking (`ExtensionScriptTagging`), and renderer-side Speculation Rules pre-rendering (`Prerender2`).
- `chrome-browser-glic-public-features.cc.patch` & `chrome-browser-glic-public-glic_enabling.cc.patch`: Disables Glic text selection context menus and hard-codes global criteria checks to return false.
- `chrome-browser-optimization_guide-chrome_browser_main_extra_parts_optimization_guide.cc.patch`: Prevents creation of OptimizationGuideGlobalState during browser startup.
- `components-optimization_guide-core-delivery-prediction_model_component_configs.cc.patch`: Disables optimization guide prediction model component delivery.
- `chrome-browser-predictors-loading_predictor_config.cc.patch`: Hard-disables loading predictor database and worker thread initialization.
- `chrome-browser-component_updater-trust_token_key_commitments_component_installer.cc.patch`: Disables registration of Trust Token Key Commitments component installer.
- `chrome-browser-ui-hats-hats_service_desktop.cc.patch`: Blocks Happiness Tracking Surveys (HaTS) desktop launch checks.
- `chrome-common-profiler-thread_profiler_configuration.cc.patch`: Completely disables background thread sampling profiler data collection.
- `components-heap_profiling-in_process-heap_profiler_parameters.cc.patch`: Disables in-process heap profiling metrics reporting.
- `components-history_clusters-core-features.cc.patch` & `components-history_clusters-core-on_device_clustering_features.cc.patch`: Disables Journeys images, navigation context clustering, on-device clustering engine, and keyword filtering.

### 2.2 System Security & Process Hardening
- `crashpad-prune-win-environment-block.patch`: Strips system environment variables from Windows crash minidumps to avoid leaking sensitive tokens and user data.
- `fsa-restrict-to-opfs.patch`: Restricts the File System Access API to the Origin Private File System sandbox, preventing sites from requesting access to arbitrary host directories.
- `defer-permission-prompts-to-load.patch`: Defers permission prompts until pages finish loading to prevent clickjacking and accidental authorizations.
- `content-browser-background_fetch-background_fetch_delegate_proxy.cc.patch`: Blocks Background Fetch API requests in Off-the-Record (Incognito) sessions to prevent first-party and cross-site cookie leakage.
- `components-password_manager-core-browser-password_form_filling.cc.patch`: Requires explicit user interaction (click or focus) before autofilling saved passwords to prevent hidden forms from harvesting credentials.
- `components-policy-core-common-cloud-cloud_policy_util.cc.patch`: Bypasses synchronous WLAN API queries in `GetNetworkName()` on Windows 11 24H2+ to prevent thread hangs and block Wi-Fi SSID reporting.
- `chrome-browser-external_protocol-external_protocol_handler.cc.patch`: Removes special privilege bypass for `mailto:` protocol to require user confirmation before launching external mail handlers.
- `components-privacy_sandbox-privacy_sandbox_features.cc.patch`: Disables Privacy Sandbox attestations check and enforcement.
- `services-device-public-cpp-device_features.cc.patch`: Enables the Allow/Ask/Block three-state permission model for Generic Sensors.
- `components-password_manager-core-browser-features-password_features.cc.patch`: Disables on-device password encryption metrics reporting.
- `components-one_time_tokens-core-common-one_time_token_features.cc.patch`: Disables Gmail OTP retrieval service in Autofill.
- `third_party-blink-common-features.cc.patch`: Disables eager and moderate viewport heuristics preloading.
- `chrome-browser-enterprise-data_protection-data_protection_features.cc.patch`: Disables enterprise forced download to cloud default feature.
- `chrome-browser-default_browser-default_browser_features.cc.patch`: Disables default browser prompt surfaces.
- `components-autofill-core-browser-studies-autofill_experiments.cc.patch`: Hard-disables credit card upload to Google Payments.
- `chrome-browser-autofill-autofill_image_fetcher_factory.cc.patch`: Returns nullptr for AutofillImageFetcher to prevent remote fetching of credit card and merchant issuer icons.

### 2.3 Tab Management & Desktop Ergonomics
- `tab-close-button-threshold.patch`: Lowers the tab close button visibility threshold to avoid accidental closures when numerous tabs are open.
- `pip-allow-full-window-size.patch`: Removes the maximum size limit on Picture-in-Picture windows, allowing arbitrary resizing across the screen.
- `download-context-menu-actions.patch`: Adds "Copy Download Link" and "Show in folder" options to the download bubble menu.
- `suppress-undo-tab-close-toast.patch`: Suppresses the "Undo closed tab" popup notification at the bottom of the screen.
- `hide-cookie-controls-location-bar-icon.patch`: Hides the third-party cookie blocking icon from the address bar to reduce visual clutter.
- `disable-global-signin-promos.patch`: Removes first-run account selection prompts and desktop sign-in promotional banners.
- `chrome-browser-ui-tabs-recent_tabs_sub_menu_model.cc.patch`: Removes Google sign-in promotional items from the recent tabs submenu when signed out.
- `chrome-browser-ui-webui-theme_source.cc.patch`: Adds null-check protection for ThemeService in `ThemeSource::SendColorsCss` to prevent crashes in SystemProfile and Profile Picker.
- `ui-gfx-image-image_skia.cc.patch`: Returns original image rep if `skia::ImageOperations::Resize` yields empty bitmap (`drawsNothing()`) to avoid downstream crashes.
- `components-omnibox-browser-omnibox_popup_selection.cc.patch`: Hides thumbs up/down feedback button focus states in Omnibox HistoryEmbeddings matches.
- `chrome-browser-signin-signin_promo_util.cc.patch`: Bypasses BatchUploadService queries in profile menu avatar button promo info.

## 3. Curated Helium Patches (`patches/helium/`)

### 3.1 Memory Conservation & Cold Startup Acceleration
- `memory-saving-by-default.patch`: Enables Memory Saver by default to discard idle background tabs automatically.
- `lazy-session-restore.patch`: Loads only the active tab on startup session restore, keeping background tabs unloaded until clicked.
- `infinite-tab-freezing.patch`: Keeps idle background tabs frozen indefinitely without periodic background wakeups.
- `hibernate-tab-context-menu.patch`: Adds a "Hibernate Tab" option to the tab context menu to manually discard individual tabs and reclaim memory.
- `prioritize-platform-policy-loading.patch`: Prioritizes enterprise and platform policy loading over background tasks to prevent startup race conditions.
- `tab-favicon-retention.patch`: Retains previous favicons during navigation and session restores to prevent blank favicon flickering.
- `tab-icon.patch`: Applies a grayscale filter to hibernated tabs to visually distinguish active and discarded tabs.

### 3.2 Display Energy Efficiency & Subpixel Rendering
- `add-low-power-framerate-flag.patch`: Adds a flag to cap rendering framerate, saving battery on high-refresh-rate displays.
- `dont-antialias-rects.patch`: Fixes subtle seam lines and subpixel jitter under fractional Windows display scaling (125%, 150%).
- `disable-ink-ripple-effect.patch`: Removes the Material Design ink ripple click animation for snappier UI feedback.
- `fix-windows-ui-position.patch`: Corrects top padding coordinate alignment for the tab strip and window caption on Windows.
- `generate-standard-qr-codes.patch`: Replaces custom dino-centered QR codes with standard high-contrast black-and-white QR codes for reliable scanning.
- `exclusive-access-bubble.patch`: Speeds up fullscreen notification animations and applies cleaner styling.
- `square-interstitial-buttons.patch`: Applies modern rounded button styling to security warning pages.
- `toolbar-window-frame-hit-test.patch`: Allows clicking and dragging the window from empty non-interactive areas in the top toolbar.
- `remove-toolbar-dividers.patch`: Removes redundant vertical dividers between extension icons and pinned toolbar items.
- `improve-flags-webui.patch`: Improves `chrome://flags` search box styling and highlights modified flags.
- `status-bubble.patch`: Redesigns the bottom-left URL status bubble into a modern floating capsule with 16px rounded corners, subtle drop shadow, and 8px floating margins.
- `toast.patch`: Compacts notification toasts to an 8px rounded container with smooth scaling animations to minimize viewport occlusion.
- `bookmark-button-bg-fix.patch`: Restores classic 6px rounded rectangle hover highlights on bookmark bar buttons.

### 3.3 Privacy, Degoogling & Network Layer Hardening
- `crash-reporter-privacy-tweaks.patch`: Disables Crashpad automatic uploads, zeroes client UUID, limits crash dump sizes, and strips sensitive values from command-line crash annotations.
- `remove-history-sync-promo.patch`: Removes the sign-in and sync promotional banner from the `chrome://history` page.
- `clear-browsing-data-popup.patch`: Removes the Google account data management link from the Clear Browsing Data dialog and defaults data types to expanded.
- `disable-history-clusters.patch`: Disables History Clusters (Journeys) grouping and background analysis.
- `split-clienthello.patch`: Randomly splits TLS ClientHello packets to resist TLS fingerprinting and SNI-based blocking.
- `spoof-chrome-ua-brand.patch`: Replaces Google Chrome brand tokens with generic identifiers in Client Hints.
- `reduce-accept-language-headers.patch`: Trims `Accept-Language` headers to reduce language-based fingerprinting.
- `disable-ad-topics-and-etc.patch`: Disables Privacy Sandbox tracking features, including the Topics API and conversion measurement.
- `clean-omnibox-suggestions.patch`: Removes promotional action suggestion buttons from address bar search results.
- `ridiculous-google-compat-exceptions.patch`: Removes hardcoded Google sign-in and service exception rules.
- `degoogle-context-menu.patch`: Strips Google Search, Lens, Gemini, Live Caption, Translate, and Reading Mode items from context menus.
- `fix-instance-id-stuck.patch`: Prevents task queues from hanging when Google Cloud Messaging is unavailable or blocked.
- `omnibox-default-search-icon.patch`: Replaces dynamically fetched search engine icons with a static privacy search icon.
- `break-favicons.patch`: Strips remote search engine favicon URLs to prevent background network pings on startup.
- `remove-unused-ai-resources.patch`: Prunes unused side-panel AI and feature assets from packaged resource bundles to reduce install size.
- `remove-experimental-webui.patch`: Disables experimental WebUI popups and prunes unused WebUI resource bundles.

### 3.4 Ergonomics & Web Content Control
- `force-paste-action.patch`: Forces paste operations to work in input fields that attempt to block clipboard pasting.
- `close-tabs-to-left.patch`: Adds a "Close tabs to the left" option to the tab context menu.
- `open-new-tabs-next-to-active-tab-option.patch`: Adds an option to open new tabs directly next to the active tab rather than at the end of the strip.
- `disable-user-education-nags.patch`: Suppresses feature tutorial popups, prompts, and promo bubbles.
- `disable-outdated-build-detector.patch`: Disables the yellow "Chrome is out of date" top warning banner.
- `disable-annoying-infobars.patch`: Removes the PDF viewing infobar and startup foreground infobars.
- `disable-fedcm-bubble.patch`: Disables FedCM third-party account selection prompt bubbles.
- `add-more-zoom-presets.patch`: Adds finer page zoom percentage increments.
- `center-window-on-launch.patch`: Centers the browser window on the screen on its first launch.
- `hide-page-actions-flag.patch`: Adds a flag to hide page action icons in the location bar.
- `hide-pip-live-caption-button.patch` & `disable-live-caption-completely.patch`: Hides the Live Caption button in Picture-in-Picture windows and disables the Live Caption background service.
- `disable-non-standard-auth-features.patch`: Disables non-standard web authentication extensions.
- `remove-dead-toolbar-actions.patch`: Removes defunct Google toolbar actions and side-panel entrypoints (Passwords, Lens, etc.).
- `remove-reading-list-from-app-menu.patch`: Removes Reading List from the primary bookmarks menu.
- `remove-dead-profile-actions.patch`: Removes Google account and sync management shortcuts from the profile menu.
- `clean-up-installed-extension-bubble.patch`: Strips promotional text and extra links from the post-installation dialog.
- `disable-tab-group-editor-footer.patch`: Disables the educational footer text in tab group editor bubbles.
- `bookmark-open-all-confirmation-flag.patch`: Prompts for confirmation when opening 15 or more bookmarks simultaneously.
- `add-default-browser-reject-button.patch`: Adds a permanent "Don't ask again" button to the default browser prompt.
- `remove-devtools-annoyances.patch`: Removes AI promotional banners, feedback surveys, and Google account sync sections from DevTools.
- `disable-side-panel-flyover.patch`: Uses continuous frame resizing for side-panel animations to eliminate jerky layout reflows on Windows.
- `simplify-side-panel-position.patch`: Disables experimental ContextualTasks panels and simplifies side-panel alignment to a straightforward left/right radio setting.
- `fix-tab-sync-unreached-error.patch`: Removes redundant tab selection sync checks when closing tabs in saved tab groups, preventing potential main process crashes.

## 4. Curated Cromite Patches (`patches/cromite/`)

### 4.1 Anti-Fingerprinting & Hardware Masking
- `Fonts-fingerprinting-mitigation.patch`: Restricts local font enumeration to mitigate font-based tracking.
- `Media-fingerprinting-mitigations.patch`: Restricts video decoder capability probing in WebCodecs to prevent hardware codec fingerprinting.
- `Reduce-input-capability-fingerprinting-through-normalization.patch`: Normalizes reported mouse, pen, and touch capabilities to reduce device diversity.
- `Prevent-mouse-wheel-fingerprinting-on-Windows.patch`: Normalizes Windows mouse wheel tick delta to `+1` / `-1` to eliminate high-entropy hardware scroll wheel fingerprinting.
- `PublicKeyCredential-fingerprinting-mitigations.patch`: Masks Windows Hello biometric availability and checks permissions before background BLE device discovery.
- `Disable-UA-full-version.patch`: Reduces client hints `uaFullVersion` and brand version list to major version only (`X.0.0.0`).
- `Remove-navigator.connection-info.patch`: Overrides `navigator.connection` network type, RTT, and bandwidth with static default values to block network status fingerprinting.
- `Disable-support-for-pointer-device-id.patch`: Disables stylus pen device ID reporting.
- `Keyboard-protection-flag.patch`: Adds a flag to block websites from querying physical keyboard layout mappings.
- `Set-caret-blink-interval-to-default.patch`: Uses a fixed caret blink interval to prevent cursor timing fingerprinting.
- `Disable-Posture-API.patch` & `Disable-Viewport-Segments.patch`: Disables foldable screen posture and viewport segment APIs.
- `Disable-idle-detection.patch`: Disables the Blink Idle Detection API to prevent user activity tracking.
- `Disable-visited-pseudo-class.patch`: Prevents querying CSS `:visited` styles for browsing history sniffing.
- `Disable-conversion-measurement-api.patch`: Disables the Attribution Reporting API to block cross-site ad conversion tracking.
- `Disable-css-preferred-text-scale.patch`, `Disable-prefers-reduced-transparency-media-query.patch` & `Disable-CSSDynamicRangeLimit.patch`: Disables non-essential CSS media queries used for browser fingerprinting.
- `Add-a-flag-to-disable-GamePad-API.patch`: Adds a flag to disable the Gamepad API.
- `Disable-Web-Bluetooth-by-default-in-desktop-platforms.patch`: Disables Web Bluetooth by default on desktop platforms.
- `Partition-MediaDeviceId-by-default.patch`: Partitions media device IDs per origin to prevent cross-site device correlation.
- `Override-Navigator-Language.patch`: Allows overriding `navigator.language` to mask the real system locale.

### 4.2 Resource Teardown & Isolation
- `Immediately-destroy-shared-workers-when-closing-the-page.patch`: Shuts down Shared Workers as soon as the last connected page closes, freeing memory immediately.
- `Keep-ComputePressure-disabled.patch`: Keeps the Compute Pressure API disabled so websites cannot poll CPU load states.
- `Keep-disabled-CpuPerformance.patch`: Disables the CPU performance benchmarking API.
- `Keep-disabled-FetchLaterAPI.patch`: Disables the `fetchLater()` API to stop pages from scheduling delayed network requests after being closed.
- `Lock-Profile-Cookie-Database.patch`: Acquires an exclusive lock on the active cookie database to prevent external processes from reading session cookies.
- `Remove-window-name-on-cross-origin-navigation.patch`: Clears `window.name` on cross-origin navigations to break cross-site tracking via window properties.
- `Clear-CORS-Preflight-Cache-on-clearing-data.patch`: Clears the CORS preflight cache whenever browsing data is deleted.
- `Disable-Service-and-Shared-workers-on-3P-iframe.patch`: Blocks Service Workers and Shared Workers inside third-party iframes.
- `Disable-Sticky-User-Activation-Across-Same-Origin-Navigation.patch`: Resets user gesture activation state when navigating between same-origin pages.
- `Disable-third-party-origin-trials.patch`: Completely disables third-party origin trials by invalidating the public key and forcing supported status to `false`.
- `Disable-text-fragments-by-default.patch`: Disables Scroll-to-Text Fragments (`#:~:text=`) by default to prevent cross-origin sensitive text side-channel probing.

### 4.3 Network & Protocol Hardening
- `Reduce-HTTP-headers-in-DoH-requests-to-bare-minimum.patch`: Strips non-essential HTTP headers from DNS-over-HTTPS (DoH) queries.
- `Replace-DoH-probe-domain-with-RIPE-domain.patch`: Replaces the default Google DoH probe domain with neutral RIPE NCC servers.
- `Disable-requests-for-single-word-Omnibar-searches.patch`: Stops single-word omnibox queries from triggering local intranet DNS lookups.
- `Enable-Global-Privacy-Control.patch`: Sends `Sec-GPC: 1` on web requests and sets `navigator.globalPrivacyControl` to `true`.
- `Remove-auth-header-upon-cross-origin-redirect.patch`: Strips the `Authorization` header on cross-origin HTTP redirects to avoid credential leakage.
- `Disable-TLS-resumption.patch`: Disables TLS 1.2/1.3 session tickets and session caching to prevent long-lived cross-network tracking without cookies.
- `Enable-Do-Not-Track-by-default.patch`: Enables the `DNT: 1` header by default alongside existing Global Privacy Control protection.

### 4.4 Windows Ecosystem & Compatibility Support
- `Override-the-MV2-deprecation.patch`: Overrides Manifest V2 deprecation, allowing classic extensions (such as uBlock Origin MV2) to run normally.
- `WIN-disable-annotate-downloads.patch`: Stops writing the Windows Mark-of-the-Web (`Zone.Identifier`) stream to downloaded files.
- `WIN-Add-some-prefs-to-secure-preferences.patch`: Adds critical settings and extensions to Windows Secure Preferences with HMAC validation against external tampering.
- `WIN-Disable-first-run.patch`: Disables the first-run welcome and setup screen on Windows.
- `WIN-Disable-search-for-image.patch`: Removes the "Search image with Google" option from context menus.
- `WIN-Fix-log-to-file.patch`: Fixes path handling and encoding when logging to files on Windows.
- `Enable-menu-on-reload-button.patch`: Adds a context menu to the reload button with Normal Reload, Hard Reload, and Empty Cache and Hard Reload.
