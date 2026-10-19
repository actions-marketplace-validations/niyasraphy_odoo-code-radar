# Changelog

## 0.1.0

First release.

- Module list from your apps.odoo.com author name, your own GitHub repo (all branches), or a local folder.
- GitHub search by technical name, module name and author, plus repos named after a module.
- Scoring from folder, manifest name, author and website; manifests are parsed, never executed.
- OPL-1 and other proprietary apps watched by default; LGPL-3 optional.
- Each leak reported once: local Markdown/JSON report with a DMCA draft, or a GitHub issue in your repo.
- `schedule daily|weekly|monthly` on this machine (systemd, cron, launchd or Task Scheduler), with
  `status` and `remove`; results as issues in a private repo or local files plus a desktop notification.
- `schedule ... --github`: the same on GitHub Actions in a private repo, set up through the GitHub CLI.
- Issues are only ever opened in private repos.
- The token stays local: sent only to GitHub hosts, never printed, refused in config files, and saved
  only for scheduled scans, to a file only the user can read.
