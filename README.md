# Missav

MissAV/Jable playback extraction and proxy logic extracted from `comic_backend/api/v1/video.py`.

## What this library provides

- Build playable source list for a video code (`MissAV` and `Jable`)
- Extract m3u8 streams with quality info
- Proxy stream/media requests with browser impersonation headers
- Rewrite m3u8 segment/key links to backend proxy URLs

## Usage inside backend

```python
from third_party.missav import get_client

client = get_client(proxy_base_path="/api/v1/video")
sources = client.build_sources("SSIS-123")
```

## Install (standalone)

```bash
pip install -e .
```

or

```bash
pip install -r requirements.txt
```
