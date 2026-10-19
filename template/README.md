# Odoo Code Radar: weekly protection for your Odoo apps

**Protect your Odoo intellectual property: find unauthorized copies of your proprietary apps on GitHub.**

Copy this template, add two settings, and GitHub checks every week whether your apps have been
published without permission. Nothing to install, nothing to host, free.

---

## The problem

You sell apps on the [Odoo Apps Store](https://apps.odoo.com) under a proprietary license such as
OPL-1. Buyers may use and modify them, but not publish them.

Still, it happens every day:

- a customer pushes their whole `custom_addons` folder to a **public** GitHub repository, your app
  included, often by accident;
- someone uploads your app on its own, in a repository named after it;
- others **fork** those repositories, and every fork is one more free copy.

Anyone can then download your app for free instead of buying it. You lose sales, and usually you
never find out, because nobody searches GitHub for every app every week.

## How this template helps

Every Monday it searches GitHub for copies of your apps, and for each new one:

1. **Opens an issue in your copy of this repository**: which app, which repository, which folder,
   why it matched, and which forks still have it.
2. **GitHub emails you** about the issue, like any other GitHub notification.
3. **Hands you a DMCA notice draft** inside the issue, laid out like GitHub's takedown form, ready to
   check and send.

Each copy is reported once. Closing the issue means "handled", and it won't come back.

### How it finds copies

1. Reads the list of your apps from the Odoo Apps Store, using your author name.
2. Searches GitHub for your apps' technical names, app names and author name.
3. Reads each match's `__manifest__.py` (only reads it, never runs it) and scores it:

   | Evidence | Points |
   |---|---|
   | Folder name is your technical name | 40 |
   | Manifest name is your app name (any Odoo version) | 40 |
   | Manifest author is you | 30 |
   | Manifest website is yours | 10 |

   80 points or more is high confidence, 50 or more is medium. Medium and up are reported.

Only **OPL-1 and other proprietary** apps are watched. LGPL-3 apps may legally be shared by buyers,
so they are skipped unless you turn them on.

---

## Setup (about 5 minutes)

### Step 1: Create your copy (private)

At the top of [the template page](https://github.com/niyasraphy/odoo-code-radar-template), click
**Use this template** → **Create a new repository**:

- **Repository name:** anything, e.g. `odoo-code-radar`
- **Visibility:** choose **Private**

Private matters: the issues list where copies of your apps are. odoo-code-radar refuses to open
issues in a public repository.

### Step 2: Add your author name

In **your new repository**: **Settings** → **Secrets and variables** → **Actions** → **Variables** tab
→ **New repository variable**

| Name | Value |
|---|---|
| `RADAR_AUTHOR` | your author name exactly as shown on apps.odoo.com, e.g. `Odoo Mates` |

To check the spelling, open one of your apps on apps.odoo.com: it is the name after "by".

### Step 3: Create a token and add it

GitHub only allows code search with a token. A read-only token with no permissions is enough.

**Create the token:** open [New fine-grained token](https://github.com/settings/personal-access-tokens/new)
(or GitHub → your avatar → **Settings** → **Developer settings** → **Personal access tokens** →
**Fine-grained tokens** → **Generate new token**):

- **Token name:** `odoo-code-radar`
- **Expiration:** e.g. 1 year (put a reminder in your calendar to renew it)
- **Repository access:** **Public repositories**
- **Permissions:** leave everything as it is
- Click **Generate token** and copy it

**Add it:** back in your repository: **Settings** → **Secrets and variables** → **Actions** →
**Secrets** tab → **New repository secret**

| Name | Value |
|---|---|
| `RADAR_TOKEN` | the token you copied |

### Step 4: Run the first scan

**Actions** tab → **Odoo Code Radar** (left side) → **Run workflow** → **Run workflow**.

It takes a few minutes, depending on how many apps you have. When it finishes:

- new copies appear under the **Issues** tab, and GitHub emails you;
- the full report is attached to the run (open the run → **Artifacts**).

From now on it runs **every Monday** by itself.

### If the run fails

Open the failed run. The first lines say what is missing:

| Message | Fix |
|---|---|
| **Token missing** | Step 3: add the `RADAR_TOKEN` secret (in the **Secrets** tab, not Variables) |
| **Author missing** | Step 2: add the `RADAR_AUTHOR` variable (in the **Variables** tab) |
| **… is public** | Step 1: make the repository private (**Settings** → **General** → **Danger Zone**) |
| **Bad credentials** | The token expired or was deleted: create a new one and update the secret |

---

## What an issue looks like

> **[OPL-1] om_dynamic_reports found in someone/recruitment_uat**
>
> | | |
> |---|---|
> | Module | `om_dynamic_reports` (OPL-1) |
> | Scope | only the module folder |
> | Forks | 6 (5 still contain the module) |
> | Confidence | high (110 points) |
>
> **Why it matched:** folder `om_dynamic_reports` matches the technical name · manifest name matches ·
> manifest author "Odoo Mates" matches
>
> **What to do** · **DMCA notice draft** (expand)

## Handling an unauthorized copy

1. **Check it.** Open the folder link in the issue: is it really your code?
2. **Optionally ask nicely.** Many copies are published by accident, and a short message to the
   repository owner often gets it removed within a day.
3. **File a takedown.** Expand "DMCA notice draft" in the issue, fill in the parts in [brackets],
   check every link, and submit it at https://github.com/contact/dmca (or email it to
   copyright@github.com). You sign it, so read it carefully.
4. **Keep track.** Add a comment like "DMCA sent 2026-10-19". Close the issue once the link shows
   404 or "unavailable for legal reasons".

---

## Options

All optional. The defaults work for most vendors.

| I want to… | How |
|---|---|
| Scan daily or monthly | Edit the `cron:` line in [`.github/workflows/odoo-code-radar.yml`](.github/workflows/odoo-code-radar.yml) (UTC): `"17 5 * * *"` daily, `"17 5 1 * *"` monthly |
| Read my apps from my own repository (more accurate) | In [`odoo-code-radar.yml`](odoo-code-radar.yml), uncomment `sources:` and set your repo. Give the token **Contents: Read** on that repo |
| Also watch LGPL-3 apps | `include_lgpl: true` in `odoo-code-radar.yml` |
| Ignore my own accounts or a customer I allowed | `ignore_owners:` / `ignore_repos:` in `odoo-code-radar.yml` |
| Pause it | **Actions** → **Odoo Code Radar** → **⋯** → **Disable workflow** |

## Questions

**Does it cost anything?** No. Private repositories get 2,000 free GitHub Actions minutes a month.
A weekly scan takes a few minutes.

**Who sees my token and results?** Only you. The token is an encrypted secret used only inside your
repository's runs. odoo-code-radar has no server: its authors never see your token, your app list
or your results. Issues are opened with the workflow's own token, so `RADAR_TOKEN` needs no write
access.

**Does it file takedowns for me?** No. It finds copies and prepares the notice; you decide and send
it. A takedown is a legal statement you make.

**Can it be wrong?** It reports evidence, not proof. High confidence means folder, name and author
all match. Always look before filing anything.

**Does it search outside GitHub?** Not yet. GitHub code search also doesn't index every repository
or branch, so some copies can be missed.

---

Made with [odoo-code-radar](https://github.com/niyasraphy/odoo-code-radar), free and open source
(MIT). Prefer the command line? `pipx install odoo-code-radar`.
