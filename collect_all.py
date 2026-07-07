import json
import os
import re
import requests
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# iOS 수집이 이 건수 미만이면 "실패로 간주" → 기존 데이터 유지
IOS_MIN_THRESHOLD = 10

APPS = {
    "roution": {
        "name": "루션",
        "var_prefix": "ROUTION",
        "google_play": {"app_id": "com.kurly.balance", "lang": "ko", "country": "kr", "count": 5000},
        "app_store": {"app_id": "6741460190", "country": "kr", "count": 2000},
        "app_store_name": "roution",
    },
    "pillyze": {
        "name": "필라이즈",
        "var_prefix": "PILLYZE",
        "google_play": {"app_id": "com.pillyze.health", "lang": "ko", "country": "kr", "count": 5000},
        "app_store": {"app_id": "1595472563", "country": "kr", "count": 2000},
        "app_store_name": "pillyze",
    },
    "inout": {
        "name": "인아웃",
        "var_prefix": "INOUT",
        "google_play": {"app_id": "com.taejinketo.inout_webview", "lang": "ko", "country": "kr", "count": 5000},
        "app_store": {"app_id": "1599210729", "country": "kr", "count": 2000},
        "app_store_name": "inout",
    },
    "mealligram": {
        "name": "밀리그램",
        "var_prefix": "MEALLIGRAM",
        "google_play": {"app_id": "com.lefal.mealligram", "lang": "ko", "country": "kr", "count": 5000},
        "app_store": {"app_id": "1514163957", "country": "kr", "count": 2000},
        "app_store_name": "mealligram",
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


def scrape_app_store_rss(config):
    """Apple RSS로 수집 (최대 500개 한도)"""
    cc = config["country"]
    aid = config["app_id"]
    
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
                print(f"    RSS page {page} 오류: {e}")
                break
        if variant_reviews:
            return variant_reviews
    return []


def scrape_app_store_library(config, app_name):
    """app-store-scraper 라이브러리로 수집 (1000+ 가능)"""
    try:
        from app_store_scraper import AppStore
        app = AppStore(country=config["country"], app_id=int(config["app_id"]), app_name=app_name)
        app.review(how_many=config["count"])
        reviews_out = []
        for r in app.reviews:
            date_str = r["date"].strftime("%Y-%m-%d") if r.get("date") else ""
            reviews_out.append({
                "store": "app_store",
                "date": date_str,
                "rating": r.get("rating", 0),
                "content": r.get("review", ""),
            })
        return reviews_out
    except Exception as e:
        print(f"    라이브러리 오류: {e}")
        return []


def dedupe_reviews(reviews):
    """content + date + rating 조합으로 중복 제거"""
    seen = set()
    unique = []
    for r in reviews:
        key = (r.get("content", ""), r.get("date", ""), r.get("rating", 0))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def scrape_app_store(config, app_name):
    """라이브러리 우선 + RSS 보완 → 중복 제거"""
    # 1. app-store-scraper 라이브러리로 최대한 수집
    library_reviews = scrape_app_store_library(config, app_name)
    print(f"  [라이브러리] {len(library_reviews)}개")
    
    # 2. Apple RSS로도 시도 (최신 리뷰 보완용)
    rss_reviews = scrape_app_store_rss(config)
    print(f"  [Apple RSS] {len(rss_reviews)}개")
    
    # 3. 합치고 중복 제거
    combined = library_reviews + rss_reviews
    unique = dedupe_reviews(combined)
    print(f"  [합계] {len(combined)}개 → 중복 제거 후 {len(unique)}개")
    
    return unique


def load_existing_ios_reviews(output_file):
    """기존 파일에서 iOS 리뷰만 추출 (완전 실패 시 폴백용)"""
    if not os.path.exists(output_file):
        return []
    try:
        with open(output_file, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'window\.\w+_REVIEWS\s*=\s*(\[.*?\]);', content, re.DOTALL)
        if not match:
            return []
        reviews = json.loads(match.group(1))
        ios_reviews = [r for r in reviews if r.get("store") == "app_store"]
        return ios_reviews
    except Exception as e:
        print(f"[폴백] 기존 파일 읽기 실패: {e}")
        return []


def main():
    updated_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    
    for app_key, cfg in APPS.items():
        print(f"\n=== {cfg['name']} 수집 시작 ===")
        output_file = f"{app_key}_reviews.js"
        
        # Google Play 수집
        gp_reviews = scrape_google_play(cfg["google_play"])
        print(f"[Google Play] {len(gp_reviews)}개")
        
        # App Store 수집
        print(f"[App Store]")
        ios_reviews = scrape_app_store(cfg["app_store"], cfg["app_store_name"])
        
        # iOS 수집이 임계값 미만이면 기존 데이터 유지
        if len(ios_reviews) < IOS_MIN_THRESHOLD:
            print(f"⚠️  iOS 수집이 {IOS_MIN_THRESHOLD}건 미만 → 기존 데이터 유지 시도")
            existing_ios = load_existing_ios_reviews(output_file)
            if len(existing_ios) > len(ios_reviews):
                print(f"   → 기존 파일에서 {len(existing_ios)}건 복원")
                ios_reviews = existing_ios
        
        all_reviews = gp_reviews + ios_reviews
        prefix = cfg["var_prefix"]
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"window.{prefix}_REVIEWS = ")
            json.dump(all_reviews, f, ensure_ascii=False, indent=2)
            f.write(";\n")
            f.write(f'window.{prefix}_UPDATED_AT = "{updated_at}";\n')
        
        print(f"✅ {output_file} 저장 완료 (총 {len(all_reviews)}개, iOS {len(ios_reviews)}건)")
    
    print(f"\n🎉 모든 앱 수집 완료 ({updated_at})")


if __name__ == "__main__":
    main()