import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.velyb.kr/community/community01.php"

# 블리비 이벤트 카테고리
CATEGORIES = {
    0: "전체",
    1: "기획전",
    2: "쁘띠성형",
    3: "피부",
    4: "리프팅",
    5: "부스터",
    6: "제모",
    7: "비만",
}

OUTPUT = Path("events.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def clean(text):
    """공백과 불필요한 문자를 정리합니다."""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def price_number(text):
    """12,900원 -> 12900"""
    if not text:
        return None

    match = re.search(r"([\d,]+)\s*원", text)

    if not match:
        return None

    return int(match.group(1).replace(",", ""))


def parse_price_line(text):
    """
    예:
    48% 289,000원 ~~566,600~~원

    결과:
    discount = 48
    price = 289000
    normal = 566600
    """

    pattern = re.compile(
        r"(?P<discount>\d+)\s*%\s*"
        r"(?P<price>[\d,]+)\s*원"
        r"(?:\s*~~(?P<normal>[\d,]+)~~\s*원)?"
    )

    match = pattern.search(text)

    if not match:
        return None

    discount = int(match.group("discount"))

    price = int(
        match.group("price").replace(",", "")
    )

    normal_text = match.group("normal")

    normal = (
        int(normal_text.replace(",", ""))
        if normal_text
        else None
    )

    return {
        "discount": discount,
        "price": price,
        "normal": normal,
    }


def parse_option_price(text):
    """
    옵션처럼 할인율이 없는 가격:
    129,000원
    """

    # 일반적인 원화 가격이 있는지 확인
    match = re.search(
        r"([\d,]+)\s*원",
        text
    )

    if not match:
        return None

    return int(
        match.group(1).replace(",", "")
    )


def get_page(category_id):
    """왕십리점의 특정 카테고리 페이지를 가져옵니다."""

    params = {
        "tb": "event_multi",
        "etc5": "왕십리점",
        "sField": str(category_id),
    }

    response = requests.get(
        BASE_URL,
        params=params,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    response.encoding = response.apparent_encoding

    return response.text


def extract_events(html, category_id):
    """
    페이지의 이벤트 항목을 추출합니다.

    블리비 페이지는
    이벤트명
    ↓
    할인율 + 이벤트 가격 + 정상가

    형태로 가격 정보가 표시되므로
    텍스트 라인을 기준으로 추출합니다.
    """

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # script/style 제거
    for tag in soup(
        ["script", "style", "noscript"]
    ):
        tag.decompose()

    text = soup.get_text(
        "\n",
        strip=True
    )

    lines = []

    for line in text.splitlines():

        line = clean(line)

        if line:
            lines.append(line)

    results = []

    # 이벤트 상품명으로 사용할 수 없는 문구
    ignore_names = {
        "왕십리점",
        "보기 토글",
        "지점안내",
        "온라인상담",
        "전화상담신청",
        "NEW",
    }

    # 가격이 들어간 줄을 찾고
    # 바로 앞의 상품명을 찾습니다.
    for index, line in enumerate(lines):

        parsed = parse_price_line(line)

        if not parsed:
            continue

        title = None

        # 가격 줄 바로 앞에서 상품명을 탐색
        for previous in range(
            index - 1,
            max(-1, index - 6),
            -1
        ):

            candidate = clean(
                lines[previous]
            )

            if not candidate:
                continue

            if candidate in ignore_names:
                continue

            if (
                candidate.startswith("왕십리점")
                or candidate.startswith("202")
            ):
                continue

            # 가격만 있는 줄 제외
            if re.fullmatch(
                r"[\d,\s%원~]+",
                candidate
            ):
                continue

            # 설명 문구 제외
            if candidate.startswith("※"):
                continue

            title = candidate
            break

        if not title:
            continue

        # 제목이 너무 긴 페이지 전체 텍스트인 경우 제외
        if len(title) > 250:
            continue

        results.append({
            "category": CATEGORIES[category_id],
            "name": title,
            "price": parsed["price"],
            "normal": parsed["normal"],
            "discount": parsed["discount"],
            "option": (
                title.startswith("옵션")
                or "옵션" in title[:10]
            ),
            "source": (
                BASE_URL
                + "?tb=event_multi"
                + "&etc5=%EC%99%95%EC%8B%AD%EB%A6%AC%EC%A0%90"
                + f"&sField={category_id}"
            ),
        })

    # 할인율이 없는 옵션 가격도 별도로 찾기
    for index, line in enumerate(lines):

        if "옵션" not in line:
            continue

        # 바로 다음 몇 줄에서 가격 찾기
        option_title = clean(line)

        if len(option_title) > 250:
            continue

        option_price = None

        for next_index in range(
            index + 1,
            min(index + 4, len(lines))
        ):

            candidate = lines[next_index]

            if parse_price_line(candidate):
                break

            option_price = parse_option_price(
                candidate
            )

            if option_price:
                break

        if not option_price:
            continue

        results.append({
            "category": CATEGORIES[category_id],
            "name": option_title,
            "price": option_price,
            "normal": None,
            "discount": None,
            "option": True,
            "source": (
                BASE_URL
                + "?tb=event_multi"
                + "&etc5=%EC%99%95%EC%8B%AD%EB%A6%AC%EC%A0%90"
                + f"&sField={category_id}"
            ),
        })

    return results


def remove_duplicates(events):
    """같은 시술이 여러 번 들어오는 것을 방지합니다."""

    unique = {}
    duplicate_count = 0

    for event in events:

        key = (
            event["category"],
            event["name"],
            event["price"],
            event["normal"],
        )

        if key in unique:
            duplicate_count += 1
            continue

        unique[key] = event

    print(
        f"중복 제거: {duplicate_count}개"
    )

    return list(unique.values())


def scrape_all():

    all_events = []

    print("")
    print("==============================")
    print(" 블리비 왕십리점 이벤트 수집")
    print("==============================")
    print("")

    # 1~7까지 각각 직접 가져옵니다.
    for category_id in range(1, 8):

        category_name = CATEGORIES[
            category_id
        ]

        print(
            f"[{category_id}/7] "
            f"{category_name} 수집 중..."
        )

        try:

            html = get_page(
                category_id
            )

            events = extract_events(
                html,
                category_id
            )

            print(
                f"  → {len(events)}개 발견"
            )

            all_events.extend(events)

        except Exception as error:

            print(
                f"  → 오류: {error}"
            )

    all_events = remove_duplicates(
        all_events
    )

    if not all_events:

        raise RuntimeError(
            "이벤트 데이터를 하나도 찾지 못했습니다."
        )

    collected_at = (
        datetime.now(timezone.utc)
        .astimezone()
        .isoformat()
    )

    for event in all_events:
        event["collected_at"] = collected_at

    # 카테고리 → 이름 순으로 정렬
    all_events.sort(
        key=lambda event: (
            event["category"],
            event["name"],
            event["price"],
        )
    )

    OUTPUT.write_text(
        json.dumps(
            all_events,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("")
    print("==============================")
    print(
        f"총 {len(all_events)}개 수집 완료!"
    )
    print("==============================")
    print("")

    # 검색 테스트
    keywords = [
        "슈링크",
        "울쎄라",
        "인모드",
        "보톡스",
        "필러",
        "제모",
    ]

    for keyword in keywords:

        count = sum(
            keyword.lower()
            in event["name"].lower()
            for event in all_events
        )

        print(
            f"검색 테스트: {keyword} → {count}개"
        )

    print("")


if __name__ == "__main__":
    scrape_all()
