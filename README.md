# EQGM Web

Browser version of **EQ Gear Management (EQGM)**. Upload EverQuest `/outputfile` inventory, MissingSpells, and Achievements dumps and download an interactive **HTML** team report.

This is a **separate project and GitHub repository** from the Windows desktop app ([Neclub/EQ-Gear-Management](https://github.com/Neclub/EQ-Gear-Management)).

## Local run

```bash
cd EQGM_Web
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
set PYTHONPATH=.;src
# PowerShell: $env:PYTHONPATH = ".;src"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open http://127.0.0.1:8000/

## Catalog cache (`cache/`)

EQ Resource / Raidloot catalog JSON and item icons live under repo [`cache/`](cache/). The web app sets `EQGM_APPDATA` to that directory, so **reads and writes go there**.

Generates **only contact EQ Resource / Raidloot on a cache miss** (unknown item, incomplete catalog row, or missing icon PNG). Warm files are reused as-is.

- **JSON catalogs:** `cache/*.json` (augs, raid BiS, sockets, item details, etc.)
- **Icons:** `cache/item_icons/{id//1000}/{id}.png` (sharded for GitHub’s 1,000-file directory limit) and `expac-*.jpg` at the icon root — embedded into BiS paper dolls and item cards

### One-shot warm on your PC (recommended)

Run this **locally once** (not on Render). It force-refreshes shared catalogs and hydrates item pages (stats/inspect), sockets, classes, gear tiers, expansions, and icons into `cache/`. Then commit and push so GitHub/Render ship the richer cache.

```bash
cd EQGM_Web
# Windows PowerShell:
$env:PYTHONPATH = ".;src"
py -3 scripts/warm_eqresource_cache.py
# Optional: also hydrate item IDs from inventory dumps (classes/gear you do not play)
py -3 scripts/warm_eqresource_cache.py "C:\path\to\Examples"

git add cache/
git commit -m "Warm EQ Resource cache for fewer live misses."
git push
```

Runtime files that should not be committed (`settings.json`, `last_report.log`) are gitignored under `cache/`.

On Render’s free plan the disk is still ephemeral: growth while the instance is awake helps, but only committed `cache/` files survive sleep/redeploy. After deploy, generates still fill true misses into `cache/` locally if you run the app on your PC—commit those updates the same way.

## Deploy on Render (free)

1. Push this repository to GitHub (for example `Neclub/EQGM-Web`).
2. In [Render](https://render.com/), **New → Blueprint** (uses `render.yaml`) or **New → Web Service** and connect **this** repo (not EQ-Gear-Management).
3. Settings if creating manually:
   - **Runtime:** Python
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
   - **Env:** `PYTHONPATH=.:src`, `EQGM_APPDATA=cache`
   - **Plan:** Free
4. After deploy, open the `*.onrender.com` URL.

### Free-tier caveats

- The service **sleeps after ~15 minutes** idle; the first request can take about a minute to wake.
- **512 MB RAM** and one generate at a time — keep rosters modest (max 20 characters in this build).
- Local disk is **ephemeral** (lost on sleep/redeploy). Uploaded files expire with the session (~30 minutes idle). Generated HTML reports are deleted after download or when a new generate starts for that session.
- Durable catalogs come from committed `cache/*.json` in this repo.

## How to use

1. In EverQuest, run `/outputfile inventory` (and optionally MissingSpells / Achievements) on each character.
2. On the web app, **Upload files** (or drag `.txt` files onto the roster).
3. Select characters, set export options, click **Generate Report**.
4. The **HTML download starts automatically** when generation finishes. The temp report is deleted after download (and older reports for the same session are cleared when you generate again).

No accounts. Do not upload files you are not allowed to share.

## License

Apache License 2.0 — same family as the desktop EQGM project. See [LICENSE](LICENSE).
