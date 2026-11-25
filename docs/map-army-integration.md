# Ground Truth: map.army integration

Voice reports from our pipeline show up as NATO military symbols on [map.army](https://www.map.army), on an MGRS grid.

## In one sentence

When the pipeline knows where a unit is, it sends the position to a small server. The server turns it into a map file, and map.army loads that file from a link.

```
voice -> transcript -> coordinates -> POST /report -> MilX layer file -> map.army
                       (our pipeline)   (this code)
```

map.army has no live API, so the integration is file-based: we generate a MilX layer (`.milxlyz`) and map.army loads it from a URL.

## Files

| File | What it does |
|---|---|
| `mgrs_convert.py` | Lat/lon to MGRS and back. Also finds spoken grids in a transcript ("three two tango november sierra six six three five ..."). |
| `milx_writer.py` | Turns a list of reports into a `.milxlyz` layer file. |
| `server.py` | FastAPI server. Takes reports, serves the layer with the CORS header map.army needs. |
| `run.sh` | Starts the server and a public HTTPS tunnel (cloudflared). |
| `requirements.txt` | Python packages: fastapi, uvicorn, mgrs. |

## Run it

```bash
bash run.sh
```

The first run sets up a Python environment and installs `cloudflared` through Homebrew if it is missing. Then it prints:

- **PUBLIC ADDRESS**: the tunnel URL, also saved to `public_url.txt`
- **TEST MARKERS**: open this to load two test markers
- **MAP LINK**: open this to see the map

Stop with Ctrl+C.

## Connect the voice pipeline

Once Layer 3 has final coordinates, post them:

```python
import requests

GROUND_TRUTH = "https://<tunnel-address>"   # from public_url.txt, or http://localhost:8000 on the same machine

requests.post(f"{GROUND_TRUTH}/report", json={
    "lat": 46.578,
    "lon": 9.866,
    "kind": "friendly_infantry",
    "label": "ALPHA 19:30",
}, timeout=5)
```

If the transcript contains a grid reference, skip the geocoder and send the text itself:

```python
requests.post(f"{GROUND_TRUTH}/report", json={
    "grid": "contact at grid three two tango november sierra seven five seven eight six four three zero",
    "kind": "hostile_armour",
    "label": "EN TANK",
}, timeout=5)
```

If the text has no valid grid, the server returns 422. Fall back to the landmark route.

### Allowed values for `kind`

- `friendly_infantry`
- `friendly_armour`
- `hostile_infantry`
- `hostile_armour`

The LLM should output one of these four words, never a raw symbol code. Anything else is rejected with 422.

## See it on the map

```
https://www.map.army/?grid=mgrs&layer=https://<tunnel-address>/layer/current.milxlyz
```

Refresh the page after each report to see new markers.

## All routes

| Route | Purpose |
|---|---|
| `POST /report` | Add a report: `{lat, lon, kind, label}` or `{grid, kind, label}` |
| `GET /reports` | List all reports with their MGRS grid |
| `POST /reset` | Clear all reports |
| `GET /demo` | Load two test markers (open in a browser) |
| `GET /layer/current.milxlyz` | The layer file map.army loads |
| `GET /link?base=https://...` | Build the map.army link for a public address |

## What has been tested

- MGRS conversion matches map.army's own grid readout (same grid square).
- A lat/lon report and a spoken-grid report both appear at the right position on map.army.
- The layer loads in map.army through the public tunnel, with the MGRS grid on.

## Limits

- **Not real time.** The map shows new markers on refresh, not by push.
- **The tunnel address changes** every time `run.sh` restarts. Keep it in one config value.
- **Markers live in memory** and clear when the server restarts.
- **Four symbol types only**, all copied from map.army's sample file. More can be added to `SYMBOLS` in `milx_writer.py` after checking they render.
- **MilX wants X = longitude, Y = latitude.** The writer handles this; send normal `lat` and `lon`.
