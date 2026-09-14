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

## Catalog cache

Lookup order for catalogs and icons:

1. **Local** `cache/` (GitHub seed on deploy + runtime writes)
2. **Cloudflare R2** shared bucket (if configured) — survives Render sleep
3. **EQ Resource / Raidloot** — only on a true miss, with per-URL singleflight and an hourly request budget

- **JSON catalogs:** `cache/*.json`
- **Icons:** `cache/item_icons/{id}.png` (and `expac-*.jpg`)

New fetches write local files **and** publish to R2 when R2 env vars are set. Without R2, behavior matches a local-only cache (still polite to EQ Resource via the budget gate).

### Optional: promote into GitHub

To bake newly fetched data into the next deploy image:

1. Copy updated `cache/*.json` / `cache/item_icons/*` from a run (or pull from R2).
2. Commit and push; redeploy.

Runtime noise (`settings.json`, `last_report.log`) stays gitignored.

### Cloudflare R2 (recommended for multi-user)

1. Create an R2 bucket (e.g. `eqgm-cache`) and an API token with Object Read & Write.
2. Set Render (or local) env vars:

| Variable | Example |
|----------|---------|
| `EQGM_R2_ACCOUNT_ID` | Cloudflare account id |
| `EQGM_R2_ACCESS_KEY_ID` | R2 access key |
| `EQGM_R2_SECRET_ACCESS_KEY` | R2 secret |
| `EQGM_R2_BUCKET` | `eqgm-cache` |
| `EQGM_R2_ENDPOINT` | optional; default `https://{account}.r2.cloudflarestorage.com` |

3. Seed the bucket once from the repo cache:

```powershell
$env:PYTHONPATH = ".;src"
$env:EQGM_APPDATA = "cache"
# set EQGM_R2_* as above
.\.venv\Scripts\python.exe scripts\push_cache_to_r2.py
```

Other env knobs:

- `EQGM_EQR_MAX_REQUESTS_PER_HOUR` — default `120`; set `0` to block all upstream fetches
- `EQGM_ALLOW_NETWORK=0` — cache-only mode (no EQ Resource / Raidloot)

## Deploy on Render (free)

1. Push this repository to GitHub (for example `Neclub/EQGM-Web`).
2. In [Render](https://render.com/), **New → Blueprint** (uses `render.yaml`) or **New → Web Service** and connect **this** repo (not EQ-Gear-Management).
3. Settings if creating manually:
   - **Runtime:** Python
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
   - **Env:** `PYTHONPATH=.:src`, `EQGM_APPDATA=cache`, plus R2 secrets above
   - **Plan:** Free
4. After deploy, open the `*.onrender.com` URL.

### Free-tier caveats

- The service **sleeps after ~15 minutes** idle; the first request can take about a minute to wake.
- **512 MB RAM** and one generate at a time — keep rosters modest (max 20 characters in this build).
- Local disk is **ephemeral**; use **R2** so catalog/icon growth survives sleep. Uploaded inventory files and finished reports still expire (~15 minutes).

## How to use

1. In EverQuest, run `/outputfile inventory` (and optionally MissingSpells / Achievements) on each character.
2. On the web app, **Upload files** (or drag `.txt` files onto the roster).
3. Select characters, set export options, click **Generate Report**.
4. **Download Excel** and/or **Download HTML** (downloads start automatically; links remain available).

No accounts. Do not upload files you are not allowed to share.

## License

Apache License 2.0 — same family as the desktop EQGM project. See [LICENSE](LICENSE).
