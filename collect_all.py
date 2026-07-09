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
        "app_store": {"app_id": "6741460190", "country": "kr"},
    },
    "pillyze": {
        "name": "필라이즈",
        "var_prefix": "PILLYZE",
        "google_play": {"app_id": "com.pillyze.health", "lang": "ko", "country": "kr", "count": 5000},
        "app_store": {"app_id": "1595472563", "country": "kr"},
    },
    "inout": {
        "name": "인아웃",
        "var_prefix": "INOUT",
        "google_play": {"app_id": "com.taejinketo.inout_webview", "lang": "ko", "country": "kr", "count": 5000},
        "app_store": {"app_id": "1599210729", "country": "kr"},
    },
    "mealligram": {
        "name": "밀리그램",
        "var_prefix": "MEALLIGRAM",
        "google_play": {"app_id": "com.lefal.mealligram", "lang": "ko", "country": "kr", "count": 5000},
        "app_store": {"app_id": "1514163957", "country": "kr"},
    },
    "pasta": {
        "name": "파스타",
        "var_prefix": "PASTA",
        "google_play": {"app_id": "com.kakaohealthcare.pasta", "lang": "ko", "country": "kr", "count": 5000},
        "app_store": {"app_id": "6462661411", "country": "kr"},
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


def scrape_app_store(config):
    """Apple RSS로 수집 (최대 500개 한도)"""
    cc = config["country"]
    aid = config["app_id"]
    
    url_variants = [
    f"https://itunes.apple.com/{cc}/rss/customerreviews/id={aid}/json",
    f"https://itunes.apple.com/{cc}/rss/customerreviews/id={aid}/sortBy=mostRecent/json",
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


def load_existing_ios_reviews(output_file):
    """기존 파일에서 iOS 리뷰만 추출 (실패 시 폴백용)"""
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
        
        # App Store RSS 수집 (최대 500개)
        new_ios = scrape_app_store(cfg["app_store"])
        print(f"[Apple RSS] {len(new_ios)}개")
        
        # 기존 iOS 리뷰 로드
        existing_ios = load_existing_ios_reviews(output_file)
        print(f"[기존 iOS] {len(existing_ios)}개")
        
        # 새 iOS + 기존 iOS 합쳐서 중복 제거
        # 새 리뷰가 우선 (최신 데이터)
        seen = set()
        merged_ios = []
        for r in new_ios + existing_ios:
            key = (r.get("content", ""), r.get("date", ""), r.get("rating", 0))
            if key not in seen:
                seen.add(key)
                merged_ios.append(r)
        
        # 새 수집이 너무 적으면 기존 데이터가 더 신뢰할 만함
        if len(new_ios) < IOS_MIN_THRESHOLD and len(existing_ios) > len(new_ios):
            print(f"⚠️  새 iOS 수집이 {IOS_MIN_THRESHOLD}건 미만 → 기존 데이터 우선 사용")
            merged_ios = existing_ios
        
        all_reviews = gp_reviews + merged_ios
        prefix = cfg["var_prefix"]
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"window.{prefix}_REVIEWS = ")
            json.dump(all_reviews, f, ensure_ascii=False, indent=2)
            f.write(";\n")
            f.write(f'window.{prefix}_UPDATED_AT = "{updated_at}";\n')
        
        print(f"✅ {output_file} 저장 완료 (총 {len(all_reviews)}개, iOS {len(merged_ios)}건)")
    
    print(f"\n🎉 모든 앱 수집 완료 ({updated_at})")


if __name__ == "__main__":
    main()