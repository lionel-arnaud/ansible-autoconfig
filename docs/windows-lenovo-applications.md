# Lenovo application migration inventory

The goal is to reproduce the old PC's useful application environment, not
the HP laptop's hardware drivers. This is a planning manifest, **not an
executable install list**. Registry and Store inventories are imperfect and
may include duplicates, orphaned entries, components, obsolete software and
software installed for another user. Rerun the health play with
`-e windows_health_show_details=true` and `windows_migration_audit.yml` for
the current inventory. Do not publish their personal logs.

## Desktop applications to carry forward

These were observed on 27 November 2026; prefer current, supported official
versions, not old installers or copied program directories. Confirm exact
Winget identifiers, publisher, install scope and target behavior before
adding an automated installation task.

| Application | Migration considerations |
| --- | --- |
| Google Chrome | Sync/bookmarks/tabs/passwords require separate verification. |
| Mozilla Firefox | Check whether its profile, bookmarks and passwords are used. |
| Mozilla Thunderbird | Restore the full profile separately; see the checklist. |
| Microsoft Office Home and Student 2019 | Retail entitlement/account and activation require a separate step; Office 2019 is unsupported. |
| Adobe Acrobat | Verify installed edition, license and signed-in account. |
| iTunes and Apple device support | Install supported current Apple software and verify library and device backup locations. |
| Zoom Workplace | Current official installer; confirm account and settings. |
| VLC media player | Current official installer. |
| RustDesk | Preserve or reconfigure remote access deliberately; do not copy credentials blindly. |
| Tailscale | Authorize the new device separately; never copy node keys. |
| GlassWire | Check license and current Windows 11 support. |
| Webex | Old registry entry; verify current version and account. |
| Microsoft OneDrive | Verify account and cloud-only/local file status before migration. |
| Microsoft Teams classic | Legacy entry; find the supported replacement and account. |
| Skype | Discontinued; a functional like-for-like install may not be possible. |
| Canon IJ Scan Utility and MP230 drivers | Check Windows 11 support and obtain official model-specific printer/scanner software. |
| HP Photosmart 7520 software / HP Smart | Printer software is distinct from HP laptop drivers; check current support. |
| Java | Two installed versions include an old 2018 release; investigate dependent applications before selecting a supported runtime. |
| OneBrowser | Identify its purpose and publisher and check its data/security before migration. |
| Codex CLI, ripgrep, zoxide | Preserve if wanted; inspect per-user installation and dependencies. |

Do not silently omit applications that have no simple supported equivalent:
identify their purpose, data and alternatives. Conversely, do not automatically
reinstall obsolete, unrecognized or potentially unsafe software merely because
an inventory entry exists. Old KMS activators and detected downloads are
explicitly excluded from migration.

## Store apps and data

The current user's Store inventory includes Simple Solitaire, Microsoft
Solitaire Collection, Wordament, Sticky Notes, OneNote for Windows 10, HP
Printer Control, Ubuntu/WSL, PowerShell, and many Windows components. Preserve
the user's apps where still available and investigate their data independently
of reinstalling the app. In particular:

- Check Sticky Notes and OneNote account synchronization and local data.
- If Ubuntu/WSL is used, inventory its distribution and personal files; a
  Store reinstall does not restore the Linux filesystem.
- Legacy Windows 10 apps or Store listings may not exist on Windows 11.
  Record alternatives and verify user acceptance rather than assuming parity.

## Device-specific and automatically supplied components

Do not carry over HP Pavilion touchpad, audio, battery, thermal, wireless,
chipset or NVIDIA drivers. Let Lenovo/Windows supply hardware-specific
drivers. HP's printer tools are an exception to the laptop-driver exclusion.
Visual C++ runtimes, Apple components, codecs and Windows framework packages
should generally come from their applications or Windows, not from a
blind replay of the old machine's component list.

## Printers discovered

- HP Photosmart 7520 series (network/WSD).
- Canon MP230 series (USB).

Test printing and scanning on the Lenovo, with current official drivers where
needed. Virtual PDF/XPS/Fax printers are Windows features, not physical devices.

## Boundaries

Installation must target a new, explicitly identified Lenovo host and use a
reviewed, idempotent Windows-only play. Installer availability, package IDs,
license terms, account sign-in, user profile context, reboots and elevation
must be checked before enabling it. Do not run this plan against the old PC.
