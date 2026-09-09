import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.velyb.kr/community/community01.php"

OUTPUT = Path("events.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


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


def clean(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_page(category_id):
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


def get_lines(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(
        ["script", "style", "noscript"]
    ):
        tag.decompose()

    text = soup.get_text("\n")

    lines = []

    for line in text.splitlines():
        line = clean(line)

        if line:
            lines.append(line)

    return lines


def parse_discount_price(text):
    """
    예:
    42% 99,000원 ~~171,000~~원

    반환:
    discount = 42
    price = 99000
    normal = 171000
    """

    pattern = re.search(
        r"(\d+)\s*%\s*"
        r"([\d,]+)\s*원"
        r"(?:\s*~~\s*([\d,]+)\s*~~\s*원)?",
        text,
    )

    if not pattern:
        return None

    return {
        "discount": int(pattern.group(1)),
        "price": int(
            pattern.group(2).replace(",", "")
        ),
        "normal": (
            int(pattern.group(3).replace(",", ""))
            if pattern.group(3)
            else None
        ),
    }


def parse_plain_price(text):
    """
    예:
    129,000원
    """

    match = re.search(
        r"([\d,]+)\s*원",
        text,
    )

    if not match:
        return None

    return int(
        match.group(1).replace(",", "")
    )


def is_price_line(text):
    return bool(
        re.search(
            r"\d[\d,]*\s*원",
            text
        )
    )


def is_discount_line(text):
    return bool(
        re.search(
            r"\d+\s*%\s*[\d,]+\s*원",
            text
        )
    )


def looks_like_treatment_name(text):
    """
    실제 시술명인지 판단합니다.
    """

    if not text:
        return False

    if len(text) < 2 or len(text) > 250:
        return False

    # 가격 줄
    if is_price_line(text):
        return False

    # UI 문구
    ignore = [
        "왕십리점",
        "보기 토글",
        "지점안내",
        "온라인상담",
        "전화상담신청",
        "전체시술",
        "기획전",
        "쁘띠성형",
        "피부",
        "리프팅",
        "부스터",
        "제모",
        "비만",
        "NEW",
        "EVENT",
        "Image:",
        "이미지",
    ]

    if text in ignore:
        return False

    # 설명 문구
    if text.startswith("※"):
        return False

    if text.startswith("피부 상태"):
        return False

    if text.startswith("기존의"):
        return False

    if text.startswith("극초단파"):
        return False

    if text.startswith("피부 깊은층"):
        return False

    if text.startswith("늘어진 피부"):
        return False

    # 날짜
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}까지",
        text
    ):
        return False

    return True


def extract_events(html, category_id):
    """
    블리비 실제 페이지 구조:

    시술명
    ↓
    할인율 + 이벤트가 + 정상가

    또는

    옵션명
    ↓
    가격
    """

    lines = get_lines(html)

    results = []

    source = (
        BASE_URL
        + "?tb=event_multi"
        + "&etc5=%EC%99%95%EC%8B%AD%EB%A6%AC%EC%A0%90"
        + f"&sField={category_id}"
    )

    for i, line in enumerate(lines):

        # 다음 줄이 할인/가격 줄인지 확인
        if i + 1 >= len(lines):
            continue

        next_line = lines[i + 1]

        parsed = parse_discount_price(
            next_line
        )

        plain_price = None

        if not parsed:
            plain_price = parse_plain_price(
                next_line
            )

        # 바로 다음 줄이 가격이 아니면
        # 시술명으로 판단하지 않음
        if not parsed and plain_price is None:
            continue

        title = line

        if not looks_like_treatment_name(
            title
        ):
            continue

        # 이전 줄이 날짜/지점명인 경우 제외
        if i > 0:

            previous = lines[i - 1]

            if previous == "왕십리점":
                continue

            if re.fullmatch(
                r"\d{4}-\d{2}-\d{2}까지",
                previous
            ):
                continue

        # 할인 이벤트
        if parsed:

            results.append({
                "category": CATEGORIES[
                    category_id
                ],

                "name": title,

                "price": parsed[
                    "price"
                ],

                "normal": parsed[
                    "normal"
                ],

                "discount": parsed[
                    "discount"
                ],

                "option": (
                    title.startswith("옵션")
                    or "옵션" in title[:10]
                ),

                "source": source,
            })

        # 옵션 등 할인율 없는 가격
        else:

            results.append({
                "category": CATEGORIES[
                    category_id
                ],

                "name": title,

                "price": plain_price,

                "normal": None,

                "discount": None,

                "option": (
                    title.startswith("옵션")
                    or "옵션" in title[:10]
                ),

                "source": source,
            })

    return results


def remove_duplicates(events):

    unique = {}

    for event in events:

        key = (
            event["category"],
            event["name"],
            event["price"],
            event["normal"],
        )

        if key not in unique:
            unique[key] = event

    return list(
        unique.values()
    )


def scrape():

    print("")
    print("==============================")
    print(" 블리비 왕십리점 전체 이벤트")
    print("==============================")
    print("")

    all_events = []

    # 1~7 카테고리 전체 수집
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
                f"  → {len(events)}개"
            )

            all_events.extend(events)

        except Exception as error:

            print(
                f"  → 오류: {error}"
            )

    # 중복 제거
    all_events = remove_duplicates(
        all_events
    )

    if not all_events:

        raise RuntimeError(
            "이벤트를 하나도 찾지 못했습니다."
        )

    # 수집 시간
    collected_at = (
        datetime.now(timezone.utc)
        .astimezone()
        .isoformat()
    )

    for event in all_events:
        event["collected_at"] = (
            collected_at
        )

    # 정렬
    all_events.sort(
        key=lambda x: (
            x["category"],
            x["name"],
            x["price"],
        )
    )

    # JSON 저장
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
        f"총 {len(all_events)}개 수집 완료"
    )
    print("==============================")
    print("")

    # 검색 테스트
    test_keywords = [
        "슈링크",
        "울쎄라",
        "인모드",
        "보톡스",
        "필러",
        "제모",
    ]

    for keyword in test_keywords:

        matches = [
            event
            for event in all_events
            if keyword.lower()
            in event["name"].lower()
        ]

        print(
            f"검색 테스트: {keyword} → "
            f"{len(matches)}개"
        )

        # 슈링크가 있으면 실제 이름 출력
        if keyword == "슈링크":

            for event in matches[:5]:

                print(
                    "   ",
                    event["name"],
                    "→",
                    f'{event["price"]:,}원'
                )

    print("")


if __name__ == "__main__":
    scrape()
