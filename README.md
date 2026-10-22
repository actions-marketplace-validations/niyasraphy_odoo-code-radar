# odoo-code-radar

**Protect your Odoo intellectual property: find unauthorized copies of your proprietary apps on GitHub.**

When a customer buys your app and pushes their addons to a public repo, anyone can take it from
there. odoo-code-radar watches GitHub for your proprietary Odoo apps, tells you about each new
unauthorized copy once, and hands you a ready DMCA notice draft. You decide what to do with it.

Free and open source. It runs only on your machine or in your own GitHub Actions. There is no server,
no account and no service behind it, so your token and results never reach the authors of this tool.

![odoo-code-radar demo: a scan finds unauthorized copies, opens GitHub issues with DMCA drafts, and runs on a schedule](https://raw.githubusercontent.com/niyasraphy/odoo-code-radar/main/docs/demo.gif)

```
$ odoo-code-radar scan --author "Your Company"
Watching 30 modules (12 open-license modules skipped, see --include-lgpl)
Searching GitHub. Code search allows 10 queries a minute, so this takes about 8 min.

     Module                 License  Repository                                    Confidence  Forks
 🔴  your_module_accountant OPL-1    https://github.com/radar-demo-1/odoo18-addons  high (110)  3

1 new unauthorized copy, 0 already reported. DMCA drafts are in the report.
Report: reports/odoo-code-radar-2026-10-19-061502.md
```

## Three ways to use it

| | For | Setup |
|---|---|---|
| **[Template](https://github.com/niyasraphy/odoo-code-radar-template)** | most vendors: nothing to install | **Use this template** → Private, add your author name and a token in Settings, run |
| **CLI** | a one-off check or your own server | `pipx install odoo-code-radar`, then `odoo-code-radar scan --author "Your Company"` |
| **CLI + `schedule`** | automatic scans set up from the terminal | `odoo-code-radar schedule weekly` (this machine) or `--github` (GitHub Actions) |

### The template: weekly scans without installing anything

1. Open [odoo-code-radar-template](https://github.com/niyasraphy/odoo-code-radar-template) →
   **Use this template** → **Create a new repository** → choose **Private**.
2. In your new repo: Settings → Secrets and variables → Actions:
   - **Variables** tab: `RADAR_AUTHOR` = your author name on apps.odoo.com
   - **Secrets** tab: `RADAR_TOKEN` = a [fine-grained token](https://github.com/settings/personal-access-tokens/new)
     (Public repositories, read-only, no extra permissions)
3. Actions → **Odoo Code Radar** → **Run workflow**.

It then runs every Monday. Each unauthorized copy becomes an issue in your repo, with a DMCA draft, and GitHub
emails you.

## How it works

1. **Your module list** comes from one of two places:
   - **Your author name** on apps.odoo.com. Quick to set up. Results stay on your machine.
   - **Your own GitHub repo** (or a local addons folder). More accurate, since it reads your real
     manifests. New unauthorized copies become **GitHub issues in that repo**, so GitHub emails you.

   Only the technical name, the manifest name, the license and the author are read. Your code is never
   read or uploaded.

2. **Searching.** For each module, GitHub is searched for manifests in a folder with your technical
   name, for manifests with your module name and author, and for repos named after your module.

3. **Checking.** Every hit's manifest is read (parsed, never executed) and scored:

   | Evidence | Points |
   |---|---|
   | Folder name is your technical name | 40 |
   | Manifest name matches (any Odoo version) | 40 |
   | Manifest author is you | 30 |
   | Manifest website is yours | 10 |

   80+ is high confidence, 50+ medium. Medium and up are reported by default.

4. **Licenses.** OPL-1 and other proprietary modules are always watched. LGPL-3 and other open-source
   licenses allow buyers to share the module, so those are off by default (`--include-lgpl` turns them on).

5. **Reporting.** Each unauthorized copy (one module in one repo) is reported once. Every run writes a Markdown and
   JSON report to `reports/`, ending with one DMCA notice draft for all new copies, laid out like
   [GitHub's takedown form](https://github.com/contact/dmca): whole repositories and single folders
   listed separately, and only the forks that still contain your module.

odoo-code-radar never files takedowns itself. Many copies are published by accident, and a friendly message to the
repo owner is often enough. A takedown is a legal statement that you make.

## Install

```
pip install odoo-code-radar
```

GitHub only allows code search when logged in, so a token is needed. If you use the GitHub CLI
(`gh auth login`), it is picked up automatically. Otherwise set `GITHUB_TOKEN`:

| Mode | Token |
|---|---|
| `--author` | Any token. A [fine-grained token](https://github.com/settings/personal-access-tokens/new) with no permissions is enough. |
| `--repo` | Fine-grained token on that repo with **Contents: Read** and **Issues: Read and write**. |

## Your token and your data

odoo-code-radar is a program you run yourself. The people who publish it run no server or service,
and receive nothing from you.

- **Your token is used only by the program running on your machine** (or in your own GitHub Actions
  run). It is read from your environment, the GitHub CLI, or the saved token file, kept in memory,
  sent only to GitHub (`api.github.com` and `raw.githubusercontent.com`), and never printed or
  logged. The code refuses to send it to any other host.
- **It is saved only if you schedule scans on this machine**, because nobody is there to type it in.
  It then goes to one file, `~/.config/odoo-code-radar/token`, created readable only by you
  (`chmod 600`). If that file ever becomes readable by others, odoo-code-radar refuses to use it.
  It never goes into the config file, the scheduler entry or the logs. `schedule remove` offers to
  delete it.
- **With `schedule --github`, nothing is saved on your machine.** The token is stored as an encrypted
  secret in your own private repo, through your GitHub CLI login.
- **There is deliberately no `--token` option**, because command-line arguments end up in your shell
  history. **The config file refuses token or password keys**, because config files get committed.
- **Requests to apps.odoo.com never carry your token.**
- **What leaves your machine:** search queries to GitHub (your technical names, module names and
  author name) and reads of public manifests. Nothing else, and nothing to us.
- **What stays local:** your module list, the results, `reports/` and `.odoo-code-radar/`. With
  `--repo`, issues are opened in your own repo with your own token.
- **Issues only go to private repos.** They show where copies of your apps are, so odoo-code-radar checks the
  repo's visibility first and refuses to open issues in a public one.
- **Least privilege:** use a fine-grained token limited to the repos it needs, with only the
  permissions above, and an expiry date. Revoke it at any time in your GitHub settings.

The code is short and open, so you can check all of this yourself: the token handling is in
[`github.py`](src/odoo_code_radar/github.py) and [`tokens.py`](src/odoo_code_radar/tokens.py).

## Use

### By author name: results on your machine

```
odoo-code-radar modules --author "Your Company"   # check which modules it found
odoo-code-radar scan --author "Your Company"
```

Already-reported copies are remembered in `.odoo-code-radar/reported.json`.

### From your repo: unauthorized copies become issues

```
odoo-code-radar scan --repo you/odoo-apps --branch 17.0 --branch 18.0
```

Each new unauthorized copy opens an issue in `you/odoo-apps` with the evidence and a DMCA draft, and GitHub emails
you as usual. The issues are the memory: once an issue exists (open or closed), that copy is never
reported again. Close it when it is handled.

Use `--issues-repo you/radar-reports` to send issues elsewhere, or `--no-issues` to keep results local.

### Config file

`odoo-code-radar init` asks a few questions and writes `odoo-code-radar.yml`, which `scan` then picks
up on its own:

```yaml
author: Your Company
sources:
  - repo: you/odoo-apps
    branches: ["17.0", "18.0"]
  - path: ~/odoo/custom_addons
include_lgpl: false
min_confidence: medium
ignore_owners: [you, your-company]   # your own accounts
ignore_repos: [customer/allowed-repo]
exclude_modules: [some_free_module]
# issues_repo: you/radar-reports
```

Options given on the command line override the file.

## Run it automatically: daily, weekly or monthly

Run `schedule` in the folder with your `odoo-code-radar.yml`. There are two ways.

### On this machine

```
odoo-code-radar schedule weekly            # or daily, monthly; --at 07:30 for another time
```

- Asks for your token (hidden while you type) and saves it to a file only you can read.
- Checks that the token works and can read your module repo.
- Asks where results should go, when you use `author` only:
  1. **issues in a private repo**, so GitHub emails you, or
  2. **only files on this machine**: `reports/` plus a desktop notification.

  With a module repo, issues go to that repo, which must be private.
- Installs a job with your system's scheduler: a systemd timer on Linux (cron where systemd is
  missing), launchd on macOS, Task Scheduler on Windows. With systemd and launchd, a scan missed while
  the machine was off runs when it is back.

On a Linux server, also run `sudo loginctl enable-linger $USER` so scans run while you are logged out.

```
odoo-code-radar schedule status            # next run, last result, recent log lines
odoo-code-radar schedule remove            # stop it (and optionally delete the saved token)
```

### On GitHub Actions (no server, your machine can be off)

1. Create an empty **private** repo for the results: https://github.com/new
2. Run:

   ```
   odoo-code-radar schedule weekly --github
   ```

   It asks for the repo name, checks that it is private, adds the workflow and your
   `odoo-code-radar.yml` to it, stores your token as the encrypted `RADAR_TOKEN` secret, and starts the
   first scan. Times are in UTC (default 05:17).

The setup uses your [GitHub CLI](https://cli.github.com) login (`gh auth login`, plus
`gh auth refresh -s workflow` once). The scan token can therefore stay read-only: **Contents: Read** on
your module repo, or no permissions with `author` only. Issues are opened with the workflow's own
token. New unauthorized copies become issues in that repo, and GitHub emails you.

Without the GitHub CLI, the command writes the workflow into your folder and lists the remaining
steps: push it, add the secret, start the first run.

`schedule status` and `schedule remove` work here too. `remove` deletes the workflow and the secret
from the repo and keeps the existing issues.

Or add the action to any workflow yourself:

```yaml
permissions:
  contents: read
  issues: write
steps:
  - uses: actions/checkout@v4
  - uses: niyasraphy/odoo-code-radar@v1
    with:
      token: ${{ secrets.RADAR_TOKEN }}
```

| Input | Default | |
|---|---|---|
| `token` | (required) | Token for search and for reading your module repo |
| `issues-token` | `github.token` | Token used to open issues |
| `config` | `odoo-code-radar.yml` | Config file |
| `author` | | Author name on apps.odoo.com (the template passes `vars.RADAR_AUTHOR`) |
| `repos` | | Module repos, space separated |
| `include-lgpl` | `false` | Also watch open-license modules |
| `issues-repo` | the current repo | Where issues go (`none` to disable) |

A full scan takes about 6.5 seconds per search query because of GitHub's search limit, roughly
10 minutes for 40 modules, well inside the free Actions minutes.

## Limits

- GitHub code search only indexes default branches, and not every repo. A copy on another branch or
  in a very large repo can be missed.
- Other sites (GitLab, Bitbucket, download sites) are not searched yet.
- Scores are evidence, not proof. Look before you file anything.

## Development

```
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check src tests && .venv/bin/mypy
```

## License

MIT
