# Changelog

## 0.1.4

- README: a demo GIF showing a scan, the GitHub issue with its DMCA draft, and scheduling.
- Examples use made-up repository owners instead of real GitHub accounts.

## 0.1.3

- Shorter Action description (the GitHub Marketplace allows 125 characters).

## 0.1.2

- Clearer wording: "Protect your Odoo intellectual property: find unauthorized copies of your
  proprietary apps on GitHub." Messages speak of unauthorized copies of your proprietary apps.

## 0.1.1

- DMCA drafts follow GitHub's takedown form: entire repositories and single folders are listed
  separately, folder links point at the current branch, and fork URLs come as the form wants them.
- Only forks that still contain the module are listed. Forks often differ from their parent.
- Reports end with one DMCA draft covering all new leaks, instead of one per leak.
- Each leak shows whether the whole repository or only a folder is a copy.
- The Action reads the author name from the `RADAR_AUTHOR` variable and explains clearly when the name
  or the token is missing.
- A template repository for weekly scans without installing anything.
- GitHub actions updated to their Node.js 24 versions.

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
