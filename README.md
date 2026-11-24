# Daily Brief

A small iPhone web app with a short, bite-sized summary of each day's most relevant U.S. and world
news, grouped by topic. It updates itself every morning, never repeats a story you already saw in
the last few days, and keeps stock-market chatter to a minimum.

## How it works (in plain terms)

- **Where the news comes from:** free public news feeds from NPR, BBC, the New York Times, CBS, ABC,
  The Guardian, Al Jazeera, Ars Technica, The Verge and ESPN (list in `scripts/feeds.json`).
- **How "relevant" is decided:** the same story is matched across outlets, and stories that many
  outlets are covering, near the top of their feeds, rank highest. Stories shown in the last 5 days
  are skipped. Day-to-day stock, index, earnings and crypto moves are dropped.
- **Summaries:** with an Anthropic API key, Claude picks the stories that matter most and writes a
  2-sentence summary plus a "why it matters" line, and a "day in 60 seconds" overview.
  Without a key, the app still works and shows each outlet's own one-line description.
- **Daily update:** GitHub runs the job every morning at about 4:15 AM Central, for free.
- **Hosting:** GitHub Pages serves the app for free at `https://<your-username>.github.io/<repo-name>/`.

## Default topics

On: U.S., Politics, World, Tech, Science & Health, Business (light).
Off (turn on in Settings): Sports, Culture & Entertainment.

## One-time setup

1. **Create the repository.** On github.com, click **+ → New repository**, name it `daily-brief`,
   choose **Public** (free GitHub Pages needs a public repo), and leave everything else blank.
2. **Add the files** in this folder to it (Claude can do this for you).
3. **Turn on the website.** In the repo, go to **Settings → Pages**. Under *Build and deployment*,
   pick **Deploy from a branch**, branch **main**, folder **/docs**, and press **Save**.
4. **Let the daily job save its work.** Go to **Settings → Actions → General → Workflow permissions**,
   choose **Read and write permissions**, and press **Save**.
5. **(Optional, recommended) Add AI summaries.** Create an API key at
   [console.anthropic.com](https://console.anthropic.com) (needs a few dollars of credit). In the repo,
   go to **Settings → Secrets and variables → Actions → New repository secret**, name it
   `ANTHROPIC_API_KEY` and paste the key.
6. **Run it once now** instead of waiting for tomorrow: **Actions → Daily brief → Run workflow**.
   It takes about a minute.

## Put it on your iPhone

1. Open `https://<your-username>.github.io/daily-brief/` in **Safari**.
2. Tap the **Share** button, then **Add to Home Screen**, then **Add**.
3. Open it from the new "Daily Brief" icon. Tap the gear to choose topics or bigger text.

## Changing things later

- **Topics and sources:** edit `scripts/feeds.json` (add or remove feed links, change how many
  stories a topic gets, or which topics are on by default).
- **Time of day:** edit the `cron` line in `.github/workflows/daily-brief.yml` (times are UTC).
- **Cost:** the default model is Claude Opus 5.5, roughly 15–25 cents a day. To make it about a cent
  a day, add a repository *variable* (Settings → Secrets and variables → Actions → Variables)
  named `BRIEF_MODEL` with the value `claude-haiku-5-5`.
- **Time zone** for "today": add a variable `BRIEF_TIMEZONE`, e.g. `America/New_York`.
