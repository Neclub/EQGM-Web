# EQGM Web

Browser version of **EQ Gear Management (EQGM)**. Upload EverQuest `/outputfile` inventory, MissingSpells, and Achievements dumps and download a team **Excel** workbook and/or interactive **HTML** report.

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

EQ Resource / Raidloot catalog JSON lives in the repo [`cache/`](cache/) folder. The web app sets `EQGM_APPDATA` to that directory, so **reads and writes go there** (not `%LOCALAPPDATA%\EQGM`).

When a generate fetches a new catalog item, it is appended to the matching `cache/*.json` file. To ship that to GitHub (and the next Render deploy):

1. Run a generate that needs the new data (locally is easiest).
2. Commit the updated `cache/*.json` files and push.
3. Redeploy (or let Render auto-deploy from `main`).

Runtime files that should not be committed (`settings.json`, `last_report.log`, `item_icons/`) are gitignored under `cache/`.

On Render’s free plan the disk is still ephemeral: growth while the instance is awake helps, but only committed `cache/` files survive sleep/redeploy.

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
- Local disk is **ephemeral** (lost on sleep/redeploy). Uploaded files and finished reports are deleted after a short TTL (~15 minutes).
- Durable catalogs come from committed `cache/*.json` in this repo.

## How to use

1. In EverQuest, run `/outputfile inventory` (and optionally MissingSpells / Achievements) on each character.
2. On the web app, **Upload files** (or drag `.txt` files onto the roster).
3. Select characters, set export options, click **Generate Report**.
4. **Download Excel** and/or **Download HTML** (downloads start automatically; links remain available).

No accounts. Do not upload files you are not allowed to share.

## License

Apache License 2.0 — same family as the desktop EQGM project. See [LICENSE](LICENSE).
