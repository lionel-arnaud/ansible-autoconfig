# Lenovo migration preparation

This is a review checklist, not an unattended migration. The Lenovo is not
yet in the inventory. Do not run Linux roles or Windows setup against it.
The old PC remains the source and should not be wiped until the new PC has
been verified and an independent backup exists.

## Discover and plan

- From the repository root, run `windows_health.yml` for installed desktop
  apps and system health; run `windows_migration_audit.yml` for Thunderbird
  and Chrome profile locations. Both inspect the old PC only. Reports and
  the Ansible log contain personal information: keep them private and out
  of Git.
- Confirm which Windows user will own the Lenovo and identify documents,
  desktop, downloads, pictures, browser profiles, mail, calendars, contacts,
  passwords, printer/scanner, and other data she actually needs. Check both
  local disks and whether OneDrive is syncing or storing cloud-only files.
- Agree on a backup destination, available capacity, encryption and recovery
  process. Test a restore. Profile and mail backups contain sensitive data.
- Review the installed apps with her; the inventory is a starting point,
  not an installation list. Drivers and HP-specific tools should not be
  blindly copied to Lenovo. Install Zoom and other chosen apps from trusted
  publishers, with explicit package IDs and versions where appropriate.

## Thunderbird

- Inventory `%APPDATA%\Thunderbird\profiles.ini` and the actual profile
  locations; profiles can be outside the default Thunderbird directory.
  Record whether mail is IMAP, POP or local folders, and whether contacts
  and calendars are local or synchronized.
- Close Thunderbird completely before copying, and make a secure verified
  backup using Mozilla's supported profile migration procedure. Preserve
  profile metadata and any externally located profile. Install Thunderbird on
  Lenovo and restore with its supported import/profile process, then verify
  mail, local folders, contacts, calendars, and sending before retiring the PC.
- Mail passwords and encrypted secrets may be present. Do not put profile
  contents into the repository, logs, or unencrypted shared storage.

## Chrome

- Confirm the correct Chrome profile and whether sync is enabled and current.
  Open tabs are not guaranteed to migrate merely by copying profile files.
  Use Chrome's sync/open-tabs feature where available; additionally save
  important tabs as bookmarks and verify they are present on the Lenovo.
- Prefer Google account sync or supported export/import for bookmarks and
  passwords. Saved passwords and cookies may be protected by Windows
  user/device encryption, so copying a raw profile is not a reliable way to
  transfer them. Handle passwords only with her consent and secure storage.

## Office

- The old PC reports Office Home & Student 2019 as licensed on the Retail
  channel. Sign in at https://account.microsoft.com/services with the
  Microsoft account that owns the purchase, confirm the entitlement, and
  install from Microsoft on the Lenovo. Activation and transfer remain subject
  to the license terms; follow Microsoft's instructions and use it on only the
  permitted number of devices. Do not remove the old installation before
  confirming the account and planning activation.
- Office 2019 reached end of support on 14 October 2025. It may still activate,
  but no longer receives normal security updates. Discuss a supported Office
  version before making it the long-term choice.
- Do not migrate KMS activators, suspicious downloads, or the inactive Office
  2016 volume license. Investigate Defender detections separately.

## Before applying a future Ansible setup

1. Set up the Lenovo's Windows account, updates and Tailscale; establish and
   verify SSH access restricted to the intended Tailscale path.
2. Add a distinct inventory host and a separate Windows-only play. Confirm
   the target explicitly. Do not reuse the old PC group for Lenovo changes.
3. Create an explicit approved package list, pin/review installer sources, and
   test idempotence and behavior under the intended Windows user. Do not apply
   WinUtil presets blindly.
4. Treat software installation, profile restore, Office activation and cleanup
   as separate opt-in phases, each with backups and verification. Decide how
   to handle elevation, reboot, logged-in apps and user interaction before
   automating any phase.
5. Verify Thunderbird, browser tabs/bookmarks, passwords, apps, printer, data
   and Office activation with her. Keep old backups until she confirms success.
