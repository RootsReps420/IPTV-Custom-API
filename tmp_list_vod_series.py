from iptv_monitor.player_sync import is_catch_all_category
from iptv_monitor.player_xtream import _as_list, load_player_config
from iptv_monitor.stream import _STREAM_UA
import httpx

cfg = load_player_config("/home/ubuntu/iptv-monitor")
params_base = {"username": cfg.username.strip(), "password": cfg.password.strip()}
with httpx.Client(verify=False, follow_redirects=True, timeout=45.0, headers={"User-Agent": _STREAM_UA}) as client:
    for kind, action in (("MOVIES", "get_vod_categories"), ("SERIES", "get_series_categories")):
        response = client.get(cfg.base + "/player_api.php", params={**params_base, "action": action})
        rows = _as_list(response.json())
        keep = [item for item in rows if not is_catch_all_category(str(item.get("category_name") or ""))]
        print(
            f"=== {kind} HTTP {response.status_code} total={len(rows)} keep={len(keep)} catch_all_skip={len(rows) - len(keep)} ==="
        )
        for item in keep:
            cid = item.get("category_id")
            name = item.get("category_name")
            print(f"{cid}\t{name}")
        print()
