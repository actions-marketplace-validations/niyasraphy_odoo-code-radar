# Odoo Code Radar for my apps

Protects my Odoo intellectual property: every week it checks GitHub for unauthorized copies of my
proprietary apps, using [odoo-code-radar](https://github.com/niyasraphy/odoo-code-radar). Each new
copy becomes an issue in this repository, and GitHub emails me. Nothing to install, nothing to host.

## Setup (5 minutes)

**1. Keep this repository private.** If you made it public, switch it: Settings → General → Danger
Zone → Change visibility. The issues show where copies of your apps are, so odoo-code-radar refuses
to open them in a public repo.

**2. Add your author name.** Settings → Secrets and variables → Actions → **Variables** tab → New
repository variable:

| Name | Value |
|---|---|
| `RADAR_AUTHOR` | your author name exactly as on apps.odoo.com, e.g. `Odoo Mates` |

**3. Add a token.** Create a [fine-grained token](https://github.com/settings/personal-access-tokens/new):
*Repository access: Public repositories*, no extra permissions, and an expiry date. Then go to
Settings → Secrets and variables → Actions → **Secrets** tab → New repository secret:

| Name | Value |
|---|---|
| `RADAR_TOKEN` | the token |

**4. Run the first scan.** Actions → **Odoo Code Radar** → **Run workflow**. It takes a few minutes.
From then on it runs every Monday by itself.

## What you get

- **An issue for each unauthorized copy** (one app found in one repository), with the evidence,
  the module folder links and a DMCA notice draft. Each copy is reported only once. Close the
  issue when it is handled.
- **An email from GitHub** for each new issue, through your normal GitHub notifications.
- **The full report** attached to each run (Actions → the run → Artifacts).

## Your token

It is stored as an encrypted GitHub secret and used only inside the runs of this repository.
odoo-code-radar has no server: its authors never see your token, your app list or your results.
Issues are opened with the workflow's own token, so `RADAR_TOKEN` needs no write access.

## Options

- **Change the day or time:** edit the `cron:` line in
  [`.github/workflows/odoo-code-radar.yml`](.github/workflows/odoo-code-radar.yml), in UTC.
  `"17 5 * * *"` runs daily, `"17 5 1 * *"` monthly.
- **Read your modules from your own repo, include LGPL apps, ignore accounts:** see
  [`odoo-code-radar.yml`](odoo-code-radar.yml).

## Handling an unauthorized copy

1. Open the issue and check the folder links: is it really your code?
2. Optionally ask the repository owner to remove it. Many copies are published by accident.
3. Otherwise file the DMCA draft from the issue at https://github.com/contact/dmca (fill in the
   brackets, check every link). You sign it, so read it first.
4. Close the issue once the copy is gone.
