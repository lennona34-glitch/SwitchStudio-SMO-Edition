import urllib.request
import urllib.parse
import json
import os

queries = {
    'BeyondJourneysEnd': 'Beyond Journey',
    'DeathCounter': 'Death Counter',
    'EmeraldCoast': 'Emerald Coast',
    'InputDisplay': 'Input Display',
    'OdysseyKingdomsExpansion': 'Kingdoms Expansion',
    'SMOInterpHighRefreshRateMod': 'SMOInterp',
    'SuperXCaptureOdyssey': 'Super [X Capture]',
    'TreetrunkMeadow': 'Treetrunk Meadow',
    'VerityAndTheCompanionsBeta': 'Verity',
    'FluffyBluffKingdom': 'Fluffy Bluff Kingdom',
    'KingdomPass': 'Kingdom Pass',
    'WuhuKingdom': 'Wuhu Kingdom',
    'YoshiStarKingdom': 'Yoshi Star Kingdom',
    'RecreatingEveryTexture': 'Recreating every texture'
}

meta_db = {}
for folder, q in queries.items():
    url = f"https://gamebanana.com/apiv11/Game/6376/Subfeed?_nPage=1&_sName={urllib.parse.quote(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": "SwitchStudio/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
            recs = [x for x in d.get("_aRecords", []) if x.get("_sModelName") == "Mod"]
            if recs:
                rec = recs[0]
                gbid = rec.get("_idRow")
                imgs = rec.get("_aPreviewMedia", {}).get("_aImages", [])
                thumb = ""
                if imgs:
                    b = imgs[0].get("_sBaseUrl", "")
                    f = imgs[0].get("_sFile530") or imgs[0].get("_sFile220") or imgs[0].get("_sFile", "")
                    thumb = f"{b}/{f}" if b and f else ""
                mod_name = rec.get("_sName")
                sub = rec.get("_aSubmitter", {}).get("_sName", "GameBanana Creator")
                cat = rec.get("_aRootCategory", {}).get("_sName", "Custom Mod")
                likes = rec.get("_nLikeCount", 0)
                views = rec.get("_nViewCount", 0)
                purl = rec.get("_sProfileUrl", f"https://gamebanana.com/mods/{gbid}")
                meta_db[folder] = {
                    "gb_id": gbid,
                    "name": mod_name,
                    "author": sub,
                    "category": cat,
                    "thumb": thumb,
                    "likes": likes,
                    "views": views,
                    "description": f"Community pack '{mod_name}' by {sub}.",
                    "profile_url": purl
                }
                print(f"[FOUND] {folder} -> #{gbid}: {mod_name} | {thumb}")
            else:
                print(f"[MISSING] {folder} for query '{q}'")
    except Exception as e:
        print(f"[ERROR] {folder}: {e}")

os.makedirs("config", exist_ok=True)
with open("config/community_metadata.json", "w", encoding="utf-8") as f:
    json.dump(meta_db, f, indent=2, ensure_ascii=False)
print("Saved config/community_metadata.json with", len(meta_db), "entries!")
