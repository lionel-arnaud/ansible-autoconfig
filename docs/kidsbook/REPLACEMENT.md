# Kidsbook Replacement Runbook

This is the repeatable path for replacing the children's computer without
recreating the parental controls, applications, or remote-management access by
hand.

## Before Replacing

1. Ensure the backup job has completed successfully and restore a sample file.
2. Record the new machine's Wi-Fi MAC address and update its DHCP reservation to
   `192.168.1.41` if the existing SSH alias is to remain unchanged.
3. Keep the hostname `kidsbook`. The Ansible inventory and the self-managing
   pull use that name.
4. Copy any data outside the managed setup: home directories, browser profiles,
   Steam libraries and saves, school files, and desktop preferences.
5. Confirm the current time limits with `timekpra --status` for `oscar` and
   `romy`.

## Install The Replacement

1. Install a supported Linux Mint release with full-disk encryption where the
   hardware supports it.
2. Create the `daddy` administrator account and retain its sudo password in the
   family password manager. The children accounts are created by Ansible.
3. Set the hostname to `kidsbook`, join the home Wi-Fi, enable OpenSSH, and add
   the homelab public key to `/home/daddy/.ssh/authorized_keys`.
4. Confirm the host key fingerprint from the local console before replacing the
   `kidsbook` entry in the controller's `known_hosts` file.
5. Run the repository bootstrap as root. It creates `/opt/ansible-pull` and
   installs the daily `autoconfig-pull` timer.

```bash
sudo ./scripts/bootstrap-server.sh
```

## Validate

1. Run an Ansible dry run on the replacement before applying it.

```bash
sudo ansible-playbook -i hosts --limit kidsbook local.yml --check
```

2. Apply the configuration after reviewing the check output.

```bash
sudo ansible-playbook -i hosts --limit kidsbook local.yml
```

3. Confirm `timekpr.service` and `autoconfig-pull.timer` are both active and
   enabled.
4. Sign in as each child, check their permitted hours and budget, and test one
   learning app and one game.
5. Restore the backed-up user data, then verify SSH with `ssh kidsbook`.

## Deliberate Decisions

- Backups must use a dedicated restricted key and the server's write-only backup
  inbox. Do not reuse an interactive SSH key.
- XRDP and iperf3 are currently LAN-reachable. Decide whether both belong on the
  replacement before enabling them.
- The managed role deliberately does not set account passwords. Set them during
  the OS installation or through a separately approved vaulted workflow.
