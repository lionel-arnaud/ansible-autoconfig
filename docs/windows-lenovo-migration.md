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
- Use the [application migration inventory](windows-lenovo-applications.md)
  as the starting point for reproducing her applications. Drivers and
  HP-laptop-specific tools should not be blindly copied to Lenovo; HP printer
  tools may still be needed. Use trusted publishers and explicit package IDs.

## Linux backup staging and malware scanning

The Linux workstation is a suitable proposed destination: on 27 November
2026 its LUKS-encrypted filesystem had roughly 381 GiB available. The
measured Thunderbird, Chrome, Documents, Downloads, Desktop and Music
locations totaled about 39 GiB before overhead or extra locations; check
capacity again and discover other relevant files. Disk encryption protects
data at rest while locked, not from other processes or users while unlocked.
Store copied data in a private user-only directory outside Git, with umask
077, and do not expose it through file sharing or synchronization.

Copy over the existing key-authenticated Tailscale SSH connection, but do not
run copied executables or scripts, follow untrusted links, or blindly restore
known activators and flagged downloads. Close Thunderbird before taking its
profile copy so it is consistent. Check transfer errors, file counts and
integrity, then test a selective restore before relying on the backup.
Windows ACLs, special files, cloud-only placeholders and files in use require
explicit handling; a simple copy is not a complete Windows system image.

The old PC is not always on. Select and test a transfer mechanism that
resumes interrupted files across disconnects and sleep without overwriting a
verified backup or deleting source files. Test interruption, reconnection and
integrity on harmless sample files before transferring personal data. A
resumable transfer alone does not make a running application's data
consistent: Thunderbird must stay closed for its final copy and verification,
and files changed between sessions must be rechecked. If it cannot remain
closed, take a suitable consistent snapshot first and verify its scope.

The existing OpenSSH path can use SFTP resume mode: from Linux, use
`sftp -a -i ~/.ssh/isabe-windows isabe@100.80.190.1`, then use `get -a -R`
for each source directory and the private staging destination. Re-run the
same command after reconnecting; `-a` resumes partial files and does not
remove source files. Do not use `sync`, `mirror`, or a destination-cleaning
operation for this migration. Confirm the exact SFTP path syntax with a small
sample first, and keep each session's output or error log private.

For each batch, generate a source-side SHA-256 manifest with PowerShell
(`Get-FileHash`) while the relevant files are stable, transfer the manifest,
and verify the received files on Linux with `sha256sum --check`. Recreate the
manifest after the final Thunderbird-closed copy; a successful resumed
transfer is not proof that a file did not change between sessions.

ClamAV was installed on the workstation, but `clamav-freshclam.service` was
disabled when checked. Before the actual scan, update and verify its signature
database using the supported local configuration. Scan the staged files
without automatic deletion, retain a private log, and review detections,
unreadable files, archive and scan-size limits before deciding what to restore.
ClamAV cannot guarantee that files are safe; encrypted archives and some
malware can evade scanning. Avoid exposing the new Windows PC to flagged
items, and do not discard the only copy of a potentially valuable file.

Keep the old PC and an independent verified copy until the Lenovo restore
is confirmed. A Linux staging copy alone does not protect against loss of
both computers or backup corruption. No data is copied by this checklist.

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
