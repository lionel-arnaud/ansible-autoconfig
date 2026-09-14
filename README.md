# 🏠 Homelab as Code

**One command rebuilds my entire home infrastructure — a family server, a
laptop, a Raspberry Pi and the kids' machine — from an empty disk.**

Everything here is *declarative*: instead of clicking through installers and
remembering what I did six months ago, the whole setup is written down as code,
version-controlled, and re-applied automatically every night. If a machine dies,
I reinstall the OS, run one command, and it comes back exactly as it was.

Built and maintained by **Lionel Arnaud** — [dinnizer.com](https://www.dinnizer.com)

---

## ✨ What it actually runs

A single refurbished office PC quietly runs the digital life of a household and
two small businesses.

### 👨‍👩‍👧‍👦 For the family

| | Service | What it does |
|---|---|---|
| ☁️ | **Nextcloud** | Private Google-Drive replacement. Family photos, documents and calendars, on hardware we own. |
| 🎬 | **Jellyfin** | The household's own Netflix — films, series and music streamed to any TV, tablet or phone. |
| 📹 | **Frigate** | Security camera recording with on-device AI person detection. No footage ever leaves the house. |
| 🛡️ | **Pi-hole** | Network-wide ad and tracker blocking. Every device on the WiFi is protected automatically. |
| 🎲 | **Tabletop Timer** | A board-game turn timer, live at [tabletop-timer.com](https://tabletop-timer.com). |
| 👧 | **Parental controls** | Screen-time limits and a curated app set on the kids' laptop. |

### 💼 For the businesses

| | Service | What it does |
|---|---|---|
| 🍽️ | **Au Menu Il Y A** | A live customer-facing site at [aumenuilya.fr](https://www.aumenuilya.fr). |
| 🥗 | **Dinnizer** | A meal-planning web app — my own product, running in production. |
| 🎨 | **Excalidraw** | Self-hosted collaborative whiteboard for sketching ideas. |
| 📄 | **BentoPDF** | Private PDF toolkit — merge, split and convert without uploading confidential files to a random website. |

### 🧪 A research lab on a Raspberry Pi

| | Service | What it does |
|---|---|---|
| 🧬 | **Biotech research assistant** | An AI analyst that follows upcoming clinical-trial results, briefs me on each one — teaching the vocabulary as it goes — asks for my call over Telegram, and keeps score of how often I am right. |
| 📈 | **Practice trading account** | Acts on those calls in a paper-money account, inside hard limits written in code that the AI cannot change. |
| 📋 | **Daily report** | A private page with positions, open questions, my past calls and the scoreboard, refreshed every night. |

### 🔧 Keeping it all alive

| | Service | What it does |
|---|---|---|
| 🔐 | **Caddy** | Front door for every site. Obtains and renews HTTPS certificates automatically. |
| 📊 | **Homepage** | One dashboard showing the health of everything at a glance. |
| 💾 | **Borg + Timeshift** | Encrypted, deduplicated backups — *with a restore that has actually been tested on a clean machine.* |
| 🚨 | **Failure alerts** | If anything breaks, my phone knows before I do. |
| 📈 | **Uptime Kuma** | Checks every public site from the outside, and warns before a certificate expires. |
| 🚫 | **fail2ban** | Automatically bans hosts that try to brute-force their way in. |

---

## 🖥️ The machines

| Machine | Role |
|---|---|
| 🗄️ **Server** | Headless Ubuntu box. Runs every service above in Docker. |
| 💻 **Laptop** | Arch Linux / Hyprland daily driver — desktop, dotfiles and dev tooling. |
| 🍓 **Raspberry Pi** | Always-on bench, and home of the biotech research assistant. |
| 👧 **Kids' laptop** | Old MacBook given a second life with Linux Mint and strict screen-time limits. |

Each machine checks this repository **every night** and reconfigures itself to
match. Config drift fixes itself while I sleep.

---

## 🧠 What this project demonstrates

*A plain-language summary of the engineering behind it.*

- **🔁 Infrastructure as Code** — ~6 000 lines of Ansible. Zero manual server
  setup; every change is reviewed and version-controlled.
- **🔒 Security engineering** — secrets never touch this public repository. They
  are generated on the machine itself or encrypted before commit. Admin
  interfaces sit behind authentication, internal services are firewalled to the
  local network, and a recent audit closed a container-escape path.
- **♻️ Reliability** — backups are encrypted, pruned on a schedule, and the
  restore path has been rehearsed end to end on a clean machine. Failures page a
  phone instead of dying silently in a log.
- **🤖 AI with guardrails** — the research assistant reasons and proposes, but
  every order passes deterministic limits written in plain code: position size,
  total exposure, trades per day and a daily loss breaker. A kill switch works
  even when the AI is stuck, every order can be traced back to the news and the
  human call that produced it, and moving to real money takes two separate,
  deliberate settings. Over 250 automated tests keep those promises in place.
- **✅ Testing & automation** — linting and a custom test harness run on every
  commit, catching the class of bug that generic linters miss.
- **📝 Documentation** — every non-obvious decision is written down with the
  reasoning behind it, so the *why* survives longer than my memory.

> **In plain terms:** this is the same discipline a professional platform or
> DevOps team applies to production systems, at household scale — where the
> users are my family and the downtime complaints arrive at dinner.

---

## 🚀 Try it yourself

```bash
sudo ansible-pull -U https://github.com/lionel-arnaud/ansible-autoconfig.git \
  -d /opt/ansible-pull -i hosts local.yml
```

That single command installs, configures and starts everything appropriate for
whichever machine it runs on.

---

# 🛠️ Technical documentation

Everything below is the working documentation: how to run it, the roadmap, the
secrets model, the storage and disaster-recovery design, and the conventions for
anyone (human or agent) changing this repo.

**Contents**

- [Usage](#usage) — how to run it, including test/dry-run modes
- [ToDo](#todo) — roadmap and open items
- [Guidelines for coding agents](#guidelines-for-coding-agents) — the contract for AI contributors
- [Design Rules](#design-rules) · [Active Layout](#active-layout) · [Current Entry Points](#current-entry-points)
- [Secrets And Vault](#secrets-and-vault) — the two-tier secret model
- [Linting](#linting) — local lint + the rendered-template test harness
- [Testing On A VM](#testing-on-a-vm)
- [Storage Model](#storage-model) · [Disaster Recovery](#disaster-recovery) · [Off-Site Backups](#off-site-backups)
- [Adding A New Public Site](#adding-a-new-public-site) · [Seeding Uptime Kuma Monitors](#seeding-uptime-kuma-monitors) · [Dead-Man's Switch](#dead-mans-switch) · [Dotfiles Model](#dotfiles-model) · [Pi-hole Source Of Truth](#pi-hole-source-of-truth)
- [Serverannah Notes](#serverannah-notes) · [Conventions](#conventions-for-future-changes) · [Known Reality](#known-reality)

## Credits and lineage

![Ansible Logo](https://www.learnlinux.tv/wp-content/uploads/2020/12/ansible-e1607524003363.png)

This repository is based on the code that Jay Lacroix (LearnLinuxTV) worked on
from his [Ansible Desktop tutorial on Youtube](https://youtu.be/gIDywsGBqf4).

Additionnal inspiration could be taken from
[Jeef Geerling's work on Ansible](https://ansible.jeffgeerling.com)

It was improved with the Ansible-pull tutorial and then coding was improved with
ChatGPT's Codex (via opencode and pi.dev).

## Usage

objective is to have something that can be run easily on a new machine or not
(idempotent) with:

```bash
sudo ansible-pull -d /opt/ansible-pull -U https://github.com/lionel-arnaud/ansible-autoconfig.git -i hosts local.yml --vault-password-file ~/secret.txt
```

The `-d /opt/ansible-pull` matters: run as `sudo`, ansible-pull otherwise clones
into `/root/.ansible/pull/…` (mode 700), and the dotfiles `stow` step — which
runs as your normal user — cannot read the repo there and fails with a
permission error. Always check out into a shared, readable path. (The managed
auto-pull timer already does this.)

in test mode, to avoid having to "git push" each modification in order to test
it locally on a development machine where the repo is present (because i'm
currently working on it for instance), use:

> sudo ansible-pull -U "~/Documents/ansible-autoconfig/" --check

or

> sudo ansible-playbook -i "localhost," -c local local.yml --check

_remember that ansible-pull is just a wrapper for ansible-playbook....so both
cmds are kinda similar ... and the check option allows to test on a system
without implementing anything ('dry run')._

## ToDo

### 🔭 Proposed next steps (Sept 2026 review)

Ranked by value for *this* setup. Resilience before new apps: the box now has
17 services and the useful question is not "what else can it run" but "what
tells me when one of them stops".

- [~] **Dead-man's switch** — mechanism implemented, needs a ping URL.
      `OnFailure=` catches a run that *fails*; it structurally cannot catch a
      timer that never fires at all. Two ways to arm it, one of which needs no
      signup because Uptime Kuma is already running — see
      [Dead-Man's Switch](#dead-mans-switch), which also records why this is
      deliberately *not* built on ntfy.
- [x] **Off-site backup copy** — implemented. The Borg repo (~6 GB) mirrors to
      Google Drive after every `borg compact`. See
      [Off-Site Backups](#off-site-backups).
- [x] **Escrow the Borg passphrase** — held in Bitwarden (hosted, deliberately
      not self-hosted: a password manager that lives on the machine whose
      passphrase it holds is circular, and this is the one service where
      depending on someone else's uptime is the *safer* choice).
- [x] **Uptime monitoring** — Uptime Kuma deployed at `status.dinnizer.com`.
      Monitors are configured in its own UI (its API is not stable enough to
      manage idempotently from Ansible, and a task pretending otherwise would
      silently diverge from what the UI shows).
- [ ] ~~Rotate the shared Caddy password / split it per site~~ — **rejected,
      deliberately.** Caddy basic auth holds no session: every page refresh
      re-prompts, and desktop Bitwarden cannot autofill a browser-native auth
      dialog (it can on mobile, where the prompt is a normal form). Per-site
      passwords would multiply that friction by six, and automatic rotation adds
      a lockout risk that outweighs the benefit. Revisit only if Caddy gains
      cookie-backed sessions, or by moving the admin routes to an auth portal
      (Authelia / tinyauth) that issues a session cookie.
- [ ] **Fix or delete push mode.** The documented
      `-e ansible_connection=ssh` entry point cannot work (see Current Entry
      Points). Either make `dotfiles_source_dir` and the `synchronize` tasks
      control-node aware, or remove the claim.
- [ ] **Make `--check` usable end to end.** A dry run currently dies on the
      Nextcloud `occ` wait loop, so the playbook cannot be pre-flighted. Guard
      the wait loops with `when: not ansible_check_mode`.
- [ ] **Docker log rotation is capped; disk usage is not monitored.** A simple
      hourly disk-percentage check wired to the new notifier would have flagged
      the 94%-full disk long before it became urgent.

- [ ] **Trading agent: act on a changed call.** Changing an answer from yes to
      no stops new purchases, but does not yet sell a position already held:
      the model is not shown current holdings. Pass holdings in, and propose an
      exit when the call behind a position flips.
- [ ] **Trading agent: wire the registry-change detector.** `trial_watch.py` is
      built and tested: it snapshots a trial's registry entry and flags changes
      to its main goal, status, planned size, dates or phase. Connect it so a
      change triggers a message and a fresh question.

*Considered and rejected, with reasons, in `docs/review/REVIEW-2026-09.md`:*
Prometheus/Grafana/Loki (5-6 containers and unbounded disk to answer a question
one 150 MB container answers), Immich (needs 200-500 GB), a full secrets manager
(introduces an unsealing bootstrap problem — the real gap is escrow, not
storage), and Watchtower (fights the role's deliberate ownership of image pulls).

### Original backlog

- [x] initiate base role
- [ ] implement server roles (fresh arch and ubuntu machines compatible)
  - [ ] keep server and workstation roles Arch-compatible where practical for
        server flexibility and future distro hopping
  - [x] use tags to only test/execute parts of the ansible-autoconfig script...
        that should accelerate dev/debug and limit need for protection against
        downloads (to preserve bandwidth).
  - [x] include running pi-hole update as part of the ansible playbook? Include
        also homepage update, etc. (since they are dockers, pull the latest
        image?)
  - [ ] pull latest container images on each run unless it slows runs down too
        much
- [ ] server services
  - [x] **nextcloud**: implement "old" users ?
  - [x] re-establish when possible the conf file for Homepage as on raspi (with
        the same "widgets" when relevant). Update also the links there.
  - [ ] **other services**:
    - [x] borg backups for
      - [x] server services — **and the restore path is tested**: a full archive
            restores cleanly onto a _fresh Ubuntu VM_ (all 53k files decrypt and
            extract, DB dumps byte-for-byte). See
            [Disaster Recovery](#disaster-recovery).
      - [ ] server files, including aumenuilya, tabletop-timer, and other
            service data (these paths are not in `backup_paths` yet)
    - [ ] timeshift back-up on SSD_512 for simple system-level checkpoints and
          restore points for serverannah internal storage only
    - [x] ~~Odoo with small database stored on serverannah internal SSD~~ —
          **decommissioned Sept 2026**. The accounting features that made it
          worthwhile are not in the free edition, so the hosted Odoo stays in
          use instead. Role, defaults, host vars, Caddy site and containers all
          removed.
    - [x] Jellyfin reading media from SSD_1TO (Plex removed)
    - [ ] Dictation app/server (voxtype, whisper, etc.) ? Need to be discussed
          before.
    - [x] Excalidraw docker (at draw.dinnizer.com, secured via caddy auth)
    - [ ] have docker-compose to try new dockers easily (Tryton, ERPNext, Hermes
          agent, Odysseus by PewDiePie, etc.)
- [x] **aumenuilya**:
  - [x] why is it an old version and not the one "running" on the pi ? use SSH
        to create the latest back-up and replace in SSD_1TO (keep the old
        back-up).
  - [x] updating wordpress to its latest version doesn't work....Debug.
- [ ] dinnizer
  - [ ] **App.dinnizer.com**:
    - [x] correct minimally and deploy the dinnizer app at app.dinnizer.com.
    - [ ] make the last debugs/improvements. These come from
          `Dinnizer app todo.csv` (kept as the detailed scratch list until the
          items below are closed; the relevant still-open ones are folded in
          here):
      - [ ] BUG: front UI breaks when a dinner has too many guests or recipes
      - [ ] BUG: `dinner_form`
      - [ ] order index pages with `.order(:last_name, :created_at)`
      - [ ] front: list each recipe's dinners and guests
      - [ ] add a Markdown content editor for recipe descriptions (if an easy
            gem exists)
      - [ ] seed the recipe base with aumenuilya recipes (or link to a recipe
            list)
      - [ ] save photos in the seed so `db:seed` does not drop them
      - [ ] link a recipe's ingredients to each guest's likes and dislikes
      - [ ] allow recipes to be categorized
      - [ ] generate default "initials" pictures for users, guests and recipes
      - [ ] add a per-user stats page
      - [ ] (later/marketing) usecase video, JBB feedback
  - [ ] develop a very simple dinnizer landing page at dinnizer.com for a CFO
        part time service.
    - [ ] serve it as a standalone static Caddy site
    - [ ] write it in HTML with the latest Material Design implementation
    - [ ] use this palette:
          <https://colorhunt.co/palette/f9f7f7dbe2ef3f72af112d4e>
    - [ ] define page contents later
- [ ] tabletop-timer
  - [ ] slightly upgrade the tabletop-timer app ? focus on mobile responsivness
        and upgrade the app's security and usability without changing the code
        significantly as it was and still needs to be the fruit of my work for
        the major part.
- [ ] analytics and monetization
  - [ ] **Google Analytics** :
    - [ ] configure tabletop-timer with G-5E4TWCP28D
    - [ ] configure app.dinnizer with G-SB091QKKGE
    - [x] leave aumenuilya alone because it was set up another way
    - [ ] add advertising/monetization to these three sites?
- [ ] secure server
  - [ ] implement tailscale — **delayed on purpose.** It is a private overlay:
        every device (you and family) must install the app and authenticate
        before reaching a hosted service, which is the wrong trade-off for the
        public family-facing sites already handled well by Caddy auth +
        fail2ban. Its real value is your own remote admin access, so it is a
        later nice-to-have, not a security upgrade over what exists.
  - [x] implement caddy auth for homepage and bentopdf and fail2ban jail after
        several failed attemps.
- [x] update server automatically
  - [x] run ansible-pull on a schedule. Implemented in `roles/base` as a systemd
        timer (`autoconfig-pull.timer`, `OnCalendar=daily`,
        `RandomizedDelaySec=30m`, `Persistent=true`) plus a helper script and a
        oneshot service. Works on both Arch and Debian families.
  - [x] make the daily pull resilient to a dirty checkout: the helper (and
        `bootstrap-server.sh`) force-sync to the remote branch (`fetch` +
        `checkout -f` + `reset --hard` + `clean -fd`) so a file an app rewrote
        through a dotfile symlink cannot break the run.
  - [ ] optionally add a dedicated passwordless-sudo user. The timer currently
        runs as root via systemd, so this is now a hardening nicety, not a
        blocker.
- [ ] implement workstation role
  - [ ] dotfiles:
    - [x] create first CLI/TUI/dotfiles foundation
    - [x] migrate the first CLI/TUI dotfiles from the standalone
          `omarchy-dotfiles` repo into `files/dotfiles/`: `nvim`, `git`, `gh`
          config, `lazygit`, plus the existing
          `bash`/`starship`/`ssh`/`opencode`. Stow runs with
          `--no-folding` so app-written files (gh token, ssh keys, lock files)
          never land in the repo; validated idempotent (`changed=0`) on the VM.
    - [ ] keep migrating remaining CLI/TUI dotfiles as needed. Gotcha: omarchy
          ships machine-specific theme symlinks (nvim `theme.lua`, `btop` theme)
          that must NOT be vendored — omarchy manages them locally. GUI/Omarchy
          desktop config stays out of scope (see below).
    - [x] protect secrets with ansible-vault so nothing lands in this public
          repo unencrypted. `~/.ssh/config.local` is vault-encrypted and
          deployed by copy-decrypt; the `gh` OAuth token is deliberately not
          committed (see [Secrets And Vault](#secrets-and-vault)).
  - [x] test on the disposable Arch/Omarchy VM (`savannarchome`). Self-pull via
        `ansible-pull` validated: base + workstation, Stow dotfiles, and the
        vaulted `config.local` deploy all apply with `failed=0`. See
        [Testing On A VM](#testing-on-a-vm).
  - [x] vault-password-file plumbing is wired end to end (bootstrap script,
        ansible-pull timer, `ansible.cfg`) and proven on the VM.
  - [ ] workstation stays CLI/TUI only for now. GUI/Omarchy config is
        intentionally out of scope (the old Betterbird/Thunderbird automation
        was removed as stale).
- [ ] implement kids role
- [ ] find inspiration in
      [jaylacroix's code](https://github.com/LearnLinuxTV/personal_ansible_desktop_configs/tree/main)
      and eventually omakub's code or Jeff Geerling's code to improve the whole.

### Guidelines for coding agents

#### Objectives

- Use ansible-pull (sudo ansible-pull -U
  <https://github.com/lionel-arnaud/ansible-autoconfig.git> --vault-password-file
  ~/secret.txt -C main) to automate the set-up of any of my family’s computer if
  they ever have to be reinstalled from scratch (on the same or different
  hardware).
- The set-up must be idem-potent so that it can be set to run automatically once
  a day on each of these machine (via a crontab job or else)
- I need to be able to “test” on a virtual machine.

My dotfiles are currently specific to Omarchy and managed with stow
(<https://github.com/lionel-arnaud/omarchy-dotfiles>)... I want to transition from
the dotfiles specific repo to this repo and have stow managed by ansible as part
of the setup. Maintenance of the files need to be feasible and easy.

- Use this for inspiration of structuration, etc.
  <https://github.com/LearnLinuxTV/personal_ansible_desktop_configs/tree/main>
- I’m writing this code also as an opportunity to learn about ansible,
  GNU/linux, neovim, opencode and other coding agents (and vibecoding in
  general), herdr, git, networking, etc. Thus explain all the code, design
  choices, structure, etc in that perspective...
- I would ideally like to lay here the foundations of an auto-config ansible
  setup that will be still valid and usable in 20 years….(comment your code
  profusely in that regard)
- The short term priority is to work on the server but the rest will be
  addressed as well (kids computer, adult's workstations, etc.).

#### Roles

- Server (Serverannah) destined to become a homelab that runs Ubuntu server
  25.10 (headless Optiplex 3070, accessed via SSH) : It is running both natively
  (on bare metal) an Nginx server to host 3 websites (including a complex
  wordpress) and more to come. It's also DNS Filtering with pi-hole (installed
  on bare metal). last, it's running multiple docker services such as frigate
   for cameras, N8N, bentopdf, Jellyfin, Timeshift (to secure backups on 1
  master and 3 different external disks copies), Nextcloud (to manage my data
  and make it accessible to the whole family) and the like. For now, those
  functions are managed on a raspi 4B (192.168.1.100) that should be retired
  soon. You don’t have to keep on serverannah things as they were on the raspi.
  It’s a good opportunity to “improve”.
- Kids are running Linux Mint (xfce but switch to cinnamon is envisaged) on a
  very old macbook. Their goal is gaming and learning. Parental control has to
  be strict
- “Mac” is my wife’s computer (not much to set-up there, she mostly works in a
  browser + GDrive and Spotify)
- Laptop is on Omarchy (hyprland) but could be switched to KDE or Gnome on Arch
  or even be switched to an Debian/Ubuntu distro

#### Extra instructions

- ask whenever in doubt and ask for feedback (i can run commands for you, etc.)
- verify your work as much as possible
- remember as much as you can of these instructions and the other instructions
  to come
- Create a “guidelines.md” inside the directory to describe everything the
  project is about, how it works, terminal commands, etc. Templates on github….

#### Do not do

- do not change code without explaining
- do not change multiples files at once when not strictly connected to the same
  taks/objective at hand

## Agent written readme

This repository is the family `ansible-pull` source of truth.

The active goal is simple:

- one main entry point: `local.yml`
- one common role: `roles/base`
- one server role: `roles/server`
- code that stays readable by a non-expert
- host-specific state stored in obvious places
- configuration changed in git first, not directly on the machine

### Design Rules

- Prefer small Ansible modules over clever shell logic.
- Keep one source of truth per concern.
- Do not encode migration hacks for old machines unless they are still truly
  needed.
- If a value is host-specific, keep it in `host_vars/serverannah`.
- If a file is the real source of truth, store it in `files/` and copy it.

### Active Layout

- `local.yml`: main playbook
- `hosts`: active inventory
- `group_vars/all`: tiny shared defaults only
- `host_vars/serverannah`: server-specific switches, domains, URLs, and hardware
  paths
- `roles/base`: packages, Starship shell init, dotfiles via Stow, ansible-pull
  automation
- `roles/server`: Docker services, reverse proxy, Pi-hole, Nextcloud, Frigate,
  fail2ban, storage bootstrap
- `roles/workstation`: first CLI/TUI and dotfiles foundation for Arch/Omarchy
  workstation testing
- `files/dotfiles/`: Stow packages actually managed by this repo
- `files/serverannah/etc/fstab`: source of truth for `serverannah` storage
  mounts
- `files/pihole/policy/`: Pi-hole adlists and allowlist imported by Ansible

### Current Entry Points

Run locally against the active inventory:

```bash
sudo ansible-playbook -i hosts --limit serverannah local.yml
```

> **This repo is pull-only. Push mode does not work.** `host_vars/serverannah`
> sets `ansible_connection: local` so the nightly `ansible-pull` timer (running
> as root on the box) applies the config with no SSH round-trip.
>
> Overriding that with `-e ansible_connection=ssh` from a laptop looks like it
> should work and does not. Two separate tasks break, both because the control
> node and the target stop being the same machine:
>
> - the dotfiles guard resolves `dotfiles_source_dir` from `playbook_dir` — the
>   *laptop's* checkout path — and then asserts it exists on the **server**;
> - `ansible.posix.synchronize` rsyncs **from** the control node, so any
>   file-seeding task looks for its source on the laptop.
>
> Run it on the target with `ansible-pull`, or via the managed timer. Fixing
> push mode properly is an open item in the ToDo.

Run with `ansible-pull` on the target machine:

```bash
sudo ansible-pull -U https://github.com/lionel-arnaud/ansible-autoconfig.git -C main -d /opt/ansible-pull local.yml
```

When testing on a VM or before public DNS/port forwarding is ready, do not ask
Caddy to obtain public HTTPS certificates yet. Keep the real `serverannah` vars
as the production target, and override only the staging network edge explicitly:

```bash
sudo ansible-pull -U https://github.com/lionel-arnaud/ansible-autoconfig.git -C main -d /opt/ansible-pull local.yml \
  -e 'server_reverse_proxy_auto_https=false server_reverse_proxy_published_ports=["8081:80"] server_reverse_proxy_sites=[{"hostname":"homepage.localtest.me","upstream":"homepage:3000"},{"hostname":"bentopdf.localtest.me","upstream":"bentopdf:8080"},{"hostname":"game-timer.localtest.me","upstream":"game-timer:80"},{"hostname":"pihole.localtest.me","upstream":"pihole:80"}]'
```

This keeps VM testing local and avoids confusing Let's Encrypt failures while
the server is not publicly reachable.

Bootstrap a fresh server that does not have Ansible yet:

```bash
sudo ./scripts/bootstrap-server.sh
```

Dry-run a local checkout when testing:

```bash
sudo ansible-playbook -i hosts --limit serverannah local.yml --check
```

### Secrets And Vault

This is a **public** repo, so secrets are handled at two levels:

1. **Generated on the host, never committed.** Service passwords (database
   passwords, Nextcloud admin password, Dinnizer secret key base, etc.) are
   generated on the target machine into `/etc/ansible/secrets/` on first run and
   reused afterwards. They never enter git at all. This is the default and
   covers most services today.
2. **Committed but encrypted with `ansible-vault`.** For files that genuinely
   have to live in the repo (for example SSH config or private keys, API tokens
   in dotfiles), encrypt them with `ansible-vault` before committing. The
   encrypted blob is safe in a public repo; only the password that unlocks it is
   secret.

The vault password itself is never committed. Supply it one of two ways:

```bash
# Per command:
sudo ansible-playbook -i hosts local.yml --vault-password-file ~/.ansible-vault-pass

# Or for every run: uncomment vault_password_file in ansible.cfg.
```

The same `--vault-password-file` flows through `scripts/bootstrap-server.sh`
(`AUTOCONFIG_VAULT_PASSWORD_FILE`) and the managed `autoconfig-pull` timer
(`autoconfig_vault_password_file`), so a scheduled pull can decrypt vaulted
files unattended. Password-file names like `~/.ansible-vault-pass`, `secret.txt`
and `*.vault-pass` are already in `.gitignore`.

Common commands:

```bash
ansible-vault encrypt files/dotfiles/ssh/.ssh/config   # encrypt in place
ansible-vault edit    files/dotfiles/ssh/.ssh/config   # edit encrypted
ansible-vault view    files/dotfiles/ssh/.ssh/config   # read without decrypting to disk
```

> Keep `vault_password_file` commented in `ansible.cfg` until at least one
> encrypted file exists, otherwise runs fail looking for a password they do not
> need.

### Linting

Linting is local-only. There is no GitHub Action and no cloud cost: everything
runs on your machine.

- `scripts/lint.sh` runs `yamllint`, `ansible-lint`, **and the rendered-template
  test harness**. On first run it builds a throwaway virtualenv (`.lint-venv/`,
  gitignored) so nothing is installed system-wide. Run it any time:

  ```bash
  ./scripts/lint.sh
  ```

- `tests/render_shell_templates.py` is the part the linters cannot do. yamllint
  and ansible-lint only ever see the YAML *before* Jinja substitution, and both
  passed cleanly while this repo shipped a folded scalar that fed `python3 -c`
  an indented first line, and a systemd unit whose `ExecStart` was the literal
  text `{{ opencode_binary }}`. The harness renders each shell-producing
  template with the role defaults and runs the result through `shellcheck`.

  Two details are what make it a test rather than decoration, each verified by
  deliberately reintroducing the bug:
  - Rendering uses `StrictUndefined`. Jinja's default turns a typo'd variable
    into an empty string and the harness would pass.
  - `shellcheck` runs at `--severity=info`, because SC2086 (unquoted expansion —
    the word-splitting class that once created two directories literally named
    `{{` and `}}`) is filtered out at `warning`.

  It does **not** catch a template that renders to valid shell but does the
  wrong thing; the TCP-only firewall guard rendered perfectly for months.

- A **pre-commit hook** is an optional convenience: a check that git runs
  automatically every time you `git commit`, refusing the commit if linting
  fails (so mistakes never reach history). It is configured in
  `.pre-commit-config.yaml` and is also fully local. One-time setup:

  ```bash
  pipx install pre-commit   # or: pip install --user pre-commit
  pre-commit install        # installs the hook into .git/hooks
  pre-commit run --all-files  # optional: lint everything now
  ```

Config lives in `.yamllint` (lenient: long lines warn, real booleans only) and
`.ansible-lint` (`basic` profile; the role-prefix naming rule is deliberately
skipped because this repo names variables by concern, e.g. `nextcloud_`,
`pihole_`, not `server_nextcloud_`). `yaml[line-length]` is warn-listed in both,
because the long lines here are inline SQL and shell one-liners that only get
harder to read when wrapped — the two linters are configured to agree on that
rather than contradict each other.

The suite currently reports **0 failures**, and the hook is installed.

### Testing On A VM

The workstation role is proven on a disposable Arch/Omarchy VM (`savannarchome`)
before touching a real laptop. The VM configures **itself** with `ansible-pull`,
exactly like a real new machine would, so no host-to-guest SSH or
port-forwarding is needed.

GNOME Boxes uses QEMU user-mode networking (the guest gets `10.0.2.15`, which
the host cannot reach), so the self-pull model is not just convenient, it is the
only simple option. Three lines inside the VM:

```bash
# 1. ansible-pull targets the inventory host whose name matches the machine's
#    hostname, so the VM must call itself savannarchome.
sudo hostnamectl set-hostname savannarchome

# 2. The vault password (same one used on the laptop) so config.local can decrypt.
printf '%s' 'YOUR_VAULT_PASSWORD' > ~/secret.txt && chmod 600 ~/secret.txt

# 3. Fetch and run the bootstrap: installs git+ansible, clones, installs
#    collections, runs ansible-pull for base + workstation.
curl -fsSL https://raw.githubusercontent.com/lionel-arnaud/ansible-autoconfig/main/scripts/bootstrap-server.sh \
  | sudo env AUTOCONFIG_VAULT_PASSWORD_FILE=/home/lion/secret.txt sh
```

A healthy first run ends with `failed=0` and shows, among others, the
`Deploy vault-encrypted dotfiles (decrypted into place)` task as `changed` (a
wrong vault password would fail there). Reset or snapshot the VM freely between
runs; the playbook is idempotent.

**Live access from the host (for fast iteration):** the self-pull above is
enough to validate a change, but to drive `--check` runs against the VM from the
host (or just poke around), a reverse SSH tunnel avoids fighting GNOME Boxes'
NAT. GNOME Boxes user-mode networking reaches the host at `10.0.2.2`, so run
**one command in the guest** to dial out and forward host port 2222 back to the
guest's sshd, then **one on the host** to install your key through it:

```bash
# In the GUEST: hold open a reverse tunnel (host:2222 -> guest:22).
ssh -fN -R 2222:127.0.0.1:22 lion@10.0.2.2

# On the HOST: authorize your key over that tunnel.
ssh-copy-id -p 2222 lion@127.0.0.1
```

After that, `ssh -p 2222 lion@127.0.0.1` works, and because
`host_vars/savannarchome` already points at `127.0.0.1:2222`, so does
`ansible -i hosts savannarchome -m ping`. The tunnel lasts until the VM reboots
or that `ssh` process is killed; wrap it in `autossh` + a systemd user unit if
you want it to persist.

**Clipboard with GNOME Boxes (Hyprland guest):** install `spice-vdagent` and
`wl-clipboard`, enable `spice-vdagentd`, and add `exec-once = spice-vdagent`
(without `-x`) to the Hyprland config so the client starts inside the Wayland
session. Sync is then automatic (normal copy/paste, no special shortcut). If the
client comes up in X11 mode (`spice-vdagent -x`), it cannot read the Wayland
clipboard; `pkill -x spice-vdagent` then re-run `spice-vdagent` from a terminal
in the live session.

### Why `requirements.yml` Stays

`requirements.yml` is not just documentation.

It is the executable dependency manifest used by the bootstrap script and the
managed `autoconfig-pull` helper to install required collections such as:

- `community.general`
- `community.docker`
- `ansible.posix`

Keeping that in code is simpler and safer than hoping the README stays in sync.

### What `group_vars/all` Still Does

Very little, by design.

It now only holds shared defaults that are still useful for the active code:

- `desktop_user`
- `ansible_python_interpreter`

Anything more specific belongs in host vars or role defaults.

### Storage Model

Storage was simplified on purpose, but Ansible does not replace the whole system
`/etc/fstab` anymore. The OS installer should keep owning `/`, `/boot`, EFI and
swap because their UUIDs are created during installation.

The repo ships only the data-disk entries:

- source: `files/serverannah/etc/fstab`
- deployed into: a marked Ansible block inside `/etc/fstab`

The server role then:

1. inserts or updates the marked data-mount block
2. creates the mount points declared in that source file
3. runs `mount -a`

This keeps data mounts versioned without hard-coding boot/root UUIDs that belong
to one specific installation.

### Disaster Recovery

Backups are Borg (see `roles/server/tasks/backup.yml`): a daily systemd timer
dumps the databases and creates an archive of the `/opt/*` service dirs into an
encrypted repo on the backup disk.

- **Repo:** `/mnt/back-up/borg/serverannah` (encryption `repokey` — the key
  lives _in_ the repo, unlocked by the passphrase, so the repo + passphrase are
  all you need to restore anywhere).
- **Passphrase:** `/etc/ansible/secrets/borg-passphrase`, generated on the host,
  **never** in this repo. Losing it means losing every archive — back it up
  separately (a password manager).

The restore path has been **tested on a fresh Ubuntu VM** (a full archive
extracts cleanly: every file decrypts, DB dumps intact). To restore on a new
machine you only need `borgbackup`, the repo (copy the disk, or stream it), and
the passphrase:

```bash
export BORG_PASSPHRASE='…'
borg list  /path/to/repo                       # pick an archive
borg extract /path/to/repo::serverannah-<ts>   # restores ./opt/... and ./var/...
```

borg's standalone binary (GitHub releases, `borg-linux-glibc236`) needs no root,
so a restore works even on a machine where you cannot install packages. Match
the binary's major version to the one that wrote the repo (currently `1.4.x`).

### Off-Site Backups

Every local copy of the data lives in one room — the main SSD, the backup disk,
the Timeshift disk. A fire, a theft or a flood takes all three at once, so the
Borg repository is mirrored to Google Drive after every run.

**How it works.** The backup runner does its normal `borg create` → `borg prune`
→ `borg compact`, then:

```sh
rclone sync "$BORG_REPO" 'Google Drive Perso:backups/borg/serverannah' \
  --config /home/lion/.config/rclone/rclone.conf --transfers 4 --checksum
```

**Why a plain mirror is safe here.** Borg segments are append-only and
immutable, so an incremental run only ever uploads *new* segments — it is not
re-uploading the archive each night. Running the sync *after* `compact` (never
before) means the remote never keeps segments the local repo has already pruned.

**Why `--config` is mandatory.** The backup runs as `root`; the Google OAuth
token belongs to the desktop user. Without an explicit config path, rclone reads
root's own empty config and reports that the remote does not exist. The runner
skips the sync with a warning — rather than failing the whole backup — if that
file is unreadable.

**Encryption.** The repo is `repokey`-encrypted, so Google only ever stores
opaque segments. No second encryption layer (`rclone crypt`) is used or needed.
The corollary is the usual one: *the passphrase is the backup.* It is held in
Bitwarden, deliberately off this machine.

**Size and cost.** The repo is ~6 GB against ~81 GB free on a 200 GB Drive
plan, so it fits with a wide margin. The first run uploads the whole repo;
after that only new segments move, typically tens of MB a night. Set
`backup_offsite_bwlimit` (e.g. `"8M"`) if that first upload saturates the
uplink.

**Tuning.** `backup_offsite_enabled`, `backup_offsite_remote`,
`backup_offsite_path`, `backup_offsite_transfers`, `backup_offsite_bwlimit` and
`backup_offsite_rclone_config` in `roles/server/defaults/main.yml`.

**Restoring from the off-site copy.** Pull it down and treat it as a normal
Borg repo — nothing about the restore path in
[Disaster Recovery](#disaster-recovery) changes:

```sh
rclone sync 'Google Drive Perso:backups/borg/serverannah' /tmp/borg-restore
BORG_PASSPHRASE=... borg list /tmp/borg-restore
```

### Adding A New Public Site

Order matters, and getting it wrong costs an hour. **Create the DNS record
first, then add the site to `server_reverse_proxy_sites`.**

Caddy requests a certificate as soon as a hostname appears in its config. If the
name does not resolve publicly yet, Let's Encrypt fails the challenge with
`NXDOMAIN`, and CertMagic backs off with a growing retry interval — it will
recover on its own, but not quickly, and in the meantime the site answers with a
TLS `internal error` rather than anything readable. After enough production
failures CertMagic also starts trying the Let's Encrypt *staging* endpoint,
whose certificates browsers do not trust, which makes the symptom look worse
than it is.

If you already added the site before the DNS record, restart the proxy once the
record resolves publicly:

```bash
docker restart server-reverse-proxy
```

That clears the backoff and the certificate is issued within a minute or so.
Verify it is a *production* certificate, not staging:

```bash
curl -sv https://newsite.example.com/ 2>&1 | grep -iE "issuer:|expire date"
# issuer: C=US; O=Let's Encrypt; ...   <- good
# issuer: ... (STAGING) ...            <- still on staging, restart again
```

One more trap on the LAN: Pi-hole caches the `NXDOMAIN` from before the record
existed, so the new name keeps failing *from inside the house* long after it
works everywhere else. `pihole restartdns` may not clear a negative entry;
restarting the container does:

```bash
docker restart pihole
```

### Seeding Uptime Kuma Monitors

Uptime Kuma 1.x has **no REST API for monitors** — `/api/monitors` returns the
single-page-app shell, not data. Everything goes over socket.io, so there is no
supported CLI, and nothing to drive from Ansible.

`scripts/helpers/seed-uptime-kuma.py` therefore uses the unofficial `uptime-kuma-api`
library, and is deliberately a **one-shot seeder rather than config
management**. That distinction matters: an upstream change to an unofficial API
breaking a tool you run by hand costs you ten minutes, while the same change
inside the nightly `ansible-pull` would break every host at once. Re-running is
safe — existing monitors are left untouched — but it will not reconcile or
remove monitors you have since edited. **The UI stays the source of truth for
monitors; this just saves the initial clicking.**

Monitors are generated from `server_reverse_proxy_sites` in host_vars — the same
list Caddy's config is rendered from — so a site cannot be proxied and silently
unmonitored.

```bash
# See the plan without touching anything (needs no credentials, no network):
./scripts/helpers/seed-uptime-kuma.py --dry-run

# Apply it, from serverannah:
sudo KUMA_USERNAME=admin KUMA_PASSWORD='...' sh scripts/helpers/seed-uptime-kuma.sh
```

The wrapper runs the seeder in a throwaway container **on the shared Docker
network**, talking to `http://uptime-kuma:3001` directly. Pointing it at
`https://status.dinnizer.com` instead would mean satisfying Caddy's basic auth
during the socket.io handshake *and* sending the Kuma admin password across the
public internet to reach a service on the same machine. Credentials can also go
in `/etc/ansible/secrets/uptime-kuma-credentials` (two lines: user, password)
instead of the environment.

**Basic-auth'd sites are monitored through their auth**, using the shared Caddy
password. Without that, a monitor only ever sees Caddy's `401` and would report
green while the application behind the gate was dead. Where the password is not
readable the seeder says so and falls back to accepting the `401` — which still
proves DNS, TLS and Caddy are alive, but nothing beyond them.

Redirect-only hosts (`aumenuilya.fr`, `www.tabletop-timer.com`) are checked with
redirect-following **off**: they are healthy when they redirect, and following
would silently test the target instead, hiding a broken redirect.

### Dead-Man's Switch

`OnFailure=` reports a job that ran and failed. It cannot report a job that
**never ran** — a masked timer, a box left switched off, a dead uplink, a hung
`git fetch`. From inside the house those are indistinguishable from silence, and
silence looks exactly like success. Only something outside can notice.

So a successful pull pings an external monitor, and that monitor alerts when the
ping is **late**:

```ini
ExecStartPost=-/usr/bin/curl -fsS --max-time 20 -o /dev/null {{ heartbeat_pull_url }}
```

Two details matter. `ExecStartPost` runs only when `ExecStart` succeeded, so a
failed run does not refresh the heartbeat. The leading `-` makes the ping
non-fatal, so an outage at the monitoring provider cannot fail the pull itself.

#### Setting it up

`heartbeat_pull_url` is empty by default, which disables the ping. Put a URL in
it and the watchdog arms itself on the next run. There are two options, and they
cover *different* failures:

**Option A — Uptime Kuma "Push" monitor.** No signup, no third party; it is
already running at `status.dinnizer.com`.

1. In Uptime Kuma: **+ Add New Monitor** → Monitor Type **Push**
2. Name it (e.g. *serverannah nightly pull*), set **Heartbeat Interval** to
   `93600` seconds (26 hours — the nightly job plus margin)
3. Save. It shows a **Push URL** like `https://status.dinnizer.com/api/push/AbC123`
4. Write it to `/etc/ansible/secrets/heartbeat-pull-url` on the host —
   **not** into `host_vars`, which lives in this public repository:

   ```bash
   printf '%s\n' 'https://status.dinnizer.com/api/push/XXXX?status=up&msg=OK&ping=' \
     | sudo tee /etc/ansible/secrets/heartbeat-pull-url >/dev/null
   sudo chmod 600 /etc/ansible/secrets/heartbeat-pull-url
   ```

   That directory is in `backup_paths`, so the URL survives a rebuild.
5. Set its notification to the existing ntfy topic

`status.dinnizer.com` sits behind Caddy basic auth, and a `curl` from a systemd
unit cannot present those credentials — so the push path is exempted from it in
`host_vars` via `basic_auth_except_paths: ["/api/push/*"]`. That is safe: the
push token in the URL is already the credential, which is the whole design of a
push monitor. Reading the dashboard still requires the password. Without that
exemption the ping returns 401 and the watchdog can never report in.

Catches: the timer being masked, disabled, erroring before it starts, or the pull
silently not running. **Cannot** catch the whole machine being down — Uptime Kuma
would be down with it.

**Option B — an external service** (healthchecks.io, Cronitor, Better Stack; all
have free tiers). Create a free account, add a check with a ~26 hour period, and
write its ping URL to the same file.

Catches everything Option A does **plus** the box being off, unplugged, or
cut off from the internet — because the watcher is not in the house.

Running both is reasonable: point `heartbeat_pull_url` at Option B and add
Option A as a second monitor, since a push URL is just a URL.

Either way it is a **capability URL**: anyone holding it can silence the alarm by
pinging it themselves. That is why it is read from a root-only file on the host
instead of a variable — this repository is public, and a ping URL committed here
would be a watchdog anyone could switch off. `heartbeat_url_file` sets the path;
the helper exits quietly when the file is absent, so an unarmed host is a normal
state rather than a failure.

**Why this is not built on ntfy**, despite the ntfy documentation describing
exactly this pattern (schedule a message, cancel it on each successful run, let
it fire when the runs stop): *it was tested and it does not hold.* Against the
free public server, `DELETE /<topic>/<id>` returns HTTP 200 and the scheduled
message fires anyway. It held in one of three trials, including a failure with
an 85-second cancellation margin. A watchdog that raises false "server is DOWN"
alarms is worse than no watchdog, because you stop believing it. If ntfy
scheduling is ever revisited, re-run that test first.

### Dotfiles Model

Dotfiles are handled with:

- Ansible as orchestrator
- Stow as symlink engine for plaintext configs
- `ansible-vault` + a copy-decrypt step for the few configs that contain secrets

Plaintext packages live under `files/dotfiles/<package>/` mirroring the home
layout. The exact set applied to a machine is whatever its
`dotfiles_stow_packages` lists (see the host's `host_vars/` file) — that list is
the single source of truth, so this README does not re-enumerate it. Every
package directory there is symlinked into `$HOME` by Stow.

Stow runs with **`--no-folding`** on purpose. By default Stow "folds" a config
directory that does not yet exist into a single directory symlink pointing into
the repo (e.g. `~/.config/gh -> repo/.../gh`). Because our repo is a _public_
checkout managed in place, any file an app then writes into that dir (gh's
`hosts.yml` token, ssh `known_hosts`, nvim lock files) would be written straight
into the git tree. `--no-folding` keeps every directory a real local dir and
symlinks only the curated files, so app-written files stay local. The pre-stow
"preserve" step is directory-aware to match (it leaves an already-managed dir
alone instead of rebuilding it every run, which keeps pulls idempotent).

Tmux was previously managed as a Stow dotfile but has been replaced by
**herdr** on Omarchy, so the `tmux` package and its dotfile tree are gone.
If you want tmux back on a Debian-only host, add `tmux` to
`dotfiles_stow_packages` in that host's `host_vars/` and re-introduce the
package list entry under `base_packages_by_family.Debian.cli`.

Do not vendor machine-specific symlinks. Omarchy points some configs at the
active theme (for example nvim `lua/plugins/theme.lua` or btop theme files) via
absolute symlinks into its local theme state. Those are gitignored / left out;
omarchy recreates them locally, and Stow `--no-folding` would (correctly) refuse
them.

Note two deliberate boundaries:

- `gh` ships only `config.yml`. `hosts.yml` holds a GitHub OAuth token and is
  **not** committed, even encrypted — let `gh auth login` recreate it per host.
- the `ssh` package ships only the sanitized public config, which does nothing
  but `Include ~/.ssh/config.local`. The real host aliases live in that local
  file.

Secret dotfiles (currently `~/.ssh/config.local`) are stored **vault-encrypted**
under `files/dotfiles-secret/` and listed in `dotfiles_secret_files`. They
cannot be Stow-symlinked, because the symlink would hand the application the
ciphertext; instead Ansible copies them into place and decrypts on the way (see
[Secrets And Vault](#secrets-and-vault)). To update one:

```bash
ansible-vault edit --vault-password-file ~/secret.txt files/dotfiles-secret/ssh/config.local
```

**Editing a managed dotfile.** After a pull the live file (e.g.
`~/.config/espanso/match/base.yml`) is a symlink into `/opt/ansible-pull`, the
**root-owned** pull checkout — so editing it in place fails as read-only
(`E166` in nvim). That is by design. Always edit the **source** in your dev
clone, then push and pull:

```bash
nvim ~/Documents/ansible-autoconfig/files/dotfiles/<pkg>/<path>
cd ~/Documents/ansible-autoconfig && git commit -am "..." && git push
sudo ansible-pull -d /opt/ansible-pull -U https://github.com/lionel-arnaud/ansible-autoconfig.git -i hosts local.yml --vault-password-file ~/secret.txt
```

(Never `sudo`-edit the `/opt/ansible-pull` copy: it is untracked and the next
pull overwrites it.)

**Espanso** is managed here too (package `espanso`, config under
`files/dotfiles/espanso/`). The binary is a special case: it is **not** in the
Arch official repos, so the workstation role builds `espanso-wayland` from the
**AUR** with `yay`, as the desktop user, guarded so it only compiles when the
binary is missing (a one-time cost on a fresh machine). Because the AUR helper
calls `pacman`, an **unattended** from-scratch build needs the desktop user to
`sudo` without a prompt; on a single-user Omarchy box that is the norm.
Otherwise the build is the one step that needs a hand — run `yay -S
espanso-wayland` once and the next pull skips it. (`secret.txt` is the *vault*
password, not a sudo password, and would not help here anyway — the prompt comes
from `yay`'s internal `pacman` call, not from Ansible's `become`.)

GUI/Omarchy desktop config beyond the migrated packages (parts of Hyprland,
theme-specific bits) stays out for now; the workstation role is otherwise
CLI/TUI focused.

### Pi-hole Source Of Truth

Pi-hole policy import now reads from:

- `files/pihole/policy/adlists_enabled.txt`
- `files/pihole/policy/allowlist_exact.txt`

Raw backups are not meant to be the long-term source of truth.

### Serverannah Notes

`serverannah` is the current production target.

Important host-specific values live in `host_vars/serverannah`, including:

- enabled services
- public domains
- Pi-hole mode
- hardware-specific device paths
- backup source paths still needed for migration

### Trading Research Agent

A biotech research assistant that runs on the Raspberry Pi: role
`roles/trading_agent`, package `trading_agent/`, enabled per host with
`trading_agent_enabled` (on for the Pi only). Design notes, the acceptance
checklist and every decision with its reasoning live in
`docs/orchestrator/trading-agent/`.

**What it does.** It watches upcoming results for late-stage clinical trials run
by companies in the XBI and IBB biotech fund holdings, using ClinicalTrials.gov
and a market news feed. For each material one, a language model (reached through
opencode, so the model is interchangeable) researches a brief, and the operator is
asked for a call over Telegram: yes, no or skip, a confidence from 1 to 5, and
free-text reasoning. The brief explains the field's vocabulary as it goes, and
calls are scored against real results, measured against the base rate for that
phase.

**How a trade happens.** Catalyst → model proposal → *view gate* (no opening
position without a recorded human call) → *guardrails* → broker. The guardrails
are pure, deterministic code with no model, network or clock inside them:
position size, total deployed, trades per day, a latched daily loss breaker, and
rejection of non-finite amounts. The broker refuses any order that did not pass
through them.

**Safety properties, each covered by tests:**

- a Telegram `/stop` halts trading and cancels resting orders, and works while
  the reasoning loop is hung, because commands run on their own thread and write
  straight to SQLite; only `/resume` clears it;
- live trading needs two independent settings changed; either one alone keeps
  the paper account;
- orders carry idempotency keys and the account is reconciled at start-up, with
  the broker treated as the source of truth, so a restart cannot double-fill;
- an optional human-approval gate above a dollar threshold is wired but off, and
  an unanswered request expires as a denial, never an approval;
- every step from catalyst to order is written to a correlated audit log, with
  credential-shaped values redacted.

**Talking to it.** `/status`, `/today` (what it did, and why), `/stop`,
`/resume`, `/help`. Answer a question by replying `yes 3 reasoning…`; several at
once, or a change of mind before results, by starting each line with the ticker.

**Operations.** It runs as a systemd service with restart limits and
failure notifications. Each night it snapshots its databases consistently and
pushes them, write-only, to the server, where the existing Borg job takes them
off-site. The same push carries a daily report page, rendered on the Pi and served
by the server as a static file behind the reverse proxy's password. It is labelled
as a daily snapshot, and warns when it is older than expected.

### Conventions For Future Changes

- package lists should stay in role defaults
- hostnames, domains, and paths should stay in host vars
- static config files should go under `files/`
- comments should explain why a choice exists, not narrate every line

### Known Reality

- the old raspi still matters as migration knowledge, but should not dictate the
  final design
- public DNS and NAT still need deliberate validation before full production
  cutover
- `ansible-pull` may print a hostname-pattern warning during its internal git
  step; the actual playbook result matters more than that warning

## Jellyfin notes

Jellyfin replaces Plex in this setup. It is fully free, has no claim
flow, no Plex Pass tier, and ships the same client apps (iOS, Android,
Roku, smart TVs, web). Caddy on port 443 fronts `jelly.dinnizer.com`
→ `jellyfin:8096` over the shared docker network.

### First-run setup was automated

The role runs the equivalent of the Jellyfin setup wizard via the same
HTTP endpoints the UI uses, in this order:

1. `POST /Startup/Configuration` → set UI culture / metadata country
2. `POST /Startup/FirstUser` → create `{{ jellyfin_admin_username }}`
   with a 32-char password generated on the host
3. `POST /Startup/RemoteAccess` → enable remote access (clients use
   the local LAN URL, but enabling this lets the official mobile apps
   reach the server through Caddy)
4. `POST /AuthenticateByName` → harvest an access token
5. `POST /Library/VirtualFolders` → create each entry in
   `jellyfin_libraries`

All API calls are idempotent — re-running the role is a no-op once
the wizard has run and the libraries exist.

### Admin password

Generated once on first run, stored at
`{{ jellyfin_admin_password_file }}` (mode 0600). The role uses it to
create the user and authenticate subsequent API calls. If you ever
need to log in to Jellyfin Web, the password is there:

```bash
ssh serverannah 'sudo cat /etc/ansible/secrets/jellyfin-admin-password'
```

