import json
import requests
from datetime import datetime

APPS = {
    "roution": {
        "name": "루션",
        "var_prefix": "ROUTION",
        "google_play": {"app_id": "com.kurly.balance", "lang": "ko", "country": "kr", "count": 200},
        "app_store": {"app_id": "6741460190", "country": "kr", "count": 500},
        "app_store_name": "roution",
    },
    "pillyze": {
        "name": "필라이즈",
        "var_prefix": "PILLYZE",
        "google_play": {"app_id": "com.pillyze.health", "lang": "ko", "country": "kr", "count": 2000},
        "app_store": {"app_id": "1595472563", "country": "kr", "count": 500},
        "app_store_name": "pillyze",
    },
    "inout": {
        "name": "인아웃",
        "var_prefix": "INOUT",
        "google_play": {"app_id": "com.taejinketo.inout_webview", "lang": "ko", "country": "kr", "count": 2000},
        "app_store": {"app_id": "1599210729", "country": "kr", "count": 500},
        "app_store_name": "inout",
    },
}


def scrape_google_play(config):
    try:
        from google_play_scraper import reviews, Sort
        result, _ = reviews(
            config["app_id"],
            lang=config["lang"],
            country=config["country"],
            sort=Sort.NEWEST,
            count=config["count"],
        )
        return [{
            "store": "google_play",
            "date": r["at"].strftime("%Y-%m-%d") if r.get("at") else "",
            "rating": r.get("score", 0),
            "content": r.get("content", ""),
        } for r in result]
    except Exception as e:
        print(f"[Google Play] 수집 실패: {e}")
        return []


def scrape_app_store(config, app_name):
    cc = config["country"]
    aid = config["app_id"]
    all_reviews = []
    
    url_variants = [
        f"https://itunes.apple.com/{cc}/rss/customerreviews/id={aid}/sortBy=mostRecent/json",
        f"https://itunes.apple.com/{cc}/rss/customerreviews/id={aid}/json",
        f"https://itunes.apple.com/{cc}/rss/customerreviews/page=1/id={aid}/sortBy=mostRecent/json",
    ]
    
    for base_url in url_variants:
        variant_reviews = []
        for page in range(1, 11):
            url = base_url.replace("page=1", f"page={page}") if "page=" in base_url else (
                base_url if page == 1 else base_url.replace("/json", f"/page={page}/json")
            )
            try:
                response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if response.status_code != 200 or not response.text.strip():
                    break
                data = response.json()
                entries = data.get("feed", {}).get("entry", [])
                if not entries:
                    break
                if isinstance(entries, dict):
                    entries = [entries]
                for entry in entries:
                    if "im:name" in entry:
                        continue
                    variant_reviews.append({
                        "store": "app_store",
                        "date": entry.get("updated", {}).get("label", "")[:10],
                        "rating": int(entry.get("im:rating", {}).get("label", 0)),
                        "content": entry.get("content", {}).get("label", ""),
                    })
            except Exception as e:
                print(f"  page {page} 오류: {e}")
                break
        if variant_reviews:
            return variant_reviews
    
    try:
        from app_store_scraper import AppStore
        app = AppStore(country=cc, app_id=int(aid), app_name=app_name)
        app.review(how_many=config["count"])
        for r in app.reviews:
            date_str = r["date"].strftime("%Y-%m-%d") if r.get("date") else ""
            all_reviews.append({
                "store": "app_store",
                "date": date_str,
                "rating": r.get("rating", 0),
                "content": r.get("review", ""),
            })
    except Exception as e:
        print(f"[App Store] 라이브러리 fallback 실패: {e}")
    
    return all_reviews


def main():
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    for app_key, cfg in APPS.items():
        print(f"\n=== {cfg['name']} 수집 시작 ===")
        
        gp_reviews = scrape_google_play(cfg["google_play"])
        print(f"[Google Play] {len(gp_reviews)}개")
        
        ios_reviews = scrape_app_store(cfg["app_store"], cfg["app_store_name"])
        print(f"[App Store] {len(ios_reviews)}개")
        
        all_reviews = gp_reviews + ios_reviews
        prefix = cfg["var_prefix"]
        
        output_file = f"{app_key}_reviews.js"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"window.{prefix}_REVIEWS = ")
            json.dump(all_reviews, f, ensure_ascii=False, indent=2)
            f.write(";\n")
            f.write(f'window.{prefix}_UPDATED_AT = "{updated_at}";\n')
        
        print(f"✅ {output_file} 저장 완료 (총 {len(all_reviews)}개)")
    
    print(f"\n🎉 모든 앱 수집 완료 ({updated_at})")


if __name__ == "__main__":
    main()